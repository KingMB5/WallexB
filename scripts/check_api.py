#!/usr/bin/env python3
"""
check_api.py — staged Wallex API probe (mirrors LiaraPilot's live_check.py).

Tier 1 (default, no key): public endpoints — markets, depth, udf/history.
Tier 2 (--private, needs WALLEX_API_KEY): balances + open orders (READ-ONLY —
         this script never places or cancels orders).

Every step prints PASS / FAIL / UNVERIFIED with a redacted error.

    python3 scripts/check_api.py
    python3 scripts/check_api.py --symbol USDTTMN
    WALLEX_API_KEY=<key> python3 scripts/check_api.py --private
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wallexbot.client import WallexApiError, WallexClient  # noqa: E402
from wallexbot.redact import mask  # noqa: E402


def step(name: str, fn):
    try:
        out = fn()
        print(f"PASS  {name}")
        return out
    except WallexApiError as e:
        print(f"FAIL  {name}: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL  {name}: {type(e).__name__}: {e}")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCTMN")
    ap.add_argument("--private", action="store_true", help="also probe private read endpoints (needs WALLEX_API_KEY)")
    args = ap.parse_args()

    key = os.environ.get("WALLEX_API_KEY")
    client = WallexClient("https://api.wallex.ir", api_key=key)

    print("== Tier 1: public endpoints (VERIFIED) ==")
    symbols = step(f"GET /v1/markets", client.markets)
    if symbols:
        print(f"      -> {len(symbols)} symbols; {args.symbol} present: {args.symbol in symbols}")
    step(f"GET /v1/depth?symbol={args.symbol}", lambda: client.depth(args.symbol))
    candles = step(f"GET /v1/udf/history ({args.symbol}, 60m)", lambda: client.candles(args.symbol, "60", 100))
    if candles:
        print(f"      -> {len(candles)} candles, last close={candles[-1]['close']}")

    ok = symbols is not None

    if args.private:
        print("\n== Tier 2: private endpoints (UNVERIFIED — read-only) ==")
        if not key:
            print("SKIP  WALLEX_API_KEY not set")
            return 1
        print(f"      key={mask(key)}")
        step("GET /v1/account/balances", client.balances)
        step(f"GET /v1/account/orders?symbol={args.symbol}", lambda: client.open_orders(args.symbol))
    else:
        print("\n(private endpoints not probed — run with --private and WALLEX_API_KEY)")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
