#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AEGIS Configuration Manager - Handles .env, setfiles, and validation."""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
import structlog

logger = structlog.get_logger()

# Directories
BASE_DIR = Path(__file__).parent.parent
LOG_DIR = BASE_DIR / "logs"
SETFILES_DIR = BASE_DIR / "setfiles"
BACKTESTS_DIR = BASE_DIR / "backtests"

for d in [LOG_DIR, SETFILES_DIR, BACKTESTS_DIR]:
    d.mkdir(exist_ok=True)


class Config:
    """Central configuration manager."""

    def __init__(self, env_path: Optional[str] = None):
        load_dotenv(env_path or BASE_DIR / ".env")
        self._validate()

    # MT5
    @property
    def mt5_path(self) -> str:
        return os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")

    @property
    def metaeditor_path(self) -> str:
        return os.getenv("METAEDITOR_PATH", r"C:\Program Files\MetaTrader 5\MetaEditor64.exe")

    # Risk
    @property
    def risk_per_trade_pct(self) -> float:
        return float(os.getenv("RISK_PER_TRADE_PCT", "2.0"))

    @property
    def max_daily_drawdown_pct(self) -> float:
        return float(os.getenv("MAX_DAILY_DRAWDOWN_PCT", "6.0"))

    @property
    def max_total_drawdown_pct(self) -> float:
        return float(os.getenv("MAX_TOTAL_DRAWDOWN_PCT", "15.0"))

    @property
    def circuit_breaker_losses(self) -> int:
        return int(os.getenv("CIRCUIT_BREAKER_CONSECUTIVE_LOSSES", "3"))

    # Telegram
    @property
    def telegram_bot_token(self) -> Optional[str]:
        return os.getenv("TELEGRAM_BOT_TOKEN")

    @property
    def telegram_chat_id(self) -> Optional[str]:
        return os.getenv("TELEGRAM_CHAT_ID")

    # Trading
    @property
    def symbols(self) -> List[str]:
        raw = os.getenv("EA_SYMBOLS", "EURUSD,GBPUSD,USDJPY,XAUUSD,BTCUSD")
        return [s.strip() for s in raw.split(",")]

    @property
    def timeframes(self) -> List[str]:
        raw = os.getenv("EA_TIMEFRAMES", "M5,H1")
        return [s.strip() for s in raw.split(",")]

    @property
    def magic_number(self) -> int:
        return int(os.getenv("EA_MAGIC_NUMBER", "998475"))

    @property
    def paper_trading(self) -> bool:
        live = os.getenv("LIVE_MODE", "false").lower() == "true"
        if live:
            return False
        return os.getenv("PAPER_TRADING", "true").lower() == "true"

    @property
    def live_mode(self) -> bool:
        return os.getenv("LIVE_MODE", "false").lower() == "true"

    @property
    def crypto_24_7(self) -> bool:
        return os.getenv("CRYPTO_24_7", "true").lower() == "true"

    # Daemon
    @property
    def daemon_interval(self) -> int:
        return int(os.getenv("DAEMON_INTERVAL_SECONDS", "60"))

    @property
    def health_check_interval(self) -> int:
        return int(os.getenv("HEALTH_CHECK_INTERVAL", "300"))

    # Setfiles
    def load_setfile(self, name: str) -> Dict[str, Any]:
        """Parse .set file into dict."""
        path = SETFILES_DIR / f"{name}.set"
        if not path.exists():
            raise FileNotFoundError(f"Setfile not found: {path}")

        params: Dict[str, Any] = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(";"):
                    continue
                match = re.match(r"^(\w+)\s*=\s*(.+)$", line)
                if match:
                    key, val = match.group(1), match.group(2).strip()
                    params[key] = self._cast_value(val)
        logger.info("setfile_loaded", name=name, params=len(params))
        return params

    def save_setfile(self, name: str, params: Dict[str, Any]) -> None:
        """Save dict to .set file."""
        path = SETFILES_DIR / f"{name}.set"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"; AEGIS Generated Setfile: {name}\n")
            for k, v in sorted(params.items()):
                f.write(f"{k}={v}\n")
        logger.info("setfile_saved", name=name, path=str(path))

    @staticmethod
    def _cast_value(val: str) -> Any:
        """Cast string value to int, float, or keep as string."""
        try:
            return int(val)
        except ValueError:
            try:
                return float(val)
            except ValueError:
                return val

    def _validate(self) -> None:
        """Ensure critical config is present."""
        if not self.telegram_bot_token and not self.paper_trading:
            logger.warning("telegram_not_configured",
                         msg="No Telegram alerts - running without notifications")
        if self.risk_per_trade_pct > 5.0:
            logger.warning("high_risk_config", pct=self.risk_per_trade_pct)


# Singleton instance
config = Config()
