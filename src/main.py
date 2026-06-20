import asyncio
import argparse
import structlog
from typing import Optional

from config import config
from daemon import Daemon
from ea_compiler import EACompiler
from mt5_controller import MT5Controller
from risk_manager import RiskManager
from telegram_alerts import TelegramAlert

logger = structlog.get_logger()


def setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


async def run_daemon() -> None:
    daemon = Daemon()
    try:
        await daemon.run()
    except KeyboardInterrupt:
        daemon.stop()
        print("\n[BYE] Daemon gestopt")


def run_compile(source_dir: str) -> None:
    compiler = EACompiler()
    deployed = compiler.compile_and_deploy(source_dir)
    print(f"Deployed to {len(deployed)} terminals")


def run_once() -> None:
    mt5 = MT5Controller()
    risk = RiskManager()

    if not mt5.connect():
        print("MT5 connection failed")
        return

    account = mt5.account
    if not account:
        print("No account info")
        mt5.disconnect()
        return

    equity = account.get("equity", 0)
    margin_level = account.get("margin_level", 0)
    breaker = risk.check_circuit_breakers(equity, margin_level)

    if breaker:
        print(f"CIRCUIT BREAKER: {breaker}")
    else:
        print(f"OK | Balance: ${account.get('balance', 0):.2f} | Equity: ${equity:.2f}")

    mt5.disconnect()


def run_optimize() -> None:
    print("Optimization not yet implemented - use backtest first")


def run_backtest() -> None:
    print("Backtest integration coming soon")


async def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="AEGIS Autonomous Trading Controller")
    parser.add_argument("--daemon", action="store_true", help="24/7 daemon mode")
    parser.add_argument("--compile", metavar="DIR", help="Compile MQL5 and deploy")
    parser.add_argument("--optimize", action="store_true", help="Optimize setfiles")
    parser.add_argument("--backtest", action="store_true", help="Run backtest")
    parser.add_argument("--once", action="store_true", help="Single health check")
    parser.add_argument("--interval", type=int, default=60, help="Daemon interval (seconds)")

    args = parser.parse_args()

    if args.daemon:
        await run_daemon()
    elif args.compile:
        run_compile(args.compile)
    elif args.optimize:
        run_optimize()
    elif args.backtest:
        run_backtest()
    else:
        run_once()


if __name__ == "__main__":
    asyncio.run(main())
