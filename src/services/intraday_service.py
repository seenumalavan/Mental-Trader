import logging
from src.config import settings
from src.engine.intraday_strategy import IntradayStrategy
from src.services.risk_manager import RiskManager
from src.services.base_dual_timeframe_service import DualTimeframeServiceBase

logger = logging.getLogger("intraday_service")

class IntradayService(DualTimeframeServiceBase):
    def __init__(self):
        super().__init__(
            primary_tf=settings.INTRADAY_PRIMARY_TIMEFRAME,
            confirm_tf=settings.INTRADAY_CONFIRM_TIMEFRAME,
            short_period=settings.EMA_SHORT,
            long_period=settings.EMA_LONG,
            warmup_bars=settings.WARMUP_BARS,
            persist_confirm_candles=False
        )
        self.risk_manager = RiskManager()
        # Backward compatibility
        self.ema_5m = self.ema_primary
        self.ema_15m = self.ema_confirm

    async def start(self, instrument_input=None):
        await super().start(instrument_input)
        logger.info("IntradayService started")

    async def stop(self):
        logger.info("Stopping IntradayService")
        await super().stop()

    async def _on_tick(self, tick):
        await super()._on_tick(tick)

    def status(self):
        s = super().status()
        s['symbols'] = s.get('symbols_primary', [])
        return s

    def build_strategy(self):
        return IntradayStrategy(
            self,
            primary_tf=self.primary_tf,
            confirm_tf=self.confirm_tf,
            short_period=self.short_period,
            long_period=self.long_period
        )
