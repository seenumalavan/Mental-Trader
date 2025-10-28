import logging
from typing import Any

from src.config import settings
from src.engine.signal_confirmation import confirm_signal
from src.engine.trend_filter import higher_timeframe_trend_ok
from src.execution.execution import Signal

logger = logging.getLogger("base_strategy")

class BaseStrategy:
    @staticmethod
    def get_scale_for_timeframe(primary_tf: str) -> float:
        """Return scale value based on timeframe: 0.004 for 5m/10m, 0.008 for 15m, else 0.006."""
        if primary_tf in ("5m", "10m"):
            return 0.004
        elif primary_tf == "15m":
            return 0.008
        else:
            return 0.006
    def __init__(self, service):
        self.service = service
        self.bar_count = {}

    def get_symbol_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol}_{timeframe}"

    def should_skip_warmup(self, symbol_key: str, warmup_bars: int) -> bool:
        self.bar_count[symbol_key] = self.bar_count.get(symbol_key, 0) + 1
        return self.bar_count[symbol_key] <= warmup_bars

    @staticmethod
    def get_crossover_threshold(bar_close: float) -> float:
        return bar_close * 0.0001  # 0.01% of current price

    @staticmethod
    def is_index(symbol: str) -> bool:
        return symbol.startswith("NSE_INDEX")

    @staticmethod
    def get_high_vol(ema_state, bar_close: float, is_index: bool) -> bool:
        if is_index:
            return False
        atr = getattr(ema_state, "atr", None)
        return atr is not None and atr > 0.02 * bar_close

    @staticmethod
    def get_trade_underlying(is_index: bool, high_vol: bool) -> bool:
        return not is_index and not high_vol

    def get_risk_size(self, bar_close: float, sl: float) -> int:
        risk_mgr = getattr(self.service, 'risk_manager', None)
        size = 1
        if risk_mgr:
            size_calc = risk_mgr.calc_size(bar_close, sl)
            logger.debug(f"Risk manager calculated size {size_calc} for price {bar_close:.2f}, sl {sl:.2f}")
            if size_calc > 0:
                size = size_calc
        return size
