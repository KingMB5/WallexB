"""
__main__.py — CLI entry point.

    python -m wallexbot run                       # paper trading loop (default, safe)
    python -m wallexbot run --once                # one paper cycle and exit
    python -m wallexbot run --live                # REAL orders (needs the double gate in .env)
    python -m wallexbot status                    # print current state (secret-free)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import __version__
from .client import WallexClient
from .config import load_config
from .engine import TradingEngine


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wallexbot", description="WallexB — Wallex spot trading bot")
    parser.add_argument("--version", action="version", version=f"WallexB {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run the trading engine")
    p_run.add_argument("--symbol")
    p_run.add_argument("--strategy", choices=["sma_cross", "rsi_reversion"])
    p_run.add_argument("--resolution", help="candle minutes, e.g. 15/60/240")
    p_run.add_argument("--poll", type=int, help="poll seconds")
    p_run.add_argument("--once", action="store_true", help="run a single cycle and exit")
    p_run.add_argument("--live", action="store_true", help="REAL orders (double gate required)")

    sub.add_parser("status", help="show current state")

    args = parser.parse_args(argv)
    cfg = load_config()
    _setup_logging(cfg.log_level)

    if args.cmd == "run":
        if args.symbol:
            cfg.symbol = args.symbol
        if args.strategy:
            cfg.strategy = args.strategy
        if args.resolution:
            cfg.resolution = args.resolution
        if args.poll:
            cfg.poll_seconds = args.poll

    client = WallexClient(cfg.base_url, api_key=cfg.api_key)

    if args.cmd == "status":
        engine = TradingEngine(cfg, client, live=False)
        print(json.dumps(engine.status(), ensure_ascii=False, indent=1))
        return 0

    # cmd == run
    try:
        engine = TradingEngine(cfg, client, live=args.live)
    except PermissionError as e:
        logging.getLogger("wallexbot").error("%s", e)
        return 2

    if args.once:
        out = engine.run_cycle()
        s = out.get("state") or {}
        print(json.dumps({"action": out.get("action"), "reason": out.get("reason"),
                          "equity": s.get("equity"), "qty": s.get("qty")}, ensure_ascii=False))
        return 0

    engine.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
