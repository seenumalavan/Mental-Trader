import statistics
from typing import Dict, List

from src.models.option_models import OptionContract, RankedStrike


def compute_chain_metrics(chain: List[OptionContract]) -> Dict[str, float]:
    if not chain:
        return {}
    calls = [c for c in chain if c.kind == 'CALL']
    puts = [p for p in chain if p.kind == 'PUT']
    total_call_oi = sum(x.oi for x in calls)
    total_put_oi = sum(x.oi for x in puts)
    pcr = (total_put_oi / total_call_oi) if total_call_oi else 0.0
    ivs = [c.iv for c in chain if c.iv > 0]
    iv_median = statistics.median(ivs) if ivs else 0.0
    iv_mean = statistics.mean(ivs) if ivs else 0.0
    skew = 0.0
    atm_call_iv = _approx_atm_iv(calls)
    atm_put_iv = _approx_atm_iv(puts)
    if atm_call_iv is not None and atm_put_iv is not None:
        skew = atm_call_iv - atm_put_iv
    return {
        'pcr': pcr,
        'iv_median': iv_median,
        'iv_mean': iv_mean,
        'iv_skew': skew
    }


def _approx_atm_iv(contracts: List[OptionContract]):
    if not contracts:
        return None
    strikes = sorted(set(c.strike for c in contracts))
    if not strikes:
        return None
    mid = strikes[len(strikes)//2]
    near = sorted(contracts, key=lambda c: abs(c.strike - mid))
    return near[0].iv if near else None


def rank_strikes(chain: List[OptionContract], side: str, spot_price: float, mode: str,
                 oi_min_percentile: int, iv_median: float,
                 spread_max_pct_scalper: float, spread_max_pct_intraday: float) -> List[RankedStrike]:
    if not chain:
        return []
    relevant = [c for c in chain if (side == 'BUY' and c.kind == 'CALL') or (side == 'SELL' and c.kind == 'PUT')]
    if not relevant:
        return []
    oi_values = sorted([c.oi for c in relevant])

    def oi_percentile(val: int) -> float:
        if not oi_values:
            return 0.0
        rank = sum(1 for x in oi_values if x <= val)
        return (rank / len(oi_values)) * 100.0

    atm_strike = round(spot_price / 50.0) * 50
    max_distance = 3 if mode == 'intraday' else 2
    spread_limit = spread_max_pct_intraday if mode == 'intraday' else spread_max_pct_scalper

    ranked: List[RankedStrike] = []
    for c in relevant:
        distance = abs(c.strike - atm_strike) // 50
        if distance > max_distance:
            continue
        pct = oi_percentile(c.oi)
        if pct < oi_min_percentile:
            continue
        if c.spread_pct > spread_limit:
            continue
        comp = {}
        comp['oi_rank'] = pct / 100.0
        comp['distance'] = 1.0 - (distance / (max_distance + 0.001))
        comp['iv_quality'] = _iv_quality_component(c.iv, iv_median)
        comp['spread'] = 1.0 - min(c.spread_pct / spread_limit, 1.0)
        if c.oi_change is not None and c.oi_prev:
            change_ratio = (c.oi_change / max(c.oi_prev, 1))
            comp['oi_change'] = max(change_ratio, 0.0)
        else:
            comp['oi_change'] = 0.5
        # Add greeks component: for BUY (calls), prefer higher delta; for SELL (puts), prefer higher abs(delta)
        delta_score = 0.5
        if c.delta is not None:
            if side == 'BUY' and c.kind == 'CALL':
                delta_score = min(c.delta, 1.0)  # Closer to 1 for ITM calls
            elif side == 'SELL' and c.kind == 'PUT':
                delta_score = min(abs(c.delta), 1.0)  # Closer to 1 for ITM puts
        comp['delta_suitability'] = delta_score
        score = (comp['oi_rank'] * 0.20 +
                 comp['distance'] * 0.10 +
                 comp['iv_quality'] * 0.20 +
                 comp['spread'] * 0.15 +
                 comp['oi_change'] * 0.15 +
                 comp['delta_suitability'] * 0.20)
        ranked.append(RankedStrike(contract=c,
                                   score=score,
                                   components=comp,
                                   distance_from_atm=distance,
                                   effective_spread_pct=c.spread_pct))
    return sorted(ranked, key=lambda r: r.score, reverse=True)


def _iv_quality_component(iv: float, iv_median: float) -> float:
    if iv_median <= 0:
        return 0.5
    deviation = abs(iv - iv_median) / iv_median
    if deviation < 0.05:
        return 1.0
    if deviation < 0.15:
        return 0.7
    if deviation < 0.30:
        return 0.4
    return 0.2
