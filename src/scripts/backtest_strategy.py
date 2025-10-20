"""Backtest EMA crossover strategy with multi-factor confirmation (RSI, CPR, Price Action).

Overview:
  1. Resolve instruments (categories like 'nifty', 'indices' or explicit symbols).
  2. Fetch historical candles day-by-day from Upstox HistoryV3Api (required to_date/from_date).
  3. Seed EMA state, then iterate candles generating raw crossover signals.
  4. Confirm signals via existing confirmation pipeline (RSI, CPR, price action).
  5. Simulate trades with simple stop/target/timeout exits.
  6. Report per-symbol and portfolio metrics; optional CSV / equity curve export.

Run (Windows CMD example):
  python -m src.scripts.backtest_strategy --symbols nifty,RELIANCE --start 2025-03-01 --end 2025-06-30 --timeframe 1m --csv summary.csv --equity equity.csv

Notes:
  * Timeframe supports suffix m/h/d (e.g. 1m, 5m, 15m, 1h, 1d).
  * CPR uses previous day OHLC; if missing you can opt to skip CPR with --skip-cpr.
  * This excludes support/resistance confirmation (per earlier request) but can be added later.
"""

from __future__ import annotations

import argparse
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

import upstox_client  # type: ignore

from src.config import settings
from src.auth.token_store import get_token
from src.engine.ema import EMAState
from src.engine.signal_confirmation import confirm_signal
from src.execution.execution import Signal
from src.execution.simulator import ExecutorSimulator
from src.utils.instruments import resolve_instruments

logging.basicConfig(level=logging.INFO, format="%Y-%m-%d %H:%M:%S %(levelname)s %(message)s")
logger = logging.getLogger("backtest")

# ------------------------
# Tunable parameters (can be externalized later)
# ------------------------
RECENT_BARS_WINDOW = 30      # bars passed into confirmation context
SL_PCT = 0.002               # 0.2% stop
TGT_PCT = 0.003              # 0.3% target
MAX_HOLD_BARS = 120          # timeout exit (e.g. 120 minutes if 1m timeframe)
SEED_EXTRA = 5               # extra candles beyond long EMA for stable initialization

# ------------------------
# Data utilities
# ------------------------
def _convert_interval(tf: str) -> Tuple[int, str]:
    if tf.endswith("m"):
        return (int(tf[:-1]), "minutes")
    if tf.endswith("h"):
        return (int(tf[:-1]), "hours")
    if tf.endswith("d"):
        return (int(tf[:-1]), "days")
    raise ValueError(f"Unsupported timeframe {tf}")

def _day_key(ts) -> str:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
    if isinstance(ts, str):
        return ts.split("T")[0]
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d")
    return str(ts)

def daterange(start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
    windows = []
    cur = start
    while cur <= end:
        nxt = cur + timedelta(days=1)
        windows.append((cur, nxt))
        cur = nxt
    return windows

def fetch_historical_range(api, instrument_key: str, timeframe: str, start: datetime, end: datetime) -> List[Dict]:
    """Fetch historical candles day-by-day to satisfy Upstox API date constraints."""
    interval, unit = _convert_interval(timeframe)
    candles: List[Dict] = []
    for frm, to in daterange(start, end):
        from_date = frm.strftime("%Y-%m-%d")
        to_date = to.strftime("%Y-%m-%d")
        try:
            resp = api.get_historical_candle_data1(
                instrument_key, unit, interval, to_date=to_date, from_date=from_date
            )
            if resp.data and resp.data.candles:
                for c in resp.data.candles:
                    candles.append({
                        "ts": c[0],
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": int(c[5]) if len(c) > 5 else 0
                    })
        except Exception as e:
            logger.warning(f"Fetch error {instrument_key} {from_date}-{to_date}: {e}")
    candles.sort(key=lambda x: x["ts"])  # chronological ascending
    return candles

def build_daily_reference(candles: List[Dict]) -> Dict[int, Dict]:
    from collections import defaultdict
    daily = defaultdict(lambda: {"high": -math.inf, "low": math.inf, "close": None})
    for c in candles:
        rec = daily[_day_key(c["ts"])]
        rec["high"] = max(rec["high"], c["high"])
        rec["low"] = min(rec["low"], c["low"])
        rec["close"] = c["close"]
    keys = sorted(daily.keys())
    ref: Dict[int, Dict] = {}
    # Map each day index to previous day OHLC (needed for CPR)
    for i in range(1, len(keys)):
        prev = daily[keys[i - 1]]
        ref[i] = {"prev_high": prev["high"], "prev_low": prev["low"], "prev_close": prev["close"]}
    return ref

def day_index_for_bar(candles: List[Dict], idx: int) -> int:
    current = None
    count = -1
    for i, c in enumerate(candles):
        dk = _day_key(c["ts"])
        if dk != current:
            current = dk
            count += 1
        if i == idx:
            return count
    return count

def daily_ref_for_index(daily_map: Dict[int, Dict], candles: List[Dict], idx: int) -> Dict:
    return daily_map.get(day_index_for_bar(candles, idx), {"prev_high": None, "prev_low": None, "prev_close": None})

def recent_bars(candles: List[Dict], idx: int, window: int) -> List[Dict]:
    start = max(0, idx - window + 1)
    return candles[start:idx + 1]

# ------------------------
# Signal generation (EMA crossover)
# ------------------------
def generate_raw_signal(ema: EMAState, bar: Dict) -> Optional[Signal]:
    prev_short = ema.prev_short
    prev_long = ema.prev_long
    if prev_short is None or prev_long is None:
        return None
    price = bar["close"]
    # Bullish crossover
    if prev_short <= prev_long and ema.short_ema > ema.long_ema:
        return Signal(symbol=ema.symbol, side="BUY", price=price, size=1,
                      stop_loss=price * (1 - SL_PCT), target=price * (1 + TGT_PCT))
    # Bearish crossover
    if prev_short >= prev_long and ema.short_ema < ema.long_ema:
        return Signal(symbol=ema.symbol, side="SELL", price=price, size=1,
                      stop_loss=price * (1 + SL_PCT), target=price * (1 - TGT_PCT))
    return None

# ------------------------
# Simulation structures
# ------------------------
@dataclass
class SimPosition:
    trade_obj: any
    entry_idx: int
    side: str
    stop: float
    target: float
    closed: bool = False
    exit_idx: Optional[int] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None

    def close(self, price: float, idx: int, reason: str, executor: ExecutorSimulator):
        if self.closed:
            return
        executor.close_trade(self.trade_obj, price)
        self.closed = True
        self.exit_idx = idx
        self.exit_reason = reason
        self.pnl = self.trade_obj.pnl

@dataclass
class BacktestResult:
    symbol: str
    positions: List[SimPosition] = field(default_factory=list)
    confirmed_signals: int = 0
    raw_signals: int = 0
    rejected_signals: int = 0
    total_bars: int = 0

    def equity_curve(self) -> List[float]:
        curve = []
        equity = 0.0
        closed_sorted = sorted([p for p in self.positions if p.closed and p.pnl is not None], key=lambda x: x.exit_idx or 0)
        ci = 0
        for i in range(self.total_bars):
            while ci < len(closed_sorted) and closed_sorted[ci].exit_idx == i:
                equity += closed_sorted[ci].pnl
                ci += 1
            curve.append(equity)
        return curve

    def max_drawdown(self) -> float:
        curve = self.equity_curve()
        peak = -math.inf
        max_dd = 0.0
        for v in curve:
            peak = max(peak, v)
            dd = peak - v
            if dd > max_dd:
                max_dd = dd
        return round(max_dd, 4)

    def summary(self) -> Dict:
        wins = sum(1 for p in self.positions if p.pnl and p.pnl > 0)
        losses = sum(1 for p in self.positions if p.pnl and p.pnl <= 0)
        gross = sum(p.pnl for p in self.positions if p.pnl is not None)
        avg_pnl = gross / len(self.positions) if self.positions else 0.0
        win_rate = wins / (wins + losses) if (wins + losses) else 0.0
        return {
            "symbol": self.symbol,
            "bars": self.total_bars,
            "raw_signals": self.raw_signals,
            "confirmed_signals": self.confirmed_signals,
            "rejected_signals": self.rejected_signals,
            "trades": len(self.positions),
            "win_rate": round(win_rate, 4),
            "avg_pnl": round(avg_pnl, 4),
            "gross_pnl": round(gross, 4),
            "max_drawdown": self.max_drawdown()
        }

# ------------------------
# Core backtest loop
# ------------------------
def run_backtest(symbol: str, candles: List[Dict], timeframe: str, skip_cpr: bool = False) -> BacktestResult:
    result = BacktestResult(symbol=symbol)
    if not candles:
        return result
    ema = EMAState(symbol, timeframe, settings.EMA_SHORT, settings.EMA_LONG)
    seed_len = settings.EMA_LONG + SEED_EXTRA
    if len(candles) <= seed_len:
        logger.warning(f"Insufficient candles to seed EMA for {symbol} (need > {seed_len}, have {len(candles)})")
        return result
    ema.initialize_from_candles(candles[:seed_len])
    daily_map = build_daily_reference(candles)
    executor = ExecutorSimulator(slippage=0.0, commission=0.0)
    open_positions: List[SimPosition] = []
    for idx, bar in enumerate(candles):
        result.total_bars += 1
        if idx < seed_len:
            continue
        ema.update_with_close(bar["close"])
        raw = generate_raw_signal(ema, bar)
        if raw:
            result.raw_signals += 1
            recent = recent_bars(candles, idx, RECENT_BARS_WINDOW)
            daily_ref = daily_ref_for_index(daily_map, candles, idx)
            confirm = confirm_signal(raw.side, ema, recent, daily_ref, require_cpr=not skip_cpr)
            if confirm["confirmed"]:
                result.confirmed_signals += 1
                trade = executor.open_trade(symbol, raw.side, raw.price, raw.size, raw.stop_loss, raw.target)
                open_positions.append(SimPosition(trade_obj=trade, entry_idx=idx, side=raw.side, stop=raw.stop_loss, target=raw.target))
            else:
                result.rejected_signals += 1
        # Manage open positions for exits
        for p in list(open_positions):
            price = bar["close"]
            stop_hit = (p.side == "BUY" and price <= p.stop) or (p.side == "SELL" and price >= p.stop)
            tgt_hit = (p.side == "BUY" and price >= p.target) or (p.side == "SELL" and price <= p.target)
            timeout = (idx - p.entry_idx) >= MAX_HOLD_BARS
            if stop_hit:
                p.close(p.stop, idx, "STOP", executor)
                open_positions.remove(p)
                result.positions.append(p)
            elif tgt_hit:
                p.close(p.target, idx, "TARGET", executor)
                open_positions.remove(p)
                result.positions.append(p)
            elif timeout:
                p.close(price, idx, "TIME_EXIT", executor)
                open_positions.remove(p)
                result.positions.append(p)
    # End-of-run cleanup
    if open_positions:
        last_price = candles[-1]["close"]
        for p in open_positions:
            p.close(last_price, len(candles) - 1, "EOD", executor)
            result.positions.append(p)
    return result

# ------------------------
# Export helpers
# ------------------------
def export_summary_csv(results: List[Dict], path: Optional[str]):
    if not path or not results:
        return
    import csv
    keys = list(results[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in results:
            w.writerow(r)
    logger.info("Summary CSV written to %s", path)

def export_equity_csv(result_map: Dict[str, BacktestResult], path: Optional[str]):
    if not path or not result_map:
        return
    import csv
    max_bars = max(r.total_bars for r in result_map.values()) if result_map else 0
    rows: List[Dict] = []
    for i in range(max_bars):
        row = {"bar_index": i}
        for sym, res in result_map.items():
            curve = res.equity_curve()
            row[f"equity_{sym}"] = curve[i] if i < len(curve) else curve[-1] if curve else 0.0
        rows.append(row)
    if not rows:
        return
    keys = rows[0].keys()
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    logger.info("Equity curve CSV written to %s", path)

# ------------------------
# Instrument resolution & CLI
# ------------------------
def resolve_inputs(raw_list: List[str]) -> List[Dict]:
    entries: List[Dict] = []
    for item in raw_list:
        try:
            entries.extend(resolve_instruments(item))
        except Exception as e:
            logger.warning(f"Failed to resolve '{item}': {e}")
    # Deduplicate by instrument_key
    uniq: Dict[str, Dict] = {}
    for e in entries:
        uniq[e['instrument_key']] = e
    return list(uniq.values())

def parse_args():
    p = argparse.ArgumentParser(description="Backtest EMA crossover with multi-factor confirmations")
    p.add_argument("--symbols", required=True, help="Comma-separated categories or symbols")
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p.add_argument("--timeframe", default="1m", help="Timeframe (e.g. 1m,5m,15m,1h)")
    p.add_argument("--csv", help="Optional summary CSV output path")
    p.add_argument("--equity", help="Optional equity curve CSV output path")
    p.add_argument("--skip-cpr", action="store_true", help="Skip CPR confirmation if previous day data missing")
    return p.parse_args()

def init_history_api(access_token: str):
    cfg = upstox_client.Configuration()
    cfg.access_token = access_token
    api_client = upstox_client.ApiClient(cfg)
    return upstox_client.HistoryV3Api(api_client)

def main():
    args = parse_args()
    raw_inputs = [s.strip() for s in args.symbols.split(',') if s.strip()]
    instruments = resolve_inputs(raw_inputs)
    if not instruments:
        logger.error("No instruments resolved from input: %s", raw_inputs)
        return
    logger.info("Resolved %d instruments: %s", len(instruments), [i['symbol'] for i in instruments])
    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    access_token = get_token()
    hist_api = init_history_api(access_token)

    summaries: List[Dict] = []
    result_map: Dict[str, BacktestResult] = {}
    for inst in instruments:
        symbol = inst['symbol']
        instrument_key = inst['instrument_key']
        logger.info(f"Fetching data for {symbol} ({instrument_key}) {args.timeframe} {args.start}->{args.end}")
        candles = fetch_historical_range(hist_api, instrument_key, args.timeframe, start, end)
        logger.info("Fetched %d candles for %s", len(candles), symbol)
        res = run_backtest(symbol, candles, args.timeframe, skip_cpr=args.skip_cpr)
        summary = res.summary()
        summaries.append(summary)
        result_map[symbol] = res
        logger.info("Summary %s: %s", symbol, summary)

    # Portfolio aggregation
    total_trades = sum(s['trades'] for s in summaries)
    gross_pnl = sum(s['gross_pnl'] for s in summaries)
    avg_win_rate = (sum(s['win_rate'] for s in summaries) / len(summaries)) if summaries else 0.0
    logger.info("Portfolio trades=%d gross_pnl=%.2f avg_win_rate=%.4f", total_trades, gross_pnl, avg_win_rate)

    print("\nRESULTS:")
    for s in summaries:
        print(s)

    export_summary_csv(summaries, args.csv)
    export_equity_csv(result_map, args.equity)

if __name__ == "__main__":
    main()
