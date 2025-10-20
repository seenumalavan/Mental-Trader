"""
Advanced Support/Resistance zone detection and signal confirmation.

Usage:
    zones = build_sr_zones(recent_bars, higher_tf_bars=higher_bars)
    ok, details = confirm_with_sr(side, current_price, zones)

Bar format required (dict):
    {
        'open': float, 'high': float, 'low': float, 'close': float,
        'volume': float (optional), 'ts': datetime or numeric timestamp
    }
"""

from typing import List, Dict, Tuple, Optional
from math import exp

# -------------------------------
# Core configuration (tune later)
# -------------------------------
SWING_LOOKBACK = 2              # bars on each side for pivot test
MAX_ZONE_REL_WIDTH = 0.003      # default max zone width relative to price (~0.3%)
MIN_TOUCHES = 2                 # minimum touches for a zone to be considered
RECENCY_DECAY = 0.0005          # decay per second (if ts numeric) or per bar index fallback
PROXIMITY_REL = 0.002           # “too close” relative threshold (0.2%) for obstruction
SUPPORT_REQUIRED_DIST_REL = 0.01  # max distance (1%) below for actionable support
RESIST_REQUIRED_DIST_REL = 0.01   # max distance (1%) above for actionable resistance
HIGHER_TF_WEIGHT = 1.6          # weight multiplier for higher timeframe pivots
VOLUME_WEIGHT_SCALE = 0.25      # scaling factor for volume contribution in score
MAX_ZONES = 25                  # cap returned zones for performance

# -------------------------------
# Pivot Detection
# -------------------------------

def _is_pivot_high(bars: List[Dict], idx: int, lookback: int) -> bool:
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    h = bars[idx]['high']
    return all(h > bars[idx - i]['high'] and h > bars[idx + i]['high'] for i in range(1, lookback + 1))

def _is_pivot_low(bars: List[Dict], idx: int, lookback: int) -> bool:
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    l = bars[idx]['low']
    return all(l < bars[idx - i]['low'] and l < bars[idx + i]['low'] for i in range(1, lookback + 1))

def _extract_pivots(bars: List[Dict], lookback: int, weight: float = 1.0) -> List[Dict]:
    pivots = []
    for i in range(len(bars)):
        if _is_pivot_high(bars, i, lookback):
            pivots.append({
                'type': 'high',
                'price': bars[i]['high'],
                'idx': i,
                'ts': bars[i].get('ts'),
                'volume': bars[i].get('volume', 0.0),
                'weight': weight
            })
        elif _is_pivot_low(bars, i, lookback):
            pivots.append({
                'type': 'low',
                'price': bars[i]['low'],
                'idx': i,
                'ts': bars[i].get('ts'),
                'volume': bars[i].get('volume', 0.0),
                'weight': weight
            })
    return pivots

# -------------------------------
# Zone Building (Clustering)
# -------------------------------

def _adaptive_width(avg_price: float) -> float:
    return avg_price * MAX_ZONE_REL_WIDTH

def _cluster_pivots(pivots: List[Dict]) -> List[List[Dict]]:
    clusters: List[List[Dict]] = []
    sorted_pivots = sorted(pivots, key=lambda p: p['price'])
    for p in sorted_pivots:
        placed = False
        for cluster in clusters:
            avg_price = sum(c['price'] for c in cluster) / len(cluster)
            width = _adaptive_width(avg_price)
            if abs(p['price'] - avg_price) <= width:
                cluster.append(p)
                placed = True
                break
        if not placed:
            clusters.append([p])
    return clusters

# -------------------------------
# Zone Scoring
# -------------------------------

def _recency_factor(pivot: Dict, latest_idx: int) -> float:
    # Prefer using bar index difference if timestamp absent
    age_bars = latest_idx - pivot['idx']
    return exp(-0.05 * age_bars)  # simple bar-based decay

def _zone_score(cluster: List[Dict], latest_idx: int) -> float:
    touches = len(cluster)
    avg_price = sum(p['price'] for p in cluster) / touches
    total_volume = sum(p['volume'] for p in cluster)
    avg_weight = sum(p['weight'] for p in cluster) / touches
    recency = max(_recency_factor(p, latest_idx) for p in cluster)
    base = touches * avg_weight
    vol_component = (total_volume ** 0.5) * VOLUME_WEIGHT_SCALE if total_volume > 0 else 0.0
    score = base * recency + vol_component
    return score

# -------------------------------
# Zone Representation
# -------------------------------

def _build_zone(cluster: List[Dict], latest_idx: int) -> Dict:
    avg_price = sum(p['price'] for p in cluster) / len(cluster)
    width = _adaptive_width(avg_price)
    high_types = sum(1 for p in cluster if p['type'] == 'high')
    low_types = sum(1 for p in cluster if p['type'] == 'low')
    zone_type = 'resistance' if high_types >= low_types else 'support'
    score = _zone_score(cluster, latest_idx)
    return {
        'type': zone_type,
        'level': avg_price,
        'lower': avg_price - width,
        'upper': avg_price + width,
        'touches': len(cluster),
        'score': score
    }

# -------------------------------
# Public Zone Builder
# -------------------------------

def build_sr_zones(
    recent_bars: List[Dict],
    higher_tf_bars: Optional[List[Dict]] = None
) -> List[Dict]:
    if len(recent_bars) < SWING_LOOKBACK * 2 + 5:
        return []
    pivots = _extract_pivots(recent_bars, SWING_LOOKBACK, weight=1.0)
    if higher_tf_bars and len(higher_tf_bars) >= SWING_LOOKBACK * 2 + 5:
        pivots.extend(_extract_pivots(higher_tf_bars, SWING_LOOKBACK, weight=HIGHER_TF_WEIGHT))
    clusters = _cluster_pivots(pivots)
    latest_idx = len(recent_bars) - 1
    zones = []
    for cluster in clusters:
        if len(cluster) < MIN_TOUCHES:
            continue
        zone = _build_zone(cluster, latest_idx)
        zones.append(zone)
    # Sort by score desc, limit
    zones.sort(key=lambda z: z['score'], reverse=True)
    return zones[:MAX_ZONES]

# -------------------------------
# Confirmation Logic
# -------------------------------

def _nearest(zones: List[Dict], zone_type: str, current_price: float) -> Optional[Dict]:
    candidates = [z for z in zones if z['type'] == zone_type]
    if not candidates:
        return None
    return min(candidates, key=lambda z: abs(z['level'] - current_price))

def confirm_with_sr(side: str, current_price: float, zones: List[Dict]) -> Tuple[bool, Dict]:
    """
    Returns (ok, details)
    details includes: reasons, nearest_support, nearest_resistance
    Logic:
        LONG: ensure a support exists below within SUPPORT_REQUIRED_DIST_REL * price
              reject if strong resistance (score high) within PROXIMITY_REL * price above.
        SHORT: mirror logic.
    """
    reasons: List[str] = []
    sp = _nearest(zones, 'support', current_price)
    rs = _nearest(zones, 'resistance', current_price)

    price_unit = current_price
    max_support_dist = price_unit * SUPPORT_REQUIRED_DIST_REL
    max_resist_dist = price_unit * RESIST_REQUIRED_DIST_REL
    proximity_cutoff = price_unit * PROXIMITY_REL

    if side == 'BUY':
        if not sp or (current_price - sp['level']) > max_support_dist:
            reasons.append("No nearby support below")
        if rs and (rs['level'] - current_price) < proximity_cutoff and rs['score'] >= (sp['score'] if sp else 0):
            reasons.append("Strong resistance too close above")
    else:  # SELL
        if not rs or (rs['level'] - current_price) > max_resist_dist:
            reasons.append("No nearby resistance above")
        if sp and (current_price - sp['level']) < proximity_cutoff and sp['score'] >= (rs['score'] if rs else 0):
            reasons.append("Strong support too close below")

    ok = len(reasons) == 0
    details = {
        'ok': ok,
        'reasons': reasons,
        'nearest_support': sp,
        'nearest_resistance': rs
    }
    return ok, details

# -------------------------------
# Convenience wrapper
# -------------------------------

def sr_confirmation(side: str, current_price: float, recent_bars: List[Dict], higher_tf_bars: Optional[List[Dict]] = None) -> Dict:
    zones = build_sr_zones(recent_bars, higher_tf_bars)
    ok, details = confirm_with_sr(side, current_price, zones)
    return {'zones': zones, **details}