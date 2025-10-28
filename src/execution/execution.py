import logging
from dataclasses import dataclass

logger = logging.getLogger("executor")

@dataclass
class Signal:
    symbol: str
    side: str
    price: float
    size: int
    stop_loss: float
    target: float

class Executor:
    def __init__(self, broker_rest, db):
        self.broker = broker_rest
        self.db = db
        self._open_orders = {}  # local map of trade/order id -> position dict (underlying)
        self._open_option_positions = {}  # contract_symbol -> position dict

    async def handle_signal(self, signal: Signal):
        """Execute underlying (spot/futures) signal and start local monitoring.

        Stores a local position dict for stop/target evaluation similar to option positions.
        Long (BUY): exits when price >= target OR price <= stop.
        Short (SELL): exits when price <= target OR price >= stop.
        """
        logger.debug(f"Executing signal: {signal.symbol} {signal.side} size={signal.size} price={signal.price}")
        order_payload = {
            "symbol": signal.symbol,
            "side": signal.side,
            "type": "MARKET",
            "quantity": int(signal.size)
        }
        try:
            logger.debug(f"Placing order: {order_payload}")
            resp = await self.broker.place_order(order_payload)
            order_id = resp.get("order_id") if isinstance(resp, dict) else None
            await self.db.insert_trade(signal, resp)
            # Track position locally
            self._open_orders[order_id] = {
                'symbol': signal.symbol,
                'side': signal.side,
                'quantity': int(signal.size),
                'entry_price': signal.price,
                'stop': signal.stop_loss,
                'target': signal.target,
                'status': 'OPEN'
            }
            logger.info("Underlying order placed symbol=%s side=%s qty=%d id=%s stop=%s target=%s", signal.symbol, signal.side, signal.size, order_id, signal.stop_loss, signal.target)
        except Exception:
            logger.exception("Order failed for %s", signal.symbol)

    async def handle_option_signal(self, opt_signal):
        """Execute an option trade derived from OptionSignal.

        Assumptions:
        - opt_signal.contract_symbol maps to a valid instrument token via broker_rest mapping.
        - Quantity is calculated as lots * lot_size (lot_size configured externally).
        Execution here is placeholder (no actual order placement) until broker option order endpoint wired.
        """
        try:
            lots = int(getattr(opt_signal, 'suggested_size_lots', 0))
            if lots <= 0:
                logger.info("Option lots <= 0; skipping execution")
                return
            # Placeholder: each lot assumed underlying lot size from config (fetch if needed)
            lot_size =  getattr(self.broker, 'default_option_lot_size', 5)
            quantity = lots * lot_size
            side = 'BUY' if opt_signal.underlying_side == 'BUY' else 'BUY'  # For SELL underlying you might BUY a PUT. Adjust logic when adding short strategies.
            order_payload = {
                'symbol': opt_signal.contract_symbol,
                'side': side,
                'type': 'MARKET',
                'quantity': quantity
            }
            resp = await self.broker.place_order(order_payload)  # Real placement when ready
            order_id = resp.get("order_id") if isinstance(resp, dict) else None
            setattr(opt_signal, 'entry_order_id', order_id)
            self._open_option_positions[opt_signal.contract_symbol] = {
                'quantity': quantity,
                'stop': opt_signal.stop_loss_premium,
                'target': opt_signal.target_premium,
                'underlying_side': opt_signal.underlying_side,
                'entry_price': opt_signal.premium_ltp,
                'entry_order_id': order_id,
                'status': 'OPEN'
            }
            await self.db.insert_option_trade(opt_signal)
            logger.info("Option order placed contract=%s side=%s lots=%d qty=%d id=%s stop=%s target=%s", opt_signal.contract_symbol, side, lots, quantity, order_id, opt_signal.stop_loss_premium, opt_signal.target_premium)
        except Exception:
            logger.exception("Option order failed for %s", getattr(opt_signal, 'contract_symbol', 'UNKNOWN'))

    async def monitor_option_positions(self, tick):
        """Call this from a tick handler passing option ticks to evaluate exits locally."""
        symbol = tick.get('symbol')
        price = tick.get('price')
        pos = self._open_option_positions.get(symbol)
        if not pos or price is None:
            return
        try:
            if pos['status'] != 'OPEN':
                return
            # Target check first
            if price >= pos['target']:
                await self._close_option_position(symbol, price, reason='TARGET')
            elif price <= pos['stop']:
                await self._close_option_position(symbol, price, reason='STOP')
        except Exception:
            logger.exception("Monitoring failed for %s", symbol)

    async def monitor_underlying_positions(self, tick):
        """Evaluate underlying positions for exit conditions using live ticks.

        tick must contain 'symbol' and 'price'.
        """
        symbol = tick.get('symbol')
        price = tick.get('price')
        if symbol is None or price is None:
            return
        # Iterate over open positions matching symbol (could be multiple partial fills in future)
        try:
            for order_id, pos in list(self._open_orders.items()):
                if pos.get('symbol') != symbol or pos.get('status') != 'OPEN':
                    continue
                side = pos['side']
                target = pos['target']
                stop = pos['stop']
                if side == 'BUY':
                    if price >= target:
                        await self._close_underlying_position(order_id, price, reason='TARGET')
                    elif price <= stop:
                        await self._close_underlying_position(order_id, price, reason='STOP')
                elif side == 'SELL':  # Short logic
                    if price <= target:
                        await self._close_underlying_position(order_id, price, reason='TARGET')
                    elif price >= stop:
                        await self._close_underlying_position(order_id, price, reason='STOP')
        except Exception:
            logger.exception("Underlying monitoring failed for %s", symbol)

    async def _close_option_position(self, symbol: str, exit_price: float, reason: str):
        pos = self._open_option_positions.get(symbol)
        if not pos:
            return
        try:
            order_payload = {
                'symbol': symbol,
                'side': 'SELL',
                'type': 'MARKET',
                'quantity': pos['quantity']
            }
            resp = await self.broker.place_order(order_payload)
            exit_id = resp.get('order_id') if isinstance(resp, dict) else None
            pos['status'] = 'CLOSED'
            pos['exit_price'] = exit_price
            pos['exit_reason'] = reason
            pos['exit_order_id'] = exit_id
            await self.db.update_option_trade_status(symbol, f"CLOSED:{reason}")
            logger.info("Closed option position %s reason=%s exit_price=%s id=%s", symbol, reason, exit_price, exit_id)
        except Exception:
            logger.exception("Failed closing option position %s", symbol)

    async def _close_underlying_position(self, order_id: str, exit_price: float, reason: str):
        pos = self._open_orders.get(order_id)
        if not pos:
            return
        try:
            side = pos['side']
            # Reverse side to exit
            exit_side = 'SELL' if side == 'BUY' else 'BUY'
            order_payload = {
                'symbol': pos['symbol'],
                'side': exit_side,
                'type': 'MARKET',
                'quantity': pos['quantity']
            }
            resp = await self.broker.place_order(order_payload)
            exit_order_id = resp.get('order_id') if isinstance(resp, dict) else None
            pos['status'] = 'CLOSED'
            pos['exit_price'] = exit_price
            pos['exit_reason'] = reason
            pos['exit_order_id'] = exit_order_id
            await self.db.update_trade_status(order_id, f"CLOSED:{reason}")
            logger.info("Closed underlying position %s symbol=%s reason=%s exit_price=%s exit_order_id=%s", order_id, pos['symbol'], reason, exit_price, exit_order_id)
        except Exception:
            logger.exception("Failed closing underlying position %s", order_id)
