import logging
from typing import Any

from src.config import settings
from src.engine.signal_confirmation import confirm_signal
from src.engine.trend_filter import higher_timeframe_trend_ok
from src.execution.execution import Signal

logger = logging.getLogger("scalping_strategy")

class ScalpStrategy:
    """
    Minimal EMA crossover scalping strategy:
    - primary TF is 1m
    - short/long are from config
    - on short crosses above long at bar close -> signal
    """

    def __init__(self, service):
        self.service = service

    async def on_bar_close(self, symbol: str, timeframe: str, bar: Any, ema_state, ema_confirm=None):
        """Process bar close event for scalping strategy."""
        logger.debug(f"Scalper on_bar_close: {symbol} {timeframe} close={bar.close:.2f}")
        primary_tf = settings.SCALP_PRIMARY_TIMEFRAME
        confirm_tf = settings.SCALP_CONFIRM_TIMEFRAME
        if timeframe != primary_tf:
            return
        prev_short = ema_state.prev_short
        prev_long = ema_state.prev_long
        curr_short = ema_state.short_ema
        curr_long = ema_state.long_ema
        if prev_short is None or prev_long is None:
            return
        def trend_ok(side: str) -> bool:
            if not settings.SCALP_ENABLE_TREND_CONFIRMATION:
                logger.debug(f"Scalper {symbol}: Trend confirmation disabled, allowing {side} signal")
                return True
            result = higher_timeframe_trend_ok(side, bar.close, primary_tf, confirm_tf, ema_confirm)
            logger.debug(f"Scalper {symbol}: Trend check for {side} signal - {'PASS' if result else 'FAIL'}")
            return result

        # Check if symbol is an index (trade only options for indices)
        is_index = symbol.startswith("NSE_INDEX")
        # Volatility filter: high vol -> prefer options; low vol -> prefer underlying
        high_vol = ema_state.atr and ema_state.atr > 0.02 * bar.close  # ATR > 2% of price
        logger.debug(f"Scalper {symbol}: high_vol={high_vol}, is_index={is_index}")
        trade_underlying = not is_index and not high_vol  # Trade underlying only for stocks in low vol
        logger.debug(f"Scalper {symbol}: trade_underlying={trade_underlying}")

        if prev_short <= prev_long and curr_short > curr_long:
            logger.debug(f"Scalper {symbol}: EMA crossover BUY signal detected")
            sl = bar.close - (0.002 * bar.close)
            tgt = bar.close + (0.003 * bar.close)
            size = 1
            if trend_ok("BUY"):
                # Signal confirmation with RSI, CPR, price action
                if settings.SCALP_ENABLE_SIGNAL_CONFIRMATION:
                    logger.debug(f"Scalper {symbol}: Checking signal confirmation for BUY")
                    recent_bars, daily_ref = await self.service._confirmation_ctx(symbol, timeframe)
                    if recent_bars:
                        result = confirm_signal("BUY", ema_state, recent_bars, daily_ref, require_cpr=settings.CONFIRMATION_REQUIRE_CPR)
                        if not result["confirmed"]:
                            logger.info(f"Scalper BUY signal rejected for {symbol}: {result['reasons']}")
                            return
                        else:
                            logger.debug(f"Scalper {symbol}: BUY signal confirmed")
                    else:
                        logger.warning(f"Scalper {symbol}: No recent bars for BUY signal confirmation")
                        return
                
                logger.info(f"Scalper BUY signal generated for {symbol}: price={bar.close:.2f}, sl={sl:.2f}, tgt={tgt:.2f}, size={size}")
                
                
                logger.debug(f"Scalper {symbol}: Executing underlying BUY order")
                signal = Signal(symbol=symbol, side="BUY", price=bar.close, size=size, stop_loss=sl, target=tgt)
                if trade_underlying:
                    await self.service.executor.handle_signal(signal)
                await self.service.notifier.notify_signal(signal)
                # Trade options in high vol or for indices
                if high_vol or is_index:
                    logger.debug(f"Scalper {symbol}: Publishing BUY signal to options manager")
                    if self.service.options_manager:
                        await self.service.options_manager.publish_underlying_signal(symbol=symbol, side="BUY", price=bar.close, timeframe=timeframe, origin="scalper")
        elif prev_short >= prev_long and curr_short < curr_long:
            logger.debug(f"Scalper {symbol}: EMA crossover SELL signal detected")
            sl = bar.close + (0.002 * bar.close)
            tgt = bar.close - (0.003 * bar.close)
            size = 1
            if trend_ok("SELL"):
                # Signal confirmation with RSI, CPR, price action
                if settings.SCALP_ENABLE_SIGNAL_CONFIRMATION:
                    logger.debug(f"Scalper {symbol}: Checking signal confirmation for SELL")
                    recent_bars, daily_ref = await self.service._confirmation_ctx(symbol, timeframe)
                    if recent_bars:
                        result = confirm_signal("SELL", ema_state, recent_bars, daily_ref, require_cpr=settings.CONFIRMATION_REQUIRE_CPR)
                        if not result["confirmed"]:
                            logger.info(f"Scalper SELL signal rejected for {symbol}: {result['reasons']}")
                            return
                        else:
                            logger.debug(f"Scalper {symbol}: SELL signal confirmed")
                    else:
                        logger.warning(f"Scalper {symbol}: No recent bars for SELL signal confirmation")
                        return
                
                logger.info(f"Scalper SELL signal generated for {symbol}: price={bar.close:.2f}, sl={sl:.2f}, tgt={tgt:.2f}, size={size}")
                
                
                signal = Signal(symbol=symbol, side="SELL", price=bar.close, size=size, stop_loss=sl, target=tgt)
                if trade_underlying:
                    await self.service.executor.handle_signal(signal)
                await self.service.notifier.notify_signal(signal)
                # Trade options in high vol or for indices
                if high_vol or is_index:
                    logger.debug(f"Scalper {symbol}: Publishing SELL signal to options manager")
                    if self.service.options_manager:
                        await self.service.options_manager.publish_underlying_signal(symbol=symbol, side="SELL", price=bar.close, timeframe=timeframe, origin="scalper")

# Extension scaffolds kept commented for future reuse.
# class ScalpStrategyAdapter(ScalpStrategy):
#     def generate_signal(self, symbol, timeframe, bar, ema_state):
#         if timeframe != "1m":
#             return None
#         prev_short = ema_state.prev_short
#         prev_long = ema_state.prev_long
#         curr_short = ema_state.short_ema
#         curr_long = ema_state.long_ema
#         if prev_short is None or prev_long is None:
#             return None
#         if prev_short <= prev_long and curr_short > curr_long:
#             sl = bar.close - (0.002 * bar.close)
#             tgt = bar.close + (0.003 * bar.close)
#             return Signal(symbol=symbol, side="BUY", price=bar.close, size=1, stop_loss=sl, target=tgt)
#         if prev_short >= prev_long and curr_short < curr_long:
#             sl = bar.close + (0.002 * bar.close)
#             tgt = bar.close - (0.003 * bar.close)
#             return Signal(symbol=symbol, side="SELL", price=bar.close, size=1, stop_loss=sl, target=tgt)
#         return None
#     async def execute_signal(self, signal):
#         await self.service.executor.handle_signal(signal)
#         await self.service.notifier.notify_signal(signal)
# class ConfirmedScalpStrategy:
#     def __init__(self, base_strategy: ScalpStrategyAdapter, confirmation_ctx_provider: Callable):
#         self.base = base_strategy
#         self.ctx_provider = confirmation_ctx_provider
#         self.logger = logging.getLogger("confirmed_strategy")
#     async def on_bar_close(self, symbol: str, timeframe: str, bar: Any, ema_state):
#         raw_signal = self.base.generate_signal(symbol, timeframe, bar, ema_state)
#         if not raw_signal:
#             return
#         recent_bars, daily_ref = self.ctx_provider(symbol, timeframe)
#         result = confirm_signal(raw_signal.side, ema_state, recent_bars, daily_ref)
#         if result["confirmed"]:
#             await self.base.execute_signal(raw_signal)
#         else:
#             self.logger.info(f"Signal {raw_signal.side} on {symbol} rejected: {result['reasons']} scores={result['scores']}")
