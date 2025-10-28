import pytest

from src.engine.ema import EMAState
from src.engine.scalping_strategy import ScalpStrategy


@pytest.mark.asyncio
async def test_crossover_signal():
    class FakeService:
        def __init__(self):
            async def handle_signal_async(*args, **kwargs):
                pass
            async def notify_signal_async(*args, **kwargs):
                pass
            self.executor = type("E", (), {"handle_signal": handle_signal_async})()
            self.notifier = type("N", (), {"notify_signal": notify_signal_async})()
            self.options_manager = None

        def _confirmation_ctx(self, symbol, timeframe):
            # Return empty recent bars and daily ref for testing
            return [], {"prev_high": None, "prev_low": None, "prev_close": None}

    svc = FakeService()
    strat = ScalpStrategy(svc)
    ema = EMAState('T', '1m', 2, 3)
    # build simple rising candles
    candles = [
        {"close": 100, "high": 101, "low": 99},
        {"close": 101, "high": 102, "low": 100},
        {"close": 102, "high": 103, "low": 101},
        {"close": 103, "high": 104, "low": 102}
    ]
    ema.initialize_from_candles(candles)
    # set prevs artificially
    ema.prev_short = ema.short_ema - 1
    ema.prev_long = ema.long_ema + 1
    bar = type("B", (), {"close": 105, "volume": 100})
    await strat.on_bar_close("T", "TEST_KEY", "1m", bar, ema)
