import logging
import time
from typing import Dict, List

import pandas as pd

from src.models.option_models import OptionContract
from src.utils.time_utils import now_ist

logger = logging.getLogger("options_provider")

class OptionsChainProvider:
    """Fetch futures price and option chain; keeps last snapshot for OI change and debounce."""
    def __init__(self, rest_client, instrument_symbol: str = None):
        self.rest = rest_client
        # Delay binding until first tick if not provided
        self.instrument_symbol = instrument_symbol
        self._last_chain: Dict[str, OptionContract] = {}
        self._last_fetch_ts: float = 0.0

    def set_instrument(self, instrument_symbol: str):
        """Update instrument symbol (e.g., from WebSocket tick instrument_key mapping)."""
        if instrument_symbol and instrument_symbol != self.instrument_symbol:
            logger.info("OptionsChainProvider instrument updated %s -> %s", self.instrument_symbol, instrument_symbol)
            self.instrument_symbol = instrument_symbol

    def fetch_futures_price(self) -> float:
        if not self.instrument_symbol:
            return 0.0
        try:
            data = self.rest.get_underlying_price(self.instrument_symbol)
            return float(data.get("last_price", 0.0))
        except Exception as e:
            logger.warning("Futures price fetch failed: %s", e)
            return 0.0

    def fetch_option_chain(self) -> List[OptionContract]:
        ts_now = now_ist()
        if not self.instrument_symbol:
            return list(self._last_chain.values())
        try:
            raw_chain = self.rest.get_option_chain(self.instrument_symbol)
        except Exception as e:
            logger.warning("Option chain fetch failed: %s", e)
            return list(self._last_chain.values())
        new_contracts: List[OptionContract] = []
        for item in raw_chain:
            try:
                symbol = item["symbol"]
                strike = int(item["strike"])
                kind = item["type"].upper()  # CALL/PUT
                expiry_val = item.get("expiry")
                expiry = pd.to_datetime(expiry_val) if isinstance(expiry_val, str) else ts_now
                oi = int(item.get("oi", 0))
                iv = float(item.get("iv", 0.0))
                ltp = float(item.get("ltp", 0.0))
                bid = float(item.get("bid", ltp))
                ask = float(item.get("ask", ltp))
                prev = self._last_chain.get(symbol)
                oc = OptionContract(
                    symbol=symbol,
                    strike=strike,
                    kind=kind,
                    expiry=expiry,
                    oi=oi,
                    oi_prev=prev.oi if prev else None,
                    iv=iv,
                    ltp=ltp,
                    bid=bid,
                    ask=ask,
                    timestamp=ts_now,
                    delta=item.get('delta'),
                    gamma=item.get('gamma'),
                    theta=item.get('theta'),
                    vega=item.get('vega'),
                    rho=item.get('rho')
                )
                new_contracts.append(oc)
            except Exception as e:
                logger.debug("Chain item parse failed: %s item=%s", e, item)
        self._last_chain = {c.symbol: c for c in new_contracts}
        self._last_fetch_ts = time.time()
        return new_contracts

    def last_snapshot_age(self) -> float:
        return time.time() - self._last_fetch_ts if self._last_fetch_ts else 1e9
