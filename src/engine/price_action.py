"""Price action pattern helpers for confirmation layer."""
from typing import Dict


def analyze_candle(bar: Dict) -> Dict:
    high = bar["high"]; low = bar["low"]; open_ = bar["open"]; close = bar["close"]
    rng = max(high - low, 1e-9)
    body = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    return {
        "range": rng,
        "body_pct": body / rng,
        "bullish": close > open_,
        "bearish": close < open_,
        "upper_wick_pct": upper_wick / rng,
        "lower_wick_pct": lower_wick / rng
    }

def is_bullish_engulf(prev_bar: Dict, cur_bar: Dict) -> bool:
    return (
        cur_bar["close"] > cur_bar["open"] and
        prev_bar["close"] < prev_bar["open"] and
        cur_bar["close"] >= prev_bar["open"] and
        cur_bar["open"] <= prev_bar["close"]
    )

def is_bearish_engulf(prev_bar: Dict, cur_bar: Dict) -> bool:
    return (
        cur_bar["close"] < cur_bar["open"] and
        prev_bar["close"] > prev_bar["open"] and
        cur_bar["open"] >= prev_bar["close"] and
        cur_bar["close"] <= prev_bar["open"]
    )

def is_hammer(bar: Dict) -> bool:
    pa = analyze_candle(bar)
    return (
        pa["bullish"] and
        pa["lower_wick_pct"] >= 1.5 * pa["body_pct"] and
        pa["upper_wick_pct"] <= 0.1
    )

def is_shooting_star(bar: Dict) -> bool:
    pa = analyze_candle(bar)
    return (
        pa["bearish"] and
        pa["upper_wick_pct"] >= 1.5 * pa["body_pct"] and
        pa["lower_wick_pct"] <= 0.1
    )

def is_three_green_candles(bars: list) -> bool:
    if len(bars) < 3:
        return False
    return all(b["close"] > b["open"] for b in bars[-3:])

def is_three_red_candles(bars: list) -> bool:
    if len(bars) < 3:
        return False
    return all(b["close"] < b["open"] for b in bars[-3:])
