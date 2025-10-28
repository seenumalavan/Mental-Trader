import logging
from typing import Any

from src.config import settings
from src.engine.base_strategy import BaseStrategy
from src.engine.signal_confirmation import confirm_signal
from src.engine.trend_filter import higher_timeframe_trend_ok
from src.execution.execution import Signal

logger = logging.getLogger("scalping_strategy")

class ScalpStrategy(BaseStrategy):
    """Configurable EMA crossover strategy: primary timeframe crossover confirmed by higher timeframe trend, with risk management and signal confirmation. Structure and comments unified with IntradayStrategy for consistency."""
    def __init__(self, service, primary_tf: str = None, confirm_tf: str = None, short_period: int = None, long_period: int = None, trend_period: int = None):
        super().__init__(service)
        self.primary_tf = primary_tf
        self.confirm_tf = confirm_tf
        self.short_period = short_period
        self.long_period = long_period
        self.trend_period = trend_period or self.long_period

    async def on_bar_close(self, symbol: str, instrument_key: str, timeframe: str, bar: Any, ema_state, ema_confirm=None):
        logger.debug(f"Scalper on_bar_close: {symbol} {instrument_key} {timeframe} close={bar.close:.2f}")
        symbol_key = self.get_symbol_key(symbol, timeframe)
        if self.should_skip_warmup(symbol_key, 1):
            logger.debug(f"Scalper {symbol}: Skipping signal generation during warmup (bar {self.bar_count[symbol_key]})")
            return
        if timeframe != self.primary_tf:
            return
        prev_short = ema_state.prev_short
        prev_long = ema_state.prev_long
        curr_short = ema_state.short_ema
        curr_long = ema_state.long_ema
        if None in (prev_short, prev_long, curr_short, curr_long):
            logger.debug(f"Scalper {symbol}: EMA values not ready (prev_short={prev_short}, prev_long={prev_long})")
            return
        crossover_threshold = self.get_crossover_threshold(bar.close)
        def trend_ok(side: str) -> bool:
            # Trend confirmation logic (unified with ScalpStrategy)
            if not getattr(settings, "SCALP_ENABLE_TREND_CONFIRMATION", True):
                logger.debug(f"Scalper {symbol}: Trend confirmation disabled, allowing {side} signal")
                return True
            result = higher_timeframe_trend_ok(side, bar.close, self.primary_tf, self.confirm_tf, ema_confirm)
            logger.debug(f"Scalper {symbol}: Trend check for {side} signal - {'PASS' if result else 'FAIL'}")
            return result
        is_index = self.is_index(instrument_key)
        high_vol = self.get_high_vol(ema_state, bar.close, is_index)
        trade_underlying = self.get_trade_underlying(is_index, high_vol)
        # Bullish crossover: short EMA crosses above long EMA
        if prev_short <= (prev_long - crossover_threshold) and curr_short > (curr_long + crossover_threshold):
            logger.debug(
                f"Scalper {symbol}: EMA crossover BUY signal detected ts={getattr(bar,'ts',None)} "
                f"(prev_short={prev_short:.4f} prev_long={prev_long:.4f} curr_short={curr_short:.4f} curr_long={curr_long:.4f} "
                f"prev_diff={prev_short - prev_long:.4f} curr_diff={curr_short - curr_long:.4f} thr={crossover_threshold:.6f})"
            )
            sl = bar.close - (0.002 * bar.close)
            tgt = bar.close + (0.003 * bar.close)
            size = self.get_risk_size(bar.close, sl)
            # Trend and signal confirmation (unified with ScalperStrategy)
            if trend_ok("BUY"):
                if getattr(settings, "SCALP_ENABLE_SIGNAL_CONFIRMATION", True):
                    logger.debug(f"Scalper {symbol}: Checking signal confirmation for BUY")
                    recent_bars, daily_ref = await self.service._confirmation_ctx(symbol, timeframe)
                    if not recent_bars:
                        logger.warning(f"Scalper {symbol}: No recent bars for BUY signal confirmation")
                        return
                    result = confirm_signal("BUY", ema_state, recent_bars, daily_ref, require_cpr=getattr(settings, "CONFIRMATION_REQUIRE_CPR", False))
                    if not result["confirmed"]:
                        logger.info(f"Scalper BUY signal rejected for {symbol}: {result['reasons']}")
                        return
                    logger.debug(f"Scalper {symbol}: BUY signal confirmed")
                logger.info(
                    f"Scalper BUY signal generated for {symbol} ts={getattr(bar,'ts',None)}: price={bar.close:.2f}, sl={sl:.2f}, tgt={tgt:.2f}, size={size} "
                    f"short={curr_short:.4f} long={curr_long:.4f} diff={curr_short-curr_long:.4f}"
                )
                # Underlying order execution (unified with ScalperStrategy)
                signal = Signal(symbol=symbol, side="BUY", price=bar.close, size=size, stop_loss=sl, target=tgt)
                if trade_underlying:
                    logger.debug(f"Scalper {symbol}: Executing underlying BUY order")
                    await self.service.executor.handle_signal(signal)
                await self.service.notifier.notify_signal(signal)
                # Option signal publication (unified with ScalperStrategy)
                if high_vol or is_index:
                    logger.debug(f"Scalper {symbol}: Publishing BUY signal to options manager")
                    if self.service.options_manager:
                        await self.service.options_manager.publish_underlying_signal(symbol=symbol, side="BUY", price=bar.close, timeframe=timeframe, origin="scalper")

        # Bearish crossover: short EMA crosses below long EMA
        elif prev_short >= (prev_long + crossover_threshold) and curr_short < (curr_long - crossover_threshold):
            logger.debug(
                f"Scalper {symbol}: EMA crossover SELL signal detected ts={getattr(bar,'ts',None)} "
                f"(prev_short={prev_short:.4f} prev_long={prev_long:.4f} curr_short={curr_short:.4f} curr_long={curr_long:.4f} "
                f"prev_diff={prev_short - prev_long:.4f} curr_diff={curr_short - curr_long:.4f} thr={crossover_threshold:.6f})"
            )
            sl = bar.close + (0.002 * bar.close)
            tgt = bar.close - (0.003 * bar.close)
            size = self.get_risk_size(bar.close, sl)
            # Trend and signal confirmation (unified with ScalperStrategy)
            if trend_ok("SELL"):
                if getattr(settings, "SCALP_ENABLE_SIGNAL_CONFIRMATION", True):
                    logger.debug(f"Scalper {symbol}: Checking signal confirmation for SELL")
                    recent_bars, daily_ref = await self.service._confirmation_ctx(symbol, timeframe)
                    if not recent_bars:
                        logger.warning(f"Scalper {symbol}: No recent bars for SELL signal confirmation")
                        return
                    result = confirm_signal("SELL", ema_state, recent_bars, daily_ref, require_cpr=getattr(settings, "CONFIRMATION_REQUIRE_CPR", False))
                    if not result["confirmed"]:
                        logger.info(f"Scalper SELL signal rejected for {symbol}: {result['reasons']}")
                        return
                    logger.debug(f"Scalper {symbol}: SELL signal confirmed")
                logger.info(
                    f"Scalper SELL signal generated for {symbol} ts={getattr(bar,'ts',None)}: price={bar.close:.2f}, sl={sl:.2f}, tgt={tgt:.2f}, size={size} "
                    f"short={curr_short:.4f} long={curr_long:.4f} diff={curr_short-curr_long:.4f}"
                )
                # Underlying order execution (unified with ScalperStrategy)
                signal = Signal(symbol=symbol, side="SELL", price=bar.close, size=size, stop_loss=sl, target=tgt)
                if trade_underlying:
                    logger.debug(f"Scalper {symbol}: Executing underlying SELL order")
                    await self.service.executor.handle_signal(signal)
                await self.service.notifier.notify_signal(signal)
                # Option signal publication (unified with ScalperStrategy)
                if high_vol or is_index:
                    logger.debug(f"Scalper {symbol}: Publishing SELL signal to options manager")
                    if self.service.options_manager:
                        await self.service.options_manager.publish_underlying_signal(symbol=symbol, side="SELL", price=bar.close, timeframe=timeframe, origin="scalper")
