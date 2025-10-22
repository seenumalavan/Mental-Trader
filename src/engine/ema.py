from dataclasses import dataclass
from typing import List

@dataclass
class EMAState:
    symbol: str
    timeframe: str
    short_period: int
    long_period: int
    short_ema: float = None
    long_ema: float = None
    prev_short: float = None
    prev_long: float = None
    atr: float = None

    def initialize_from_candles(self, candles: List[dict]):
        # candles: chronological (old -> new) list of {ts, open, high, low, close, volume}
        closes = [c["close"] for c in candles]
        if not closes:
            return
        # Calculate ATR
        if len(candles) > 1:
            trs = []
            prev_close = candles[0]["close"]
            for c in candles[1:]:
                tr = max(c["high"] - c["low"], abs(c["high"] - prev_close), abs(c["low"] - prev_close))
                trs.append(tr)
                prev_close = c["close"]
            if trs:
                self.atr = sum(trs) / len(trs)  # Simple average, could use EMA for ATR
        # seed EMA with SMA of first N if possible
        def sma(data, n):
            return sum(data[-n:]) / n if len(data) >= n else sum(data) / len(data)

        if len(closes) >= self.short_period:
            self.short_ema = sma(closes, self.short_period)
        else:
            self.short_ema = closes[-1]

        if len(closes) >= self.long_period:
            self.long_ema = sma(closes, self.long_period)
        else:
            self.long_ema = closes[-1]

        # iterate remaining to smooth
        start = 0
        for price in closes[start:]:
            self.short_ema = self._ema_step(price, self.short_ema, self.short_period)
            self.long_ema = self._ema_step(price, self.long_ema, self.long_period)

    def _ema_step(self, price: float, prev_ema: float, period: int) -> float:
        alpha = 2.0 / (period + 1)
        return alpha * price + (1 - alpha) * prev_ema

    def update_with_close(self, close_price: float):
        self.prev_short = self.short_ema
        self.prev_long = self.long_ema
        if self.short_ema is None:
            self.short_ema = close_price
        else:
            self.short_ema = self._ema_step(close_price, self.short_ema, self.short_period)
        if self.long_ema is None:
            self.long_ema = close_price
        else:
            self.long_ema = self._ema_step(close_price, self.long_ema, self.long_period)
