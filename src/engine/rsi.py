"""RSI calculation utilities.

Implements a minimal Wilder-style RSI suitable for intraday confirmation.
Avoids external dependencies; uses a simple backward-looking window.
"""
from typing import List, Optional


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


def compute_rsi_series(closes: List[float], period: int = 14) -> Optional[List[float]]:
    """Compute RSI series for a list of closing prices.

    Returns a list of RSI values, one for each valid period.
    Each RSI value represents the RSI at that point in time.
    """
    if len(closes) < period + 1:
        return None

    rsi_values = []
    for i in range(period, len(closes)):
        # Calculate RSI for the window ending at index i
        window_closes = closes[i-period:i+1]
        rsi = compute_rsi(window_closes, period)
        if rsi is not None:
            rsi_values.append(rsi)

    return rsi_values if rsi_values else None


def compute_rsi_wilder_stream(prev_avg_gain: float, prev_avg_loss: float, change: float, period: int):
    """Compute RSI using Wilder's smoothing for streaming data.

    Args:
        prev_avg_gain: Previous average gain
        prev_avg_loss: Previous average loss
        change: Current price change
        period: RSI period

    Returns:
        tuple: (new_avg_gain, new_avg_loss, rsi_value)
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