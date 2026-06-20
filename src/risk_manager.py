import structlog
from datetime import datetime
from typing import Optional, Dict, Any, List

from config import config

logger = structlog.get_logger()


class RiskManager:
    """Risk management with circuit breakers and position sizing."""

    def __init__(self):
        self._daily_equity_high = 0.0
        self._total_equity_high = 0.0
        self._consecutive_losses = 0
        self._trades_today = 0
        self._last_reset = datetime.now().date()
        self._circuit_breaker_active = False

    def reset_daily(self, equity: float) -> None:
        """Reset daily tracking."""
        today = datetime.now().date()
        if today != self._last_reset:
            self._daily_equity_high = equity
            self._trades_today = 0
            self._consecutive_losses = 0
            self._last_reset = today
            logger.info("daily_reset", equity=equity)

        if self._total_equity_high == 0:
            self._total_equity_high = equity
        if self._daily_equity_high == 0:
            self._daily_equity_high = equity

    def update_equity(self, equity: float) -> None:
        """Update equity highs."""
        self.reset_daily(equity)
        if equity > self._total_equity_high:
            self._total_equity_high = equity
        if equity > self._daily_equity_high:
            self._daily_equity_high = equity

    def check_circuit_breakers(self, equity: float, margin_level: float) -> Optional[str]:
        """Check all circuit breakers.

        Returns:
            Alert message if breaker triggered, else None.
        """
        if self._circuit_breaker_active:
            return "CIRCUIT_BREAKER_ACTIVE"

        self.update_equity(equity)

        # 1. Daily drawdown
        if self._daily_equity_high > 0:
            daily_dd = (self._daily_equity_high - equity) / self._daily_equity_high * 100
            if daily_dd > config.max_daily_drawdown_pct:
                self._circuit_breaker_active = True
                msg = f"DAILY_DRAWDOWN: {daily_dd:.1f}% > {config.max_daily_drawdown_pct}%"
                logger.critical("circuit_breaker", reason=msg)
                return msg

        # 2. Total drawdown
        if self._total_equity_high > 0:
            total_dd = (self._total_equity_high - equity) / self._total_equity_high * 100
            if total_dd > config.max_total_drawdown_pct:
                self._circuit_breaker_active = True
                msg = f"TOTAL_DRAWDOWN: {total_dd:.1f}% > {config.max_total_drawdown_pct}%"
                logger.critical("circuit_breaker", reason=msg)
                return msg

        # 3. Margin level
        if margin_level < 100:
            self._circuit_breaker_active = True
            msg = f"MARGIN_LEVEL: {margin_level:.1f}% < 100%"
            logger.critical("circuit_breaker", reason=msg)
            return msg

        # 4. Consecutive losses
        if self._consecutive_losses >= config.circuit_breaker_losses:
            self._circuit_breaker_active = True
            msg = f"CONSECUTIVE_LOSSES: {self._consecutive_losses}"
            logger.critical("circuit_breaker", reason=msg)
            return msg

        return None

    def calculate_position_size(self, balance: float, stop_loss_pips: float,
                                pip_value: float = 10.0) -> float:
        """Calculate lot size based on 2% risk rule.

        Returns:
            Lot size.
        """
        risk_amount = balance * (config.risk_per_trade_pct / 100)
        if stop_loss_pips <= 0 or pip_value <= 0:
            logger.warning("invalid_sl_or_pip_value", sl=stop_loss_pips, pip=pip_value)
            return 0.01  # Minimum

        lots = risk_amount / (stop_loss_pips * pip_value)
        lots = round(lots, 2)
        lots = max(0.01, lots)  # Minimum lot size
        logger.info("position_size", lots=lots, risk=risk_amount,
                   balance=balance, sl=stop_loss_pips)
        return lots

    def record_trade_result(self, profit: float) -> None:
        """Record trade result for consecutive loss tracking."""
        self._trades_today += 1
        if profit < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0
        logger.info("trade_recorded", profit=profit,
                   consecutive_losses=self._consecutive_losses)

    def reset_circuit_breaker(self) -> None:
        """Manual reset of circuit breaker (use with caution)."""
        self._circuit_breaker_active = False
        self._consecutive_losses = 0
        logger.warning("circuit_breaker_reset")

    @property
    def is_active(self) -> bool:
        return self._circuit_breaker_active

    def get_status(self) -> Dict[str, Any]:
        return {
            "circuit_breaker_active": self._circuit_breaker_active,
            "consecutive_losses": self._consecutive_losses,
            "daily_equity_high": self._daily_equity_high,
            "total_equity_high": self._total_equity_high,
            "trades_today": self._trades_today,
        }
