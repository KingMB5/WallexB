# Wallex Adaptive Hybrid v1 — standalone scaffold

Status: initial, unvalidated hypothesis for long-only Wallex spot; never places orders.
Existing `breakout_pullback` is not included or modified. PAPER mode must remain enabled.

## Files
- `adaptive_hybrid_strategy.py`: regime classifier, signal candidate and risk sizing helpers.
- `test_adaptive_hybrid_strategy.py`: basic unit tests.

## Input contract
Pass M15/M5/M1 candles as dictionaries sorted oldest to newest, with `timestamp`, `open`, `high`, `low`, `close`, `volume`. Last candle of each list must be closed. Defaults require 300 M15 candles and 100 each M5/M1.

## Critical limitations
This is not yet integrated into the user's local bot repository because its source was not available in this turn. Strategy thresholds need realistic historical tests. The caller must enforce data freshness, depth/slippage, order minimums/precision, daily loss lock, exposure/correlation caps, duplicate order prevention, partial fills, actual filled quantities, and the 12-hour time exit. No live mode, no live orders.

## Backtest gates
Use fees + slippage; prevent lookahead; compare each setup separately and combined; report net return, PF, expectancy, max drawdown/recovery, trade count, R metrics, costs/gross profit, and out-of-sample/walk-forward performance. Do not claim profitability until evidence supports it.

## Run tests
`python -m unittest -v`
