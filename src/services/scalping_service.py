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

    async def _confirmation_ctx(self, symbol: str, timeframe: str):
        """Provide context for signal confirmation: recent bars and previous day reference."""
        try:
            import pandas as pd
            # Get recent bars for RSI/price action analysis
            recent_bars = []
            key = self.symbol_to_key.get(symbol, symbol)
            candles = await self.db.load_candles(symbol, key, timeframe, limit=settings.CONFIRMATION_RECENT_BARS)
            if candles:
                recent_bars = [{
                    'close': c['close'],
                    'open': c['open'],
                    'high': c['high'],
                    'low': c['low'],
                    'volume': c['volume']
                } for c in candles[-settings.CONFIRMATION_RECENT_BARS:]]
            
            # Get previous day OHLC for CPR calculation by resampling minute data to daily
            daily_ref = {"prev_high": None, "prev_low": None, "prev_close": None}
            # Use the same candles loaded for RSI, resample to daily
            # Calculate minimum candles needed: ~375 minutes per trading day * 2 days
            if timeframe.endswith('m'):
                timeframe_minutes = int(timeframe.rstrip('m'))
            elif timeframe.endswith('h'):
                timeframe_minutes = int(timeframe.rstrip('h')) * 60
            else:
                timeframe_minutes = 1  # fallback
            min_candles_needed = (375 // timeframe_minutes) * 2  # At least 2 trading days worth
            logger.debug(f"Timeframe {timeframe}: {timeframe_minutes}min, need {min_candles_needed} candles for 2 days")
            if candles and len(candles) > min_candles_needed:
                df = pd.DataFrame(candles)
                df['parsed_ts'] = pd.to_datetime(df['ts'], errors='coerce', utc=False)
                df = df.dropna(subset=['parsed_ts'])
                df = df.set_index('parsed_ts').sort_index()
                # Resample to daily
                daily_agg = df.resample('D').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna(subset=['open', 'close'])
                daily_list = daily_agg.reset_index().to_dict('records')
                if len(daily_list) >= 2:
                    # Second to last is previous day
                    prev_day = daily_list[-2]
                    daily_ref = {
                        "prev_high": prev_day['high'],
                        "prev_low": prev_day['low'],
                        "prev_close": prev_day['close']
                    }
            
            return recent_bars, daily_ref
        except Exception as e:
            logger.warning(f"Failed to get confirmation context for {symbol}: {e}")
            return [], {"prev_high": None, "prev_low": None, "prev_close": None}

    def status(self):
        s = super().status()
        s['symbols'] = s.pop('symbols_primary')
        s['confirm_symbols'] = s.pop('symbols_confirm')
        return s

    def build_strategy(self):
        return ScalpStrategy(self)
