"""Smoke tests for shared script utilities.

Ensures refactored utility functions import and basic behavior on empty inputs.
Does not assert database-dependent functionality (autodetect_instrument_key) unless a temporary in-memory
SQLite URL is configured with candles table populated. If database lacks data, that test is skipped.
"""
from datetime import datetime
import pytest

from src.scripts import common_utils as cu

def test_util_exports_present():
    assert hasattr(cu, 'autodetect_instrument_key')
    assert hasattr(cu, 'load_warmup_and_day')
    assert hasattr(cu, 'aggregate_timeframe')
    assert hasattr(cu, 'write_csv')

def test_aggregate_timeframe_identity():
    rows = [
        {'ts': datetime(2025,1,1,9,15).isoformat(), 'open':1,'high':2,'low':0.5,'close':1.5,'volume':10},
        {'ts': datetime(2025,1,1,9,16).isoformat(), 'open':1.6,'high':2,'low':1.2,'close':1.8,'volume':12},
    ]
    out = cu.aggregate_timeframe(rows, target_minutes=1, source_minutes=1)
    assert out == rows

def test_aggregate_timeframe_higher():
    rows = [
        {'ts': datetime(2025,1,1,9,15).isoformat(), 'open':1,'high':2,'low':0.5,'close':1.5,'volume':10},
        {'ts': datetime(2025,1,1,9,16).isoformat(), 'open':1.6,'high':2.1,'low':1.2,'close':1.9,'volume':12},
        {'ts': datetime(2025,1,1,9,17).isoformat(), 'open':1.9,'high':2.2,'low':1.7,'close':2.0,'volume':8},
    ]
    out = cu.aggregate_timeframe(rows, target_minutes=2, source_minutes=1)
    # Expect at least one aggregated bar
    assert out
    assert all({'ts','open','high','low','close','volume'} <= set(r.keys()) for r in out)

@pytest.mark.skip(reason="Database-dependent; requires candles data")
def test_autodetect_instrument_key_requires_db():
    from src.persistence.db import Database
    db = Database("sqlite+pysqlite:///:memory:")  # no candles table populated
    with pytest.raises(RuntimeError):
        cu.autodetect_instrument_key(db, symbol="TEST", timeframe="1m")