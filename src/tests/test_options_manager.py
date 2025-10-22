import asyncio
from datetime import datetime
from src.options.options_manager import OptionsManager
from src.providers.options_chain_provider import OptionsChainProvider
from src.models.option_models import OptionContract
from src.utils.time_utils import now_ist

class DummyRest:
    def __init__(self):
        self._calls = 0
    def get_option_chain(self, instrument_symbol):
        self._calls += 1
        ts = now_ist()
        return [
            {"symbol":"NIFTY_C_24000","strike":24000,"type":"CALL","expiry":ts.isoformat(),"oi":120000,"iv":12.5,"ltp":120.0,"bid":119.5,"ask":120.5},
            {"symbol":"NIFTY_P_24000","strike":24000,"type":"PUT","expiry":ts.isoformat(),"oi":110000,"iv":13.0,"ltp":130.0,"bid":129.0,"ask":131.0}
        ]
    def get_underlying_price(self, instrument_symbol):
        return {"last_price":24005}

async def _collector(signal_list, sig):
    signal_list.append(sig)

async def test_manager_basic():
    rest = DummyRest()
    provider = OptionsChainProvider(rest)
    collected = []
    cfg = {"OPTION_ENABLE": True, "OPTION_RISK_CAP_PER_TRADE": 10000}
    mgr = OptionsManager(provider, cfg, lambda s: _collector(collected, s))
    await mgr.publish_underlying_signal(symbol="Nifty 50", side="BUY", price=24005, timeframe="1m", origin="scalper")
    assert collected, "No option signal emitted"
    assert collected[0].contract_symbol.startswith("NIFTY_C_"), "Expected call option for BUY side"

# Additional tests for cooldown/debounce could be added.
