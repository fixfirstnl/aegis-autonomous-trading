import asyncio
from typing import Optional
import structlog

from config import config

logger = structlog.get_logger()


class TelegramAlert:
    """Telegram bot for alerts and remote commands."""

    def __init__(self):
        self.token = config.telegram_bot_token
        self.chat_id = config.telegram_chat_id
        self.enabled = bool(self.token and self.chat_id)

    async def send(self, message: str, severity: str = "info") -> bool:
        """Send Telegram message."""
        if not self.enabled:
            logger.debug("telegram_disabled", message=message)
            return False

        try:
            import aiohttp
            emoji = {"critical": "", "warning": "", "info": "", "success": ""}
            prefix = emoji.get(severity, "")
            full_msg = f"{prefix} AEGIS {prefix}\n\n{message}"

            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": full_msg,
                "parse_mode": "HTML",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info("telegram_sent", message=message[:50])
                        return True
                    else:
                        logger.error("telegram_failed", status=resp.status)
                        return False
        except Exception as e:
            logger.error("telegram_error", error=str(e))
            return False

    async def send_alert(self, alert_type: str, message: str, severity: str = "warning") -> bool:
        """Send formatted alert."""
        return await self.send(f"<b>{alert_type}</b>\n{message}", severity)

    async def send_trade(self, symbol: str, action: str, volume: float, price: float) -> bool:
        """Send trade notification."""
        msg = f"<b>Trade Executed</b>\nSymbol: {symbol}\nAction: {action}\nVolume: {volume}\nPrice: {price}"
        return await self.send(msg, "info")

    async def send_circuit_breaker(self, reason: str) -> bool:
        """Send circuit breaker alert."""
        return await self.send_alert("CIRCUIT BREAKER", reason, "critical")

    async def send_equity(self, balance: float, equity: float) -> bool:
        """Send daily equity summary."""
        msg = f"<b>Daily Summary</b>\nBalance: ${balance:.2f}\nEquity: ${equity:.2f}"
        return await self.send(msg, "info")
