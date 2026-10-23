# WallexB

**A trend-gated breakout–pullback spot trading bot for [Wallex](https://wallex.ir) — hard-coded risk layer, fail-closed LLM confirmation, paper mode by default.**

WallexB scans a small universe (USDTTMN / BTCTMN / ETHTMN), only considers longs
when the higher-timeframe trend gate (EMA20/200 on 4h or 1D) is up, waits for a
breakout–retest setup, sizes the position from a fixed risk budget, and manages
exits with R-multiples (breakeven → trailing → time stop → kill switch). A final
LLM check (BoxAPI, `gpt-5-mini`) must explicitly approve every entry — and it is
**fail-closed**: a missing, invalid or errored verdict is a rejection.

Nothing places a real order by accident: live trading needs BOTH `mode: live` in
`config.yaml` AND the `--live` CLI flag.

## Repository layout

```
run.py                   CLI: discover | check | scan-once | run | status | report | export | reset-halt
backtest.py              historical backtester over Wallex UDF candles
config.yaml              the whole bot behaviour — markets, trend gate, risk, strategy, LLM, loop
pilot/                   the engine package
  wallex.py              the ONLY file that talks to the Wallex HTTP API (retries, 429 backoff, cache)
  engine.py              scan → consider → try_enter (fee gate, LLM gate) + position management loop
  risk.py                hard limits — nothing (not even the LLM) can override them
  broker.py              PaperBroker | LiveBroker
  journal.py             SQLite trade journal (data/pilot.db)
  llm.py                 BoxAPI confirmation client (fail-closed, capped calls/day)
  trend.py               EMA20/200 trend gate on 240m / 1D
  indicators.py          ATR & co
  strategies/            plugin strategies (breakout_pullback, adaptive_hybrid)
wallex_adaptive_lab/     read-only research lab: M1→M15 backtest + one-pass shadow scan (never orders)
strategy_v1_draft/       unvalidated adaptive-hybrid hypothesis + unit tests
tests/                   smoke tests
data/                    backtest artifacts (summaries committed; CSVs/db stay local)
reports/                 lab outputs (adaptive_trades.jsonl, shadow.jsonl)
```

## Quickstart — PAPER (default, safe)

```bash
pip install -r requirements.txt
python run.py discover              # list markets matching oil/gold/silver keywords (or --all)
python run.py check                 # mode/equity + trend gate per symbol
python run.py scan-once             # one dry scan — logs what it *would* do
python run.py run                   # paper trading loop (SQLite journal at data/pilot.db)
```

Status & results:

```bash
python run.py status                # equity, halted flag, open trades, stats
python run.py report                # last 20 closed trades with R multiples
python run.py export                # journal -> data/journal.csv
python run.py reset-halt            # clear kill switch, reset peak equity
```

`mode: paper` in `config.yaml` is the safe default; paper fills apply realistic
fees and slippage (configurable).

## Going LIVE (real money — read carefully)

1. `cp .env.example .env` and set `WALLEX_API_KEY` (wallex.ir → API keys; use a
   dedicated key, restrict permissions, allowlist your IP if possible).
2. Optional LLM confirmation: set `BOXAPI_KEY` (without it, `on_error: reject`
   means every entry is rejected — the bot will paper-scan but never buy).
3. Change `mode: paper` → `mode: live` in `config.yaml`.
4. Start with a small `paper_equity_tmn`-sized universe and reduced
   `risk_per_trade`, then: `python run.py run --live`

Both switches are required; the engine double-locks them.

## Hard risk layer (config.yaml `risk:` — no exceptions)

| Control | Default |
|---|---|
| Risk per trade | 3% of equity |
| Max concurrent positions | 2 |
| Max exposure | 50% of equity |
| Daily loss limit | 3% → no new entries today |
| Kill switch drawdown | 8% under peak equity → close all + halt (needs `reset-halt`) |
| Breakeven / TP / trailing | at 1R stop→BE, at 2R trail by 1R |
| Time stop | 24h |
| Fee gate | expected move ≥ 3× round-trip fees |
| Max stop width | 8% |

## Backtest evidence (honest numbers)

From `backtest.py` (strategy-only; trend gate & LLM not simulated; fees 0.3% +
slippage 0.1% per side):

| Symbol | Bars | Trades | Win rate | Return | PF | Max DD |
|---|---|---|---|---|---|---|
| BTCTMN | 2000 | 48 | 14.6% | **−14.7%** | 0.20 | 15.3% |
| USDTTMN | 1978 | 39 | 7.7% | **−9.3%** | 0.05 | 9.3% |
| XAUTTMN | 2000 | 46 | 6.5% | **−17.1%** | 0.11 | 17.1% |

The raw breakout–pullback strategy is **not profitable as-is** — that is exactly
why this repo ships with paper-only defaults, a research lab
(`wallex_adaptive_lab/`) and a draft strategy (`strategy_v1_draft/`). Do not go
live expecting the current config to make money.

## Disclaimer

Trading crypto involves substantial risk. This is an engineering project, not
financial advice. Run paper for days, inspect `report` output, and never trade
money you cannot afford to lose.

## خلاصه‌ی فارسی

**والکس‌بی** ربات اسپات برای صرافی والکس است: فقط وقتی روند تایم‌بالاتر (EMA20/200
در ۴ساعته یا روزانه) صعودی باشد سراغ ستاپ‌های شکست–پولبک می‌رود، حجم را از بودجه‌ی
ریسک ثابت حساب می‌کند و خروج‌ها را با مضارب R مدیریت می‌کند (سر‌به‌سر در 1R، تریلینگ
در 2R، تایم‌استاپ ۲۴ ساعته و کیل‌سوییچ افت ۸٪). قبل از هر خرید واقعی، یک LLM
(باکس‌ای‌پی‌آی) باید صریحاً تأیید کند — و اگر جوابی نیامد یا خراب بود، «رد» می‌شود
(fail-closed). هیچ‌چیز به‌صورت تصادفی سفارش واقعی نمی‌گذارد: برای لایو بودن، هم
`mode: live` در کانفیگ لازم است هم فلگ `--live`. حالت پیش‌فرض paper با کارمزد و
لغزش واقع‌گرایانه است و همه‌ی محدودیت‌های ریسک سخت‌کد هستند و حتی LLM هم نمی‌تواند
دورشان بزند. نتایج بک‌تست فعلی منفی است (صادقانه در جدول بالا) — یعنی با این کانفیگ
لایو نرو؛ اول paper و آزمایشگاه تحقیقاتی. دستورهای اصلی: `discover`، `check`،
`scan-once`، `run`، `status`، `report`، `export`، `reset-halt`.
