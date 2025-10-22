from dataclasses import dataclass


@dataclass
class SimTrade:
    symbol: str
    side: str
    entry: float
    size: int
    sl: float
    tg: float
    exit: float = None
    pnl: float = None

class ExecutorSimulator:
    def __init__(self, slippage=0.0, commission=0.0):
        self.trades = []
        self.slippage = slippage
        self.commission = commission

    def open_trade(self, symbol, side, price, size, sl, tg):
        fill = price + (self.slippage if side == "BUY" else -self.slippage)
        t = SimTrade(symbol, side, fill, size, sl, tg)
        self.trades.append(t)
        return t

    def close_trade(self, trade: SimTrade, exit_price: float):
        trade.exit = exit_price
        multiplier = 1 if trade.side == "BUY" else -1
        gross = (trade.exit - trade.entry) * trade.size * multiplier
        trade.pnl = gross - self.commission
        return trade
