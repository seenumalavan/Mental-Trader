import asyncio
import logging
from typing import Dict, List

from src.utils.instruments import resolve_instruments
from src.config import settings, watchlist_symbols
from src.persistence.db import Database
from src.providers.broker_ws import BrokerWS
from src.providers.broker_rest import BrokerRest
from src.engine.bar_builder import BarBuilder
from src.engine.ema import EMAState
from src.engine.strategy import ScalpStrategy, ScalpStrategyAdapter, ConfirmedScalpStrategy
from src.execution.execution import Executor
from src.services.notifier import Notifier
from src.auth.token_store import get_token

logger = logging.getLogger("service")

class ScalperService:
    def __init__(self):
        self.db = Database(settings.DATABASE_URL)

        # Use Upstox credentials
        access_token = get_token()
        api_key = settings.UPSTOX_API_KEY
        api_secret = settings.UPSTOX_API_SECRET
        self.rest = BrokerRest(api_key, api_secret, access_token=access_token)
        # Use Upstox SDK streamer
        self.ws = BrokerWS(access_token)
        self.bar_builder = BarBuilder()
        self.ema_states: Dict[str, EMAState] = {}            # 1m (primary) EMA states
        self.ema_states_5m: Dict[str, EMAState] = {}         # 5m EMA states for confirmation
        self.symbol_to_key: Dict[str, str] = {}  # Store symbol to instrument_key mapping
        # Strategy wrapper will be constructed after warmup in start()
        self.strategy = None
        self.executor = Executor(self.rest, self.db)
        self.notifier = Notifier(settings.NOTIFIER_WEBHOOK)
        self._running = False
        self._task = None

    async def start(self, instrument_input=None):
        """
        Start the scalping service.
        
        Args:
            instrument_input: Can be:
                - String: "nifty", "indices", "RELIANCE", or "RELIANCE,TCS"
                - List: ["nifty", "indices"] or ["RELIANCE", "TCS"]
                - None: Defaults to "nifty"
        """
        if self._running:
            logger.info("Service already running")
            return
        logger.info("Starting ScalperService")
        await self.db.connect()
        #await self.rest.ping()  # optional check
        await self.ws.connect()
        
        # Use default "nifty" if no input provided
        if instrument_input is None:
            instrument_input = "nifty"
        
        instruments = resolve_instruments(instrument_input)
        logger.info(f"Resolved {len(instruments)} instruments for trading: {[i['symbol'] for i in instruments]}")

        # Warm-up per symbol: load candles from DB or broker REST
        for instrument_data in instruments:
            symbol = instrument_data['symbol']
            instrument_key = instrument_data['instrument_key']
            
            # Store the mapping for later use
            self.symbol_to_key[symbol] = instrument_key
            
            candles = await self.db.load_candles(symbol, instrument_key, settings.SCALP_PRIMARY_TIMEFRAME, limit=settings.WARMUP_BARS)
            if not candles:
                logger.info("DB warmup missing, fetching historical for %s (key: %s)", symbol, instrument_key)
                candles = await self.rest.fetch_historical(instrument_key, settings.SCALP_PRIMARY_TIMEFRAME, limit=settings.WARMUP_BARS)
                await self.db.persist_candles_bulk(symbol, instrument_key, settings.SCALP_PRIMARY_TIMEFRAME, candles)
            # Fetch intraday (today) partial candles and merge/upsert to cover current session
            intraday = await self.rest.fetch_intraday(instrument_key, settings.SCALP_PRIMARY_TIMEFRAME)
            if intraday:
                await self.db.persist_candles_bulk(symbol, instrument_key, settings.SCALP_PRIMARY_TIMEFRAME, intraday)
                # Extend warmup seed with today candles if not already present
                seen = {c["ts"] if isinstance(c, dict) else c.ts for c in candles}
                for ic in intraday:
                    if ic["ts"] not in seen:
                        candles.append(ic)

            ema_1m = EMAState(symbol, settings.SCALP_PRIMARY_TIMEFRAME, settings.EMA_SHORT, settings.EMA_LONG)
            ema_1m.initialize_from_candles(candles)
            self.ema_states[symbol] = ema_1m
            # Initialize 5m EMA state (lightweight). Only one period (50) used for trend filter; reuse class with same short/long.
            ema_5m = EMAState(symbol, "5m", 50, 50)
            # Attempt to seed with any available 5m historical candles (optional minimal fetch)
            try:
                candles_5m = await self.rest.fetch_historical(instrument_key, "5m", limit=60)
                if candles_5m:
                    ema_5m.initialize_from_candles(candles_5m)
            except Exception:
                pass
            self.ema_states_5m[symbol] = ema_5m

        # Subscribe to WebSocket using instrument keys
        instrument_keys = [item['instrument_key'] for item in instruments]
        await self.ws.subscribe(instrument_keys)
        self.ws.on_tick = self._on_tick  # set callback
        # Build strategy wrapper now that symbols loaded
        #base = ScalpStrategyAdapter(self)
        #self.strategy = ConfirmedScalpStrategy(base, self._confirmation_ctx)
        self.strategy = ScalpStrategy(self)
        self._running = True
        logger.info("ScalperService started")

    async def stop(self):
        if not self._running:
            return
        logger.info("Stopping ScalperService")
        await self.ws.disconnect()
        # persist EMA states
        for symbol, state in self.ema_states.items():
            instrument_key = self.symbol_to_key.get(symbol, symbol)
            await self.db.upsert_ema_state(symbol, instrument_key, settings.SCALP_PRIMARY_TIMEFRAME, state.short_period, state.short_ema)
            await self.db.upsert_ema_state(symbol, instrument_key, settings.SCALP_PRIMARY_TIMEFRAME, state.long_period, state.long_ema)
        await self.db.disconnect()
        self._running = False
        logger.info("Stopped")

    async def _on_tick(self, tick):
        # tick: dict {symbol, price, volume, ts}
        closed = self.bar_builder.push_tick(tick)
        for symbol, tf, bar in closed:
            instrument_key = self.symbol_to_key.get(symbol, symbol)
            if tf == "5m":
                ema5 = self.ema_states_5m.get(symbol)
                if ema5 is None:
                    ema5 = EMAState(symbol, "5m", 50, 50)
                    ema5.initialize_from_candles([])
                    self.ema_states_5m[symbol] = ema5
                ema5.update_with_close(bar.close)
                # Persist 5m bar
                await self.db.persist_candle(symbol, instrument_key, tf, bar)
                continue

            # 1m path (primary)
            ema1 = self.ema_states.get(symbol)
            if ema1 is None:
                candles = await self.db.load_candles(symbol, instrument_key, tf, limit=settings.WARMUP_BARS)
                ema1 = EMAState(symbol, tf, settings.EMA_SHORT, settings.EMA_LONG)
                ema1.initialize_from_candles(candles)
                self.ema_states[symbol] = ema1
            ema1.update_with_close(bar.close)
            ema5 = self.ema_states_5m.get(symbol)  # may be None or not ready
            await self.strategy.on_bar_close(symbol, tf, bar, ema1, ema5)
            await self.db.persist_candle(symbol, instrument_key, tf, bar)

    def _confirmation_ctx(self, symbol: str, timeframe: str):
        """Return (recent_bars, daily_ref) for confirmation.

        recent_bars: last N 1m bars as list of dicts with open/high/low/close/volume.
        daily_ref: previous day OHLC for CPR.
        Simplified implementation reading from DB; optimize/correct as needed.
        """
        N = 30
        # Load recent candles (most recent first assumed from DB, reverse to chronological if needed)
        # Assuming db.load_candles returns list of candle objects with attributes.
        instrument_key = self.symbol_to_key.get(symbol, symbol)
        # NOTE: Avoid calling async DB from sync context; rely on cached bars.
        candles = []  # Placeholder if you later adapt to include DB snapshot.
        # Build recent bars from bar_builder cache if available.
        recent_bars: List[Dict] = []
        if hasattr(self.bar_builder, 'recent_bars'):
            recent_objs = [b for b in self.bar_builder.recent_bars.get(symbol, []) if getattr(b, 'timeframe', timeframe) == timeframe][-N:]
            recent_bars = [
                {"open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": getattr(b, 'volume', 0)}
                for b in recent_objs
            ]
        # Previous day OHLC placeholder: could query historical API once per morning and cache.
        daily_ref = {"prev_high": None, "prev_low": None, "prev_close": None}
        return recent_bars, daily_ref

    def status(self):
        return {"running": self._running, "symbols": list(self.ema_states.keys())}
