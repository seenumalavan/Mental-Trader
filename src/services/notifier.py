import logging
import httpx

logger = logging.getLogger("notifier")

class Notifier:
    def __init__(self, webhook_url: str = ""):
        self.webhook = webhook_url
        self.client = httpx.AsyncClient(timeout=5.0)

    async def notify_signal(self, signal):
        msg = {
            "symbol": signal.symbol,
            "side": signal.side,
            "price": signal.price,
            "size": signal.size,
            "sl": signal.stop_loss,
            "tg": signal.target
        }
        if not self.webhook:
            logger.info("Signal: %s", msg)
            return
        try:
            await self.client.post(self.webhook, json=msg)
        except Exception:
            logger.exception("Notifier failed")
