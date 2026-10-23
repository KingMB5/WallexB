"""
config.py — all settings come from environment (or .env), never from code.

Live trading is double-gated: it happens only when BOTH of these hold —
  1) LIVE_TRADING=1        (deliberate configuration)
  2) CONFIRM_LIVE=YES      (explicit human confirmation)
  3) WALLEX_API_KEY set    (the actual credential)
Everything else — every default path — is paper trading. Nothing can place a
real order by accident.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # optional convenience: load .env if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .redact import mask

BASE_URL = "https://api.wallex.ir"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(_env(name, str(default))))
    except ValueError:
        return default


@dataclass
class Config:
    # --- identity / API -------------------------------------------------
    api_key: str = field(default_factory=lambda: _env("WALLEX_API_KEY"))
    base_url: str = field(default_factory=lambda: _env("WALLEX_BASE_URL", BASE_URL) or BASE_URL)

    # --- market ---------------------------------------------------------
    symbol: str = field(default_factory=lambda: _env("SYMBOL", "BTCTMN"))
    resolution: str = field(default_factory=lambda: _env("RESOLUTION", "60"))  # minutes per candle
    poll_seconds: int = field(default_factory=lambda: _env_int("POLL_SECONDS", 30))
    candles: int = field(default_factory=lambda: _env_int("CANDLES", 200))  # history window

    # --- strategy -------------------------------------------------------
    strategy: str = field(default_factory=lambda: _env("STRATEGY", "sma_cross"))
    sma_fast: int = field(default_factory=lambda: _env_int("SMA_FAST", 9))
    sma_slow: int = field(default_factory=lambda: _env_int("SMA_SLOW", 21))
    rsi_period: int = field(default_factory=lambda: _env_int("RSI_PERIOD", 14))
    rsi_oversold: float = field(default_factory=lambda: _env_float("RSI_OVERSOLD", 30.0))
    rsi_overbought: float = field(default_factory=lambda: _env_float("RSI_OVERBOUGHT", 70.0))

    # --- money & risk ---------------------------------------------------
    order_quote_amount: float = field(default_factory=lambda: _env_float("ORDER_QUOTE_AMOUNT", 500_000.0))  # TMN per buy
    max_position_quote: float = field(default_factory=lambda: _env_float("MAX_POSITION_QUOTE", 2_000_000.0))
    stop_loss_pct: float = field(default_factory=lambda: _env_float("STOP_LOSS_PCT", 3.0))
    take_profit_pct: float = field(default_factory=lambda: _env_float("TAKE_PROFIT_PCT", 6.0))
    daily_max_loss_pct: float = field(default_factory=lambda: _env_float("DAILY_MAX_LOSS_PCT", 5.0))
    min_notional: float = field(default_factory=lambda: _env_float("MIN_NOTIONAL", 50_000.0))
    fee_pct: float = field(default_factory=lambda: _env_float("FEE_PCT", 0.25))  # paper trading fee
    starting_cash: float = field(default_factory=lambda: _env_float("STARTING_CASH", 10_000_000.0))  # paper TMN

    # --- safety switches ------------------------------------------------
    live_trading: bool = field(default_factory=lambda: _env("LIVE_TRADING") == "1")
    confirm_live: str = field(default_factory=lambda: _env("CONFIRM_LIVE"))
    dry_run: bool = True  # CLI may flip this after the double gate passes

    # --- housekeeping ---------------------------------------------------
    state_file: str = field(default_factory=lambda: _env("STATE_FILE", "state/state.json"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    tg_bot_token: str = field(default_factory=lambda: _env("TG_BOT_TOKEN"))
    tg_chat_id: str = field(default_factory=lambda: _env("TG_CHAT_ID"))

    # -------------------------------------------------------------------
    @property
    def live_confirmed(self) -> bool:
        return self.live_trading and self.confirm_live.upper() == "YES" and bool(self.api_key)

    def safety_report(self) -> str:
        """One-line, secret-free summary of the live gate — for logs and CLI."""
        return (
            f"LIVE_TRADING={'1' if self.live_trading else '0'} "
            f"CONFIRM_LIVE={'YES' if self.confirm_live.upper() == 'YES' else '<not-yes>'} "
            f"WALLEX_API_KEY={mask(self.api_key)}"
        )

    def safe_dict(self) -> dict:
        """Secret-free snapshot of the whole config (safe for logs/state)."""
        d = vars(self).copy()
        d["api_key"] = mask(self.api_key)
        d["tg_bot_token"] = mask(self.tg_bot_token)
        return d


def load_config() -> Config:
    return Config()
