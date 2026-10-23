"""
redact.py — secret masking helper.

Rule (inherited from LiaraPilot): a secret may appear in memory, but never in
logs, state files, error messages, or reports. Everything that looks like a
credential goes through `mask()` first.
"""

_SECRET_KEYS = {"WALLEX_API_KEY", "API_KEY", "TG_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TOKEN", "PASSWORD", "SECRET"}


def mask(value: str | None, keep: int = 4) -> str:
    """Mask a secret for safe display: 'abcd1234wxyz' -> 'abcd…wxyz'."""
    if not value:
        return "<empty>"
    value = str(value)
    if len(value) <= keep * 2:
        return "…"
    return f"{value[:keep]}…{value[-keep:]}"


def is_secret_key(name: str) -> bool:
    upper = name.upper()
    return any(s in upper for s in _SECRET_KEYS) or upper.endswith("_KEY")


def safe_config(items: dict) -> dict:
    """Return a copy of a config dict with every secret-looking value masked."""
    return {k: (mask(v) if is_secret_key(k) and v else v) for k, v in items.items()}
