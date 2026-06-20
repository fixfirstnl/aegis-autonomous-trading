import MetaTrader5 as mt5
import structlog
from datetime import datetime
from typing import Optional, List, Dict, Any

from config import config

logger = structlog.get_logger()


class MT5Controller:
    """Manages MetaTrader 5 connection and trading operations."""

    def __init__(self):
        self.connected = False
        self._account_info: Optional[Dict[str, Any]] = None

    def connect(self) -> bool:
        """Initialize MT5 connection."""
        if self.connected:
            return True

        try:
            mt5.shutdown()
        except Exception:
            pass

        initialized = mt5.initialize(timeout=30000)
        if not initialized:
            logger.error("mt5_init_failed", error=mt5.last_error())
            return False

        self.connected = True
        self._refresh_account()
        logger.info("mt5_connected", server=self._account_info.get("server"))
        return True

    def disconnect(self) -> None:
        """Close MT5 connection."""
        mt5.shutdown()
        self.connected = False
        logger.info("mt5_disconnected")

    def _refresh_account(self) -> None:
        """Refresh cached account info."""
        info = mt5.account_info()
        if info is None:
            logger.error("mt5_no_account_info")
            return

        self._account_info = {
            "login": info.login,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "margin_level": info.margin_level,
            "profit": info.profit,
            "currency": info.currency,
        }

    @property
    def account(self) -> Optional[Dict[str, Any]]:
        """Get latest account info."""
        self._refresh_account()
        return self._account_info

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions."""
        if not self.connected:
            return []
        positions = mt5.positions_get()
        if positions is None:
            return []
        return [self._position_to_dict(p) for p in positions]

    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get symbol tick info."""
        if not self.connected:
            return None
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return {
            "symbol": symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": tick.ask - tick.bid,
            "time": datetime.fromtimestamp(tick.time),
        }

    def get_symbols(self) -> List[str]:
        """Get all available symbols."""
        if not self.connected:
            return []
        symbols = mt5.symbols_get()
        if symbols is None:
            return []
        return [s.name for s in symbols]

    def send_order(self, symbol: str, action: int, volume: float,
                   price: Optional[float] = None,
                   sl: Optional[float] = None,
                   tp: Optional[float] = None,
                   comment: str = "AEGIS") -> Optional[Dict[str, Any]]:
        """Send a trade order to MT5."""
        if not self.connected:
            logger.error("mt5_not_connected")
            return None

        if config.paper_trading:
            logger.info("paper_trade", symbol=symbol, action=action,
                       volume=volume, price=price, sl=sl, tp=tp)
            return {"ticket": 0, "paper": True}

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error("symbol_not_found", symbol=symbol)
            return None

        order_price = price or tick.ask
        request = {
            "action": action,
            "symbol": symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY,
            "price": order_price,
            "deviation": 10,
            "magic": config.magic_number,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if sl:
            request["sl"] = sl
        if tp:
            request["tp"] = tp

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error("order_failed", retcode=result.retcode,
                        symbol=symbol, action=action)
            return None

        logger.info("order_sent", ticket=result.order, symbol=symbol,
                   volume=volume, price=result.price)
        return {"ticket": result.order, "price": result.price}

    @staticmethod
    def _position_to_dict(pos) -> Dict[str, Any]:
        return {
            "ticket": pos.ticket,
            "symbol": pos.symbol,
            "type": "buy" if pos.type == 0 else "sell",
            "volume": pos.volume,
            "open_price": pos.price_open,
            "current_price": pos.price_current,
            "profit": pos.profit,
            "swap": pos.swap,
            "magic": pos.magic,
            "comment": pos.comment,
        }
