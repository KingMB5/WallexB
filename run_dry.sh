#!/usr/bin/env bash
# WallexB — one-click PAPER trading (safe: no real orders possible)
set -e
cd "$(dirname "$0")"
pip install -r requirements.txt >/dev/null 2>&1 || pip3 install -r requirements.txt >/dev/null 2>&1
exec python3 -m wallexbot run "$@"
