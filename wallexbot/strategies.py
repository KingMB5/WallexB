"""
strategies.py — pluggable signal strategies.

A strategy looks at closed candles (the newest candle is still forming and is
ignored) and emits one of: "buy" | "sell" | None, plus a human-readable reason.
No strategy ever touches money — it only reads prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .indicators import rsi, sma

Signal = Literal["buy", "sell"]


@dataclass
class StrategyResult:
    signal: Signal | None
    reason: str
    snapshot: dict  # indicator values for logging (no secrets, no money)


@dataclass
class SmaCross:
    fast: int = 9
    slow: int = 21
    name: str = "sma_cross"

    def evaluate(self, candles: list[dict]) -> StrategyResult:
        closes = [c["close"] for c in candles[:-1]]  # ignore the forming candle
        fast = sma(closes, self.fast)
        slow = sma(closes, self.slow)
        snap = {"sma_fast": fast[-1], "sma_slow": slow[-1], "close": closes[-1] if closes else None}
        if len(closes) < self.slow + 1 or fast[-1] is None or slow[-1] is None or fast[-2] is None or slow[-2] is None:
            return StrategyResult(None, "not enough history", snap)
        crossed_up = fast[-2] <= slow[-2] and fast[-1] > slow[-1]
        crossed_down = fast[-2] >= slow[-2] and fast[-1] < slow[-1]
        if crossed_up:
            return StrategyResult("buy", f"SMA{self.fast} crossed above SMA{self.slow}", snap)
        if crossed_down:
            return StrategyResult("sell", f"SMA{self.fast} crossed below SMA{self.slow}", snap)
        return StrategyResult(None, "no cross", snap)


@dataclass
class RsiReversion:
    period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0
    name: str = "rsi_reversion"

    def evaluate(self, candles: list[dict]) -> StrategyResult:
        closes = [c["close"] for c in candles[:-1]]
        r = rsi(closes, self.period)
        snap = {"rsi": r[-1], "close": closes[-1] if closes else None}
        if r[-1] is None or r[-2] is None:
            return StrategyResult(None, "not enough history", snap)
        if r[-2] < self.oversold <= r[-1]:
            return StrategyResult("buy", f"RSI left oversold ({self.oversold}) upward", snap)
        if r[-2] > self.overbought >= r[-1]:
            return StrategyResult("sell", f"RSI left overbought ({self.overbought}) downward", snap)
        return StrategyResult(None, "RSI neutral", snap)


def get_strategy(cfg) -> SmaCross | RsiReversion:
    if cfg.strategy == "sma_cross":
        return SmaCross(fast=cfg.sma_fast, slow=cfg.sma_slow)
    if cfg.strategy == "rsi_reversion":
        return RsiReversion(period=cfg.rsi_period, oversold=cfg.rsi_oversold, overbought=cfg.rsi_overbought)
    raise ValueError(f"unknown strategy {cfg.strategy!r} (use sma_cross | rsi_reversion)")
