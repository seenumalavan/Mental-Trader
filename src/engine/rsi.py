"""RSI calculation utilities.

Implements a minimal Wilder-style RSI suitable for intraday confirmation.
Avoids external dependencies; uses a simple backward-looking window.
"""
from typing import List, Optional, Tuple

def compute_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """Compute RSI for a list of closing prices.

    Returns None if insufficient data (need period + 1 closes).
    Uses classic Wilder smoothing only for initial snapshot (no streamed state).
    """
    if len(closes) < period + 1:
        return None
    gains: List[float] = []
    losses: List[float] = []
    # Look back last `period` changes
    for i in range(1, period + 1):
        change = closes[-i] - closes[-(i+1)]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-change)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))

def stream_rsi_step(prev_avg_gain: float, prev_avg_loss: float, change: float, period: int) -> Tuple[float, float, float]:
    """Perform one streaming RSI step returning (avg_gain, avg_loss, rsi).

    Useful if later you decide to keep running RSI state per symbol.
    """
    gain = max(change, 0.0)
    loss = max(-change, 0.0)
    avg_gain = (prev_avg_gain * (period - 1) + gain) / period
    avg_loss = (prev_avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        rsi = 100.0
    else:
        rsi = 100.0 - (100.0 / (1 + (avg_gain / avg_loss)))
    return avg_gain, avg_loss, rsi
# Minimal RSI calculator (Wilder’s smoothing)
from typing import List, Optional

def compute_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, period + 1):
        change = closes[-(i+0)] - closes[-(i+1)]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-change)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))

def compute_rsi_wilder_stream(prev_avg_gain: float, prev_avg_loss: float, change: float, period: int):
    gain = max(change, 0.0)
    loss = max(-change, 0.0)
    avg_gain = (prev_avg_gain * (period - 1) + gain) / period
    avg_loss = (prev_avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        rsi = 100.0
    else:
        rsi = 100.0 - (100.0 / (1 + (avg_gain / avg_loss)))
    return avg_gain, avg_loss, rsi