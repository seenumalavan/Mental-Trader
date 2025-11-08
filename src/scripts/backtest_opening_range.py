"""Opening Range Breakout backtest (end-to-end).

This version instantiates the real OpeningRangeBreakoutStrategy plus OptionsManager to run
confirmation logic (CPR, PA, OI change) exactly as in production code, instead of a custom harness.

Workflow:
  1. Load timeframe bars for the requested trading date.
  2. Fetch previous day daily candle and inject into a lightweight service stub for CPR.
  3. Create a synthetic or live option chain provider. Synthetic provider returns OptionContract objects
     and inflates OI near ATM after a breakout to satisfy OI change confirmation.
  4. Feed bars sequentially to strategy.on_bar_close; capture emitted OptionSignal via OptionsManager callback.
  5. Support modes: replay (default), range (dump collection & post-range phases), performance (simple R multiple sim).

CLI flags --disable-cpr / --disable-pa temporarily override settings before strategy creation.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Any, Optional
import sys
import logging

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.auth.token_store import get_token
from src.providers.broker_rest import BrokerRest
from src.providers.options_chain_provider import OptionsChainProvider
from src.services.options.options_manager import OptionsManager
from src.utils.instruments import get_symbol_to_key_mapping
from src.engine.opening_range_breakout_strategy import OpeningRangeBreakoutStrategy
from src.utils.time_utils import now_ist

# ---------------- CLI -----------------

def parse_args():
    p = argparse.ArgumentParser(description="Opening Range (first 15m) options breakout backtest")
    p.add_argument('--symbol', required=True)
    p.add_argument('--date', required=True, help='YYYY-MM-DD trading day')
    p.add_argument('--timeframe', default=settings.OPENING_RANGE_TIMEFRAME, help='Primary timeframe (default settings.OPENING_RANGE_TIMEFRAME)')
    p.add_argument('--instrument-key', dest='instrument_key', help='Override instrument key (autodetect if omitted)')
    p.add_argument('--mode', choices=['replay','range','performance'], default='replay')
    p.add_argument('--output', help='CSV output path (range/replay events)')
    p.add_argument('--report', help='JSON performance report output (performance mode)')
    p.add_argument('--disable-cpr', action='store_true', help='Disable CPR confirmation')
    p.add_argument('--disable-pa', action='store_true', help='Disable basic price action confirmation')
    p.add_argument('--oi-threshold', type=float, default=None, help='Override minimum OI change % required')
    p.add_argument('--live-chain', action='store_true', help='Use live option chain provider (requires valid token)')
    p.add_argument('--synthetic-chain-size', type=int, default=9, help='Synthetic strikes around ATM when not live')
    return p.parse_args()

# (Synthetic option chain removed: backtest now always uses live chain provider.)

# ------------- Harness Service Stub -------------

class _ServiceStub:
    """Minimal surface needed by OpeningRangeBreakoutStrategy for backtesting."""
    def __init__(self, rest: BrokerRest, symbol: str, instrument_key: str, option_provider):
        self.rest = rest
        self.symbol_to_key = {symbol: instrument_key}
        self.day_candles: Dict[str, List[Dict[str, Any]]] = {}
        self._captured: List[Dict[str, Any]] = []

        async def emit_callback(opt_signal):
            self._captured.append({
                'timestamp': getattr(opt_signal, 'timestamp', None),
                'side': getattr(opt_signal, 'underlying_side', None),
                'price': getattr(opt_signal, 'premium_ltp', None),
                'contract': getattr(opt_signal, 'contract_symbol', None),
                'lots': getattr(opt_signal, 'suggested_size_lots', None),
            })
        self.options_manager = OptionsManager(option_provider, config={
            'OPTION_ENABLE': True,
            'OPTION_LOT_SIZE': settings.OPTION_LOT_SIZE,
            'OPTION_RISK_CAP_PER_TRADE': settings.OPTION_RISK_CAP_PER_TRADE,
            'OPTION_OI_MIN_PERCENTILE': settings.OPTION_OI_MIN_PERCENTILE,
            'OPTION_SPREAD_MAX_PCT_SCALPER': settings.OPTION_SPREAD_MAX_PCT_SCALPER,
            'OPTION_SPREAD_MAX_PCT_INTRADAY': settings.OPTION_SPREAD_MAX_PCT_INTRADAY,
            'OPTION_DEBOUNCE_SEC': settings.OPTION_DEBOUNCE_SEC,
            'OPTION_DEBOUNCE_INTRADAY_SEC': settings.OPTION_DEBOUNCE_INTRADAY_SEC,
            'OPTION_COOLDOWN_SEC': settings.OPTION_COOLDOWN_SEC,
        }, emit_callback=emit_callback)

    @property
    def captured_signals(self):
        return self._captured

# ------------- Data Loading -------------

async def load_timeframe_bars(rest: BrokerRest, instrument_key: str, timeframe: str, day: datetime) -> List[Dict[str, Any]]:
    """Fetch candles for a specific date and timeframe using historical date-range API.

    Only returns bars whose timestamp date matches 'day'. Does not rely on local DB.
    """
    from_dt = datetime(day.year, day.month, day.day)
    to_dt = from_dt  # single-day range
    data = await rest.fetch_historical_date_range(instrument_key, timeframe, from_dt, to_dt)
    rows: List[Dict[str, Any]] = []
    for c in data:
        try:
            ts = datetime.fromisoformat(str(c['ts']))
        except Exception:
            continue
        if ts.date() != from_dt.date():
            continue
        rows.append({'ts': ts.isoformat(), 'open': c['open'], 'high': c['high'], 'low': c['low'], 'close': c['close'], 'volume': c.get('volume', 0)})
    rows.sort(key=lambda r: r['ts'])
    return rows

def _prev_day_from_daily(daily: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return daily[0] if daily else None

# ------------- Performance Simulation -------------

@dataclass
class PerfResult:
    side: str
    entry_ts: str
    entry_price: float
    stop: float
    target: float
    exit_ts: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: Optional[str] = None
    r_multiple: Optional[float] = None

def simulate_performance(rows: List[Dict[str, Any]], signal: Dict[str, Any]) -> PerfResult:
    side = signal['side']
    entry_ts = signal['timestamp'] or signal.get('ts') or ''
    entry_price = signal['price'] or 0.0
    stop = entry_price * (0.997 if side == 'BUY' else 1.003)
    target = entry_price * (1.006 if side == 'BUY' else 0.994)
    res = PerfResult(side, entry_ts, entry_price, stop, target)
    after = False
    for r in rows:
        if str(r['ts']) == entry_ts:
            after = True
            continue
        if not after:
            continue
        high = r['high']; low = r['low']
        if side == 'BUY':
            if low <= stop:
                res.exit_ts = str(r['ts']); res.exit_price = stop; res.outcome = 'LOSS'; res.r_multiple = -1.0; break
            if high >= target:
                res.exit_ts = str(r['ts']); res.exit_price = target; res.outcome = 'WIN'; res.r_multiple = (target-entry_price)/(entry_price-stop); break
        else:
            if high >= stop:
                res.exit_ts = str(r['ts']); res.exit_price = stop; res.outcome = 'LOSS'; res.r_multiple = -1.0; break
            if low <= target:
                res.exit_ts = str(r['ts']); res.exit_price = target; res.outcome = 'WIN'; res.r_multiple = (entry_price-target)/(stop-entry_price); break
    return res

# ------------- Main Replay Logic -------------

@dataclass
class Bar:
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float

async def run(args):
    trade_day_dt = datetime.strptime(args.date, '%Y-%m-%d')
    symbol = args.symbol
    timeframe = args.timeframe
    if timeframe != '5m':
        print(f"WARNING: Opening range is designed for 5m; using {timeframe} anyway.")

    access_token = get_token()
    rest = BrokerRest(settings.UPSTOX_API_KEY, settings.UPSTOX_API_SECRET, access_token=access_token)

    # Instrument key resolution: provided -> mapping fallback
    if args.instrument_key:
        instrument_key = args.instrument_key
    else:
        mapping = get_symbol_to_key_mapping()
        instrument_key = mapping.get(symbol, symbol)

    tf_rows = await load_timeframe_bars(rest, instrument_key, timeframe, trade_day_dt)
    if not tf_rows:
        print("No candles for date from API")
        return 1

    # Live option chain provider (always). Warn if backtesting past dates since historical chain snapshots aren't available.
    trade_is_today = datetime.utcnow().date() == trade_day_dt.date()
    if not trade_is_today:
        print("WARNING: Historical option chain snapshots not available; using current live chain which may not reflect past OI/IV.")
    rest_live = BrokerRest(settings.UPSTOX_API_KEY, settings.UPSTOX_API_SECRET, access_token=get_token())
    option_provider = OptionsChainProvider(rest_live, instrument_key)

    service = _ServiceStub(rest, symbol, instrument_key, option_provider)
    # Override settings if flags provided (temporary adjustments)
    original_cpr = settings.OPENING_RANGE_REQUIRE_CPR
    original_pa = settings.OPENING_RANGE_REQUIRE_PRICE_ACTION
    original_oi = settings.OPENING_RANGE_MIN_OI_CHANGE_PCT
    if args.disable_cpr:
        settings.OPENING_RANGE_REQUIRE_CPR = False
    if args.disable_pa:
        settings.OPENING_RANGE_REQUIRE_PRICE_ACTION = False
    if args.oi_threshold is not None:
        settings.OPENING_RANGE_MIN_OI_CHANGE_PCT = args.oi_threshold
    try:
        # Previous day candle for CPR list
        try:
            daily = await rest.fetch_historical(instrument_key, '1d', limit=3)
        except Exception:
            daily = []
        prev_day = _prev_day_from_daily(daily)
        if prev_day:
            service.day_candles[symbol] = [prev_day]
        strategy = OpeningRangeBreakoutStrategy(service, primary_tf=timeframe)
    finally:
        # Restore settings (strategy already captured values)
        settings.OPENING_RANGE_REQUIRE_CPR = original_cpr
        settings.OPENING_RANGE_REQUIRE_PRICE_ACTION = original_pa
        settings.OPENING_RANGE_MIN_OI_CHANGE_PCT = original_oi

    events: List[Dict[str, Any]] = []
    sym_state = strategy._get_symbol_state(symbol)
    for r in tf_rows:
        b = Bar(ts=str(r['ts']), open=r['open'], high=r['high'], low=r['low'], close=r['close'], volume=r['volume'])
        await strategy.on_bar_close(symbol, instrument_key, timeframe, b, None, None)
        phase = 'collect'
        if sym_state['range_complete']:
            phase = 'post_range'
        if sym_state['signals_emitted'] > 0:
            phase = 'signal'
        events.append({'ts': b.ts, 'close': b.close, 'phase': phase, 'range_high': sym_state.get('range_high'), 'range_low': sym_state.get('range_low'), 'range_complete': int(sym_state['range_complete'])})
        if phase == 'signal':
            break

    # Output handling
    captured = service.captured_signals
    if args.mode == 'range':
        rng_rows = [e for e in events if e['phase'] in ('collect','post_range')]
        if args.output and rng_rows:
            with open(args.output, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=rng_rows[0].keys())
                w.writeheader(); w.writerows(rng_rows)
            print(f"Wrote {len(rng_rows)} range rows to {args.output}")
        else:
            print('ts,close,phase,range_high,range_low,range_complete')
            for e in rng_rows:
                print(f"{e['ts']},{e['close']},{e['phase']},{e.get('range_high')},{e.get('range_low')},{e.get('range_complete')}")
    elif args.mode == 'performance':
        if captured:
            perf = simulate_performance(tf_rows, captured[0])
            report = {
                'symbol': symbol,
                'date': args.date,
                'side': perf.side,
                'entry_ts': perf.entry_ts,
                'entry_price': perf.entry_price,
                'stop': perf.stop,
                'target': perf.target,
                'exit_ts': perf.exit_ts,
                'exit_price': perf.exit_price,
                'outcome': perf.outcome,
                'r_multiple': perf.r_multiple,
            }
            if args.report:
                with open(args.report, 'w', encoding='utf-8') as fh:
                    json.dump(report, fh, indent=2)
            print(json.dumps(report, indent=2))
        else:
            print('No signal emitted; performance report skipped')
    else:  # replay
        if captured:
            sig = captured[0]
            print(f"Signal: {sig['side']} contract={sig['contract']} price={sig['price']} ts={sig['timestamp']}")
        else:
            print('No opening range breakout signal emitted')
        if args.output and events:
            with open(args.output, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=events[0].keys())
                w.writeheader(); w.writerows(events)
            print(f"Wrote {len(events)} events to {args.output}")
    return 0

def main():
    args = parse_args()
    rc = asyncio.run(run(args))
    if rc != 0:
        sys.exit(rc)

if __name__ == '__main__':
    main()
