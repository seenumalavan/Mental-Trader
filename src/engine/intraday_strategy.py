import logging
from typing import Any

from src.config import settings
from src.engine.base_strategy import BaseStrategy
from src.engine.signal_confirmation import confirm_signal
from src.engine.trend_filter import higher_timeframe_trend_ok
from src.execution.execution import Signal
from src.utils.time_utils import get_time_window

logger = logging.getLogger("intraday_strategy")

class IntradayStrategy(BaseStrategy):
    """Configurable intraday strategy: primary timeframe crossover confirmed by higher timeframe trend."""
    def __init__(self, service, primary_tf: str, confirm_tf: str, short_period: int = None, long_period: int = None, trend_period: int = None):
        super().__init__(service)
        self.primary_tf = primary_tf
        self.confirm_tf = confirm_tf
        self.short_period = short_period
        self.long_period = long_period
        self.trend_period = trend_period or self.long_period

    async def on_bar_close(self, symbol: str, instrument_key: str, timeframe: str, bar: Any, ema_primary, ema_confirm):
        logger.debug(f"Intraday on_bar_close: {symbol} {instrument_key} {timeframe} close={bar.close:.2f}")
        symbol_key = self.get_symbol_key(symbol, timeframe)
        if self.should_skip_warmup(symbol_key, 1):
            logger.debug(f"Intraday {symbol}: Skipping signal generation during warmup (bar {self.bar_count[symbol_key]})")
            return
        if timeframe != self.primary_tf:
            return
        
        # Check time window
        time_window = get_time_window(getattr(bar, 'ts', ''))
        if time_window == "midday":
            logger.debug(f"Intraday {symbol}: Skipping mid-day signal")
            return
        
        if not self.service.can_trade(time_window):
            logger.debug(f"Intraday {symbol}: Monthly trade limit reached for {time_window}")
            return
        
        prev_short = ema_primary.prev_short
        prev_long = ema_primary.prev_long
        curr_short = ema_primary.short_ema
        curr_long = ema_primary.long_ema
        if None in (prev_short, prev_long, curr_short, curr_long):
            logger.debug(f"Intraday {symbol}: EMA values not ready (prev_short={prev_short}, prev_long={prev_long})")
            return
        #crossover_threshold = self.get_crossover_threshold(bar.close)
        crossover_threshold = 0
        def trend_ok(side: str) -> bool:
            # Trend confirmation logic (unified with IntradayStrategy)
            if not getattr(settings, "INTRADAY_ENABLE_TREND_CONFIRMATION", True):
                logger.debug(f"Intraday {symbol}: Trend confirmation disabled, allowing {side} signal")
                return True
            result = higher_timeframe_trend_ok(side, bar.close, self.primary_tf, self.confirm_tf, ema_confirm)
            logger.debug(f"Intraday {symbol}: Trend check for {side} signal - {'PASS' if result else 'FAIL'}")
            return result
        is_index = self.is_index(instrument_key)
        high_vol = self.get_high_vol(ema_primary, bar.close, is_index)
        trade_underlying = self.get_trade_underlying(is_index, high_vol)
        # Bullish crossover
        if prev_short <= (prev_long - crossover_threshold) and curr_short > (curr_long + crossover_threshold):
            logger.debug(
                f"Intraday {symbol}: EMA crossover BUY signal detected ts={getattr(bar,'ts',None)} "
                f"(prev_short={prev_short:.4f} prev_long={prev_long:.4f} curr_short={curr_short:.4f} curr_long={curr_long:.4f} "
                f"prev_diff={prev_short - prev_long:.4f} curr_diff={curr_short - curr_long:.4f} thr={crossover_threshold:.6f})"
            )
            scale = self.get_scale_for_timeframe(self.primary_tf)
            sl = bar.close - (scale * bar.close)
            tgt = bar.close + (scale * settings.INTRADAY_RR_RATIO * bar.close)
            size = self.get_risk_size(bar.close, sl)
            # Trend and signal confirmation (unified with IntradayStrategy)
            if trend_ok("BUY"):
                if getattr(settings, "INTRADAY_ENABLE_SIGNAL_CONFIRMATION", True):
                    logger.debug(f"Intraday {symbol}: Checking signal confirmation for BUY")
                    recent_bars, daily_ref = await self.service._confirmation_ctx(symbol, timeframe)
                    if not recent_bars:
                        logger.warning(f"Intraday {symbol}: No recent bars for BUY signal confirmation")
                        return
                    result = confirm_signal("BUY", ema_primary, recent_bars, daily_ref, symbol=symbol, time_window=time_window)
                    if not result["confirmed"]:
                        logger.info(f"Intraday BUY signal rejected for {symbol}: {result['reasons']}")
                        return
                    logger.debug(f"Intraday {symbol}: BUY signal confirmed")

                logger.info(
                    f"Scalper BUY signal generated for {symbol} ts={getattr(bar,'ts',None)}: price={bar.close:.2f}, sl={sl:.2f}, tgt={tgt:.2f}, size={size} "
                    f"short={curr_short:.4f} long={curr_long:.4f} diff={curr_short-curr_long:.4f}"
                )
                # Underlying order execution (unified with IntradayStrategy)
                signal = Signal(symbol=symbol, side="BUY", price=bar.close, size=size, stop_loss=sl, target=tgt)
                if trade_underlying:
                    logger.debug(f"Intraday {symbol}: Executing underlying BUY order")
                    await self.service.executor.handle_signal(signal)
                    self.service.increment_trade_count(time_window)
                await self.service.notifier.notify_signal(signal)
                # Option signal publication (unified with IntradayStrategy)
                if high_vol or is_index:
                    logger.debug(f"Intraday {symbol}: Publishing BUY signal to options manager")
                    if self.service.options_manager:
                        await self.service.options_manager.publish_underlying_signal(symbol=symbol, side="BUY", price=bar.close, timeframe=timeframe, origin="intraday")
        # Bearish crossover
        elif prev_short >= (prev_long + crossover_threshold) and curr_short < (curr_long - crossover_threshold):
            logger.debug(
                f"Intraday {symbol}: EMA crossover SELL signal detected ts={getattr(bar,'ts',None)} "
                f"(prev_short={prev_short:.4f} prev_long={prev_long:.4f} curr_short={curr_short:.4f} curr_long={curr_long:.4f} "
                f"prev_diff={prev_short - prev_long:.4f} curr_diff={curr_short - curr_long:.4f} thr={crossover_threshold:.6f})"
            )
            scale = self.get_scale_for_timeframe(self.primary_tf)
            sl = bar.close + (scale * bar.close)
            tgt = bar.close - (scale * settings.INTRADAY_RR_RATIO * bar.close)
            size = self.get_risk_size(bar.close, sl)
            # Trend and signal confirmation (unified with IntradayStrategy)
            if trend_ok("SELL"):
                if getattr(settings, "INTRADAY_ENABLE_SIGNAL_CONFIRMATION", True):
                    logger.debug(f"Intraday {symbol}: Checking signal confirmation for SELL")
                    recent_bars, daily_ref = await self.service._confirmation_ctx(symbol, timeframe)
                    if not recent_bars:
                        logger.warning(f"Intraday {symbol}: No recent bars for SELL signal confirmation")
                        return
                    result = confirm_signal("SELL", ema_primary, recent_bars, daily_ref, symbol=symbol, time_window=time_window)
                    if not result["confirmed"]:
                        logger.info(f"Intraday SELL signal rejected for {symbol}: {result['reasons']}")
                        return
                    logger.debug(f"Intraday {symbol}: SELL signal confirmed")

                logger.info(
                    f"Intraday SELL signal generated for {symbol} ts={getattr(bar,'ts',None)}: price={bar.close:.2f}, sl={sl:.2f}, tgt={tgt:.2f}, size={size} "
                    f"short={curr_short:.4f} long={curr_long:.4f} diff={curr_short-curr_long:.4f}"
                )
                # Underlying order execution (unified with IntradayStrategy)
                signal = Signal(symbol=symbol, side="SELL", price=bar.close, size=size, stop_loss=sl, target=tgt)
                if trade_underlying:
                    logger.debug(f"Intraday {symbol}: Executing underlying SELL order")
                    await self.service.executor.handle_signal(signal)
                    self.service.increment_trade_count(time_window)
                await self.service.notifier.notify_signal(signal)
                # Option signal publication (unified with IntradayStrategy)
                if high_vol or is_index:
                    logger.debug(f"Intraday {symbol}: Publishing SELL signal to options manager")
                    if self.service.options_manager:
                        await self.service.options_manager.publish_underlying_signal(symbol=symbol, side="SELL", price=bar.close, timeframe=timeframe, origin="intraday") # For options trading I am going to buy but PE instead of CE
