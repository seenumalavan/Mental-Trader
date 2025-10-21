from math import floor
from typing import Dict
from src.models.option_models import OptionContract


def compute_option_position(contract: OptionContract,
                            underlying_side: str,
                            account_risk_cap: float,
                            lot_size: int,
                            mode: str) -> Dict[str, float]:
    premium = contract.ltp
    if premium <= 0:
        return {'lots': 0, 'stop': premium, 'target': premium}
    if mode == 'scalper':
        target_move_pct = 0.20
        stop_move_pct = 0.12
    else:
        target_move_pct = 0.35
        stop_move_pct = 0.20
    target = premium * (1 + target_move_pct)
    stop = premium * (1 - stop_move_pct)
    per_lot_risk = (premium - stop) * lot_size
    if per_lot_risk <= 0:
        return {'lots': 0, 'stop': stop, 'target': target}
    lots = floor(account_risk_cap / per_lot_risk)
    return {'lots': max(lots, 0), 'stop': stop, 'target': target}
