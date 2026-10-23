"""
risk.py — every order passes through here. No exceptions.

Three-tier risk model (inherited from LiaraPilot's approval-gate philosophy):
  tier 0 (automatic)  : paper orders, indicator reads
  tier 1 (gated)      : live orders — require the double live-gate in config
  tier 2 (never)      : leveraged/margin trades, orders above MAX_POSITION_QUOTE,
                        trading after the daily loss cap fired today

The RiskManager never sees or stores any credential — it only does math.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass


@dataclass
class RiskDecision:
    allowed: bool
    reason: str


class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.day_anchor_equity: float | None = None
        self.day: str = ""
        self.halted_today: bool = False

    # ------------------------------------------------------------------
    def _roll_day(self, equity: float) -> None:
        today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        if today != self.day:
            self.day = today
            self.day_anchor_equity = equity
            self.halted_today = False

    def daily_loss_pct(self, equity: float) -> float:
        self._roll_day(equity)
        if not self.day_anchor_equity:
            return 0.0
        return max(0.0, (self.day_anchor_equity - equity) / self.day_anchor_equity * 100.0)

    # ------------------------------------------------------------------
    def can_open(self, position_quote: float, order_quote: float, equity: float) -> RiskDecision:
        self._roll_day(equity)
        if self.halted_today:
            return RiskDecision(False, "daily loss cap already fired today — halted until tomorrow")
        if position_quote + order_quote > self.cfg.max_position_quote:
            return RiskDecision(
                False,
                f"position cap: {position_quote + order_quote:,.0f} would exceed MAX_POSITION_QUOTE={self.cfg.max_position_quote:,.0f}",
            )
        if order_quote < self.cfg.min_notional:
            return RiskDecision(False, f"order below minNotional ({self.cfg.min_notional:,.0f} TMN)")
        loss_pct = self.daily_loss_pct(equity)
        if loss_pct >= self.cfg.daily_max_loss_pct:
            self.halted_today = True
            return RiskDecision(
                False, f"daily loss {loss_pct:.2f}% >= cap {self.cfg.daily_max_loss_pct:.2f}% — trading halted for today"
            )
        return RiskDecision(True, "ok")

    def should_exit(self, entry_price: float, last_price: float) -> RiskDecision:
        if not entry_price or not last_price:
            return RiskDecision(False, "no price")
        change_pct = (last_price - entry_price) / entry_price * 100.0
        if change_pct <= -self.cfg.stop_loss_pct:
            return RiskDecision(True, f"STOP-LOSS hit ({change_pct:.2f}% <= -{self.cfg.stop_loss_pct}%)")
        if change_pct >= self.cfg.take_profit_pct:
            return RiskDecision(True, f"TAKE-PROFIT hit ({change_pct:.2f}% >= +{self.cfg.take_profit_pct}%)")
        return RiskDecision(False, f"within band ({change_pct:+.2f}%)")
