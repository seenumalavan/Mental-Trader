"""Tests for performance simulation logic in unified backtest scripts.

We simulate deterministic bar sequences so that:
 - A BUY trade hits target
 - A SELL trade hits stop

This validates R multiple and win/loss classification.
"""
from datetime import datetime, timedelta

from src.scripts.backtest_scalper import simulate_performance as scalper_sim
from src.scripts.backtest_intraday import simulate_performance as intraday_sim


def _make_rows(start_price: float = 100.0):
    # Create 10 sequential minute bars
    base = datetime(2025,1,1,9,15)
    rows = []
    price = start_price
    for i in range(10):
        # simple ascending then descending pattern
        open_p = price
        high_p = price * 1.003
        low_p = price * 0.997
        close_p = price * (1.001 if i < 5 else 0.999)
        rows.append({
            'ts': base + timedelta(minutes=i),
            'open': open_p,
            'high': high_p,
            'low': low_p,
            'close': close_p,
            'volume': 1000,
        })
        price = close_p
    return rows

def test_scalper_simulation_win_loss():
    rows = _make_rows()
    # Two signals: BUY then SELL
    entry_buy = rows[1]['close']
    stop_buy = entry_buy * 0.998  # 0.2% risk
    target_buy = entry_buy * 1.003  # 0.3% reward (should hit via high)
    entry_sell = rows[2]['close']
    stop_sell = entry_sell * 1.002  # 0.2% risk
    target_sell = entry_sell * 0.997  # 0.3% reward (unlikely before stop in ascending first half)
    signals = [
        {'ts': str(rows[1]['ts']), 'side':'BUY','price':entry_buy,'stop_loss':stop_buy,'target':target_buy},
        {'ts': str(rows[2]['ts']), 'side':'SELL','price':entry_sell,'stop_loss':stop_sell,'target':target_sell},
    ]
    metrics = asyncio_run(scalper_sim(rows, signals))
    assert metrics['trades'] == 2
    assert metrics['wins'] == 1
    assert metrics['losses'] == 1
    assert 0.45 < metrics['win_rate'] < 0.55  # ~0.5

def test_intraday_simulation_win_loss():
    rows = _make_rows(200.0)
    entry_buy = rows[1]['close']
    stop_buy = entry_buy * 0.998
    target_buy = entry_buy * 1.003
    signals = [
        {'ts': str(rows[1]['ts']), 'side':'BUY','price':entry_buy,'stop_loss':stop_buy,'target':target_buy},
    ]
    metrics = asyncio_run(intraday_sim(rows, signals))
    assert metrics['wins'] == 1
    assert metrics['losses'] == 0

# Helper for awaiting coroutine without importing asyncio in each test
import asyncio
def asyncio_run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)