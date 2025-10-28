"""
Database models for the trading system.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Candle:
	"""Represents a price candle/bar."""
	symbol: str
	timeframe: str
	ts: datetime
	open: float
	high: float
	low: float
	close: float
	volume: int

	def to_dict(self):
		return {
			"symbol": self.symbol,
			"timeframe": self.timeframe,
			"ts": self.ts.isoformat(),
			"open": self.open,
			"high": self.high,
			"low": self.low,
			"close": self.close,
			"volume": self.volume
		}


@dataclass
class Trade:
	"""Represents a trade record."""
	id: str
	symbol: str
	timeframe: str
	side: str
	entry_price: float
	size: int
	stop_loss: float
	target: float
	status: str
	created_at: datetime
	exit_price: Optional[float] = None
	exit_time: Optional[datetime] = None
	pnl: Optional[float] = None


@dataclass
class EMAStateRecord:
	"""Represents stored EMA state."""
	symbol: str
	timeframe: str
	period: int
	ema_value: float
	last_ts: datetime