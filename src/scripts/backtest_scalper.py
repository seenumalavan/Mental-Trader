"""Unified Scalper backtest script.

Modes:
    crossover   - Enumerate EMA crossovers (similar to legacy backtest_scalper_day)
    replay      - Replay a single day through strategy (generates signals) without PnL attribution
    performance - Replay + simulate trade exits using static stop/target to compute metrics
    diagnose    - Per-bar matrix of crossover detection vs actual strategy signal emission (merged from diagnose_scalper_crossovers.py)

Usage examples:
    python -m src.scripts.backtest_scalper --symbol NIFTY --date 2025-01-17 --mode crossover --output crosses.csv
    python -m src.scripts.backtest_scalper --symbol NIFTY --date 2025-01-17 --mode replay --disable-trend
    python -m src.scripts.backtest_scalper --symbol NIFTY --date 2025-01-17 --mode performance --report perf.json
    python -m src.scripts.backtest_scalper --symbol NIFTY --date 2025-01-17 --mode diagnose --threshold-pct 0.0001 --output diagnose.csv

Performance Metrics:
  trades            Total closed trades
  wins / losses     Counts based on stop/target outcome
  win_rate          wins / trades
  avg_r             Mean R multiple (target ~ +1.5R given sl 0.2%, tgt 0.3%)
  profit_factor     Gross profit / gross loss (abs)

Assumptions:
  - Immediate fill at bar close for entry.
  - Exit occurs when price reaches stop or target on subsequent bars (using bar high/low range test).
  - If neither hit by end of session, trade marked 'open' and excluded from closed metrics.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional, Any
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.persistence.db import Database
from src.engine.ema import EMAState
from src.engine.scalping_strategy import ScalpStrategy
from src.scripts.common_utils import (
    autodetect_instrument_key,
    load_warmup_and_day,
    write_csv,
)
from src.services.options.options_manager import OptionsManager
from src.providers.options_chain_provider import OptionsChainProvider

CROSS_FIELDNAMES = [
    'ts','side','price','prev_short','prev_long','curr_short','curr_long','prev_diff','curr_diff'
]

@dataclass
class Bar:
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: int

class CaptureExecutor:
    def __init__(self):
        self.signals: List = []
    async def handle_signal(self, signal):
        self.signals.append(signal)
    async def monitor_underlying_positions(self, tick):
        return
    async def monitor_option_positions(self, tick):
        return
    async def handle_option_signal(self, opt_signal):
        self.signals.append(opt_signal)

class CaptureNotifier:
    def __init__(self):
        self.emitted = []
    async def notify_signal(self, signal):
        self.emitted.append(signal)

class Harness:
    def __init__(self, symbol: str, instrument_key: str, timeframe: str):
        self.symbol = symbol
        self.instrument_key = instrument_key
        self.primary_tf = timeframe
        self.confirm_tf = settings.SCALP_CONFIRM_TIMEFRAME
        self.executor = CaptureExecutor()
        self.notifier = CaptureNotifier()
        self.option_signals: List = []
        if settings.OPTION_ENABLE:
            from src.auth.token_store import get_token
            from src.providers.broker_rest import BrokerRest
            access_token = get_token()
            api_key = settings.UPSTOX_API_KEY
            api_secret = settings.UPSTOX_API_SECRET
            rest = BrokerRest(api_key, api_secret, access_token=access_token)
            chain_provider = OptionsChainProvider(rest)
            async def emit_callback(opt_signal):
                await self.executor.handle_option_signal(opt_signal)
                self.option_signals.append(opt_signal)
            self.options_manager = OptionsManager(chain_provider, config={
                'OPTION_ENABLE': settings.OPTION_ENABLE,
                'OPTION_LOT_SIZE': settings.OPTION_LOT_SIZE,
                'OPTION_RISK_CAP_PER_TRADE': settings.OPTION_RISK_CAP_PER_TRADE,
                'OPTION_OI_MIN_PERCENTILE': settings.OPTION_OI_MIN_PERCENTILE,
                'OPTION_SPREAD_MAX_PCT_SCALPER': settings.OPTION_SPREAD_MAX_PCT_SCALPER,
                'OPTION_SPREAD_MAX_PCT_INTRADAY': settings.OPTION_SPREAD_MAX_PCT_INTRADAY,
                'OPTION_DEBOUNCE_SEC': settings.OPTION_DEBOUNCE_SEC,
                'OPTION_DEBOUNCE_INTRADAY_SEC': settings.OPTION_DEBOUNCE_SEC,  # Use same for simplicity
                'OPTION_COOLDOWN_SEC': settings.OPTION_COOLDOWN_SEC,
            }, emit_callback=emit_callback)
        else:
            self.options_manager = None
        self.db = None
        self.ema_primary = EMAState(instrument_key, timeframe, settings.EMA_SHORT, settings.EMA_LONG)
        self.ema_confirm = EMAState(instrument_key, self.confirm_tf, settings.EMA_SHORT, settings.EMA_LONG) if self.confirm_tf != timeframe else None
        self.strategy = ScalpStrategy(self)
    async def _confirmation_ctx(self, symbol: str, timeframe: str):
        return [], {"prev_high": None, "prev_low": None, "prev_close": None}

# ---------------- Arg Parsing -----------------

def parse_args():
    p = argparse.ArgumentParser(description='Unified scalper backtest tool')
    p.add_argument('--symbol', required=True)
    p.add_argument('--date', required=True, help='YYYY-MM-DD')
    p.add_argument('--timeframe', default=settings.SCALP_PRIMARY_TIMEFRAME)
    p.add_argument('--instrument-key', dest='instrument_key')
    p.add_argument('--warmup-bars', type=int, default=400)
    p.add_argument('--mode', choices=['crossover','replay','performance','diagnose'], default='crossover')
    p.add_argument('--disable-trend', action='store_true')
    p.add_argument('--disable-confirmation', action='store_true')
    # Diagnose / advanced parameters
    p.add_argument('--threshold-pct', type=float, default=0.0, help='Threshold pct for strict crossover in diagnose mode')
    p.add_argument('--strict', action='store_true', help='Use strict threshold logic for diagnose mode')
    p.add_argument('--show-all', action='store_true', help='Show all bars (diagnose mode)')
    p.add_argument('--output', help='CSV output (crossover/signals/diagnose rows)')
    p.add_argument('--report', help='JSON report path (performance mode)')
    return p.parse_args()

# --------------- Crossover Enumeration ---------------

async def enumerate_crossovers(rows: List[Dict], ema_state: EMAState) -> List[Dict]:
    events: List[Dict] = []
    for r in rows:
        ema_state.update_with_close(r['close'])
        if ema_state.prev_short is None or ema_state.prev_long is None:
            continue
        prev_short = ema_state.prev_short
        prev_long = ema_state.prev_long
        curr_short = ema_state.short_ema
        curr_long = ema_state.long_ema
        if prev_short <= prev_long and curr_short > curr_long:
            events.append({
                'ts': str(r['ts']), 'side':'BUY','price':r['close'],
                'prev_short': prev_short,'prev_long':prev_long,'curr_short':curr_short,'curr_long':curr_long,
                'prev_diff': prev_short-prev_long,'curr_diff': curr_short-curr_long
            })
        elif prev_short >= prev_long and curr_short < curr_long:
            events.append({
                'ts': str(r['ts']), 'side':'SELL','price':r['close'],
                'prev_short': prev_short,'prev_long':prev_long,'curr_short':curr_short,'curr_long':curr_long,
                'prev_diff': prev_short-prev_long,'curr_diff': curr_short-curr_long
            })
    return events

# --------------- Replay Logic ---------------

async def replay_strategy(symbol: str, harness: Harness, warm: List[Dict], day_rows: List[Dict], use_filters: bool) -> List[Dict]:
    # Seed EMAs
    for r in warm:
        harness.ema_primary.update_with_close(r['close'])
        if harness.ema_confirm:
            harness.ema_confirm.update_with_close(r['close'])  # naive seed same bars
    settings.SCALP_ENABLE_TREND_CONFIRMATION = use_filters
    settings.SCALP_ENABLE_SIGNAL_CONFIRMATION = use_filters
    events: List[Dict] = []
    for r in day_rows:
        harness.ema_primary.update_with_close(r['close'])
        bar = Bar(ts=str(r['ts']), open=r['open'], high=r['high'], low=r['low'], close=r['close'], volume=r['volume'])
        await harness.strategy.on_bar_close(symbol, harness.instrument_key, harness.primary_tf, bar, harness.ema_primary, harness.ema_confirm)
        if harness.executor.signals:
            sig = harness.executor.signals[-1]
            if hasattr(sig, 'ts') and (not events or events[-1]['ts'] != sig.ts):
                events.append({
                    'ts': sig.ts,
                    'side': sig.side,
                    'price': sig.price,
                    'stop_loss': sig.stop_loss,
                    'target': sig.target,
                })
            elif hasattr(sig, 'timestamp') and (not events or events[-1]['ts'] != sig.timestamp):
                events.append({
                    'ts': sig.timestamp,
                    'underlying_symbol': sig.underlying_symbol,
                    'side': sig.underlying_side,
                    'price': sig.premium_ltp,
                    'stop_loss': getattr(sig, 'stop_loss_premium', None),
                    'target': getattr(sig, 'target_premium', None),
                    'contract_symbol': sig.contract_symbol,
                    'lots': sig.suggested_size_lots,
                })
    return events

# --------------- Diagnose Logic ---------------

DIAGNOSE_HEADERS = ['ts','price','prev_short','prev_long','curr_short','curr_long','prev_diff','curr_diff','threshold','detected_buy','detected_sell','strict_mode','skipped_warmup','signal_generated','signal_side']

async def diagnose_crossovers(symbol: str, instrument_key: str, timeframe: str, warm: List[Dict], day_rows: List[Dict], threshold_pct: float, strict: bool, show_all: bool, disable_trend: bool, disable_confirmation: bool) -> List[Dict]:
    # Apply runtime flags
    if disable_trend:
        settings.SCALP_ENABLE_TREND_CONFIRMATION = False
    if disable_confirmation:
        settings.SCALP_ENABLE_SIGNAL_CONFIRMATION = False
    ema = EMAState(instrument_key, timeframe, settings.EMA_SHORT, settings.EMA_LONG)
    for b in warm:
        ema.update_with_close(b['close'])
    harness = Harness(symbol, instrument_key, timeframe)
    strategy = harness.strategy
    bar_count = 0
    rows_out: List[Dict[str, Any]] = []
    for b in day_rows:
        ema.update_with_close(b['close'])
        bar_count += 1
        prev_short = ema.prev_short
        prev_long = ema.prev_long
        curr_short = ema.short_ema
        curr_long = ema.long_ema
        if prev_short is None or prev_long is None:
            continue
        thr = b['close'] * threshold_pct if threshold_pct else 0.0
        simple_buy = prev_short <= prev_long and curr_short > curr_long
        simple_sell = prev_short >= prev_long and curr_short < curr_long
        strict_buy = prev_short <= (prev_long - thr) and curr_short > (curr_long + thr)
        strict_sell = prev_short >= (prev_long + thr) and curr_short < (curr_long - thr)
        detected_buy = strict_buy if strict else simple_buy
        detected_sell = strict_sell if strict else simple_sell
        class _Bar: pass
        bar_obj = _Bar()
        bar_obj.close = b['close']
        bar_obj.ts = str(b['ts'])
        skipped_warmup = bar_count <= 5
        signal_generated = False
        signal_side = None
        if not skipped_warmup and (detected_buy or detected_sell):
            pre_count = len(harness.executor.signals)
            try:
                await strategy.on_bar_close(symbol, instrument_key, timeframe, bar_obj, ema, None)
            except Exception:
                pass
            post_count = len(harness.executor.signals)
            if post_count > pre_count:
                signal_generated = True
                last_sig = harness.executor.signals[-1]
                signal_side = getattr(last_sig, 'side', getattr(last_sig, 'underlying_side', ''))
        include = show_all or detected_buy or detected_sell
        if include:
            rows_out.append({
                'ts': str(b['ts']),
                'price': b['close'],
                'prev_short': prev_short,
                'prev_long': prev_long,
                'curr_short': curr_short,
                'curr_long': curr_long,
                'prev_diff': prev_short - prev_long,
                'curr_diff': curr_short - curr_long,
                'threshold': thr,
                'detected_buy': int(detected_buy),
                'detected_sell': int(detected_sell),
                'strict_mode': int(strict),
                'skipped_warmup': int(skipped_warmup),
                'signal_generated': int(signal_generated),
                'signal_side': signal_side or ''
            })
    return rows_out

# --------------- Performance Simulation ---------------

@dataclass
class Trade:
    side: str
    entry_ts: str
    entry_price: float
    stop: float
    target: float
    exit_ts: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: Optional[str] = None  # WIN / LOSS
    r_multiple: Optional[float] = None

async def simulate_performance(day_rows: List[Dict], signals: List[Dict]) -> Dict:
    # Build trades list
    trades: List[Trade] = []
    for s in signals:
        trades.append(Trade(
            side=s['side'], entry_ts=s['ts'], entry_price=s['price'], stop=s['stop_loss'], target=s['target']
        ))
    # Iterate bars after each trade entry to resolve
    for trade in trades:
        after = False
        for r in day_rows:
            if str(r['ts']) == trade.entry_ts:
                after = True
                continue
            if not after:
                continue
            high = r['high']
            low = r['low']
            if trade.side == 'BUY':
                # Stop first then target assumption (conservative) if both inside bar
                if low <= trade.stop:
                    trade.exit_ts = str(r['ts'])
                    trade.exit_price = trade.stop
                    trade.outcome = 'LOSS'
                    risk = trade.entry_price - trade.stop
                    trade.r_multiple = -1.0 if risk else 0.0
                    break
                if high >= trade.target:
                    trade.exit_ts = str(r['ts'])
                    trade.exit_price = trade.target
                    trade.outcome = 'WIN'
                    reward = trade.target - trade.entry_price
                    risk = trade.entry_price - trade.stop
                    trade.r_multiple = reward / risk if risk else 0.0
                    break
            else:  # SELL
                if high >= trade.stop:
                    trade.exit_ts = str(r['ts'])
                    trade.exit_price = trade.stop
                    trade.outcome = 'LOSS'
                    risk = trade.stop - trade.entry_price
                    trade.r_multiple = -1.0 if risk else 0.0
                    break
                if low <= trade.target:
                    trade.exit_ts = str(r['ts'])
                    trade.exit_price = trade.target
                    trade.outcome = 'WIN'
                    reward = trade.entry_price - trade.target
                    risk = trade.stop - trade.entry_price
                    trade.r_multiple = reward / risk if risk else 0.0
                    break
    closed = [t for t in trades if t.outcome]
    wins = [t for t in closed if t.outcome == 'WIN']
    losses = [t for t in closed if t.outcome == 'LOSS']
    gross_profit = sum((t.exit_price - t.entry_price) if t.side=='BUY' else (t.entry_price - t.exit_price) for t in wins)
    gross_loss = sum((t.entry_price - t.exit_price) if t.side=='BUY' else (t.exit_price - t.entry_price) for t in losses)
    avg_r = sum(t.r_multiple for t in closed if t.r_multiple is not None)/len(closed) if closed else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss else None
    return {
        'trades': len(closed),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': (len(wins)/len(closed)) if closed else 0.0,
        'avg_r': avg_r,
        'profit_factor': profit_factor,
        'open_trades': len(trades) - len(closed),
    }

# --------------- Main Flow ---------------

async def main_async():
    args = parse_args()
    day = datetime.strptime(args.date, '%Y-%m-%d')
    db = Database(settings.DATABASE_URL)
    await db.connect()
    if not args.instrument_key:
        instrument_key = autodetect_instrument_key(db, args.symbol, args.timeframe)
    else:
        instrument_key = args.instrument_key
    warm, day_rows = load_warmup_and_day(db, args.symbol, instrument_key, args.timeframe, day, args.warmup_bars)
    await db.disconnect()
    if not day_rows:
        print('No candles for date')
        return

    if args.mode == 'crossover':
        ema_state = EMAState(instrument_key, args.timeframe, settings.EMA_SHORT, settings.EMA_LONG)
        for r in warm:
            ema_state.update_with_close(r['close'])
        events = await enumerate_crossovers(day_rows, ema_state)
        print(','.join(CROSS_FIELDNAMES))
        for e in events:
            print(','.join([
                e['ts'], e['side'], f"{e['price']:.2f}", f"{e['prev_short']:.4f}", f"{e['prev_long']:.4f}",
                f"{e['curr_short']:.4f}", f"{e['curr_long']:.4f}", f"{e['prev_diff']:.4f}", f"{e['curr_diff']:.4f}"
            ]))
        if args.output:
            write_csv(args.output, CROSS_FIELDNAMES, events)
    elif args.mode == 'diagnose':
        rows = await diagnose_crossovers(
            args.symbol,
            instrument_key,
            args.timeframe,
            warm,
            day_rows,
            threshold_pct=args.threshold_pct,
            strict=args.strict,
            show_all=args.show_all,
            disable_trend=args.disable_trend,
            disable_confirmation=args.disable_confirmation,
        )
        if not rows:
            print('No crossover detections.')
        else:
            print(','.join(DIAGNOSE_HEADERS))
            for r in rows:
                print(','.join([
                    r['ts'],
                    f"{r['price']:.2f}", f"{r['prev_short']:.4f}", f"{r['prev_long']:.4f}",
                    f"{r['curr_short']:.4f}", f"{r['curr_long']:.4f}",
                    f"{r['prev_diff']:.4f}", f"{r['curr_diff']:.4f}",
                    f"{r['threshold']:.4f}",
                    str(r['detected_buy']), str(r['detected_sell']), str(r['strict_mode']), str(r['skipped_warmup']), str(r['signal_generated']), r['signal_side']
                ]))
            if args.output:
                write_csv(args.output, DIAGNOSE_HEADERS, rows)
    else:
        harness = Harness(args.symbol, instrument_key, args.timeframe)
        use_filters = not (args.disable_trend or args.disable_confirmation)
        signals = await replay_strategy(args.symbol, harness, warm, day_rows, use_filters=use_filters)
        if args.mode == 'replay':
            if signals:
                print('ts,side,price,stop_loss,target,contract_symbol,lots')
                for s in signals:
                    contract = s.get('contract_symbol', '')
                    lots = s.get('lots', '')
                    print(f"{s['ts']},{s['side']},{s['price']:.2f},{s['stop_loss']:.2f},{s['target']:.2f},{contract},{lots}")
                if args.output:
                    write_csv(args.output, ['ts','side','price','stop_loss','target','contract_symbol','lots'], signals)
            else:
                print('No signals generated.')
            if harness.option_signals:
                print('Option signals:')
                for opt in harness.option_signals:
                    print(f"{opt.contract_symbol} {opt.underlying_side} lots={opt.suggested_size_lots} premium={opt.premium_ltp:.2f}")
        else:  # performance
            metrics = await simulate_performance(day_rows, signals)
            import json
            print('Performance Metrics:')
            print(json.dumps(metrics, indent=2))
            if args.report:
                with open(args.report,'w') as f:
                    json.dump(metrics, f, indent=2)


def main():
    asyncio.run(main_async())

if __name__ == '__main__':
    main()
