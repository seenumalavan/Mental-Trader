import logging
from typing import Any
from src.execution.execution import Signal
from src.engine.trend_filter import higher_timeframe_trend_ok
from src.config import settings

logger = logging.getLogger("intraday_strategy")

class IntradayStrategy:
    """Configurable intraday strategy: primary timeframe crossover confirmed by higher timeframe trend.

    Parameters:
      primary_tf: timeframe generating entries (e.g. '5m' or '15m').
      confirm_tf: higher timeframe used for trend filter (e.g. '15m'). If same as primary, filter is skipped.
      short_period/long_period: EMA periods for crossover.
      trend_period: which EMA (short or long) to use for trend check on confirm timeframe (defaults to long).
    """
    def __init__(self, service, primary_tf: str, confirm_tf: str, short_period: int, long_period: int, trend_period: int = None):
        self.service = service
        self.primary_tf = primary_tf
        self.confirm_tf = confirm_tf
        self.short_period = short_period
        self.long_period = long_period
        self.trend_period = trend_period or long_period

    async def on_bar_close(self, symbol: str, timeframe: str, bar: Any, ema_primary, ema_confirm):
        if timeframe != self.primary_tf:
            return
        prev_short = ema_primary.prev_short
        prev_long = ema_primary.prev_long
        curr_short = ema_primary.short_ema
        curr_long = ema_primary.long_ema
        if prev_short is None or prev_long is None:
            return

        def trend_ok(side: str) -> bool:
            if not settings.INTRADAY_ENABLE_CONFIRM_FILTER:
                return True
            return higher_timeframe_trend_ok(side, bar.close, self.primary_tf, self.confirm_tf, ema_confirm)

        # Bullish crossover
        if prev_short <= prev_long and curr_short > curr_long:
            if not trend_ok("BUY"):
                return
            # Stop/target scale: wider for larger timeframe entries
            scale = 0.004 if self.primary_tf in ("5m", "10m") else 0.006
            sl = bar.close - (scale * bar.close)
            tgt = bar.close + (scale * 1.5 * bar.close)
            risk_mgr = getattr(self.service, 'risk_manager', None)
            size = 1
            if risk_mgr:
                size_calc = risk_mgr.calc_size(bar.close, sl)
                if size_calc > 0:
                    size = size_calc
            signal = Signal(symbol=symbol, side="BUY", price=bar.close, size=size, stop_loss=sl, target=tgt)
            await self.service.executor.handle_signal(signal)
            await self.service.notifier.notify_signal(signal)
            if self.service.options_manager:
                await self.service.options_manager.publish_underlying_signal(symbol=symbol, side="BUY", price=bar.close, timeframe=timeframe, origin="intraday")
        # Bearish crossover
        elif prev_short >= prev_long and curr_short < curr_long:
            if not trend_ok("SELL"):
                return
            scale = 0.004 if self.primary_tf in ("5m", "10m") else 0.006
            sl = bar.close + (scale * bar.close)
            tgt = bar.close - (scale * 1.5 * bar.close)
            risk_mgr = getattr(self.service, 'risk_manager', None)
            size = 1
            if risk_mgr:
                size_calc = risk_mgr.calc_size(bar.close, sl)
                if size_calc > 0:
                    size = size_calc
            signal = Signal(symbol=symbol, side="SELL", price=bar.close, size=size, stop_loss=sl, target=tgt)
            await self.service.executor.handle_signal(signal)
            await self.service.notifier.notify_signal(signal)
            if self.service.options_manager:
                await self.service.options_manager.publish_underlying_signal(symbol=symbol, side="SELL", price=bar.close, timeframe=timeframe, origin="intraday")
