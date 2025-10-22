
from src.engine.ema import EMAState
from src.engine.signal_confirmation import SignalType, confirm_signal


def test_confirm_long_basic():
    ema = EMAState("TEST", "1m", 9, 21, short_ema=105, long_ema=100)
    # Build recent bars (simple upward move)
    recent = []
    price = 100.0
    for i in range(20):
        price += 0.5
        recent.append({"open": price-0.3, "high": price+0.2, "low": price-0.4, "close": price, "volume": 100})
    daily_ref = {"prev_high": 120, "prev_low": 95, "prev_close": 110}
    result = confirm_signal(SignalType.LONG, ema, recent, daily_ref)
    assert "Insufficient" not in " ".join(result["reasons"])

def test_reject_long_rsi_too_high():
    ema = EMAState("TEST", "1m", 9, 21, short_ema=105, long_ema=100)
    # Artificial RSI > 90 by steep rise
    recent = []
    price = 50.0
    for i in range(20):
        price += 5.0
        recent.append({"open": price-4.5, "high": price+1.0, "low": price-4.6, "close": price, "volume": 100})
    daily_ref = {"prev_high": 60, "prev_low": 30, "prev_close": 55}
    result = confirm_signal(SignalType.LONG, ema, recent, daily_ref)
    assert not result["confirmed"]