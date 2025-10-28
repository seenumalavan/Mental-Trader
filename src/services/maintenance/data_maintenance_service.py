"""
Data maintenance service for cleaning up old data and filling gaps.
Handles historical data cleanup and gap filling for continuous trading.
"""

import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

import pandas as pd

from src.config import settings
from src.persistence.db import Database, candles
from src.providers.broker_rest import BrokerRest
from src.utils.time_utils import IST

logger = logging.getLogger("data_maintenance")

@dataclass
class DataGap:
    """Represents a gap in historical data."""
    symbol: str
    instrument_key: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    expected_candles: int
    actual_candles: int

@dataclass
class MaintenanceStats:
    """Statistics from data maintenance operations."""
    gaps_filled: int
    candles_added: int
    candles_removed: int
    symbols_processed: int
    errors: List[str]

class DataMaintenanceService:
    """Service for maintaining historical data integrity."""

    def __init__(self):
        self.db = Database(settings.DATABASE_URL)
        self.broker_rest = None  # Will be initialized when needed
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Configuration
        self.data_retention_days = getattr(settings, 'DATA_RETENTION_DAYS', 90)  # Keep 90 days of data
        self.gap_fill_enabled = getattr(settings, 'GAP_FILL_ENABLED', True)
        self.cleanup_enabled = getattr(settings, 'CLEANUP_ENABLED', True)
        self.maintenance_interval_hours = getattr(settings, 'MAINTENANCE_INTERVAL_HOURS', 24)  # Daily

    async def start(self):
        """Start the data maintenance service."""
        if self._running:
            return

        await self.db.connect()
        self._running = True
        self._task = asyncio.create_task(self._maintenance_loop())

        logger.info("Data maintenance service started")

    async def stop(self):
        """Stop the data maintenance service."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        await self.db.disconnect()
        logger.info("Data maintenance service stopped")

    async def _maintenance_loop(self):
        """Main maintenance loop."""
        while self._running:
            try:
                await self.run_maintenance()
                await asyncio.sleep(self.maintenance_interval_hours * 3600)  # Convert hours to seconds
            except Exception as e:
                logger.error(f"Error in maintenance loop: {e}")
                await asyncio.sleep(3600)  # Wait 1 hour before retry

    async def run_maintenance(self, symbols: Optional[List[str]] = None) -> MaintenanceStats:
        """Run complete data maintenance cycle.

        Args:
            symbols: Specific symbols to maintain, or None for all symbols

        Returns:
            Maintenance statistics
        """
        if not self._running:
            raise RuntimeError("Data maintenance service is not running. Call start() first.")

        stats = MaintenanceStats(0, 0, 0, 0, [])

        try:
            # Get symbols to process
            if symbols is None:
                symbols = await self._get_all_symbols()

            stats.symbols_processed = len(symbols)
            logger.info(f"Starting data maintenance for {len(symbols)} symbols")

            for symbol in symbols:
                try:
                    await self._maintain_symbol_data(symbol, stats)
                except Exception as e:
                    error_msg = f"Failed to maintain data for {symbol}: {str(e)}"
                    logger.error(error_msg)
                    stats.errors.append(error_msg)

            logger.info(f"Data maintenance completed: {stats.gaps_filled} gaps filled, "
                       f"{stats.candles_added} candles added, {stats.candles_removed} candles removed")

        except Exception as e:
            error_msg = f"Data maintenance failed: {str(e)}"
            logger.error(error_msg)
            stats.errors.append(error_msg)

        return stats

    async def _get_all_symbols(self) -> List[str]:
        """Get all symbols that have data in the database."""
        try:
            return await self.db.get_all_symbols()
        except Exception as e:
            logger.error(f"Failed to get symbols: {e}")
            return []

    async def _maintain_symbol_data(self, symbol: str, stats: MaintenanceStats):
        """Maintain data for a specific symbol."""
        logger.debug(f"Maintaining data for {symbol}")

        # Get instrument keys for this symbol
        instrument_keys = await self._get_instrument_keys_for_symbol(symbol)
        if not instrument_keys:
            logger.warning(f"No instrument keys found for {symbol}")
            return

        for instrument_key in instrument_keys:
            # Clean up old data
            if self.cleanup_enabled:
                removed = await self._cleanup_old_data(symbol, instrument_key)
                stats.candles_removed += removed

            # Fill data gaps
            if self.gap_fill_enabled:
                gaps_filled, candles_added = await self._fill_data_gaps(symbol, instrument_key)
                stats.gaps_filled += gaps_filled
                stats.candles_added += candles_added

    async def _get_instrument_keys_for_symbol(self, symbol: str) -> List[str]:
        """Get all instrument keys for a symbol."""
        try:
            from sqlalchemy import select
            query = select(candles.c.instrument_key).where(candles.c.symbol == symbol).distinct()
            result = await self.db.execute(query)
            rows = result.fetchall()  # Remove await - fetchall() is synchronous
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Failed to get instrument keys for {symbol}: {e}")
            return []

    async def _cleanup_old_data(self, symbol: str, instrument_key: str) -> int:
        """Clean up data older than retention period.

        Returns number of candles removed.
        """
        if not self._running:
            raise RuntimeError("Data maintenance service is not running. Call start() first.")

        try:
            cutoff_date = datetime.now(IST) - timedelta(days=self.data_retention_days)

            # Get count before cleanup
            from sqlalchemy import select, func
            count_query = select(func.count()).where(
                (candles.c.symbol == symbol) & 
                (candles.c.instrument_key == instrument_key) & 
                (candles.c.ts < cutoff_date)
            )
            result = await self.db.execute(count_query)
            count_before = result.fetchone()[0]  # Remove await - fetchone() is synchronous

            if count_before > 0:
                # Delete old data
                from sqlalchemy import delete
                delete_query = delete(candles).where(
                    (candles.c.symbol == symbol) & 
                    (candles.c.instrument_key == instrument_key) & 
                    (candles.c.ts < cutoff_date)
                )
                await self.db.execute(delete_query)

                logger.info(f"Cleaned up {count_before} old candles for {symbol} ({instrument_key})")
                return count_before

        except Exception as e:
            logger.error(f"Failed to cleanup old data for {symbol} ({instrument_key}): {e}")

        return 0

    async def _fill_data_gaps(self, symbol: str, instrument_key: str) -> tuple[int, int]:
        """Fill gaps in historical data.

        Returns (gaps_filled, candles_added)
        """
        if not self._running:
            raise RuntimeError("Data maintenance service is not running. Call start() first.")

        gaps_filled = 0
        candles_added = 0

        try:
            # Get all timeframes for this symbol
            timeframes = await self._get_timeframes_for_symbol_instrument(symbol, instrument_key)

            for timeframe in timeframes:
                gaps = await self._find_data_gaps(symbol, instrument_key, timeframe)
                for gap in sorted(gaps, key=lambda g: g.start_date, reverse=True):
                    # Use intraday_service for intraday timeframes, else broker_rest
                    if gap.start_date.date() == pd.Timestamp.now(IST).date() and gap.end_date.date() == pd.Timestamp.now(IST).date():
                        logger.info(f"Skipping gap fill for {gap.symbol} ({gap.timeframe}) on current date {gap.start_date.date()}")
                        try:
                            if self.broker_rest is None:
                                from src.auth.token_store import get_token
                                access_token = get_token()
                                if access_token:
                                    self.broker_rest = BrokerRest(
                                        settings.UPSTOX_API_KEY,
                                        settings.UPSTOX_API_SECRET,
                                        access_token
                                    )
                                else:
                                    logger.warning("No access token available for gap filling")
                                    candles = []
                            if self.broker_rest:
                                candles = await self.broker_rest.fetch_intraday(
                                    gap.instrument_key,
                                    gap.timeframe
                                )
                            else:
                                candles = []
                        except Exception as e:
                            logger.error(f"IntradayService gap fill failed for {symbol} {timeframe}: {e}")
                            candles = []
                    else:
                        if self.broker_rest is None:
                            from src.auth.token_store import get_token
                            access_token = get_token()
                            if access_token:
                                self.broker_rest = BrokerRest(
                                    settings.UPSTOX_API_KEY,
                                    settings.UPSTOX_API_SECRET,
                                    access_token
                                )
                            else:
                                logger.warning("No access token available for gap filling")
                                candles = []
                        if self.broker_rest:
                            candles = await self.broker_rest.fetch_historical_date_range(
                                gap.instrument_key,
                                gap.timeframe,
                                gap.start_date,
                                gap.end_date
                            )
                        else:
                            candles = []

                    if candles:
                        await self.db.persist_candles_bulk(
                            gap.symbol,
                            gap.instrument_key,
                            gap.timeframe,
                            candles
                        )
                        logger.info(f"Filled gap for {gap.symbol} ({gap.timeframe}): {len(candles)} candles added")
                        gaps_filled += 1
                        candles_added += len(candles)

        except Exception as e:
            logger.error(f"Failed to fill data gaps for {symbol} ({instrument_key}): {e}")

        return gaps_filled, candles_added

    async def _get_timeframes_for_symbol_instrument(self, symbol: str, instrument_key: str) -> List[str]:
        """Get all timeframes for a symbol-instrument combination."""
        try:
            from sqlalchemy import select
            query = select(candles.c.timeframe).where(
                (candles.c.symbol == symbol) & 
                (candles.c.instrument_key == instrument_key)
            ).distinct()
            result = await self.db.execute(query)
            rows = result.fetchall()  # Remove await - fetchall() is synchronous
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Failed to get timeframes for {symbol} ({instrument_key}): {e}")
            return []

    async def _find_data_gaps(self, symbol: str, instrument_key: str, timeframe: str) -> List[DataGap]:
        """Find gaps in historical data for the last 30 days."""
        gaps = []

        try:
            # Get data for the last 90 days
            end_date = pd.Timestamp.now(IST)
            start_date = end_date - pd.Timedelta(days=settings.DATA_RETENTION_DAYS)

            from sqlalchemy import select
            # Fetch all timestamps for the period - let pandas handle date grouping
            query = select(candles.c.ts).where(
                (candles.c.symbol == symbol) & 
                (candles.c.instrument_key == instrument_key) & 
                (candles.c.timeframe == timeframe) &
                (candles.c.ts >= start_date) & 
                (candles.c.ts <= end_date)
            ).order_by(candles.c.ts.desc())
            
            result = await self.db.execute(query)
            rows = result.fetchall()

            # Use pandas to group by date and count
            if rows:
                timestamps = [row[0] for row in rows]
                df = pd.DataFrame({'ts': timestamps})
                df['date'] = pd.to_datetime(df['ts'], utc=False).dt.date
                date_counts = df.groupby('date').size().to_dict()
            else:
                date_counts = {}

            # Check each date for gaps
            current_date = start_date.date()
            end_date_only = end_date.date()

            while current_date <= end_date_only:
                # Skip weekends for equity data (adjust based on your market)

                if current_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
                    current_date += pd.Timedelta(days=1)
                    continue

                expected_candles = self._get_expected_candles_for_date(timeframe, current_date)
                actual_candles = date_counts.get(current_date, 0)

                # If we have significantly fewer candles than expected, consider it a gap
                if actual_candles < expected_candles * 0.8:  # Less than 80% of expected
                    gap_start = pd.Timestamp.combine(current_date, pd.Timestamp.min.time()).replace(tzinfo=IST)
                    gap_end = pd.Timestamp.combine(current_date, pd.Timestamp.max.time()).replace(tzinfo=IST)

                    if gap_start.date() == (end_date + timedelta(days=-1)).date():
                        gap_end += pd.Timedelta(days=1)

                    gaps.append(DataGap(
                        symbol=symbol,
                        instrument_key=instrument_key,
                        timeframe=timeframe,
                        start_date=gap_start,
                        end_date=gap_end,
                        expected_candles=expected_candles,
                        actual_candles=actual_candles
                    ))

                current_date += timedelta(days=1)

        except Exception as e:
            logger.error(f"Failed to find data gaps for {symbol} ({instrument_key}, {timeframe}): {e}")

        return gaps

    def _get_expected_candles_for_date(self, timeframe: str, date) -> int:
        """Get expected number of candles for a date based on timeframe."""
        # Indian market trading hours: 9:15 AM to 3:30 PM = 6.25 hours
        TRADING_HOURS_PER_DAY = 6.25

        if timeframe.endswith('m'):
            minutes = int(timeframe[:-1])
            trading_minutes = TRADING_HOURS_PER_DAY * 60
            # Use math.ceil for partial candles
            return math.ceil(trading_minutes / minutes)
        elif timeframe.endswith('h'):
            hours = int(timeframe[:-1])
            # Use math.ceil for partial candles
            return math.ceil(TRADING_HOURS_PER_DAY / hours)
        else:
            return 1  # Daily or other timeframes

    async def _fetch_and_store_gap_data(self, gap: DataGap) -> int:
        """Fetch and store data for a gap.

        Returns number of candles added.
        """
        try:
            # Initialize broker_rest if needed
            if self.broker_rest is None:
                from src.auth.token_store import get_token
                access_token = get_token()
                if access_token:
                    self.broker_rest = BrokerRest(
                        settings.UPSTOX_API_KEY,
                        settings.UPSTOX_API_SECRET,
                        access_token
                    )
                else:
                    logger.warning("No access token available for gap filling")
                    return 0

            # Fetch historical data for the gap period
            candles = await self.broker_rest.fetch_historical_date_range(
                gap.instrument_key,
                gap.timeframe,
                gap.start_date,
                gap.end_date
            )

            if candles:
                # Store the candles
                await self.db.persist_candles_bulk(
                    gap.symbol,
                    gap.instrument_key,
                    gap.timeframe,
                    candles
                )

                logger.info(f"Filled gap for {gap.symbol} ({gap.timeframe}): {len(candles)} candles added")
                return len(candles)

        except Exception as e:
            logger.error(f"Failed to fetch and store gap data for {gap.symbol}: {e}")

        return 0

    async def get_data_health_report(self, symbols: Optional[List[str]] = None) -> Dict:
        """Generate a data health report."""
        if not self._running:
            raise RuntimeError("Data maintenance service is not running. Call start() first.")

        report = {
            "total_symbols": 0,
            "symbols_with_gaps": 0,
            "total_gaps": 0,
            "oldest_data_date": None,
            "newest_data_date": None,
            "data_coverage_days": 0,
            "symbol_details": []
        }

        try:
            if symbols is None:
                symbols = await self._get_all_symbols()

            report["total_symbols"] = len(symbols)

            for symbol in symbols:
                symbol_report = await self._get_symbol_health_report(symbol)
                report["symbol_details"].append(symbol_report)

                if symbol_report["gaps_found"] > 0:
                    report["symbols_with_gaps"] += 1
                    report["total_gaps"] += symbol_report["gaps_found"]

                # Update date ranges
                if symbol_report["oldest_date"]:
                    if report["oldest_data_date"] is None or symbol_report["oldest_date"] < report["oldest_data_date"]:
                        report["oldest_data_date"] = symbol_report["oldest_date"]

                if symbol_report["newest_date"]:
                    if report["newest_data_date"] is None or symbol_report["newest_date"] > report["newest_data_date"]:
                        report["newest_data_date"] = symbol_report["newest_date"]

            # Calculate coverage
            if report["oldest_data_date"] and report["newest_data_date"]:
                report["data_coverage_days"] = (report["newest_data_date"] - report["oldest_data_date"]).days

        except Exception as e:
            logger.error(f"Failed to generate health report: {e}")

        return report

    async def _get_symbol_health_report(self, symbol: str) -> Dict:
        """Get health report for a specific symbol."""
        if not self._running:
            raise RuntimeError("Data maintenance service is not running. Call start() first.")

        report = {
            "symbol": symbol,
            "timeframes": [],
            "total_candles": 0,
            "gaps_found": 0,
            "oldest_date": None,
            "newest_date": None,
            "data_days": 0
        }

        try:
            instrument_keys = await self._get_instrument_keys_for_symbol(symbol)

            for instrument_key in instrument_keys:
                timeframes = await self._get_timeframes_for_symbol_instrument(symbol, instrument_key)

                for timeframe in timeframes:
                    # Get basic stats
                    from sqlalchemy import select, func
                    query = select(
                        func.count().label('count'),
                        func.min(candles.c.ts).label('oldest'),
                        func.max(candles.c.ts).label('newest')
                    ).where(
                        (candles.c.symbol == symbol) & 
                        (candles.c.instrument_key == instrument_key) & 
                        (candles.c.timeframe == timeframe)
                    )
                    result = await self.db.execute(query)
                    row = result.fetchone()  # Remove await - fetchone() is synchronous

                    if row[0] > 0:
                        report["total_candles"] += row[0]
                        report["timeframes"].append(timeframe)

                        if row[1]:  # oldest
                            if report["oldest_date"] is None or row[1] < report["oldest_date"]:
                                report["oldest_date"] = row[1]

                        if row[2]:  # newest
                            if report["newest_date"] is None or row[2] > report["newest_date"]:
                                report["newest_date"] = row[2]

                    # Check for gaps in recent data
                    gaps = await self._find_data_gaps(symbol, instrument_key, timeframe)
                    report["gaps_found"] += len(gaps)

            if report["oldest_date"] and report["newest_date"]:
                report["data_days"] = (report["newest_date"] - report["oldest_date"]).days

        except Exception as e:
            logger.error(f"Failed to get health report for {symbol}: {e}")

        return report
