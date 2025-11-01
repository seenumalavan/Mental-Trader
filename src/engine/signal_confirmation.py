"""Signal confirmation pipeline using CPR and price action."""
import logging
from typing import Dict, List

from src.engine.cpr import compute_cpr
from src.engine.ema import EMAState
from src.engine.price_action import (analyze_candle, is_bearish_engulf,
                                     is_bullish_engulf, is_hammer, is_shooting_star,
                                     is_three_green_candles, is_three_red_candles)
from src.engine.rsi import compute_rsi

logger = logging.getLogger("signal_confirm")

class SignalType:
    LONG = "BUY"
    SHORT = "SELL"

def is_virgin_cpr_break(side: str, recent_bars: List[Dict], cpr: Dict) -> bool:
    """Check if CPR level break is 'virgin' (level untouched in recent bars)"""
    if not cpr or len(recent_bars) < 10:
        return False
    
    if side == SignalType.LONG:
        tc_level = cpr["TC"]
        # Check if TC was touched in last 10 bars (excluding current bar)
        touched_recently = any(
            bar["high"] >= tc_level >= bar["low"] 
            for bar in recent_bars[-11:-1]  # Last 10 bars before current
        )
        current_break = recent_bars[-1]["close"] > tc_level
        return current_break and not touched_recently
    else:  # SHORT
        bc_level = cpr["BC"]
        # Check if BC was touched in last 10 bars (excluding current bar)
        touched_recently = any(
            bar["high"] >= bc_level >= bar["low"] 
            for bar in recent_bars[-11:-1]  # Last 10 bars before current
        )
        current_break = recent_bars[-1]["close"] < bc_level
        return current_break and not touched_recently

def count_active_filters(side: str, scores: Dict, recent_bars: List[Dict], symbol: str = "") -> int:
    """Count how many technical filters are currently active/passing"""
    count = 0
    
    # RSI slope (always included if calculated)
    if "rsi_slope" in scores:
        if side == SignalType.LONG and scores["rsi_slope"] > 0:
            count += 1
        elif side == SignalType.SHORT and scores["rsi_slope"] < 0:
            count += 1
    
    # Volume (adaptive threshold)
    if "volume_ratio" in scores:
        is_option = "CE" in symbol.upper() or "PE" in symbol.upper()
        threshold = 1.2 if is_option else 1.7
        if scores["volume_ratio"] >= threshold:
            count += 1
    
    # VWAP
    if "vwap" in scores and recent_bars:
        current_price = recent_bars[-1]["close"]
        vwap = scores["vwap"]
        if side == SignalType.LONG and current_price > vwap:
            count += 1
        elif side == SignalType.SHORT and current_price < vwap:
            count += 1
    
    return count

def get_required_filters(time_window: str) -> int:
    """Get minimum required active filters based on time window"""
    if time_window == "morning":
        return 4  # EMA + PA + CPR + minimum 1 technical filter
    elif time_window == "afternoon":
        return 3  # EMA + PA + minimum 1 technical filter (CPR optional)
    else:
        return 2  # Minimum viable for other times

def confirm_signal(
    side: str,
    ema_state: EMAState,
    recent_bars: List[Dict],
    daily_ref: Dict,  # expects prev_high/prev_low/prev_close
    symbol: str = "",  # Symbol to detect options vs futures
    time_window: str = "morning"  # "morning", "afternoon", "midday"
) -> Dict:
    """Confirm a raw EMA signal using ADAPTIVE CPR SNIPER logic (75%+ Win Rate).

    Progressive Filter Stack with Virgin CPR:
    1. EMA Crossover (base signal)
    2. Virgin CPR Break (morning only) - Fresh break of untouched levels
    3. Price Action - Engulfing/Hammer patterns
    4. RSI(7) Slope - Up for longs, down for shorts
    5. Volume/Tick Volume (1.7x/1.2x average) - Above average volume
    6. VWAP - Price above VWAP for longs, below for shorts

    Adaptive Requirements by Time Window:
    - Morning (9:15-10:30): Virgin CPR + PA + 4+ active filters
    - Afternoon (14:30-15:15): PA + 3+ active filters (CPR optional)
    - Mid-day: Skip all signals

    Volume Handling:
    - Futures/Index: Real volume (1.7x threshold)
    - Options: Tick volume (1.2x threshold, skipped if zero)

    Returns dict {confirmed, reasons, scores, rsi, cpr, active_filters, required_filters}.
    `side` should be "BUY" or "SELL" matching Signal.side.
    """
    reasons: List[str] = []
    scores: Dict[str, float] = {}
    confirmed = True

    # Skip for midday
    if time_window == "midday":
        return {"confirmed": False, "reasons": ["Mid-day skip"], "scores": scores, "rsi": None, "cpr": None}

    # Get closes for potential use
    closes = [b["close"] for b in recent_bars] if recent_bars else []

    # Morning: EMA + PA + CPR (Virgin CPR required)
    if time_window == "morning":
        # CPR check with virgin break requirement
        cpr = None
        have_daily = all(k in daily_ref and daily_ref[k] is not None for k in ("prev_high", "prev_low", "prev_close"))
        if have_daily:
            cpr = compute_cpr(daily_ref["prev_high"], daily_ref["prev_low"], daily_ref["prev_close"])
            scores.update({"P": cpr["P"], "BC": cpr["BC"], "TC": cpr["TC"]})
            
            # Check for virgin CPR break
            virgin_break = is_virgin_cpr_break(side, recent_bars, cpr)
            if not virgin_break:
                confirmed = False
                reasons.append("CPR break not virgin (level touched recently)")
        else:
            reasons.append("Missing previous day data for CPR")
            confirmed = False

    # Afternoon: EMA + PA only (no CPR, no RSI)
    # Mid-day: skipped above

    # Price Action (required for both morning and afternoon)
    pa_confirmed = False
    if len(recent_bars) >= 2:
        prev_bar = recent_bars[-2]
        cur_bar = recent_bars[-1]
        pa = analyze_candle(cur_bar)
        scores["body_pct"] = pa["body_pct"]
        if side == SignalType.LONG:
            engulf_ok = is_bullish_engulf(prev_bar, cur_bar)
            hammer_ok = is_hammer(cur_bar)
            three_green_ok = is_three_green_candles(recent_bars)
            if engulf_ok or hammer_ok or three_green_ok:
                pa_confirmed = True
                reasons.append("Valid LONG PA: " + ("engulf" if engulf_ok else "hammer" if hammer_ok else "3 green"))
            else:
                confirmed = False
                reasons.append("No valid LONG PA pattern")
        else:
            engulf_ok = is_bearish_engulf(prev_bar, cur_bar)
            shooting_ok = is_shooting_star(cur_bar)
            three_red_ok = is_three_red_candles(recent_bars)
            if engulf_ok or shooting_ok or three_red_ok:
                pa_confirmed = True
                reasons.append("Valid SHORT PA: " + ("engulf" if engulf_ok else "shooting" if shooting_ok else "3 red"))
            else:
                confirmed = False
                reasons.append("No valid SHORT PA pattern")
    else:
        confirmed = False
        reasons.append("Insufficient bars for price action analysis")

    # RSI(7) Slope Check
    rsi_values = compute_rsi(closes, period=7) if len(closes) >= 7 else None
    if rsi_values and len(rsi_values) >= 2:
        current_rsi = rsi_values[-1]
        prev_rsi = rsi_values[-2]
        rsi_slope = current_rsi - prev_rsi
        scores["rsi_7"] = current_rsi
        scores["rsi_slope"] = rsi_slope
        
        if side == SignalType.LONG and rsi_slope <= 0:
            confirmed = False
            reasons.append(f"RSI(7) not sloping up: {rsi_slope:.2f}")
        elif side == SignalType.SHORT and rsi_slope >= 0:
            confirmed = False
            reasons.append(f"RSI(7) not sloping down: {rsi_slope:.2f}")
    else:
        confirmed = False
        reasons.append("Insufficient data for RSI(7) slope")

    # Volume Check (adaptive for futures vs options)
    is_option = "CE" in symbol.upper() or "PE" in symbol.upper()
    
    if len(recent_bars) >= 10:  # Need enough bars for average
        volumes = [b.get("volume", 0) for b in recent_bars[-10:]]  # Last 10 bars
        avg_volume = sum(volumes) / len(volumes)
        current_volume = recent_bars[-1].get("volume", 0)
        
        if is_option and current_volume == 0:
            # Skip volume check for options with zero volume
            scores["volume_ratio"] = 0.0
            reasons.append("Volume check skipped for options (zero volume)")
        else:
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
            scores["volume_ratio"] = volume_ratio
            
            # Different thresholds for futures vs options
            threshold = 1.2 if is_option else 1.7
            
            if volume_ratio < threshold:
                confirmed = False
                reasons.append(f"Volume below {threshold}x average: {volume_ratio:.2f}x ({'options' if is_option else 'futures'})")
    else:
        confirmed = False
        reasons.append("Insufficient bars for volume analysis")

    # VWAP Check
    if len(recent_bars) >= 5:  # Need some bars for VWAP
        # Calculate VWAP for recent bars
        price_volume_sum = 0
        volume_sum = 0
        valid_bars = 0
        
        for bar in recent_bars[-20:]:  # Use last 20 bars for VWAP
            vol = bar.get("volume", 0)
            if vol > 0:  # Only include bars with volume
                typical_price = (bar["high"] + bar["low"] + bar["close"]) / 3
                price_volume_sum += typical_price * vol
                volume_sum += vol
                valid_bars += 1
        
        if valid_bars >= 5:  # Need at least 5 bars with volume
            vwap = price_volume_sum / volume_sum if volume_sum > 0 else None
            if vwap is not None:
                scores["vwap"] = vwap
                current_price = recent_bars[-1]["close"]
                
                if side == SignalType.LONG and current_price <= vwap:
                    confirmed = False
                    reasons.append(f"Price below VWAP for LONG: {current_price:.2f} <= {vwap:.2f}")
                elif side == SignalType.SHORT and current_price >= vwap:
                    confirmed = False
                    reasons.append(f"Price above VWAP for SHORT: {current_price:.2f} >= {vwap:.2f}")
            else:
                if not is_option:
                    confirmed = False
                    reasons.append("Unable to calculate VWAP")
                else:
                    reasons.append("VWAP skipped for options (insufficient volume data)")
        else:
            if not is_option:
                confirmed = False
                reasons.append("Insufficient bars with volume for VWAP")
            else:
                reasons.append("VWAP skipped for options (insufficient volume data)")
    else:
        confirmed = False
        reasons.append("Insufficient bars for VWAP analysis")

    # Adaptive Filter Counting (Pine Script style)
    active_filters = count_active_filters(side, scores, recent_bars, symbol)
    required_filters = get_required_filters(time_window)
    
    if active_filters < required_filters:
        confirmed = False
        reasons.append(f"Insufficient active filters: {active_filters}/{required_filters} required for {time_window}")

    final = {
        "confirmed": confirmed and pa_confirmed,
        "reasons": reasons,
        "scores": scores,
        "rsi": rsi_values[-1] if rsi_values else None,
        "cpr": cpr if time_window == "morning" else None,
        "active_filters": active_filters,
        "required_filters": required_filters
    }
    logger.debug(f"Confirmation result: {final}")
    return final
