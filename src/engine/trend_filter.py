import logging
from typing import Optional

logger = logging.getLogger("trend_filter")

def higher_timeframe_trend_ok(side: str, price: float, primary_tf: str, confirm_tf: str, ema_confirm) -> bool:
    """Return True if trend filter passes.

    Rules:
      - If confirm timeframe equals primary timeframe -> allow (no filter).
      - If confirm EMA state not ready -> allow (warmup grace).
      - Otherwise require price relation to confirm long EMA:
          BUY: price > long EMA
          SELL: price < long EMA
    ema_confirm is expected to have attribute long_ema.
    """
    if confirm_tf == primary_tf:
        return True
    if ema_confirm is None or getattr(ema_confirm, "long_ema", None) is None:
        return True
    trend_ema = ema_confirm.long_ema
    if side == "BUY":
        return price > trend_ema
    return price < trend_ema
