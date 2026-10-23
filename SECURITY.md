# Security — WallexB

## Credential handling

- The Wallex API key lives **only** in the environment (`.env`, never committed)
  or the process env of your runtime. It is never written to state files, never
  logged, never sent anywhere except `x-api-key` headers to
  `https://api.wallex.ir`.
- `wallexbot/redact.py` masks every secret-looking value in logs, state and the
  CLI (`abcd…wxyz`); `state.py` strips secret-looking keys defensively before
  writing JSON.
- Telegram tokens (if you enable notifications) are treated with the same rules.

## The live double gate

Real orders require ALL of:

1. `LIVE_TRADING=1` (deliberate configuration)
2. `CONFIRM_LIVE=YES` (explicit human confirmation string)
3. `WALLEX_API_KEY` present

The engine checks the gate before constructing `LiveBroker`, and the broker
re-checks it defensively. Paper mode is the default for every code path.

## Key hygiene on Wallex

- Create a dedicated API key for the bot (not your main account key).
- Restrict permissions to the minimum the bot needs; enable IP allowlisting if
  offered.
- Rotate the key if it ever appears in a screenshot, chat, or log — revocation
  first, cleanup second.
- Prefer small caps (`MAX_POSITION_QUOTE`) over trust.

## Runtime posture

- Read-only network egress in paper mode: only `api.wallex.ir` public endpoints
  (+ Telegram if enabled).
- `scripts/check_api.py --private` is strictly read-only: it never places or
  cancels orders.
- State files are written atomically (`state/state.json.tmp` → rename) and are
  secret-free by construction.

## Reporting

Found a security issue? Please report privately instead of opening a public
issue.
