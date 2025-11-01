import asyncio
import logging
from datetime import datetime

import pandas as pd
from pytz import timezone

from src.config import settings
from src.engine.intraday_strategy import IntradayStrategy
from src.services.strategies.base_service import ServiceBase
from src.services.risk_manager import RiskManager
from src.utils.time_utils import get_time_window, IST

logger = logging.getLogger("intraday_service")

def _minutes(tf: str) -> int:
    if tf.endswith('m'):
        try:
            return int(tf[:-1])
        except ValueError:
            return 1
    if tf.endswith('h'):
        try:
            return int(tf[:-1]) * 60
        except ValueError:
            return 60
    return 1

class IntradayService(ServiceBase):
    def __init__(self):
        super().__init__(
            primary_tf=settings.INTRADAY_PRIMARY_TIMEFRAME,
            confirm_tf=settings.INTRADAY_CONFIRM_TIMEFRAME,
            short_period=settings.INTRADAY_EMA_SHORT,
            long_period=settings.INTRADAY_EMA_LONG,
            warmup_bars=settings.WARMUP_BARS,
            persist_confirm_candles=False
        )
        self.risk_manager = RiskManager()
        # Backward compatibility
        self.ema_5m = self.ema_primary
        self.ema_15m = self.ema_confirm

    async def start(self, instrument_input=None):
        # Wait until the next timeframe boundary
        interval_minutes = _minutes(self.primary_tf)
        now = pd.Timestamp.now()
        current_minute = now.minute
        boundary_minute = ((current_minute // interval_minutes) + 1) * interval_minutes
        extra_hours = boundary_minute // 60
        boundary_minute %= 60
        next_boundary = now.replace(hour=now.hour + extra_hours, minute=boundary_minute, second=0, microsecond=0)
        delay_seconds = (next_boundary - now).total_seconds()
        if delay_seconds > 0:
            logger.info(f"Waiting {delay_seconds:.1f} seconds until next {interval_minutes}-minute boundary")
            await asyncio.sleep(delay_seconds)
        
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

    def can_trade(self, time_window: str) -> bool:
        """Check if we can trade based on monthly limits by counting actual trades from DB."""
        if not self.db or not self.db._connected:
            logger.warning("Database not available, allowing trade")
            return True
            
        try:
            # Get current month and year
            now = datetime.now()
            current_month = now.month
            current_year = now.year
            
            # Query both regular trades and option trades for current month
            regular_trades = self.db.get_trades_for_month(current_year, current_month)
            option_trades = self.db.get_option_trades_for_month(current_year, current_month)
            
            # Count trades by time window
            window_count = 0
            
            # Count regular trades
            for trade in regular_trades:
                trade_ts = trade.get('created_at')
                if trade_ts:
                    # Convert to string format for get_time_window
                    if isinstance(trade_ts, datetime):
                        ts_str = trade_ts.isoformat()
                    else:
                        ts_str = str(trade_ts)
                    
                    trade_window = get_time_window(ts_str)
                    if trade_window == time_window:
                        window_count += 1
            
            # Count option trades
            for trade in option_trades:
                trade_ts = trade.get('created_at')
                if trade_ts:
                    # Convert to string format for get_time_window
                    if isinstance(trade_ts, datetime):
                        ts_str = trade_ts.isoformat()
                    else:
                        ts_str = str(trade_ts)
                    
                    trade_window = get_time_window(ts_str)
                    if trade_window == time_window:
                        window_count += 1
            
            # Check limit
            limit_key = f"INTRADAY_MAX_TRADES_{time_window.upper()}_MONTHLY"
            limit = getattr(settings, limit_key, 0)
            
            if window_count >= limit:
                logger.info(f"Monthly trade limit reached for {time_window}: {window_count}/{limit}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error checking trade limits: {e}")
            # Allow trade on error to avoid blocking trading
            return True

    def increment_trade_count(self, time_window: str):
        """No-op: trade count is calculated from DB, not incremented."""
        pass

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
                } for c in candles]
            
            # Get previous day OHLC for CPR calculation by resampling minute data to daily
            daily_ref = {"prev_high": None, "prev_low": None, "prev_close": None}
            day_candles = self.day_candles.get(symbol, [])
            if day_candles:
                df_day = pd.DataFrame(day_candles)
                if not df_day.empty:
                    prev_day = df_day.iloc[-1]  # last row
                    daily_ref = {
                        "prev_high": prev_day['high'],
                        "prev_low": prev_day['low'],
                        "prev_close": prev_day['close']
                    }
            return recent_bars, daily_ref
        except Exception as e:
            logger.warning(f"Failed to get confirmation context for {symbol}: {e}")
            return [], {"prev_high": None, "prev_low": None, "prev_close": None}

    def build_strategy(self):
        return IntradayStrategy(
            self,
            primary_tf=self.primary_tf,
            confirm_tf=self.confirm_tf,
            short_period=self.short_period,
            long_period=self.long_period
        )
