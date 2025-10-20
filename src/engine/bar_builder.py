from collections import defaultdict
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Tuple
import math

@dataclass
class Bar:
    ts: str   # ISO timestamp of bucket start
    open: float
    high: float
    low: float
    close: float
    volume: int

    def to_dict(self):
        return {"ts": self.ts, "open": self.open, "high": self.high, "low": self.low, "close": self.close, "volume": self.volume}

class BarBuilder:
    """
    Build 1m and 5m bars from incoming ticks.
    push_tick returns list of closed bars: [(symbol,timeframe,Bar), ...]
    """
    def __init__(self):
        self._current = {}  # key=(symbol,tf)-> dict(bucket,open,high,low,close,volume)

    def _to_dt(self, ts):
        if isinstance(ts, (int, float)):
            # assume ms
            return datetime.fromtimestamp(ts/1000.0, tz=timezone.utc)
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts)
            except Exception:
                return datetime.utcnow().replace(tzinfo=timezone.utc)
        return datetime.utcnow().replace(tzinfo=timezone.utc)

    def _bucket(self, dt, timeframe: str):
        if timeframe == "1m":
            return dt.replace(second=0, microsecond=0)
        if timeframe == "5m":
            minute = (dt.minute // 5) * 5
            return dt.replace(minute=minute, second=0, microsecond=0)
        return dt.replace(second=0, microsecond=0)

    def push_tick(self, tick) -> List[Tuple[str,str,Bar]]:
        symbol = tick["symbol"]
        price = float(tick["price"])
        vol = int(tick.get("volume", 0) or 0)
        ts = tick.get("ts")
        dt = self._to_dt(ts)
        closed = []
        for tf in ("1m", "5m"):
            key = (symbol, tf)
            bucket = self._bucket(dt, tf)
            cur = self._current.get(key)
            if cur is None or cur["bucket"] != bucket:
                # close previous
                if cur is not None:
                    bar = Bar(ts=cur["bucket"].isoformat(), open=cur["open"], high=cur["high"],
                              low=cur["low"], close=cur["close"], volume=cur["volume"])
                    closed.append((symbol, tf, bar))
                # start new
                self._current[key] = {"bucket": bucket, "open": price, "high": price, "low": price, "close": price, "volume": vol}
            else:
                cur["high"] = max(cur["high"], price)
                cur["low"] = min(cur["low"], price)
                cur["close"] = price
                cur["volume"] += vol
        return closed
