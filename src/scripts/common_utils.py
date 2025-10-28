"""Shared utility functions for script-level backtests/diagnostics.

Consolidates duplicated logic previously spread across:
  - backtest_scalper_day.py
  - backtest_scalper_service_day.py
  - diagnose_scalper_crossovers.py

Provides:
  autodetect_instrument_key(db, symbol, timeframe) -> str
  load_warmup_and_day(db, symbol, instrument_key, timeframe, day, warmup) -> (warmup_rows, day_rows)
  aggregate_timeframe(rows, target_minutes, source_minutes) -> List[Dict]
  write_csv(path, fieldnames, rows)

All functions are intentionally lightweight and synchronous (DB access uses SQLAlchemy connection blocks).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Sequence

from sqlalchemy import text

from src.persistence.db import Database, candles as candles_table

# ---------------------------------------------------------------------------
# Instrument key autodetection
# ---------------------------------------------------------------------------

def autodetect_instrument_key(db: Database, symbol: str, timeframe: str) -> str:
    """Return the most common instrument_key for (symbol,timeframe) from candles.

    Raises RuntimeError if none found.
    """
    if candles_table is None or db.engine is None:
        raise RuntimeError("Database not initialized")
    q = text(
        """
        SELECT instrument_key, COUNT(*) AS cnt
        FROM candles
        WHERE symbol=:symbol AND timeframe=:tf
        GROUP BY instrument_key
        ORDER BY cnt DESC
        LIMIT 1
        """
    )
    with db.engine.connect() as conn:
        row = conn.execute(q, {"symbol": symbol, "tf": timeframe}).fetchone()
        if not row:
            raise RuntimeError(f"No instrument_key found for symbol={symbol} timeframe={timeframe}")
        return row.instrument_key

# ---------------------------------------------------------------------------
# Warmup + day candle loading
# ---------------------------------------------------------------------------

def load_warmup_and_day(
    db: Database,
    symbol: str,
    instrument_key: str,
    timeframe: str,
    day: datetime,
    warmup: int,
) -> Tuple[List[Dict], List[Dict]]:
    """Load warmup (preceding) candles and trading day candles.

    Returns (warmup_rows, day_rows) chronologically ascending.
    """
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    warmup_rows: List[Dict] = []
    if warmup > 0:
        q_warm = text(
            """
            SELECT symbol, instrument_key, timeframe, ts, open, high, low, close, volume
            FROM candles
            WHERE symbol=:symbol AND instrument_key=:ik AND timeframe=:tf AND ts < :start
            ORDER BY ts DESC
            LIMIT :lim
            """
        )
        with db.engine.connect() as conn:
            res = conn.execute(
                q_warm,
                {"symbol": symbol, "ik": instrument_key, "tf": timeframe, "start": start, "lim": warmup},
            )
            warmup_rows = [dict(r._mapping) for r in res.fetchall()][::-1]
    q_day = text(
        """
        SELECT symbol, instrument_key, timeframe, ts, open, high, low, close, volume
        FROM candles
        WHERE symbol=:symbol AND instrument_key=:ik AND timeframe=:tf AND ts >= :start AND ts < :end
        ORDER BY ts ASC
        """
    )
    with db.engine.connect() as conn:
        res = conn.execute(
            q_day, {"symbol": symbol, "ik": instrument_key, "tf": timeframe, "start": start, "end": end}
        )
        day_rows = [dict(r._mapping) for r in res.fetchall()]
    return warmup_rows, day_rows

# ---------------------------------------------------------------------------
# Timeframe aggregation (e.g. 1m -> 5m) using pandas resample semantics.
# ---------------------------------------------------------------------------

def aggregate_timeframe(rows: Sequence[Dict], target_minutes: int, source_minutes: int) -> List[Dict]:
    """Aggregate source timeframe rows into target timeframe bars.

    If target == source, returns list(rows) copy.
    Rows must contain 'ts','open','high','low','close','volume'. Timestamps can be str ISO or datetime.
    """
    if target_minutes == source_minutes:
        return list(rows)
    try:
        import pandas as pd  # local import; pandas is already a dependency elsewhere
    except ImportError:  # pragma: no cover
        raise RuntimeError("pandas required for timeframe aggregation but not installed")
    import pandas as pd  # type: ignore
    df = pd.DataFrame(rows)
    if df.empty:
        return []
    df['parsed_ts'] = pd.to_datetime(df['ts'], errors='coerce', utc=False)
    df = df.dropna(subset=['parsed_ts']).set_index('parsed_ts').sort_index()
    rule = f"{target_minutes}T"
    agg = (
        df.resample(rule)
        .agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'})
        .dropna(subset=['open', 'close'])
    )
    out: List[Dict] = []
    for ts_idx, row in agg.iterrows():
        out.append(
            {
                'ts': ts_idx.isoformat(),
                'open': float(row.open),
                'high': float(row.high),
                'low': float(row.low),
                'close': float(row.close),
                'volume': int(row.volume),
            }
        )
    return out

# ---------------------------------------------------------------------------
# CSV writing helper
# ---------------------------------------------------------------------------

def write_csv(path: str, fieldnames: Sequence[str], rows: Sequence[Dict]):
    """Write iterable of dict rows to CSV if non-empty."""
    if not rows:
        return
    import csv
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

__all__ = [
    'autodetect_instrument_key',
    'load_warmup_and_day',
    'aggregate_timeframe',
    'write_csv',
]
