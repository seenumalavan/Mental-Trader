"""Signal confirmation pipeline using RSI, CPR and price action."""
import logging
from typing import Dict, List

from src.engine.cpr import compute_cpr
from src.engine.ema import EMAState
from src.engine.price_action import (analyze_candle, is_bearish_engulf,
                                     is_bullish_engulf)
from src.engine.rsi import compute_rsi

logger = logging.getLogger("signal_confirm")

class SignalType:
    LONG = "BUY"
    SHORT = "SELL"

def confirm_signal(
    side: str,
    ema_state: EMAState,
    recent_bars: List[Dict],
    daily_ref: Dict,  # expects prev_high/prev_low/prev_close
    rsi_period: int = 14,
    require_cpr: bool = False
) -> Dict:
    """Confirm a raw EMA signal using RSI, CPR and price action heuristics.

    Returns dict {confirmed, reasons, scores, rsi, cpr}.
    `side` should be "BUY" or "SELL" matching Signal.side.
    """
    reasons: List[str] = []
    scores: Dict[str, float] = {}
    confirmed = True

    # RSI
    closes = [b["close"] for b in recent_bars]
    rsi = compute_rsi(closes)
    scores["rsi"] = rsi if rsi is not None else -1
    if rsi is None:
        reasons.append("Insufficient data for RSI")
        confirmed = False
    else:
        if side == SignalType.LONG:
            if not (45 <= rsi <= 70):
                confirmed = False
                reasons.append(f"RSI out of preferred LONG zone: {rsi:.2f}")
        else:  # SHORT
            if not (30 <= rsi <= 55):
                confirmed = False
                reasons.append(f"RSI out of preferred SHORT zone: {rsi:.2f}")

    # CPR
    cpr = None
    have_daily = all(k in daily_ref and daily_ref[k] is not None for k in ("prev_high", "prev_low", "prev_close"))
    if have_daily:
        cpr = compute_cpr(daily_ref["prev_high"], daily_ref["prev_low"], daily_ref["prev_close"])
        scores.update({"P": cpr["P"], "BC": cpr["BC"], "TC": cpr["TC"]})
        last_close = closes[-1] if closes else None
        if last_close is not None:
            if side == SignalType.LONG and last_close < cpr["P"]:
                confirmed = False
                reasons.append("Price below Pivot for LONG")
            if side == SignalType.SHORT and last_close > cpr["P"]:
                confirmed = False
                reasons.append("Price above Pivot for SHORT")
    else:
        if require_cpr:
            reasons.append("Missing previous day data for CPR")
            confirmed = False
        else:
            reasons.append("CPR skipped (missing daily data)")

    # Price Action
    if len(recent_bars) >= 2:
        prev_bar = recent_bars[-2]
        cur_bar = recent_bars[-1]
        pa = analyze_candle(cur_bar)
        scores["body_pct"] = pa["body_pct"]
        if side == SignalType.LONG:
            bullish_ok = pa["bullish"] and pa["body_pct"] >= 0.55
            engulf_ok = is_bullish_engulf(prev_bar, cur_bar)
            if not (bullish_ok or engulf_ok):
                confirmed = False
                reasons.append("Weak bullish price action")
        else:
            bearish_ok = pa["bearish"] and pa["body_pct"] >= 0.55
            engulf_ok = is_bearish_engulf(prev_bar, cur_bar)
            if not (bearish_ok or engulf_ok):
                confirmed = False
                reasons.append("Weak bearish price action")
    else:
        confirmed = False
        reasons.append("Insufficient bars for price action analysis")

    final = {
        "confirmed": confirmed and not reasons,
        "reasons": reasons,
        "scores": scores,
        "rsi": rsi,
        "cpr": cpr
    }
    logger.debug(f"Confirmation result: {final}")
    return final
