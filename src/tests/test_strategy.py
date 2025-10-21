import pytest
from src.engine.ema import EMAState
from src.engine.scalping_strategy import ScalpStrategy

@pytest.mark.asyncio
async def test_crossover_signal():
    class FakeService:
        def __init__(self):
            self.executor = type("E", (), {"handle_signal": lambda *a, **k: None})()
            self.notifier = type("N", (), {"notify_signal": lambda *a, **k: None})()

    svc = FakeService()
    strat = ScalpStrategy(svc)
    ema = EMAState('T', '1m', 2, 3)
    # build simple rising candles
    candles = [{"close": 100}, {"close": 101}, {"close": 102}, {"close": 103}]
    ema.initialize_from_candles(candles)
    # set prevs artificially
    ema.prev_short = ema.short_ema - 1
    ema.prev_long = ema.long_ema + 1
    bar = type("B", (), {"close": 105, "volume": 100})
    await strat.on_bar_close("T", "1m", bar, ema)
