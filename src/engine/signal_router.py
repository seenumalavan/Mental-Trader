# Simple router; intentionally small to avoid duplication of orders
from dataclasses import dataclass

@dataclass
class SignalMessage:
    symbol: str
    side: str
    price: float
    size: int
    stop_loss: float
    target: float
