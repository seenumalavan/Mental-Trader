import logging
from src.config import settings
from src.engine.scalping_strategy import ScalpStrategy
from src.services.base_dual_timeframe_service import DualTimeframeServiceBase

logger = logging.getLogger("service")

class ScalperService(DualTimeframeServiceBase):
    def __init__(self):
        super().__init__(
            primary_tf=settings.SCALP_PRIMARY_TIMEFRAME,
            confirm_tf=settings.SCALP_CONFIRM_TIMEFRAME,
            short_period=settings.EMA_SHORT,
            long_period=settings.EMA_LONG,
            warmup_bars=settings.WARMUP_BARS,
            persist_confirm_candles=False
        )
        # Backward compatibility alias
        self.ema_states = self.ema_primary
        self._task = None

    async def start(self, instrument_input=None):
        await super().start(instrument_input)
        logger.info("ScalperService started")

    async def stop(self):
        logger.info("Stopping ScalperService")
        await super().stop()

    async def _on_tick(self, tick):
        await super()._on_tick(tick)

    def _confirmation_ctx(self, symbol: str, timeframe: str):
        return [], {"prev_high": None, "prev_low": None, "prev_close": None}

    def status(self):
        s = super().status()
        s['symbols'] = s.pop('symbols_primary')
        s['confirm_symbols'] = s.pop('symbols_confirm')
        return s

    def build_strategy(self):
        return ScalpStrategy(self)
