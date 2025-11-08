import logging
from typing import Any, Dict, List

from src.config import settings
from src.engine.base_strategy import BaseStrategy
from src.engine.price_action import (
    analyze_candle,
    is_bullish_engulf,
    is_bearish_engulf,
    is_hammer,
    is_shooting_star,
    is_three_green_candles,
    is_three_red_candles,
)
from src.engine.rsi import compute_rsi_series
from src.engine.cpr import compute_cpr

logger = logging.getLogger("opening_range_strategy")


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """Opening Range Breakout strategy (options only).

    Collects first N minutes (configured) to form opening range on the primary timeframe (default 5m).
    After range completion, watches for breakout above high or below low. Confirms with:
      - CPR (previous day) if required
      - Price action pattern on breakout bar if required
      - RSI slope (optional)
      - Option chain OI change (calls vs puts) relative to baseline snapshot

    Emits ONLY option signals (no underlying execution) via the shared OptionsManager.
    Limits to max signals per day (default 1).
    """

    def __init__(
        self,
        service,
        primary_tf: str,
    ):
        super().__init__(service)
        self.primary_tf = primary_tf
        self.range_minutes = settings.OPENING_RANGE_RANGE_MINUTES
        self.require_cpr = settings.OPENING_RANGE_REQUIRE_CPR
        self.require_pa = settings.OPENING_RANGE_REQUIRE_PRICE_ACTION
        self.require_rsi = settings.OPENING_RANGE_REQUIRE_RSI_SLOPE
        self.min_oi_change_pct = settings.OPENING_RANGE_MIN_OI_CHANGE_PCT
        self.debounce_sec = settings.OPENING_RANGE_DEBOUNCE_SEC
        self.max_signals = settings.OPENING_RANGE_MAX_SIGNALS_PER_DAY

        # per-symbol state
        self.state: Dict[str, Dict[str, Any]] = {}

    # ------------- Helpers -------------
    def _get_symbol_state(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self.state:
            self.state[symbol] = {
                'bars': [],
                'range_high': None,
                'range_low': None,
                'range_complete': False,
                'signals_emitted': 0,
                'baseline_call_oi': None,
                'baseline_put_oi': None,
                'last_detection_ts': None,
            }
        return self.state[symbol]

    def _within_opening_window(self, bar_ts) -> bool:
        try:
            import pandas as pd
            ts = pd.Timestamp(bar_ts)
            # Opening window ends at 09:30 (15m from 09:15) local IST assumption
            return ts.hour == 9 and ts.minute < 30
        except Exception:
            return False

    def _after_cutoff(self, bar_ts) -> bool:
        cutoff = settings.OPENING_RANGE_LAST_TRADE_TIME  # 'HH:MM'
        try:
            import pandas as pd
            ts = pd.Timestamp(bar_ts)
            hh, mm = cutoff.split(':')
            cutoff_ts = ts.replace(hour=int(hh), minute=int(mm))
            return ts >= cutoff_ts
        except Exception:
            return True  # fail safe: treat as after cutoff

    def _aggregate_baseline_oi(self, chain: List[Any], spot: float) -> Dict[str, float]:
        """Aggregate OI near ATM (choose strikes closest to spot) supporting either dicts or OptionContract objects.

        Accepts a heterogeneous list because tests feed simple dict objects while the live provider
        returns `OptionContract` instances. We normalise field access via a small helper so that both
        representations work without additional conversions.
        """
        if not chain or spot is None:
            return {'call': 0.0, 'put': 0.0}

        def _val(obj, field, default=None):
            if isinstance(obj, dict):
                return obj.get(field, default)
            return getattr(obj, field, default)

        try:
            atm_contract = min(chain, key=lambda c: abs((_val(c, 'strike', 0) or 0) - spot))
            atm_strike = _val(atm_contract, 'strike', spot) or spot
        except Exception:
            atm_strike = spot

        window = [atm_strike - 1, atm_strike, atm_strike + 1]
        call_oi = 0.0
        put_oi = 0.0
        for c in chain:
            k = (_val(c, 'kind', '') or '').upper()
            strike = _val(c, 'strike')
            if strike not in window:
                continue
            oi_val = float(_val(c, 'oi', 0) or 0)
            if k in ('CALL', 'CE'):
                call_oi += oi_val
            elif k in ('PUT', 'PE'):
                put_oi += oi_val
        return {'call': call_oi, 'put': put_oi}

    def _oi_change_pct(self, baseline: float, current: float) -> float:
        if baseline is None or baseline <= 0:
            return 0.0
        return ((current - baseline) / baseline) * 100.0

    def _price_action_ok(self, side: str, recent_bars: List[Dict]) -> bool:
        if len(recent_bars) < 2:
            return False
        prev_bar = recent_bars[-2]
        cur_bar = recent_bars[-1]
        pa = analyze_candle(cur_bar)
        if side == 'BUY':
            return (
                is_bullish_engulf(prev_bar, cur_bar) or
                is_hammer(cur_bar) or
                is_three_green_candles(recent_bars)
            )
        else:
            return (
                is_bearish_engulf(prev_bar, cur_bar) or
                is_shooting_star(cur_bar) or
                is_three_red_candles(recent_bars)
            )

    def _rsi_slope_ok(self, closes: List[float], side: str) -> bool:
        if not self.require_rsi:
            return True
        series = compute_rsi_series(closes, period=7)
        if not series or len(series) < 2:
            return False
        slope = series[-1] - series[-2]
        if side == 'BUY':
            return slope > 0
        else:
            return slope < 0

    def _compute_cpr_prev_day(self, symbol: str) -> Dict[str, float]:
        # day_candles stored in service.day_candles[symbol] or similar; use last entry
        day_candles = self.service.day_candles.get(symbol, []) if hasattr(self.service, 'day_candles') else []
        if not day_candles:
            return {}
        prev = day_candles[-1]
        try:
            return compute_cpr(prev['high'], prev['low'], prev['close'])
        except Exception:
            return {}

    async def on_bar_close(self, symbol: str, instrument_key: str, timeframe: str, bar: Any, ema_state=None, ema_confirm=None):
        if timeframe != self.primary_tf:
            return
        st = self._get_symbol_state(symbol)
        # enforce max signals per day
        if st['signals_emitted'] >= self.max_signals:
            return
        # Late start reconstruction: if service began after opening window and no bars collected yet
        if not st['range_complete'] and not st['bars'] and not self._within_opening_window(getattr(bar, 'ts', '')):
            try:
                import pandas as pd
                needed_minutes = self.range_minutes
                per_bar = self._minutes_for_tf(self.primary_tf)
                bars_needed = max(int(needed_minutes / per_bar), 1)
                candles = await self.service.rest.fetch_intraday(instrument_key, self.primary_tf)
                if candles:
                    tmp = []
                    for c in candles:
                        ts_val = c.get('ts') or c.get('timestamp') or c.get('time')
                        try:
                            ts_parsed = pd.Timestamp(ts_val)
                        except Exception:
                            continue
                        # Opening window start 09:15 inclusive, end 09:15+range_minutes (typically 09:30) exclusive
                        if ts_parsed.hour == 9 and 15 <= ts_parsed.minute < 15 + self.range_minutes:
                            tmp.append({
                                'open': c.get('open'),
                                'high': c.get('high'),
                                'low': c.get('low'),
                                'close': c.get('close'),
                                'volume': c.get('volume', 0),
                                'ts': ts_val
                            })
                    tmp = sorted(tmp, key=lambda x: x['ts'])
                    if len(tmp) >= bars_needed:
                        st['bars'] = tmp[:bars_needed]
                        st['range_high'] = max(b['high'] for b in st['bars'])
                        st['range_low'] = min(b['low'] for b in st['bars'])
                        st['range_complete'] = True
                        logger.info(f"(Late start) Reconstructed opening range for {symbol}: high={st['range_high']} low={st['range_low']}")
                        if self.service.options_manager:
                            chain = self.service.options_manager.provider.fetch_option_chain()
                            baseline = self._aggregate_baseline_oi(chain, getattr(bar, 'close', None))
                            st['baseline_call_oi'] = baseline['call']
                            st['baseline_put_oi'] = baseline['put']
                    else:
                        logger.warning(f"(Late start) Insufficient candles to reconstruct opening range for {symbol} ({len(tmp)}/{bars_needed})")
            except Exception:
                logger.exception(f"(Late start) Failed reconstructing opening range for {symbol}")
        # collect bars for opening range
        if not st['range_complete'] and self._within_opening_window(getattr(bar, 'ts', '')):
            st['bars'].append({
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': getattr(bar, 'volume', 0),
                'ts': getattr(bar, 'ts', '')
            })
            collected_minutes = len(st['bars']) * self._minutes_for_tf(self.primary_tf)
            if collected_minutes >= self.range_minutes:
                st['range_high'] = max(b['high'] for b in st['bars'])
                st['range_low'] = min(b['low'] for b in st['bars'])
                st['range_complete'] = True
                logger.info(f"Opening range complete for {symbol}: high={st['range_high']} low={st['range_low']}")
                # baseline OI snapshot
                if self.service.options_manager:
                    chain = self.service.options_manager.provider.fetch_option_chain()
                    spot = bar.close
                    baseline = self._aggregate_baseline_oi(chain, spot)
                    st['baseline_call_oi'] = baseline['call']
                    st['baseline_put_oi'] = baseline['put']
                return  # wait for next bar for potential breakout
            return

        # after range formed: watch for breakout until cutoff time
        if not st['range_complete'] or self._after_cutoff(getattr(bar, 'ts', '')):
            return

        # debounce same timestamp
        ts = getattr(bar, 'ts', None)
        if st['last_detection_ts'] == ts:
            return

        side = None
        if bar.close > st['range_high']:
            side = 'BUY'
        elif bar.close < st['range_low']:
            side = 'SELL'
        if not side:
            return

        # # confirmations
        # # CPR
        # if self.require_cpr:
        #     cpr = self._compute_cpr_prev_day(symbol)
        #     if not cpr:
        #         logger.debug(f"{symbol} breakout rejected: missing CPR")
        #         return
        #     if side == 'BUY' and bar.close < cpr.get('TC', float('inf')):
        #         logger.debug(f"{symbol} BUY breakout rejected: close < TC")
        #         return
        #     if side == 'SELL' and bar.close > cpr.get('BC', -float('inf')):
        #         logger.debug(f"{symbol} SELL breakout rejected: close > BC")
        #         return

        # Price Action
        if self.require_pa and not self._price_action_ok(side, st['bars'] + [{
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': getattr(bar, 'volume', 0),
        }]):
            logger.debug(f"{symbol} breakout rejected: PA not confirmed")
            return

        # # RSI slope
        # closes = [b['close'] for b in st['bars']] + [bar.close]
        # if not self._rsi_slope_ok(closes, side):
        #     logger.debug(f"{symbol} breakout rejected: RSI slope not aligned")
        #     return

        # OI Change
        if self.service.options_manager:
            chain = self.service.options_manager.provider.fetch_option_chain()
            spot = bar.close
            curr = self._aggregate_baseline_oi(chain, spot)
            if side == 'BUY':
                pct = self._oi_change_pct(st['baseline_call_oi'], curr['call'])
            else:
                pct = self._oi_change_pct(st['baseline_put_oi'], curr['put'])
            if pct < self.min_oi_change_pct:
                logger.debug(f"{symbol} breakout rejected: OI change {pct:.2f}% < {self.min_oi_change_pct}%")
                return
        else:
            logger.debug(f"{symbol} breakout rejected: options manager not available")
            return

        # Publish option signal only
        logger.info(f"Opening Range Breakout CONFIRMED for {symbol} side={side} price={bar.close:.2f}")
        st['signals_emitted'] += 1
        st['last_detection_ts'] = ts
        await self.service.options_manager.publish_underlying_signal(symbol, side, bar.close, self.primary_tf, origin='opening_range')

    @staticmethod
    def _minutes_for_tf(tf: str) -> int:
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
