import math

class RiskManager:
    def __init__(self, account_balance: float = 100000.0, risk_per_trade: float = 0.005, max_daily_loss: float = 0.02):
        self.account_balance = account_balance
        self.risk_per_trade = risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.daily_loss = 0.0

    def calc_size(self, entry_price: float, stop_loss: float, lot_size: int = 1) -> int:
        risk_amount = self.account_balance * self.risk_per_trade
        per_share_risk = abs(entry_price - stop_loss)
        if per_share_risk <= 0:
            return 0
        raw_qty = risk_amount / per_share_risk
        qty = math.floor(raw_qty / lot_size) * lot_size
        return max(0, int(qty))

    def register_loss(self, loss_amount: float):
        self.daily_loss += loss_amount

    def check_daily_stop(self) -> bool:
        return self.daily_loss >= (self.account_balance * self.max_daily_loss)
