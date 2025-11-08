import asyncio
import types
from datetime import datetime, timedelta

import pytest

from src.engine.opening_range_breakout_strategy import OpeningRangeBreakoutStrategy
from src.config import settings

class DummyBar:
    def __init__(self, ts, open_, high, low, close, volume=0):
        self.ts = ts
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume

class DummyOptionsProvider:
    def __init__(self, chains):
        self.chains = chains
        self.instrument_symbol = "NIFTY"
    def set_instrument(self, sym):
        self.instrument_symbol = sym
    def fetch_option_chain(self):
        return self.chains.pop(0) if self.chains else []

class DummyOptionsManager:
    def __init__(self, provider):
        self.provider = provider
        self.published = []
    async def publish_underlying_signal(self, symbol, side, price, timeframe, origin="opening_range"):
        self.published.append({
            'symbol': symbol,
            'side': side,
            'price': price,
            'timeframe': timeframe,
            'origin': origin
        })

class DummyService:
    def __init__(self, chains):
        self.options_manager = DummyOptionsManager(DummyOptionsProvider(chains))
        self.day_candles = { 'NIFTY': [ { 'high': 22000, 'low': 21500, 'close': 21800 } ] }
        self.symbol_to_key = { 'NIFTY': 'NIFTY-I' }

@pytest.mark.asyncio
async def test_opening_range_breakout_buy_signal():
    settings.OPENING_RANGE_REQUIRE_CPR = True
    settings.OPENING_RANGE_REQUIRE_PRICE_ACTION = False
    settings.OPENING_RANGE_REQUIRE_RSI_SLOPE = False
    settings.OPENING_RANGE_MIN_OI_CHANGE_PCT = 5.0

    # Two chains: baseline then breakout with increased call OI
    chains = [
        [ {'kind': 'CALL', 'strike': 21800, 'oi': 1000}, {'kind': 'PUT', 'strike': 21800, 'oi': 1200} ],
        [ {'kind': 'CALL', 'strike': 21800, 'oi': 1100}, {'kind': 'PUT', 'strike': 21800, 'oi': 1000} ],
    ]
    service = DummyService(chains)
    strat = OpeningRangeBreakoutStrategy(service, primary_tf='5m')

    # Collect opening range bars (simulate 3 bars of 5m -> 15m)
    start = datetime(2025, 1, 1, 9, 15)
    bars = [
        DummyBar(start.isoformat(), 21800, 21820, 21790, 21810),
        DummyBar((start + timedelta(minutes=5)).isoformat(), 21810, 21825, 21805, 21815),
        DummyBar((start + timedelta(minutes=10)).isoformat(), 21815, 21830, 21800, 21825),
    ]
    # Breakout bar above range high
    breakout = DummyBar((start + timedelta(minutes=15)).isoformat(), 21825, 21840, 21820, 21835)

    for b in bars:
        await strat.on_bar_close('NIFTY', 'NIFTY-I', '5m', b)
    await strat.on_bar_close('NIFTY', 'NIFTY-I', '5m', breakout)

    assert len(service.options_manager.published) == 1, 'Expected one published option signal'
    sig = service.options_manager.published[0]
    assert sig['side'] == 'BUY'
    assert sig['origin'] == 'opening_range'

@pytest.mark.asyncio
async def test_opening_range_breakout_sell_signal():
    settings.OPENING_RANGE_REQUIRE_CPR = False  # disable CPR for isolated sell test
    settings.OPENING_RANGE_REQUIRE_PRICE_ACTION = False
    settings.OPENING_RANGE_REQUIRE_RSI_SLOPE = False
    settings.OPENING_RANGE_MIN_OI_CHANGE_PCT = 5.0

    chains = [
        [ {'kind': 'CALL', 'strike': 21800, 'oi': 1000}, {'kind': 'PUT', 'strike': 21800, 'oi': 900} ],
        [ {'kind': 'CALL', 'strike': 21800, 'oi': 900}, {'kind': 'PUT', 'strike': 21800, 'oi': 1000} ],
    ]
    service = DummyService(chains)
    strat = OpeningRangeBreakoutStrategy(service, primary_tf='5m')

    start = datetime(2025, 1, 1, 9, 15)
    bars = [
        DummyBar(start.isoformat(), 21800, 21820, 21790, 21810),
        DummyBar((start + timedelta(minutes=5)).isoformat(), 21810, 21815, 21800, 21805),
        DummyBar((start + timedelta(minutes=10)).isoformat(), 21805, 21810, 21795, 21798),
    ]
    breakout = DummyBar((start + timedelta(minutes=15)).isoformat(), 21798, 21800, 21780, 21785)

    for b in bars:
        await strat.on_bar_close('NIFTY', 'NIFTY-I', '5m', b)
    await strat.on_bar_close('NIFTY', 'NIFTY-I', '5m', breakout)

    assert len(service.options_manager.published) == 1
    assert service.options_manager.published[0]['side'] == 'SELL'
