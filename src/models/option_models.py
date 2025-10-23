from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class OptionContract:
    symbol: str
    strike: int
    kind: str  # 'CALL' or 'PUT'
    expiry: datetime
    oi: int
    oi_prev: Optional[int]
    iv: float
    ltp: float
    bid: float
    ask: float
    timestamp: datetime
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None

    @property
    def oi_change(self) -> Optional[int]:
        if self.oi_prev is None:
            return None
        return self.oi - self.oi_prev

    @property
    def spread(self) -> float:
        return max(self.ask - self.bid, 0.0)

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2.0 if self.ask and self.bid else self.ltp

    @property
    def spread_pct(self) -> float:
        m = self.mid
        return (self.spread / m) if m else 0.0

@dataclass
class RankedStrike:
    contract: OptionContract
    score: float
    components: Dict[str, float]
    distance_from_atm: int
    effective_spread_pct: float

@dataclass
class OptionSignal:
    underlying_side: str  # 'BUY' or 'SELL'
    contract_symbol: str
    strike: int
    kind: str
    premium_ltp: float
    suggested_size_lots: int
    stop_loss_premium: float
    target_premium: float
    metrics_snapshot: Dict[str, float]
    reasoning: List[str]
    timestamp: datetime
