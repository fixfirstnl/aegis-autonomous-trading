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
from telegram_alerts import TelegramAlert
import MetaTrader5 as mt5

logger = structlog.get_logger()


class Daemon:
    """24/7 execution loop for AEGIS trading. Phase 4: Live Trading."""

    def __init__(self):
        self.mt5 = MT5Controller()
        self.risk = RiskManager()
        self.telegram = TelegramAlert()
        self.running = False
        self.cycle = 0
        self._health_log = LOG_DIR / "daemon_health.jsonl"
        self._live_warned = False

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
        
        if config.live_mode:
            logger.critical("LIVE_MODE_ACTIVE", 
                          msg="REAL MONEY ON THE LINE - Circuit breakers armed")
            await self.telegram.send_alert("LIVE MODE", 
                "AEGIS Daemon started in LIVE MODE. Real money at risk.", "critical")
        else:
            logger.info("daemon_started_paper", interval=config.daemon_interval)
            await self.telegram.send("AEGIS Daemon started in PAPER mode", "info")

        while self.running:
            self.cycle += 1
            try:
                await self._cycle()
            except Exception as e:
                logger.error("daemon_cycle_error", error=str(e))
                self._log_event("cycle_error", {"error": str(e)})
                await self.telegram.send_alert("Daemon Error", str(e), "critical")

            await asyncio.sleep(config.daemon_interval)

    async def _cycle(self) -> None:
        """Single health check and trading cycle."""
        connected = self.mt5.connect()
        if not connected:
            logger.warning("mt5_connection_failed", cycle=self.cycle)
            self._log_event("mt5_disconnect")
            await self.telegram.send_alert("MT5 Disconnect", 
                "Cannot connect to MetaTrader 5", "warning")
            return

        account = self.mt5.account
        if not account:
            logger.warning("no_account_info", cycle=self.cycle)
            self.mt5.disconnect()
            return

        equity = account.get("equity", 0)
        margin_level = account.get("margin_level", 0)
        balance = account.get("balance", 0)

        # Skip if no valid account data (margin_level=0 means no account logged in)
        if margin_level == 0:
            logger.warning("no_valid_account_data", equity=equity, margin_level=margin_level)
            self.mt5.disconnect()
            return

        # Check circuit breakers
        breaker = self.risk.check_circuit_breakers(equity, margin_level)
        if breaker:
            logger.critical("circuit_breaker_triggered", reason=breaker)
            self._log_event("circuit_breaker", {"reason": breaker})
            await self.telegram.send_circuit_breaker(breaker)
            
            # CLOSE ALL POSITIONS IMMEDIATELY
            await self._emergency_close_all()
            
            self.mt5.disconnect()
            return

        # Get positions and track P&L
        positions = self.mt5.get_positions()
        total_pnl = 0.0
        for pos in positions:
            profit = pos.get("profit", 0)
            total_pnl += profit
            self.risk.record_trade_result(profit)
            
            # Alert on large individual losses
            if profit < -50:
                await self.telegram.send_alert("Large Loss", 
                    f"Position {pos['ticket']} ({pos['symbol']}) loss: ${profit:.2f}", 
                    "warning")

        # Log health
        self._log_event("health_check", {
            "balance": balance,
            "equity": equity,
            "margin_level": margin_level,
            "positions": len(positions),
            "total_pnl": total_pnl,
            "circuit_breaker": self.risk.is_active,
            "live_mode": config.live_mode,
        })

        logger.info("daemon_cycle_complete", cycle=self.cycle,
                   balance=balance, equity=equity, positions=len(positions),
                   pnl=total_pnl, live=config.live_mode)

        self.mt5.disconnect()

    async def _emergency_close_all(self) -> None:
        """Close all open positions immediately."""
        if not self.mt5.connected:
            self.mt5.connect()
        
        positions = self.mt5.get_positions()
        closed = 0
        failed = 0
        
        for pos in positions:
            try:
                # Determine close action based on position type
                symbol = pos.get("symbol")
                ticket = pos.get("ticket")
                volume = pos.get("volume")
                
                if pos.get("type") == "buy":
                    # Close buy = sell
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": symbol,
                        "volume": volume,
                        "type": mt5.ORDER_TYPE_SELL,
                        "position": ticket,
                        "price": mt5.symbol_info_tick(symbol).bid,
                        "deviation": 10,
                        "magic": config.magic_number,
                        "comment": "AEGIS EMERGENCY CLOSE",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    }
                else:
                    # Close sell = buy
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": symbol,
                        "volume": volume,
                        "type": mt5.ORDER_TYPE_BUY,
                        "position": ticket,
                        "price": mt5.symbol_info_tick(symbol).ask,
                        "deviation": 10,
                        "magic": config.magic_number,
                        "comment": "AEGIS EMERGENCY CLOSE",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    }
                
                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    closed += 1
                    logger.info("emergency_close", ticket=ticket, symbol=symbol)
                else:
                    failed += 1
                    logger.error("emergency_close_failed", 
                               ticket=ticket, retcode=result.retcode)
            except Exception as e:
                failed += 1
                logger.error("emergency_close_error", ticket=ticket, error=str(e))
        
        await self.telegram.send_alert("Emergency Close", 
            f"Closed {closed} positions, {failed} failed. Circuit breaker active.", 
            "critical")
        logger.critical("emergency_close_complete", closed=closed, failed=failed)

    def stop(self) -> None:
        """Graceful shutdown."""
        self.running = False
        logger.info("daemon_stopped", cycles=self.cycle)
        self._log_event("daemon_stop", {"cycles": self.cycle})
