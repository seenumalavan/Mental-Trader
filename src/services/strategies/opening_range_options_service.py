import logging
from typing import Any

from src.config import settings
from src.services.strategies.base_service import ServiceBase
from src.engine.opening_range_breakout_strategy import OpeningRangeBreakoutStrategy

logger = logging.getLogger("opening_range_service")


class OpeningRangeOptionsService(ServiceBase):
    """Service wiring OpeningRangeBreakoutStrategy (options-only breakout).

    Differences vs other services:
      - Only primary timeframe used (configured via OPENING_RANGE_TIMEFRAME).
      - Confirmation timeframe logic disabled.
      - Emits ONLY option signals (no underlying trades) utilizing shared OptionsManager.
    """

    def __init__(self):
        super().__init__(
            primary_tf=settings.OPENING_RANGE_TIMEFRAME,
            confirm_tf=settings.OPENING_RANGE_TIMEFRAME,  # same to disable confirm aggregation
            short_period=0,  # EMA not required
            long_period=0,
            warmup_bars=0,   # No EMA warmup needed; bars collected manually for range
            persist_confirm_candles=False,
            enable_ema=False  # Disable all EMA logic in base service
        )
        # EMA maps already empty due to enable_ema=False; no additional clearing required.

    async def start(self, instrument_input=None):  # type: ignore[override]
        if not settings.OPENING_RANGE_ENABLED:
            logger.warning("OpeningRangeOptionsService start requested but OPENING_RANGE_ENABLED is False")
            return
        await super().start(instrument_input)
        # Bind option chain provider instrument immediately (first resolved instrument)
        if self.options_manager and self.options_manager.provider and not self.options_manager.provider.instrument_symbol:
            try:
                first_symbol = next(iter(self.symbol_to_key.values()), None)
                if first_symbol:
                    self.options_manager.provider.set_instrument(first_symbol)
                    logger.info("OpeningRange service bound option chain instrument=%s on start", first_symbol)
            except Exception:
                logger.exception("Failed binding option chain instrument on start")
        logger.info("OpeningRangeOptionsService started timeframe=%s", self.primary_tf)

    def build_strategy(self):
        return OpeningRangeBreakoutStrategy(self, primary_tf=self.primary_tf)

    async def _on_tick(self, tick: Any):  # type: ignore[override]
        """Override tick to skip EMA updates, only bar building then strategy call."""
        # Dynamic instrument binding (in case start binding failed or multiple symbols)
        if self.options_manager and self.options_manager.provider and not self.options_manager.provider.instrument_symbol:
            sym = tick.get('instrument_key') or tick.get('symbol')
            if sym:
                self.options_manager.provider.set_instrument(sym)
                logger.info("OpeningRange service bound option chain instrument from tick=%s", sym)
        closed = self.bar_builder.push_tick(tick)
        for symbol, tf, bar in closed:
            # ensure instrument key mapping
            key = self.symbol_to_key.get(symbol, symbol)
            if tf != self.primary_tf:
                continue
            if self.strategy:
                await self.strategy.on_bar_close(symbol, key, tf, bar, None, None)
            # persist raw candle
            try:
                await self.db.persist_candle(symbol, key, tf, bar)
            except Exception:
                logger.exception("Failed to persist candle for %s", symbol)

    def status(self):  # type: ignore[override]
        base = super().status()
        base['type'] = 'opening_range'
        return base
