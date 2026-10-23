"""
engine.py — the trading loop: candles -> strategy -> risk -> broker -> state.

Design rules:
  * signals are evaluated on CLOSED candles only (the forming candle is ignored);
  * every order — paper or live — passes RiskManager.can_open / should_exit;
  * the live gate is checked here AND defensively re-checked inside LiveBroker;
  * state is saved to disk after every cycle (crash-safe, secret-free);
  * logs never contain the API key (redact.mask everywhere it could appear).
"""

from __future__ import annotations

import logging
import time

from .brokers import LiveBroker, PaperBroker
from .notify import Notifier
from .risk import RiskManager
from .state import load_state, save_state
from .strategies import get_strategy

log = logging.getLogger("wallexbot.engine")


class TradingEngine:
    def __init__(self, cfg, client, live: bool = False):
        self.cfg = cfg
        self.client = client
        self.strategy = get_strategy(cfg)
        self.risk = RiskManager(cfg)
        self.notifier = Notifier(cfg.tg_bot_token, cfg.tg_chat_id)
        if live:
            if not cfg.live_confirmed:
                raise PermissionError(
                    f"--live refused. Double gate not satisfied: {cfg.safety_report()}"
                )
            self.broker = LiveBroker(cfg, client)
            log.warning("LIVE TRADING ENABLED — real orders will be placed on %s", cfg.symbol)
        else:
            self.broker = PaperBroker(cfg, client)
            log.info("paper mode — no real orders can be placed")
        st = load_state(cfg.state_file)
        if st.get("cash") is not None and isinstance(self.broker, PaperBroker):
            self.broker.cash = float(st["cash"])
            self.broker.qty = float(st.get("qty") or 0)
            self.broker.entry_price = float(st.get("entry_price") or 0)
            self.broker.trades = list(st.get("trades") or [])
            self.risk.day = st.get("day", "")
            self.risk.day_anchor_equity = st.get("day_anchor_equity")
            self.risk.halted_today = bool(st.get("halted_today"))
            log.info("state restored: cash=%.0f qty=%.8f", self.broker.cash, self.broker.qty)

    # ------------------------------------------------------------------
    def _snapshot_state(self, last_price: float | None) -> dict:
        return {
            "symbol": self.cfg.symbol,
            "strategy": self.cfg.strategy,
            "mode": "live" if isinstance(self.broker, LiveBroker) else "paper",
            "cash": round(self.broker.cash, 2),
            "qty": self.broker.qty,
            "entry_price": self.broker.entry_price,
            "last_price": last_price,
            "equity": round(self.broker.equity(last_price), 2),
            "day": self.risk.day,
            "day_anchor_equity": self.risk.day_anchor_equity,
            "halted_today": self.risk.halted_today,
            "trades": self.broker.trades[-200:],
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _notify(self, text: str) -> None:
        self.notifier.send(text)

    # ------------------------------------------------------------------
    def run_cycle(self) -> dict:
        cfg = self.cfg
        candles = self.client.candles(cfg.symbol, cfg.resolution, max(cfg.candles, cfg.sma_slow * 3))
        if len(candles) < cfg.sma_slow + 2:
            log.warning("not enough candles yet (%d) — skipping cycle", len(candles))
            return {}
        last_price = float(candles[-1]["close"])

        # 1) protective exit first (risk before signals)
        if self.broker.qty > 0 and not isinstance(self.broker, LiveBroker):
            exit_decision = self.risk.should_exit(self.broker.entry_price, last_price)
            if exit_decision.allowed:
                trade = self.broker.sell(cfg.symbol)
                self._notify(f"🔻 {cfg.symbol} EXIT — {exit_decision.reason}")
                state = self._snapshot_state(last_price)
                save_state(cfg.state_file, state)
                return {"action": "sell", "reason": exit_decision.reason, "state": state}

        # 2) strategy signal
        result = self.strategy.evaluate(candles)
        state = self._snapshot_state(last_price)

        if result.signal == "buy" and self.broker.qty == 0:
            decision = self.risk.can_open(self.broker.position_quote, cfg.order_quote_amount, self.broker.equity(last_price))
            if decision.allowed:
                trade = self.broker.buy(cfg.order_quote_amount, cfg.symbol)
                self._notify(f"🔺 {cfg.symbol} BUY {cfg.order_quote_amount:,.0f} TMN — {result.reason}")
                state = self._snapshot_state(last_price)
                save_state(cfg.state_file, state)
                return {"action": "buy", "reason": result.reason, "state": state}
            log.info("buy signal suppressed by risk: %s", decision.reason)

        elif result.signal == "sell" and self.broker.qty > 0:
            trade = self.broker.sell(cfg.symbol)
            self._notify(f"🔻 {cfg.symbol} SELL — {result.reason}")
            state = self._snapshot_state(last_price)
            save_state(cfg.state_file, state)
            return {"action": "sell", "reason": result.reason, "state": state}

        # 3) idle — persist snapshot for the status command
        save_state(cfg.state_file, state)
        return {"action": None, "reason": result.reason, "state": state}

    # ------------------------------------------------------------------
    def run_forever(self) -> None:
        log.info("engine started: symbol=%s strategy=%s resolution=%sm poll=%ss",
                 self.cfg.symbol, self.cfg.strategy, self.cfg.resolution, self.cfg.poll_seconds)
        try:
            while True:
                try:
                    out = self.run_cycle()
                    if out.get("state"):
                        s = out["state"]
                        log.info("cycle: close=%s equity=%s qty=%.8f | %s",
                                 s.get("last_price"), s.get("equity"), s.get("qty") or 0, out.get("reason"))
                except Exception:  # keep the loop alive on transient API errors
                    log.exception("cycle failed — retrying next poll")
                time.sleep(self.cfg.poll_seconds)
        except KeyboardInterrupt:
            log.info("stopped by user (Ctrl+C)")
            self._notify("🛑 WallexB stopped")

    def status(self) -> dict:
        st = load_state(self.cfg.state_file)
        if not st:
            st = self._snapshot_state(None)
        return st
