"""
EMA State persistence utilities.
"""
from datetime import datetime
from typing import Optional, Dict, Tuple
from src.persistence.db import Database
from src.engine.ema import EMAState


class EMAStatePersistence:
    """Handles persistence and restoration of EMA states."""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def save_ema_state(self, ema_state: EMAState) -> None:
        """Save EMA state to database."""
        if ema_state.short_ema is not None:
            await self.db.upsert_ema_state(
                ema_state.symbol,
                ema_state.timeframe,
                ema_state.short_period,
                ema_state.short_ema
            )
        
        if ema_state.long_ema is not None:
            await self.db.upsert_ema_state(
                ema_state.symbol,
                ema_state.timeframe,
                ema_state.long_period,
                ema_state.long_ema
            )
    
    async def load_ema_state(
        self, 
        symbol: str, 
        timeframe: str, 
        short_period: int, 
        long_period: int
    ) -> Optional[EMAState]:
        """Load EMA state from database."""
        try:
            # This would need a proper query method in the Database class
            # For now, return None and let the system reinitialize
            return None
        except Exception:
            return None
    
    async def save_all_states(self, states: Dict[str, EMAState]) -> None:
        """Save all EMA states in bulk."""
        for symbol, state in states.items():
            await self.save_ema_state(state)