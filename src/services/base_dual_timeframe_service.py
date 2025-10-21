import logging
from typing import Dict, List, Any
from datetime import datetime, timezone
import pandas as pd

from src.config import settings
from src.utils.instruments import resolve_instruments
from src.persistence.db import Database
from src.providers.broker_rest import BrokerRest
from src.providers.broker_ws import BrokerWS
from src.engine.bar_builder import BarBuilder
from src.engine.ema import EMAState
from src.execution.execution import Executor
from src.services.notifier import Notifier
from src.auth.token_store import get_token
from src.options.options_manager import OptionsManager
from src.providers.options_chain_provider import OptionsChainProvider

logger = logging.getLogger("dual_service")

def _minutes(tf: str) -> int:
    if tf.endswith('m'):
        try:
            return int(tf[:-1])
        except ValueError:
            return 1
    if tf.endswith('h'):
        try:
            return int(tf[:-1]) * 60
        except ValueError:
            return 60
    return 1

class DualTimeframeServiceBase:
    """Generic service base for primary + confirm timeframe operations.

    Handles warmup, in-memory aggregation for confirm timeframe, EMA state management,
    websocket subscription and tick -> bar handling, and conditional candle persistence.
    Subclasses implement build_strategy() to supply strategy instance.
    """
    def __init__(self, primary_tf: str, confirm_tf: str, short_period: int, long_period: int, warmup_bars: int, persist_confirm_candles: bool = False):
        self.primary_tf = primary_tf
        self.confirm_tf = confirm_tf
        self.short_period = short_period
        self.long_period = long_period
        self.warmup_bars = warmup_bars
        self.persist_confirm_candles = persist_confirm_candles

        self.db = Database(settings.DATABASE_URL)
        access_token = get_token()
        api_key = settings.UPSTOX_API_KEY
        api_secret = settings.UPSTOX_API_SECRET
        self.rest = BrokerRest(api_key, api_secret, access_token=access_token)
        self.ws = BrokerWS(access_token)
        self.bar_builder = BarBuilder()
        self.ema_primary: Dict[str, EMAState] = {}
        self.ema_confirm: Dict[str, EMAState] = {}
        self.symbol_to_key: Dict[str, str] = {}
        self.executor = Executor(self.rest, self.db)
        self.notifier = Notifier(settings.NOTIFIER_WEBHOOK)
        self.strategy = None
        self._running = False
        self.options_manager = None  # Will hold OptionsManager if enabled

    async def start(self, instrument_input=None):
        if self._running:
            logger.info("Service already running")
            return
        await self.db.connect()
        await self.ws.connect()
        if instrument_input is None:
            instrument_input = "nifty"
        instruments = resolve_instruments(instrument_input)
        logger.info("Resolved instruments: %s", [i['symbol'] for i in instruments])
        for inst in instruments:
            symbol = inst['symbol']
            key = inst['instrument_key']
            self.symbol_to_key[symbol] = key
            candles_primary = await self.db.load_candles(symbol, key, self.primary_tf, limit=self.warmup_bars)
            if not candles_primary:
                candles_primary = await self.rest.fetch_historical(key, self.primary_tf, limit=self.warmup_bars)
                if candles_primary:
                    await self.db.persist_candles_bulk(symbol, key, self.primary_tf, candles_primary)
            intraday = await self.rest.fetch_intraday(key, self.primary_tf)
            if intraday:
                await self.db.persist_candles_bulk(symbol, key, self.primary_tf, intraday)
                seen = {c['ts'] if isinstance(c, dict) else c.ts for c in candles_primary}
                for ic in intraday:
                    if ic['ts'] not in seen:
                        candles_primary.append(ic)
            candles_confirm: List[dict] = []
            if self.confirm_tf != self.primary_tf:
                m_p = _minutes(self.primary_tf)
                m_c = _minutes(self.confirm_tf)
                if m_c % m_p == 0 and candles_primary:
                    try:
                        df = pd.DataFrame(candles_primary)
                        # Parse timestamps as naive local time (data already stored in local timezone).
                        df['ts'] = pd.to_datetime(df['ts'], errors='coerce')
                        df = df.dropna(subset=['ts'])  # drop unparsable rows
                        df = df.set_index('ts').sort_index()
                        rule = f'{m_c}T'
                        agg = df.resample(rule).agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna(subset=['open','close'])
                        # Use naive current local time for completeness check
                        # Use pandas Timestamps uniformly for comparison to avoid type mismatch
                        now_ts = pd.Timestamp.now()  # naive local timestamp as pandas Timestamp
                        interval = pd.Timedelta(minutes=m_c)
                        valid = []
                        for ts_idx, row in agg.iterrows():
                            # ts_idx is a pandas Timestamp (index). Ensure bar fully elapsed before accepting.
                            if (ts_idx + interval) <= now_ts:
                                valid.append({
                                    'ts': ts_idx.isoformat(),
                                    'open': float(row.open),
                                    'high': float(row.high),
                                    'low': float(row.low),
                                    'close': float(row.close),
                                    'volume': int(row.volume)
                                })
                        candles_confirm = valid[-self.warmup_bars:]
                    except Exception as e:
                        logger.warning("Confirm aggregation failed for %s: %s", symbol, e)
            ema_p = EMAState(symbol, self.primary_tf, self.short_period, self.long_period)
            ema_p.initialize_from_candles(candles_primary)
            self.ema_primary[symbol] = ema_p
            if self.confirm_tf != self.primary_tf:
                ema_c = EMAState(symbol, self.confirm_tf, self.short_period, self.long_period)
                ema_c.initialize_from_candles(candles_confirm)
                self.ema_confirm[symbol] = ema_c
        keys = [i['instrument_key'] for i in instruments]
        await self.ws.subscribe(keys)
        self.ws.on_tick = self._on_tick
        self.strategy = self.build_strategy()
        # Initialize shared OptionsManager if enabled
        if settings.OPTION_ENABLE:
            chain_provider = OptionsChainProvider(self.rest, instrument_symbol="Nifty 50")
            async def emit_option(opt_signal):
                # For now just log and notify; executor for options not yet implemented
                logger.info("OptionSignal emitted %s %s lots=%s", opt_signal.contract_symbol, opt_signal.underlying_side, opt_signal.suggested_size_lots)
                await self.notifier.notify_signal(opt_signal)
            self.options_manager = OptionsManager(chain_provider, config={
                'OPTION_ENABLE': settings.OPTION_ENABLE,
                'OPTION_LOT_SIZE': settings.OPTION_LOT_SIZE,
                'OPTION_RISK_CAP_PER_TRADE': settings.OPTION_RISK_CAP_PER_TRADE,
                'OPTION_OI_MIN_PERCENTILE': settings.OPTION_OI_MIN_PERCENTILE,
                'OPTION_SPREAD_MAX_PCT_SCALPER': settings.OPTION_SPREAD_MAX_PCT_SCALPER,
                'OPTION_SPREAD_MAX_PCT_INTRADAY': settings.OPTION_SPREAD_MAX_PCT_INTRADAY,
                'OPTION_DEBOUNCE_SEC': settings.OPTION_DEBOUNCE_SEC,
                'OPTION_DEBOUNCE_INTRADAY_SEC': settings.OPTION_DEBOUNCE_INTRADAY_SEC,
                'OPTION_COOLDOWN_SEC': settings.OPTION_COOLDOWN_SEC,
            }, emit_callback=emit_option)
        self._running = True
        logger.info("Service started primary=%s confirm=%s", self.primary_tf, self.confirm_tf)

    async def stop(self):
        if not self._running:
            return
        await self.ws.disconnect()
        for symbol, state in self.ema_primary.items():
            key = self.symbol_to_key.get(symbol, symbol)
            await self.db.upsert_ema_state(symbol, key, self.primary_tf, state.short_period, state.short_ema)
            await self.db.upsert_ema_state(symbol, key, self.primary_tf, state.long_period, state.long_ema)
        if self.confirm_tf != self.primary_tf:
            for symbol, state in self.ema_confirm.items():
                key = self.symbol_to_key.get(symbol, symbol)
                await self.db.upsert_ema_state(symbol, key, self.confirm_tf, state.short_period, state.short_ema)
                await self.db.upsert_ema_state(symbol, key, self.confirm_tf, state.long_period, state.long_ema)
        await self.db.disconnect()
        self._running = False
        logger.info("Service stopped")

    async def _on_tick(self, tick: Dict[str, Any]):
        closed = self.bar_builder.push_tick(tick)
        for symbol, tf, bar in closed:
            key = self.symbol_to_key.get(symbol, symbol)
            if tf == self.primary_tf:
                ema_p = self.ema_primary.get(symbol)
                if ema_p is None:
                    ema_p = EMAState(symbol, self.primary_tf, self.short_period, self.long_period)
                    ema_p.initialize_from_candles([])
                    self.ema_primary[symbol] = ema_p
                ema_p.update_with_close(bar.close)
                ema_c = self.ema_confirm.get(symbol) if self.confirm_tf != self.primary_tf else None
                if self.strategy:
                    await self.strategy.on_bar_close(symbol, tf, bar, ema_p, ema_c)
                await self.db.persist_candle(symbol, key, tf, bar)
            elif tf == self.confirm_tf and self.confirm_tf != self.primary_tf:
                ema_c = self.ema_confirm.get(symbol)
                if ema_c is None:
                    ema_c = EMAState(symbol, self.confirm_tf, self.short_period, self.long_period)
                    ema_c.initialize_from_candles([])
                    self.ema_confirm[symbol] = ema_c
                ema_c.update_with_close(bar.close)
                if self.persist_confirm_candles:
                    await self.db.persist_candle(symbol, key, tf, bar)
                else:
                    continue

    def status(self) -> Dict[str, Any]:
        return {
            'running': self._running,
            'primary_tf': self.primary_tf,
            'confirm_tf': self.confirm_tf,
            'symbols_primary': list(self.ema_primary.keys()),
            'symbols_confirm': list(self.ema_confirm.keys())
        }

    def build_strategy(self):
        raise NotImplementedError
