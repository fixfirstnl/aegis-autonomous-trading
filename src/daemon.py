import asyncio
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import structlog

from config import config, LOG_DIR
from mt5_controller import MT5Controller
from risk_manager import RiskManager

logger = structlog.get_logger()


class Daemon:
    """24/7 execution loop for AEGIS trading."""

    def __init__(self):
        self.mt5 = MT5Controller()
        self.risk = RiskManager()
        self.running = False
        self.cycle = 0
        self._health_log = LOG_DIR / "daemon_health.jsonl"

    def _log_event(self, event_type: str, data: Dict[str, Any] = None) -> None:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "cycle": self.cycle,
            "type": event_type,
            "data": data or {},
        }
        with open(self._health_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    async def run(self) -> None:
        """Main daemon loop."""
        self.running = True
        logger.info("daemon_started", interval=config.daemon_interval)

        while self.running:
            self.cycle += 1
            try:
                await self._cycle()
            except Exception as e:
                logger.error("daemon_cycle_error", error=str(e))
                self._log_event("cycle_error", {"error": str(e)})

            await asyncio.sleep(config.daemon_interval)

    async def _cycle(self) -> None:
        """Single health check and trading cycle."""
        connected = self.mt5.connect()
        if not connected:
            logger.warning("mt5_connection_failed", cycle=self.cycle)
            self._log_event("mt5_disconnect")
            return

        account = self.mt5.account
        if not account:
            logger.warning("no_account_info", cycle=self.cycle)
            self.mt5.disconnect()
            return

        equity = account.get("equity", 0)
        margin_level = account.get("margin_level", 0)
        balance = account.get("balance", 0)

        # Check circuit breakers
        breaker = self.risk.check_circuit_breakers(equity, margin_level)
        if breaker:
            logger.critical("circuit_breaker_triggered", reason=breaker)
            self._log_event("circuit_breaker", {"reason": breaker})
            self._alert(f"CIRCUIT BREAKER: {breaker}")
            # TODO: Close all positions if configured
            self.mt5.disconnect()
            return

        # Get positions
        positions = self.mt5.get_positions()
        for pos in positions:
            self.risk.record_trade_result(pos.get("profit", 0))

        # Log health
        self._log_event("health_check", {
            "balance": balance,
            "equity": equity,
            "margin_level": margin_level,
            "positions": len(positions),
            "circuit_breaker": self.risk.is_active,
        })

        logger.info("daemon_cycle_complete", cycle=self.cycle,
                   balance=balance, equity=equity, positions=len(positions))

        self.mt5.disconnect()

    def _alert(self, message: str) -> None:
        """Send alert via Telegram or fallback."""
        logger.warning("alert", message=message)
        # TODO: Telegram integration

    def stop(self) -> None:
        """Graceful shutdown."""
        self.running = False
        logger.info("daemon_stopped", cycles=self.cycle)
        self._log_event("daemon_stop", {"cycles": self.cycle})
