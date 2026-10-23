WALLEX ADAPTIVE LAB — M15 + M1 ONLY
===================================

Purpose
-------
A separate read-only research tool for historical backtesting and a one-pass
shadow scan. It fetches M1 history and derives M15 candles only from complete,
UTC-aligned groups of 15 consecutive M1 bars. It never submits orders or calls
order endpoints. It does not modify the existing bot or config.yaml.

Important caveats
-----------------
- M5 has deliberately been removed.
- Missing M1 bars are never fabricated; incomplete 15-minute groups are dropped.
- Strategy rules are a prototype, not a validated profitable strategy.
- Backtest is simplified: single position per symbol, next-M1-open entry,
  conservative stop-first resolution when stop and target are both touched,
  fee/slippage assumptions per side. No bid/ask data is available here.
- It is not yet a full portfolio/risk engine and does not claim competition-ready
  performance. Inspect data warnings and trades before relying on metrics.

Install
-------
From the wallex-bot project folder, copy adaptive_lab.py there (or run it from
its own folder with --config pointing at your project's config.yaml), then:

  python -m pip install requests PyYAML

Backtest 14 days
----------------
  python adaptive_lab.py --config config.yaml --symbols BTCTMN ETHTMN --days 14 backtest

One-pass shadow scan (read-only)
--------------------------------
  python adaptive_lab.py --config config.yaml --symbols BTCTMN ETHTMN shadow

Outputs
-------
reports/adaptive_trades.jsonl : closed backtest trades
reports/shadow.jsonl          : one JSON record per symbol per shadow run

Fee/slippage defaults are assumptions, not exchange-confirmed fills. Do not
enable live trading based on this prototype. No order submission is implemented.
