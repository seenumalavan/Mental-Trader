"""Unified Intraday backtest script.

Modes:
    replay      - Strategy signals (with optional filters)
    performance - Replay + simulate exits for performance metrics
    diagnose    - Per-bar matrix of crossover detection vs actual strategy signal emission (mirrors scalper diagnose mode)

Usage:
    python -m src.scripts.backtest_intraday --symbol NIFTY --date 2025-01-17 --mode replay
    python -m src.scripts.backtest_intraday --symbol NIFTY --date 2025-01-17 --mode performance --report intraday_perf.json
    python -m src.scripts.backtest_intraday --symbol NIFTY --date 2025-01-17 --mode diagnose --threshold-pct 0.0001 --output diagnose.csv

Assumptions:
    - Works on a single primary timeframe (settings.INTRADAY_PRIMARY_TIMEFRAME or --timeframe override)
    - Stop/target scaled similarly to strategy logic; metrics treat first touch priority (stop before target if same bar)
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
from src.engine.intraday_strategy import IntradayStrategy
from src.scripts.common_utils import (
    autodetect_instrument_key,
    load_warmup_and_day,
    write_csv,
)
from src.services.options.options_manager import OptionsManager
from src.providers.options_chain_provider import OptionsChainProvider

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
    def __init__(self, symbol: str, instrument_key: str, primary_tf: str, confirm_tf: str, candles: List[Dict] = None):
        self.symbol = symbol
        self.instrument_key = instrument_key
        self.primary_tf = primary_tf
        self.confirm_tf = confirm_tf
        self.candles = candles or []
        
        # Load symbol to instrument key mapping
        from src.utils.instruments import get_symbol_to_key_mapping
        self.symbol_to_key = get_symbol_to_key_mapping()
        
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
            chain_provider = OptionsChainProvider(rest, instrument_key)
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
                'OPTION_DEBOUNCE_INTRADAY_SEC': settings.OPTION_DEBOUNCE_INTRADAY_SEC,
                'OPTION_COOLDOWN_SEC': settings.OPTION_COOLDOWN_SEC,
            }, emit_callback=emit_callback)
        else:
            self.options_manager = None
        self.db = None
        self.ema_primary = EMAState(instrument_key, primary_tf, settings.INTRADAY_EMA_SHORT, settings.INTRADAY_EMA_LONG)
        self.ema_confirm = EMAState(instrument_key, confirm_tf, settings.INTRADAY_EMA_SHORT, settings.INTRADAY_EMA_LONG) if confirm_tf != primary_tf else None
        self.strategy = IntradayStrategy(self, primary_tf, confirm_tf, settings.INTRADAY_EMA_SHORT, settings.INTRADAY_EMA_LONG)
    
    def can_trade(self, time_window: str) -> bool:
        """For backtesting, always allow trades (no monthly limits)."""
        return True
    async def _confirmation_ctx(self, symbol: str, timeframe: str):
        """Provide context for signal confirmation: recent bars and previous day reference using API daily data."""
        try:
            # Get recent bars for RSI/price action analysis
            recent_bars = []
            instrument_key = self.symbol_to_key.get(symbol, symbol)
            candles = self.candles[-settings.CONFIRMATION_RECENT_BARS:] if self.candles else []
            if candles:
                recent_bars = [{
                    'close': c['close'],
                    'open': c['open'],
                    'high': c['high'],
                    'low': c['low'],
                    'volume': c['volume']
                } for c in candles]
            
            # Get previous day OHLC using API for daily timeframe (accurate and reliable)
            daily_ref = {"prev_high": None, "prev_low": None, "prev_close": None}
            
            try:
                # Fetch daily historical data directly from API
                from src.auth.token_store import get_token
                from src.providers.broker_rest import BrokerRest
                
                access_token = get_token()
                api_key = settings.UPSTOX_API_KEY
                api_secret = settings.UPSTOX_API_SECRET
                rest = BrokerRest(api_key, api_secret, access_token=access_token)
                
                # Get daily data for the past few days
                daily_candles = await rest.fetch_historical(instrument_key, timeframe="1d", limit=5)
                
                if len(daily_candles) >= 2:
                    # Second to last is previous day (last might be partial current day)
                    prev_day = daily_candles[0]
                    daily_ref = {
                        "prev_high": prev_day['high'],
                        "prev_low": prev_day['low'],
                        "prev_close": prev_day['close']
                    }
                    print(f"DEBUG: Using API daily data for {symbol}: prev_close={prev_day['close']:.2f}")
                else:
                    print(f"WARNING: Insufficient daily data from API for {symbol}")
                    
            except Exception as e:
                print(f"ERROR: Failed to fetch daily data from API for {symbol}: {e}")
                # No fallback - if API fails, daily_ref remains None
            
            return recent_bars, daily_ref
        except Exception as e:
            print(f"Failed to get confirmation context for {symbol}: {e}")
            return [], {"prev_high": None, "prev_low": None, "prev_close": None}

# -------- Args ---------

def parse_args():
    p = argparse.ArgumentParser(description='Unified intraday backtest tool')
    p.add_argument('--symbol', required=True)
    p.add_argument('--date', required=True, help='YYYY-MM-DD')
    p.add_argument('--timeframe', default=getattr(settings, 'INTRADAY_PRIMARY_TIMEFRAME', '5m'))
    p.add_argument('--confirm-tf', default=getattr(settings, 'INTRADAY_CONFIRM_TIMEFRAME', '15m'))
    p.add_argument('--instrument-key', dest='instrument_key')
    p.add_argument('--warmup-bars', type=int, default=500)
    p.add_argument('--mode', choices=['replay','performance','diagnose'], default='replay')
    p.add_argument('--disable-trend', action='store_false')
    p.add_argument('--disable-confirmation', action='store_true')
    # Diagnose / advanced parameters
    p.add_argument('--threshold-pct', type=float, default=0.0, help='Threshold pct for strict crossover in diagnose mode')
    p.add_argument('--strict', action='store_true', help='Use strict threshold logic for diagnose mode')
    p.add_argument('--show-all', action='store_true', help='Show all bars (diagnose mode)')
    p.add_argument('--output', help='CSV output (replay/diagnose rows)')
    p.add_argument('--report', help='JSON report for performance mode')
    return p.parse_args()
# -------- Main ---------

# -------- Diagnose Logic (mirrors scalper) ---------

DIAGNOSE_HEADERS = ['ts','price','prev_short','prev_long','curr_short','curr_long','prev_diff','curr_diff','threshold','detected_buy','detected_sell','strict_mode','skipped_warmup','signal_generated','signal_side']

async def diagnose_crossovers(symbol: str, instrument_key: str, timeframe: str, warm: List[Dict], day_rows: List[Dict], threshold_pct: float, strict: bool, show_all: bool, disable_trend: bool, disable_confirmation: bool) -> List[Dict]:
    if disable_trend:
        settings.INTRADAY_ENABLE_TREND_CONFIRMATION = False
    if disable_confirmation:
        settings.INTRADAY_ENABLE_SIGNAL_CONFIRMATION = True
    ema = EMAState(symbol, timeframe, settings.INTRADAY_EMA_SHORT, settings.INTRADAY_EMA_LONG)
    for b in warm:
        ema.update_with_close(b['close'])
    harness = Harness(symbol, instrument_key, timeframe, getattr(settings, 'INTRADAY_CONFIRM_TIMEFRAME', '15m'))
    strategy = harness.strategy
    bar_count = 0
    rows_out: List[Dict] = []
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

# -------- Replay ---------

async def replay(symbol: str, harness: Harness, warm: List[Dict], day_rows: List[Dict], disable_trend: bool, disable_confirmation: bool) -> List[Dict]:
    for r in warm:
        harness.ema_primary.update_with_close(r['close'])
        if harness.ema_confirm:
            harness.ema_confirm.update_with_close(r['close'])
    settings.INTRADAY_ENABLE_TREND_CONFIRMATION = not disable_trend
    settings.INTRADAY_ENABLE_SIGNAL_CONFIRMATION = not disable_confirmation
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
                    'stop_loss': getattr(sig, 'stop_loss', None),
                    'target': getattr(sig, 'target', None),
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

# -------- Performance Simulation (mirrors scalper approach) ---------

from dataclasses import dataclass
from typing import Optional

@dataclass
class Trade:
    side: str
    entry_ts: str
    entry_price: float
    stop: float
    target: float
    exit_ts: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: Optional[str] = None
    r_multiple: Optional[float] = None

async def simulate_performance(day_rows: List[Dict], signals: List[Dict]) -> Dict:
    trades: List[Trade] = []
    for s in signals:
        if s.get('stop_loss') is None or s.get('target') is None:
            continue
        trades.append(Trade(side=s['side'], entry_ts=s['ts'], entry_price=s['price'], stop=s['stop_loss'], target=s['target']))
    for trade in trades:
        after = False
        for r in day_rows:
            if str(r['ts']) == trade.entry_ts:
                after = True
                continue
            if not after:
                continue
            high = r['high']; low = r['low']
            if trade.side == 'BUY':
                if low <= trade.stop:
                    trade.exit_ts = str(r['ts']); trade.exit_price = trade.stop; trade.outcome = 'LOSS'
                    risk = trade.entry_price - trade.stop; trade.r_multiple = -1.0 if risk else 0.0; break
                if high >= trade.target:
                    trade.exit_ts = str(r['ts']); trade.exit_price = trade.target; trade.outcome = 'WIN'
                    reward = trade.target - trade.entry_price; risk = trade.entry_price - trade.stop
                    trade.r_multiple = reward / risk if risk else 0.0; break
            else:
                if high >= trade.stop:
                    trade.exit_ts = str(r['ts']); trade.exit_price = trade.stop; trade.outcome = 'LOSS'
                    risk = trade.stop - trade.entry_price; trade.r_multiple = -1.0 if risk else 0.0; break
                if low <= trade.target:
                    trade.exit_ts = str(r['ts']); trade.exit_price = trade.target; trade.outcome = 'WIN'
                    reward = trade.entry_price - trade.target; risk = trade.stop - trade.entry_price
                    trade.r_multiple = reward / risk if risk else 0.0; break
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

# -------- Main ---------


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
        print('No candles for date'); return

    if args.mode == 'diagnose':
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
        return

    harness = Harness(args.symbol, instrument_key, args.timeframe, args.confirm_tf, warm + day_rows)
    signals = await replay(args.symbol, harness, warm, day_rows, args.disable_trend, args.disable_confirmation)

    if args.mode == 'replay':
        if signals:
            print('ts,side,price,stop_loss,target,contract_symbol,lots')
            for s in signals:
                contract = s.get('contract_symbol', '')
                lots = s.get('lots', '')
                print(f"{s['ts']},{s['side']},{s['price']:.2f},{s.get('stop_loss',0):.2f},{s.get('target',0):.2f},{contract},{lots}")
            if args.output:
                write_csv(args.output, ['ts','side','price','stop_loss','target','contract_symbol','lots'], signals)
        else:
            print('No signals generated.')
        if harness.option_signals:
            print('Option signals:')
            for opt in harness.option_signals:
                print(f"{opt.contract_symbol} {opt.underlying_side} lots={opt.suggested_size_lots} premium={opt.premium_ltp:.2f}")
    else:
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
