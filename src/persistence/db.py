import logging
from datetime import datetime
from typing import List

# Simple SQLAlchemy-only approach
try:
    import sqlalchemy
    from sqlalchemy import (Column, DateTime, Float, Integer, MetaData, String,
                            Table, UniqueConstraint, create_engine, text)
    DATABASE_AVAILABLE = True
except ImportError:
    sqlalchemy = None
    DATABASE_AVAILABLE = False

logger = logging.getLogger("database")

if DATABASE_AVAILABLE:
    metadata = MetaData()

    # Store raw API timestamp (e.g. 2025-10-21T13:49:00+05:30) including offset without conversion.
    # Using String instead of DateTime so the original timezone info is preserved exactly as received.
    candles = Table(
        'candles', metadata,
        Column('symbol', String, primary_key=True),
        Column('instrument_key', String, primary_key=True),
        Column('timeframe', String, primary_key=True),
        Column('ts', DateTime(timezone=True), primary_key=True),  # raw ISO8601 with offset
        Column('open', Float),
        Column('high', Float),
        Column('low', Float),
        Column('close', Float),
        Column('volume', Integer),
        UniqueConstraint('instrument_key', 'ts', name='uq_candles_inst_ts')
    )

    ema_state = Table(
        'ema_state', metadata,
        Column('symbol', String, primary_key=True),
        Column('instrument_key', String, primary_key=True),
        Column('timeframe', String, primary_key=True),
        Column('period', Integer, primary_key=True),
        Column('ema_value', Float),
        Column('last_ts', DateTime)
    )

    trades = Table(
        'trades', metadata,
        Column('id', String, primary_key=True),
        Column('symbol', String),
        Column('timeframe', String),
        Column('side', String),
        Column('entry_price', Float),
        Column('size', Integer),
        Column('stop_loss', Float),
        Column('target', Float),
        Column('status', String),
        Column('created_at', DateTime, server_default=text('now()'))
    )

    option_trades = Table(
        'option_trades', metadata,
        Column('id', String, primary_key=True),
        Column('contract_symbol', String),
        Column('underlying_side', String),
        Column('strike', Integer),
        Column('kind', String),
        Column('premium_ltp', Float),
        Column('size_lots', Integer),
        Column('stop_loss_premium', Float),
        Column('target_premium', Float),
        Column('reasoning', String),
        Column('entry_order_id', String),
        Column('stop_order_id', String),
        Column('target_order_id', String),
        Column('status', String, default='OPEN'),
        Column('created_at', DateTime, server_default=text('now()'))
    )
else:
    metadata = None
    candles = None
    ema_state = None  
    trades = None
    option_trades = None

class Database:
    def __init__(self, url: str):
        self.url = url
        self.engine = None
        self._connected = False
        
        if not DATABASE_AVAILABLE:
            logger.warning("SQLAlchemy not installed. Running in memory-only mode.")
            return
        
        # Create simple engine
        try:
            self.engine = create_engine(url)
            if metadata:
                metadata.create_all(self.engine)
            logger.info("Database engine created successfully")
        except Exception as e:
            logger.warning(f"Database creation failed: {e}")
            self.engine = None

    async def connect(self):
        if not DATABASE_AVAILABLE or not self.engine:
            logger.warning("Database not available")
            return
            
        try:
            # Test connection
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            self._connected = True
            logger.info("Database connected successfully")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            self._connected = False

    async def disconnect(self):
        self._connected = False
        logger.info("Database disconnected")

    async def execute(self, query):
        """Execute a SQLAlchemy query and return the result."""
        if not self._connected or not self.engine:
            raise RuntimeError("Database not connected")
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query)
                conn.commit()  # Commit any changes
                return result
        except Exception as e:
            logger.error(f"Database query execution failed: {e}")
            raise

    async def load_candles(self, symbol, instrument_key, timeframe, limit=200):
        if not self._connected or not self.engine:
            return []
        
        try:
            query = candles.select().where(
                (candles.c.symbol == symbol) & 
                (candles.c.instrument_key == instrument_key) &
                (candles.c.timeframe == timeframe)
            ).order_by(candles.c.ts.desc()).limit(limit)
            
            with self.engine.connect() as conn:
                result = conn.execute(query)
                rows = result.fetchall()
            
            # Return in chronological order
            rows = list(reversed(rows))
            return [dict(r._mapping) for r in rows]
        except Exception as e:
            logger.error(f"Failed to load candles: {e}")
            return []

    async def persist_candle(self, symbol, instrument_key, timeframe, bar):
        if not self._connected or not self.engine:
            return
            
        try:
            with self.engine.connect() as conn:
                # Simple upsert: insert if not exists, update if exists
                from sqlalchemy import text
                
                upsert_sql = """
                    INSERT INTO candles (symbol, instrument_key, timeframe, ts, open, high, low, close, volume)
                    VALUES (:symbol, :instrument_key, :timeframe, :ts, :open, :high, :low, :close, :volume)
                    ON CONFLICT (instrument_key, ts) DO UPDATE SET
                        symbol = EXCLUDED.symbol,
                        timeframe = EXCLUDED.timeframe,
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """
                
                conn.execute(text(upsert_sql), {
                    'symbol': symbol,
                    'instrument_key': instrument_key,
                    'timeframe': timeframe,
                    'ts': bar.ts,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                })
                conn.commit()
        except Exception as e:
            logger.debug(f"Failed to persist candle: {e}")

    async def persist_candles_bulk(self, symbol, instrument_key, timeframe, bars):
        if not self._connected or not self.engine:
            return
            
        try:
            with self.engine.connect() as conn:
                from sqlalchemy import text
                
                upsert_sql = """
                    INSERT INTO candles (symbol, instrument_key, timeframe, ts, open, high, low, close, volume)
                    VALUES (:symbol, :instrument_key, :timeframe, :ts, :open, :high, :low, :close, :volume)
                    ON CONFLICT (instrument_key, ts) DO UPDATE SET
                        symbol = EXCLUDED.symbol,
                        timeframe = EXCLUDED.timeframe,
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """
                
                for b in bars:
                    ts_val = b.get('ts') if isinstance(b, dict) else b.ts
                    
                    conn.execute(text(upsert_sql), {
                        'symbol': symbol,
                        'instrument_key': instrument_key,
                        'timeframe': timeframe,
                        'ts': ts_val,
                        'open': b.get('open') if isinstance(b, dict) else b.open,
                        'high': b.get('high') if isinstance(b, dict) else b.high,
                        'low': b.get('low') if isinstance(b, dict) else b.low,
                        'close': b.get('close') if isinstance(b, dict) else b.close,
                        'volume': b.get('volume') if isinstance(b, dict) else b.volume
                    })
                conn.commit()
        except Exception as e:
            logger.debug(f"Failed to persist candles bulk: {e}")

    async def upsert_ema_state(self, symbol, instrument_key, timeframe, period, value):
        if not self._connected or not self.engine:
            return
            
        try:
            # Simple insert (replace if exists)
            query = ema_state.insert().values(
                symbol=symbol,
                instrument_key=instrument_key,
                timeframe=timeframe,
                period=period,
                ema_value=value,
                last_ts=datetime.now()  # Use local timestamp instead of UTC
            )
            
            with self.engine.connect() as conn:
                conn.execute(query)
                conn.commit()
        except Exception as e:
            logger.debug(f"Failed to upsert EMA state: {e}")

    async def insert_trade(self, signal, resp):
        if not self._connected or not self.engine:
            return
            
        try:
            order_id = resp.get("order_id") or resp.get("id") or str(datetime.utcnow().timestamp())
            query = trades.insert().values(
                id=order_id,
                symbol=signal.symbol,
                timeframe="1m",
                side=signal.side,
                entry_price=signal.price,
                size=signal.size,
                stop_loss=signal.stop_loss,
                target=signal.target,
                status="OPEN"
            )
            
            with self.engine.connect() as conn:
                conn.execute(query)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert trade: {e}")

    async def update_trade_status(self, trade_id: str, status: str):
        if not self._connected or not self.engine or trades is None:
            return
        try:
            with self.engine.connect() as conn:
                stmt = trades.update().where(trades.c.id == trade_id).values(status=status)
                conn.execute(stmt)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to update trade status: {e}")

    async def insert_option_trade(self, opt_signal):
        if not self._connected or not self.engine or option_trades is None:
            return
        try:
            import uuid
            trade_id = str(uuid.uuid4())
            reasoning_str = ";".join(opt_signal.reasoning) if getattr(opt_signal, 'reasoning', None) else ''
            entry_id = getattr(opt_signal, 'entry_order_id', None)
            stop_id = getattr(opt_signal, 'stop_order_id', None)
            target_id = getattr(opt_signal, 'target_order_id', None)
            status_val = getattr(opt_signal, 'status', 'OPEN')
            query = option_trades.insert().values(
                id=trade_id,
                contract_symbol=opt_signal.contract_symbol,
                underlying_side=opt_signal.underlying_side,
                strike=opt_signal.strike,
                kind=opt_signal.kind,
                premium_ltp=opt_signal.premium_ltp,
                size_lots=opt_signal.suggested_size_lots,
                stop_loss_premium=opt_signal.stop_loss_premium,
                target_premium=opt_signal.target_premium,
                reasoning=reasoning_str,
                entry_order_id=entry_id,
                stop_order_id=stop_id,
                target_order_id=target_id,
                status=status_val
            )
            with self.engine.connect() as conn:
                conn.execute(query)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert option trade: {e}")

    async def update_option_trade_status(self, contract_symbol: str, status: str):
        if not self._connected or not self.engine or option_trades is None:
            return
        try:
            with self.engine.connect() as conn:
                stmt = option_trades.update().where(option_trades.c.contract_symbol == contract_symbol).values(status=status)
                conn.execute(stmt)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to update option trade status: {e}")

    async def get_all_symbols(self) -> List[str]:
        """Get all symbols that have data in the database."""
        if not self._connected or not self.engine or candles is None:
            return []
        
        try:
            from sqlalchemy import select
            query = select(candles.c.symbol).distinct()
            result = await self.execute(query)
            rows = result.fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Failed to get symbols: {e}")
            return []
