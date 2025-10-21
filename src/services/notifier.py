import logging
import httpx
import asyncio
import smtplib
from email.message import EmailMessage
from src.config import settings

logger = logging.getLogger("notifier")

class Notifier:
    def __init__(self, webhook_url: str = ""):
        self.webhook = webhook_url
        self.client = httpx.AsyncClient(timeout=5.0)
        # Pre-validate SMTP config
        self.smtp_enabled = settings.SMTP_ENABLE and settings.SMTP_USERNAME and settings.SMTP_PASSWORD and settings.SMTP_TO and settings.SMTP_FROM

    async def _send_email(self, subject: str, body: str):
        if not self.smtp_enabled:
            return
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM
        msg["To"] = settings.SMTP_TO
        msg.set_content(body)
        loop = asyncio.get_running_loop()
        try:
            def _send():
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                    server.starttls()
                    server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                    server.send_message(msg)
            await loop.run_in_executor(None, _send)
        except Exception:
            logger.exception("SMTP send failed")

    async def notify_signal(self, signal):
        # Support underlying Signal or OptionSignal
        if hasattr(signal, 'contract_symbol'):
            msg = {
                "contract_symbol": signal.contract_symbol,
                "underlying_side": signal.underlying_side,
                "strike": signal.strike,
                "kind": signal.kind,
                "premium_ltp": signal.premium_ltp,
                "lots": signal.suggested_size_lots,
                "stop_loss_premium": signal.stop_loss_premium,
                "target_premium": signal.target_premium
            }
            email_subject = f"Option Signal {signal.underlying_side} {signal.contract_symbol}"
        else:
            msg = {
                "symbol": signal.symbol,
                "side": signal.side,
                "price": signal.price,
                "size": signal.size,
                "sl": signal.stop_loss,
                "tg": signal.target
            }
            email_subject = f"Trade Signal {signal.side} {signal.symbol}"
        if not self.webhook:
            logger.info("Signal: %s", msg)
            if self.smtp_enabled:
                await self._send_email(subject=email_subject, body=f"Signal: {msg}")
            return
        try:
            await self.client.post(self.webhook, json=msg)
            if self.smtp_enabled:
                await self._send_email(subject=email_subject, body=f"Signal: {msg}")
        except Exception:
            logger.exception("Notifier failed")
