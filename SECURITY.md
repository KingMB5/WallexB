# Security — WallexB

## Credential handling

- `WALLEX_API_KEY` (trading) and `BOXAPI_KEY` (LLM confirmation) live **only**
  in the environment or a local `.env` file — never in git, never in
  `config.yaml`, never in logs. Code reads them via `os.environ` only
  (`pilot/wallex.py`, `pilot/llm.py`).
- `.env` is git-ignored. `.env.example` ships empty placeholders only.
- The LLM never receives secrets; it only sees the setup snapshot (symbol,
  candles, trend detail) and returns a verdict.

## Going live — the double lock

Real orders require BOTH:

1. `mode: live` in `config.yaml` (deliberate configuration), AND
2. `--live` on the command line (explicit human action)

`Engine.__init__` computes `live = live_flag and cfg["mode"] == "live"`. Every
entry additionally passes: trend gate → fee gate → hard risk sizing → LLM
fail-closed approval. A rejected order blocks that symbol for the rest of the day.

## Hard risk layer

`pilot/risk.py` limits (risk-per-trade, exposure, daily loss, kill switch,
fee gate, max stop) are hard-coded by config and cannot be overridden by the
LLM or by any strategy. The kill switch halts the bot entirely and requires an
explicit `python run.py reset-halt`.

## Key hygiene on Wallex

- Use a dedicated API key for the bot with minimal permissions; allowlist your
  server IP if the panel supports it.
- Rotate immediately if a key ever appears in a screenshot, chat or log —
  revoke first, clean up second.
- The LLM provider key (`BOXAPI_KEY`) has a hard cap (`max_calls_per_day: 30`).

## Runtime posture

- Market data (markets/UDF history) is public and needs no key; private calls
  (balances/orders) are only made when a key is configured.
- Trade journal (`data/pilot.db`) and exports stay local (git-ignored).
- `wallex_adaptive_lab/` is read-only by design — it never touches order
  endpoints.

## Reporting

Found a security issue? Report privately instead of opening a public issue.
