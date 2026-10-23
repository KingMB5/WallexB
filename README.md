# WallexB

**A dry-run-first spot trading bot for [Wallex](https://wallex.ir) (Iranian crypto exchange) — paper trading by default, live orders behind a double safety gate.**

WallexB polls real Wallex market data (order book + candles), runs a pluggable
signal strategy (SMA crossover or RSI reversion), enforces a hard risk layer
(stop-loss, take-profit, position cap, daily loss halt), and only then — paper
or live — executes. Nothing places a real order by accident: live trading needs
**three** things to line up (`LIVE_TRADING=1` + `CONFIRM_LIVE=YES` + an API key),
and every secret is masked in every log, state file and report.

Public Wallex endpoints used by this bot were **verified live** against
`https://api.wallex.ir` (see `docs/ARCHITECTURE.md`); private endpoints are
clearly marked UNVERIFIED until you run the staged probe below.

## Repository layout

```
wallexbot/           the bot package
  client.py          Wallex REST wrapper (VERIFIED public / UNVERIFIED private, secret-redacting)
  config.py          env-driven settings + the live double-gate
  strategies.py      SmaCross | RsiReversion (closed candles only)
  indicators.py      SMA + Wilder RSI in pure python
  risk.py            stop-loss / take-profit / position cap / daily loss halt
  brokers.py         PaperBroker (ledger + book-priced fills) | LiveBroker (gated)
  engine.py          candles -> signal -> risk -> order -> state
  state.py           atomic JSON state, secret-stripped on write
  notify.py          optional Telegram (no extra dependency)
  redact.py          secret masking used everywhere
scripts/
  check_api.py       staged API probe — tier 1 public (no key), tier 2 private reads
docs/
  ARCHITECTURE.md    flow, strategy math, risk tiers, VERIFIED/UNVERIFIED matrix
```

## Run — PAPER mode (default, safe, real market data)

```bash
pip install -r requirements.txt
python3 -m wallexbot run                    # paper loop, BTCTMN, SMA cross, 1h candles
```

One-click launchers: `run_dry.sh` (Linux/macOS) / `run_dry.bat` (Windows).
Single cycle (great for cron/CI):

```bash
python3 -m wallexbot run --once
python3 -m wallexbot status                 # secret-free state snapshot
```

Paper fills are priced from the **live order book** (best ask/bid) with
slippage and a configurable fee — so paper results are a realistic rehearsal,
not a fantasy backtest.

## Verify the API before going live

```bash
python3 scripts/check_api.py                            # tier 1: public, no key needed
WALLEX_API_KEY=<key> python3 scripts/check_api.py --private   # tier 2: read-only account probes
```

Every step prints PASS/FAIL/UNVERIFIED with a redacted error. The script never
places or cancels orders.

## Run — LIVE mode (real money — read this twice)

1. `cp .env.example .env`, set `WALLEX_API_KEY` (from wallex.ir → API Keys —
   **restrict its permissions** to what the bot needs and use an IP allowlist
   if the panel offers one).
2. Set `LIVE_TRADING=1` **and** `CONFIRM_LIVE=YES`.
3. Start with tiny limits: `ORDER_QUOTE_AMOUNT=100000 MAX_POSITION_QUOTE=200000 STOP_LOSS_PCT=2`.
4. Then: `python3 -m wallexbot run --live`

The engine re-checks the gate and refuses to start otherwise. Private order
endpoints are UNVERIFIED — your first `--live` run IS the verification: start
with the smallest possible order and watch the logs.

## Risk layer (always on)

| Control | Env | Default |
|---|---|---|
| Stop-loss | `STOP_LOSS_PCT` | 3% |
| Take-profit | `TAKE_PROFIT_PCT` | 6% |
| Max open position | `MAX_POSITION_QUOTE` | 2,000,000 TMN |
| Daily loss halt (auto-resets next day) | `DAILY_MAX_LOSS_PCT` | 5% |
| Min order size | `MIN_NOTIONAL` | 50,000 TMN |

Tier-2 (never offered): margin/leverage, orders above the position cap, trading
after the daily halt fired. See `docs/ARCHITECTURE.md`.

## Disclaimer

Trading crypto involves substantial risk. This bot is an engineering project,
not financial advice. Paper-trade for days before enabling live mode, and never
trade money you cannot afford to lose.

## خلاصه‌ی فارسی

**والکس‌بی** ربات معامله‌گر اسپات برای صرافی والکس است که با اصل «اول شبیه‌سازی،
بعد معامله‌ی واقعی» ساخته شده: به‌صورت پیش‌فرض با داده‌ی واقعی بازار (عمق بازار و
کندل‌های UDF) اما با پول کاغذی کار می‌کند و هیچ‌وقت تصادفی سفارش واقعی نمی‌گذارد.
برای معامله‌ی واقعی، سه چیز باید هم‌زمان برقرار باشد: `LIVE_TRADING=1`،
`CONFIRM_LIVE=YES` و کلید API — و در همه‌ی لاگ‌ها و فایل‌های وضعیت، کلیدها با
`redact.py` ماسک می‌شوند. دو استراتژی آماده دارد (تقاطع SMA و بازگشت RSI) و هر
سیگنال قبل از اجرا از لایه‌ی ریسک رد می‌شود: حد ضرر، حد سود، سقف موقعیت، توقف
روزانه‌ی ضرر و حداقل حجم سفارش. اسکریپت `scripts/check_api.py` اندپوینت‌های
عمومی (وریفای‌شده) و خصوصی (فقط خواندنی) را مرحله‌به‌مرحله چک می‌کند و وضعیت
PASS/FAIL/UNVERIFIED چاپ می‌کند. اعلان اختیاری تلگرام هم دارد. توصیه‌ی جدی: چند
روز در حالت paper اجرا کن، بعد با کوچک‌ترین سفارش ممکن live برو — این پروژه
مهندسی است، نه توصیه‌ی مالی.
