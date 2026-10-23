# Architecture — WallexB

## Flow

```
            ┌──────────────────────────────────────────────────────────┐
            │                       engine.run_cycle                    │
            └──────────────────────────────────────────────────────────┘
   GET /v1/udf/history ──► closed candles ──► strategy.evaluate()
        (VERIFIED)                              │  buy / sell / None
                                                ▼
                                  ┌──────────────────────────┐
                                  │        risk layer         │
                                  │ stop-loss / take-profit   │
                                  │ position cap              │
                                  │ daily loss halt           │
                                  └──────────────────────────┘
                                       allowed?          │ yes
                                                ▼        ▼
                                  PaperBroker (default)  LiveBroker
                                  book-priced fills      POST /v1/account/orders
                                  local ledger           (double-gated, UNVERIFIED*)
                                                │
                                                ▼
                                  state/state.json (atomic, secret-free)
```

\* UNVERIFIED means: documented by Wallex, not yet exercised by the maintainers.
`scripts/check_api.py --private` verifies reads; your first tiny `--live` order
verifies writes.

## Endpoint verification matrix

| Endpoint | Auth | Status | Probed |
|---|---|---|---|
| `GET /v1/markets` | none | **VERIFIED** | 2026-10-23 |
| `GET /v1/depth?symbol=` | none | **VERIFIED** | 2026-10-23 |
| `GET /v1/udf/history?symbol&resolution&from&to` | none | **VERIFIED** | 2026-10-23 |
| `GET /v1/account/balances` | `x-api-key` | UNVERIFIED (read) | — |
| `GET /v1/account/orders` | `x-api-key` | UNVERIFIED (read) | — |
| `POST /v1/account/orders` | `x-api-key` | UNVERIFIED (write) | — |
| `DELETE /v1/account/orders/{id}` | `x-api-key` | UNVERIFIED (write) | — |

Probe yourself: `python3 scripts/check_api.py --private`.

## Strategies (signals on closed candles only)

### sma_cross
- `SMA_FAST` (default 9) vs `SMA_SLOW` (default 21) on close prices.
- fast crosses **above** slow → buy; crosses **below** → sell/exit.

### rsi_reversion
- Wilder RSI (default 14). RSI leaves **oversold** (30) upward → buy.
- RSI leaves **overbought** (70) downward → sell/exit.

The forming (newest) candle is always excluded from evaluation to avoid
repainting.

## Risk tiers

| Tier | Who decides | Examples |
|---|---|---|
| 0 — automatic | the bot | paper orders, indicator reads, state writes |
| 1 — gated | you, via config | live orders (double gate + key) |
| 2 — never | nobody | leverage/margin, orders over the position cap, trading after the daily halt |

## Paper fills

Buys fill at best ask × (1 + 5bps), sells at best bid × (1 − 5bps), plus
`FEE_PCT` (default 0.25%). The paper ledger tracks cash, position, average
entry, realized PnL and equity — persisted after every cycle.

## State format (`state/state.json`)

`symbol`, `strategy`, `mode`, `cash`, `qty`, `entry_price`, `last_price`,
`equity`, `day`, `day_anchor_equity`, `halted_today`, `trades[]`, `updated_at`.
Secret-looking keys are stripped on write; `mode` is always visible so you can
never confuse paper with live.
