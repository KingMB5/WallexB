"""
brokers.py — where signals become (paper or real) trades.

PaperBroker (default): a local ledger with realistic fills taken from the live
order book (best ask to buy, best bid to sell), fee and slippage applied.

LiveBroker: real Wallex spot orders. Reaching this class requires the triple
gate (LIVE_TRADING=1 + CONFIRM_LIVE=YES + WALLEX_API_KEY); the engine checks
the gate before constructing it, and the broker re-checks defensively.
"""

from __future__ import annotations

import logging
import time
import uuid

from .redact import mask

log = logging.getLogger("wallexbot.broker")


class PaperBroker:
    def __init__(self, cfg, client):
        self.cfg = cfg
        self.client = client
        self.cash = cfg.starting_cash
        self.qty = 0.0
        self.entry_price = 0.0
        self.trades: list[dict] = []

    # ------------------------------------------------------------------
    @property
    def position_quote(self) -> float:
        return self.qty * self.entry_price

    def buy(self, quote_amount: float, symbol: str) -> dict:
        _, ask = self.client.best_prices(symbol)
        if not ask:
            raise RuntimeError("empty order book — cannot price a paper fill")
        slip = ask * (1 + 0.0005)  # 5 bps slippage
        fee = quote_amount * (self.cfg.fee_pct / 100.0)
        qty = (quote_amount - fee) / slip
        if self.cash < quote_amount:
            raise RuntimeError(f"paper cash insufficient: {self.cash:,.0f} < {quote_amount:,.0f}")
        self.cash -= quote_amount
        total_cost = self.entry_price * self.qty + slip * qty
        self.qty += qty
        self.entry_price = total_cost / self.qty if self.qty else 0.0
        trade = {"ts": int(time.time()), "side": "BUY", "qty": qty, "price": slip,
                 "quote": quote_amount, "fee": fee, "mode": "paper", "id": uuid.uuid4().hex[:12]}
        self.trades.append(trade)
        log.info("PAPER BUY %s qty=%.8f @ %.0f (fee=%.0f)", symbol, qty, slip, fee)
        return trade

    def sell(self, symbol: str) -> dict:
        bid, _ = self.client.best_prices(symbol)
        if not bid:
            raise RuntimeError("empty order book — cannot price a paper fill")
        slip = bid * (1 - 0.0005)
        gross = self.qty * slip
        fee = gross * (self.cfg.fee_pct / 100.0)
        self.cash += gross - fee
        trade = {"ts": int(time.time()), "side": "SELL", "qty": self.qty, "price": slip,
                 "quote": gross - fee, "fee": fee, "mode": "paper",
                 "pnl": gross - fee - self.position_quote, "id": uuid.uuid4().hex[:12]}
        self.qty = 0.0
        self.entry_price = 0.0
        self.trades.append(trade)
        log.info("PAPER SELL %s qty=%.8f @ %.0f (fee=%.0f, pnl=%.0f)",
                 symbol, trade["qty"], slip, fee, trade.get("pnl", 0))
        return trade

    def equity(self, last_price: float | None) -> float:
        mark = (last_price or self.entry_price) * self.qty
        return self.cash + mark


class LiveBroker:
    """Real orders — only constructed when cfg.live_confirmed is True."""

    def __init__(self, cfg, client):
        if not cfg.live_confirmed:  # defensive re-check
            raise PermissionError(
                "live trading refused: double gate not satisfied "
                f"[{cfg.safety_report()}]"
            )
        self.cfg = cfg
        self.client = client

    def buy(self, quote_amount: float, symbol: str) -> dict:
        res = self.client.place_order(symbol, "BUY", "MARKET", quote_quantity=quote_amount)
        log.warning("LIVE BUY placed on %s quote=%.0f (key=%s) — result=%s",
                    symbol, quote_amount, mask(self.client.api_key), res.get("result", {}).get("clientOrderId"))
        return {"ts": int(time.time()), "side": "BUY", "quote": quote_amount, "mode": "live", "raw": res}

    def sell(self, symbol: str) -> dict:
        # sell the whole base balance we hold (market order)
        res = self.client.place_order(symbol, "SELL", "MARKET")
        log.warning("LIVE SELL placed on %s (key=%s)", symbol, mask(self.client.api_key))
        return {"ts": int(time.time()), "side": "SELL", "mode": "live", "raw": res}

    def equity(self, last_price: float | None) -> float:
        return 0.0  # live equity is read from /v1/account/balances by the engine
