import logging
from datetime import datetime
from typing import Any, Dict, Optional

from src.analytics.options_chain_analyzer import (compute_chain_metrics,
                                                  rank_strikes)
from src.models.option_models import OptionSignal
from src.providers.options_chain_provider import OptionsChainProvider
from src.risk.option_position_sizing import compute_option_position
from src.utils.time_utils import now_ist

logger = logging.getLogger("options_manager")

class OptionsManager:
    """Shared Options Manager that receives underlying signals from scalper and intraday services.

    Responsibilities:
    - Debounce option chain fetches.
    - Prevent duplicate option trades within cooldown window.
    - Select best strike using ranking.
    - Emit OptionSignal via callback.
    """

    def __init__(self,
                 chain_provider: OptionsChainProvider,
                 config: Dict[str, Any],
                 emit_callback):
        self.provider = chain_provider
        self.cfg = config
        self.emit_callback = emit_callback  # async function accepting OptionSignal
        self.last_trade_side: Optional[str] = None
        self.last_trade_ts: Optional[datetime] = None

    def _cooldown_active(self, side: str) -> bool:
        cooldown = int(self.cfg.get('OPTION_COOLDOWN_SEC', 300))
        if not self.last_trade_ts or not self.last_trade_side:
            return False
        if self.last_trade_side != side:
            return False
        delta = (now_ist() - self.last_trade_ts).total_seconds()
        return delta < cooldown

    async def publish_underlying_signal(self,
                                        symbol: str,
                                        side: str,
                                        price: float,
                                        timeframe: str,
                                        origin: str):
        if not self.cfg.get('OPTION_ENABLE', False):
            return
        if self._cooldown_active(side):
            logger.info("Options cooldown active for side=%s; skipping", side)
            return
        mode = 'scalper' if origin == 'scalper' else 'intraday'
        debounce = int(self.cfg.get('OPTION_DEBOUNCE_SEC', 30)) if mode == 'scalper' else int(self.cfg.get('OPTION_DEBOUNCE_INTRADAY_SEC', 60))
        # Always fetch fresh option chain upon underlying signal for immediate OI/IV data
        chain = self.provider.fetch_option_chain()
        metrics = compute_chain_metrics(chain)
        ranked = rank_strikes(
            chain=chain,
            side=side,
            spot_price=price,
            mode=mode,
            oi_min_percentile=int(self.cfg.get('OPTION_OI_MIN_PERCENTILE', 60)),
            iv_median=metrics.get('iv_median', 0.0),
            spread_max_pct_scalper=float(self.cfg.get('OPTION_SPREAD_MAX_PCT_SCALPER', 0.015)),
            spread_max_pct_intraday=float(self.cfg.get('OPTION_SPREAD_MAX_PCT_INTRADAY', 0.025))
        )
        if not ranked:
            logger.info("No ranked option strikes for side=%s origin=%s", side, origin)
            return
        top = ranked[0]
        pos = compute_option_position(
            top.contract,
            side,
            account_risk_cap=float(self.cfg.get('OPTION_RISK_CAP_PER_TRADE', 2500)),
            lot_size=int(self.cfg.get('OPTION_LOT_SIZE', 75)),
            mode=mode
        )
        if pos['lots'] <= 0:
            logger.info("Position sizing produced 0 lots; skipping option trade")
            return
        reasoning = [
            f"OI_rank={top.components.get('oi_rank'):.2f}",
            f"IV_quality={top.components.get('iv_quality'):.2f}",
            f"Spread_pct={top.effective_spread_pct:.4f}",
            f"Distance={top.distance_from_atm}",
            f"OI_change={top.components.get('oi_change'):.2f}",
            f"PCR={metrics.get('pcr',0):.2f}",
        ]
        opt_signal = OptionSignal(
            underlying_side=side,
            contract_symbol=top.contract.symbol,
            strike=top.contract.strike,
            kind=top.contract.kind,
            premium_ltp=top.contract.ltp,
            suggested_size_lots=pos['lots'],
            stop_loss_premium=pos['stop'],
            target_premium=pos['target'],
            metrics_snapshot=metrics,
            reasoning=reasoning,
            timestamp=now_ist()
        )
        # Update cooldown markers
        self.last_trade_side = side
        self.last_trade_ts = opt_signal.timestamp
        try:
            await self.emit_callback(opt_signal)
        except Exception:
            logger.exception("Emit callback failed for option signal")
