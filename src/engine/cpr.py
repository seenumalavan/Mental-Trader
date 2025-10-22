"""Central Pivot Range (CPR) utilities.

Computes Pivot (P), Bottom Central (BC), Top Central (TC) from previous day OHLC.
Includes a simple width classification useful for volatility context.
"""
from typing import Dict


def compute_cpr(prev_high: float, prev_low: float, prev_close: float) -> Dict[str, float]:
    p = (prev_high + prev_low + prev_close) / 3.0
    bc = (prev_high + prev_low) / 2.0
    tc = (p - bc) + p
    return {"P": p, "BC": bc, "TC": tc}

def classify_cpr_width(prev_high: float, prev_low: float, prev_close: float) -> str:
    p = (prev_high + prev_low + prev_close) / 3.0
    bc = (prev_high + prev_low) / 2.0
    tc = (p - bc) + p
    width = tc - bc
    rel = width / p if p else 0.0
    if rel < 0.0025:
        return "narrow"
    if rel < 0.005:
        return "normal"
    return "wide"
