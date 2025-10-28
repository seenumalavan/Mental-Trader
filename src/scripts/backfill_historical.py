"""Backfill historical candles for specified instruments.

Examples (run from project root):
  python -m src.scripts.backfill_historical --inputs nifty
  python -m src.scripts.backfill_historical --inputs nifty,indices
  python -m src.scripts.backfill_historical --inputs RELIANCE,TCS

Categories and symbols are resolved via instruments file (see src/utils/instruments.py).
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Path bootstrap to allow direct execution without -m
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.auth.token_store import get_token
from src.config import settings
from src.persistence.db import Database
from src.providers.broker_rest import BrokerRest
from src.utils.instruments import resolve_instruments

logger = logging.getLogger("backfill")

def parse_args():
    p = argparse.ArgumentParser(description="Backfill historical candles to DB from broker REST")
    p.add_argument("--inputs", required=True, help="Comma-separated categories or symbols (e.g. nifty,RELIANCE,TCS)")
    p.add_argument("--timeframe", default="1m", help="Timeframe (default 1m)")
    p.add_argument("--limit", type=int, default=300, help="Number of candles to fetch per instrument")
    return p.parse_args()

async def run(raw_inputs: str, timeframe: str, limit: int):
    db = Database(settings.DATABASE_URL)
    await db.connect()
    rest = BrokerRest(settings.UPSTOX_API_KEY, settings.UPSTOX_API_SECRET, access_token=get_token())
    inputs = [s.strip() for s in raw_inputs.split(',') if s.strip()]
    instruments = []
    for inp in inputs:
        instruments.extend(resolve_instruments(inp))
    # Deduplicate by instrument_key
    uniq = {}
    for inst in instruments:
        uniq[inst['instrument_key']] = inst
    instruments = list(uniq.values())
    logger.info("Resolved %d instruments", len(instruments))
    for inst in instruments:
        symbol = inst['symbol']
        instrument_key = inst['instrument_key']
        logger.info("Fetching %s (%s) timeframe=%s limit=%d", symbol, instrument_key, timeframe, limit)
        candles = await rest.fetch_historical(instrument_key, timeframe, limit=limit)
        await db.persist_candles_bulk(symbol, instrument_key, timeframe, candles)
        logger.info("Persisted %d candles for %s", len(candles), symbol)
    await db.disconnect()

def main():
    args = parse_args()
    asyncio.run(run(args.inputs, args.timeframe, args.limit))

if __name__ == "__main__":
    main()
