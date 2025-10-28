
import pytest

from src.services.options.options_manager import OptionsManager
from src.providers.options_chain_provider import OptionsChainProvider
from src.utils.time_utils import now_ist


class DummyRest:
    def __init__(self):
        self._calls = 0
        self.ts = now_ist().replace(hour=10, minute=0, second=0, microsecond=0)  # Fixed ts for test
    def get_option_chain(self, instrument_symbol):
        self._calls += 1
        return [
            {"symbol":"NIFTY","strike":24000,"type":"CE","expiry":self.ts.isoformat(),"oi":120000,"iv":15.0,"ltp":120.0,"bid":119.5,"ask":120.5},
            {"symbol":"NIFTY","strike":24000,"type":"PE","expiry":self.ts.isoformat(),"oi":110000,"iv":13.0,"ltp":130.0,"bid":129.0,"ask":131.0}
        ]
    def get_option_contracts(self, instrument_symbol):
        return [
            {"strike":24000,"kind":"CALL","expiry":self.ts.isoformat(),"trading_symbol":"NIFTY25OCT24000CE"},
            {"strike":24000,"kind":"PUT","expiry":self.ts.isoformat(),"trading_symbol":"NIFTY25OCT24000PE"}
        ]
    def get_underlying_price(self, instrument_symbol):
        return {"last_price":23995}

async def _collector(signal_list, sig):
    signal_list.append(sig)

@pytest.mark.asyncio
async def test_manager_basic():
    rest = DummyRest()
    provider = OptionsChainProvider(rest)
    provider.set_instrument("NIFTY")  # Set the instrument symbol
    collected = []
    cfg = {"OPTION_ENABLE": True, "OPTION_RISK_CAP_PER_TRADE": 100000, "OPTION_LOT_SIZE": 1}
    async def callback(sig):
        await _collector(collected, sig)
    mgr = OptionsManager(provider, cfg, callback)
    await mgr.publish_underlying_signal(symbol="Nifty 50", side="BUY", price=23995, timeframe="1m", origin="scalper")
    assert collected, "No option signal emitted"
    assert collected[0].trading_symbol == "NIFTY25OCT24000CE", "Expected mapped trading symbol for call option"
    assert collected[0].contract_symbol == "NIFTY", "Contract symbol should be underlying"

# Additional tests for cooldown/debounce could be added.
