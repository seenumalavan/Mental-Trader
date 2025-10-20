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
        self._open_orders = {}  # local map of signal_id -> broker order id

    async def handle_signal(self, signal: Signal):
        # place market/IOC order — idempotency considerations needed in prod
        order_payload = {
            "symbol": signal.symbol,
            "side": signal.side,
            "type": "MARKET",
            "quantity": int(signal.size)
        }
        try:
            #resp = await self.broker.place_order(order_payload)
            resp = None
            # persist trade
            await self.db.insert_trade(signal, resp)
            logger.info("Placed order for %s resp=%s", signal.symbol, resp)
        except Exception:
            logger.exception("Order failed for %s", signal.symbol)
