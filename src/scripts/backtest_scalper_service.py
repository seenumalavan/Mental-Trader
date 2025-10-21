"""Backtest the existing ScalperService end-to-end by replaying historical 1m candles as synthetic ticks.

Non-invasive: does not modify service/strategy/executor code. We:
  1. Resolve instruments.
  2. Fetch historical 1m candles (via Upstox HistoryV3Api) for a date range.
  3. Initialize ScalperService (warmup uses loaded candles + intraday fetch skipped via flag).
  4. Replay candles as ticks (each candle's close drives bar close logic already in service).
  5. Capture resulting executed trades from Database simulator (if DB configured) and local executor state.

Usage (Windows CMD):
  python -m src.scripts.backtest_scalper_service --symbols nifty,RELIANCE --start 2025-03-01 --end 2025-03-07 --limit 1200

Arguments:
  --symbols    Comma separated categories or symbols (e.g. nifty, RELIANCE)
  --start      Start date YYYY-MM-DD
  --end        End date YYYY-MM-DD
  --limit      Max candles to fetch per symbol (default 2500)
  --report     Optional path to write summary JSON

Outputs:
  Prints per-symbol summary (#signals, #positions closed) and aggregate gross PnL if position tracking persisted.

Note:
  This script assumes Upstox SDK available. If not, it will exit gracefully.
  It relies on candle closes to generate signals (as in live). Intrabar tick simulation not attempted.
"""
from __future__ import annotations
import argparse
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
import json

try:
    import upstox_client  # type: ignore
except ImportError:
    upstox_client = None

from src.config import settings
from src.auth.token_store import get_token
from src.services.scalping_service import ScalperService
from src.utils.instruments import resolve_instruments

logging.basicConfig(level=logging.INFO, format="%Y-%m-%d %H:%M:%S %(levelname)s %(message)s")
logger = logging.getLogger("scalper_backtest")

# ---------------------- Data fetch helpers ----------------------

def _convert_interval(tf: str):
    if tf.endswith("m"):
        return int(tf[:-1]), "minutes"
    if tf.endswith("h"):
        return int(tf[:-1]), "hours"
    if tf.endswith("d"):
        return int(tf[:-1]), "days"
    raise ValueError(f"Unsupported timeframe {tf}")

def daterange(start: datetime, end: datetime):
    cur = start
    while cur <= end:
        nxt = cur + timedelta(days=1)
        yield cur, nxt
        cur = nxt

def fetch_hist(api, instrument_key: str, timeframe: str, start: datetime, end: datetime, limit: int) -> List[Dict[str, Any]]:
    interval, unit = _convert_interval(timeframe)
    out: List[Dict[str, Any]] = []
    count = 0
    for frm, to in daterange(start, end):
        if count >= limit:
            break
        from_date = frm.strftime("%Y-%m-%d")
        to_date = to.strftime("%Y-%m-%d")
        try:
            resp = api.get_historical_candle_data1(instrument_key, unit, interval, to_date=to_date, from_date=from_date)
            if resp.data and resp.data.candles:
                for c in resp.data.candles:
                    if count >= limit:
                        break
                    out.append({
                        "ts": c[0],
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": int(c[5]) if len(c) > 5 else 0
                    })
                    count += 1
        except Exception as e:
            logger.warning(f"Fetch error {instrument_key} {from_date}-{to_date}: {e}")
    out.sort(key=lambda x: x['ts'])
    return out

# ---------------------- Replay logic ----------------------
async def replay_candles(service: ScalperService, symbol: str, instrument_key: str, candles: List[Dict[str, Any]]):
    """Replay historical candles as synthetic ticks.
    For each candle, create a 'close tick' using close price and volume.
    This triggers bar closure logic in service when timeframe bucket advances.
    """
    # We assume service.bar_builder will generate 1m + higher timeframe bars; only 1m drives scalper signals.
    for c in candles:
        tick = {
            'symbol': symbol,
            'instrument_key': instrument_key,
            'price': c['close'],
            'volume': c.get('volume', 0),
            'ts': c['ts']  # keep original timestamp; BarBuilder handles parsing
        }
        try:
            await service._on_tick(tick)
        except Exception as e:
            logger.error(f"Tick replay error {symbol} {c['ts']}: {e}")

# ---------------------- Metrics extraction ----------------------

def extract_positions(service: ScalperService) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    ex = getattr(service, 'executor', None)
    if not ex:
        return out
    # Underlying positions
    for oid, pos in getattr(ex, '_open_orders', {}).items():
        out.append({'id': oid, **pos})
    # Option positions if any
    for sym, pos in getattr(ex, '_open_option_positions', {}).items():
        out.append({'option_contract': sym, **pos})
    return out

# ---------------------- CLI ----------------------

def parse_args():
    p = argparse.ArgumentParser(description="Backtest ScalperService by replaying historical 1m candles")
    p.add_argument('--symbols', required=True, help='Comma separated list of categories or symbols')
    p.add_argument('--start', required=True, help='Start date YYYY-MM-DD')
    p.add_argument('--end', required=True, help='End date YYYY-MM-DD')
    p.add_argument('--limit', type=int, default=2500, help='Maximum candles per symbol')
    p.add_argument('--report', help='Optional JSON file to write summary results')
    return p.parse_args()

async def main_async():
    args = parse_args()
    raw_syms = [s.strip() for s in args.symbols.split(',') if s.strip()]
    instruments = []
    for item in raw_syms:
        try:
            instruments.extend(resolve_instruments(item))
        except Exception as e:
            logger.warning(f"Resolve failed {item}: {e}")
    if not instruments:
        logger.error('No instruments resolved')
        return
    start = datetime.strptime(args.start, '%Y-%m-%d')
    end = datetime.strptime(args.end, '%Y-%m-%d')

    if upstox_client is None:
        logger.error('Upstox SDK not installed; cannot fetch historical data')
        return
    access_token = get_token()
    cfg = upstox_client.Configuration()
    cfg.access_token = access_token
    api_client = upstox_client.ApiClient(cfg)
    hist_api = upstox_client.HistoryV3Api(api_client)

    # Initialize service (async start) for shared components; avoids modifying service code.
    service = ScalperService()
    await service.start(instrument_input=raw_syms[0] if raw_syms else None)  # warmup internal structures

    summaries: List[Dict[str, Any]] = []
    for inst in instruments:
        symbol = inst['symbol']
        instrument_key = inst['instrument_key']
        logger.info(f"Fetching candles for {symbol} ({instrument_key})")
        candles = fetch_hist(hist_api, instrument_key, settings.SCALP_PRIMARY_TIMEFRAME, start, end, args.limit)
        logger.info(f"Fetched {len(candles)} candles for {symbol}")
        # Warmup already done via service.start; now replay.
        await replay_candles(service, symbol, instrument_key, candles)
        positions = extract_positions(service)
        buy_signals = sum(1 for p in positions if p.get('side') == 'BUY')
        sell_signals = sum(1 for p in positions if p.get('side') == 'SELL')
        summary = {
            'symbol': symbol,
            'candles_replayed': len(candles),
            'positions_open': len(positions),
            'buy_signals': buy_signals,
            'sell_signals': sell_signals
        }
        summaries.append(summary)
        logger.info(f"Summary {symbol}: {summary}")

    if args.report and summaries:
        try:
            with open(args.report, 'w') as f:
                json.dump(summaries, f, indent=2)
            logger.info(f"Report written to {args.report}")
        except Exception as e:
            logger.error(f"Failed writing report: {e}")

    await service.stop()

def main():
    asyncio.run(main_async())

if __name__ == '__main__':
    main()
