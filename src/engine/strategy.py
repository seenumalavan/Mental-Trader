from typing import Any, Callable, List, Dict
import logging
from src.config import settings
from src.execution.execution import Signal
from src.engine.signal_confirmation import confirm_signal, SignalType

class ScalpStrategy:
    """
    Minimal EMA crossover scalping strategy:
    - primary TF is 1m
    - short/long are from config
    - on short crosses above long at bar close -> signal
    """

    def __init__(self, service):
        self.service = service

    async def on_bar_close(self, symbol: str, timeframe: str, bar: Any, ema_state):
        if timeframe != "1m":
            return
        # ensure prev ema present
        prev_short = ema_state.prev_short
        prev_long = ema_state.prev_long
        curr_short = ema_state.short_ema
        curr_long = ema_state.long_ema
        if prev_short is None or prev_long is None:
            return
        # bullish crossover
        if prev_short <= prev_long and curr_short > curr_long:
            # compute stop loss and  target using small ATR-ish rule (placeholder)
            sl = bar.close - (0.002 * bar.close)  # 0.2% default stop
            tgt = bar.close + (0.003 * bar.close) # 0.3% target
            # compute size via risk manager (simple fallback: 1 share)
            size = 1
            signal = Signal(symbol=symbol, side="BUY", price=bar.close, size=size, stop_loss=sl, target=tgt)
            await self.service.executor.handle_signal(signal)
            await self.service.notifier.notify_signal(signal)
        # bearish crossover
        elif prev_short >= prev_long and curr_short < curr_long:
            sl = bar.close + (0.002 * bar.close)  # stop above entry
            tgt = bar.close - (0.003 * bar.close)  # target below
            size = 1
            signal = Signal(symbol=symbol, side="SELL", price=bar.close, size=size, stop_loss=sl, target=tgt)
            await self.service.executor.handle_signal(signal)
            await self.service.notifier.notify_signal(signal)

# # Pseudo-extension (can live in same file or a new adapter file)

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

#         # Bullish crossover
#         if prev_short <= prev_long and curr_short > curr_long:
#             sl = bar.close - (0.002 * bar.close)
#             tgt = bar.close + (0.003 * bar.close)
#             return Signal(symbol=symbol, side="BUY", price=bar.close, size=1, stop_loss=sl, target=tgt)
#         # Bearish crossover
#         if prev_short >= prev_long and curr_short < curr_long:
#             sl = bar.close + (0.002 * bar.close)
#             tgt = bar.close - (0.003 * bar.close)
#             return Signal(symbol=symbol, side="SELL", price=bar.close, size=1, stop_loss=sl, target=tgt)
#         return None

#     async def execute_signal(self, signal):
#         await self.service.executor.handle_signal(signal)
#         await self.service.notifier.notify_signal(signal)

# class ConfirmedScalpStrategy:
#     """Wrapper that adds multi-indicator confirmation to a base scalping strategy.

#     Expects the base strategy to supply generate_signal() and execute_signal().
#     confirmation_ctx_provider(symbol, timeframe) -> (recent_bars, daily_ref)
#     recent_bars: chronological list of dict bars with keys open/high/low/close/volume
#     daily_ref: dict containing prev_high/prev_low/prev_close
#     """
#     def __init__(self, base_strategy: ScalpStrategyAdapter, confirmation_ctx_provider: Callable):
#         self.base = base_strategy
#         self.ctx_provider = confirmation_ctx_provider
#         self.logger = logging.getLogger("confirmed_strategy")

#     async def on_bar_close(self, symbol: str, timeframe: str, bar: Any, ema_state):
#         raw_signal = self.base.generate_signal(symbol, timeframe, bar, ema_state)
#         if not raw_signal:
#             return
#         recent_bars, daily_ref = self.ctx_provider(symbol, timeframe)
#         result = confirm_signal(
#             raw_signal.side,
#             ema_state,
#             recent_bars,
#             daily_ref
#         )
#         if result["confirmed"]:
#             await self.base.execute_signal(raw_signal)
#         else:
#             self.logger.info(
#                 f"Signal {raw_signal.side} on {symbol} rejected: {result['reasons']} scores={result['scores']}"
#             )
