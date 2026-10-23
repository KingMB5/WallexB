import math
import time
import uuid
from dataclasses import dataclass


@dataclass
class Fill:
    price: float
    qty: float


def floor_qty(q, dp):
    f = 10 ** dp
    return math.floor(q * f + 1e-9) / f


class PaperBroker:
    live = False

    def __init__(self, cfg, journal, wx):
        self.j, self.slip = journal, cfg.get("paper_slippage", 0.001)
        if journal.kv_get("paper_cash_tmn") is None:
            journal.kv_set("paper_cash_tmn", float(cfg["paper_equity_tmn"]))

    def cash_tmn(self, prices):
        return float(self.j.kv_get("paper_cash_tmn"))

    def free_cash_tmn(self, quote, prices):
        return self.cash_tmn(prices)

    def buy(self, symbol, qty, price, fx, fee, info):
        px = price * (1 + self.slip)
        cost = qty * px * fx * (1 + fee)
        if cost > self.cash_tmn(None):
            return None
        self.j.kv_set("paper_cash_tmn", self.cash_tmn(None) - cost)
        return Fill(px, qty)

    def sell(self, symbol, qty, price, fx, fee, info):
        px = price * (1 - self.slip)
        self.j.kv_set("paper_cash_tmn", self.cash_tmn(None) + qty * px * fx * (1 - fee))
        return Fill(px, qty)


class LiveBroker:
    live = True

    def __init__(self, wx, usdt_symbol):
        self.wx, self.usdt = wx, usdt_symbol

    def cash_tmn(self, prices):
        b = self.wx.balances()
        return b.get("TMN", (0, 0))[0] + b.get("USDT", (0, 0))[0] * prices.get(self.usdt, 0)

    def free_cash_tmn(self, quote, prices):
        free = self.wx.balances().get(quote, (0, 0))[1]
        return free * (1 if quote == "TMN" else prices.get(self.usdt, 0))

    def _market(self, symbol, side, qty, price):
        cid = f"wp-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        self.wx.place_market(symbol, side, qty, cid)
        o = {}
        for _ in range(10):
            time.sleep(1)
            o = self.wx.get_order(cid)
            if str(o.get("status", "")).upper() == "FILLED":
                break
        else:
            try:
                self.wx.cancel(cid)
                o = self.wx.get_order(cid)
            except Exception:
                pass
        done = float(o.get("executedQty") or 0)
        if done <= 0:
            return None
        return Fill(float(o.get("executedPrice") or o.get("price") or price), done)

    def buy(self, symbol, qty, price, fx, fee, info):
        return self._market(symbol, "BUY", qty, price)

    def sell(self, symbol, qty, price, fx, fee, info):
        free_base = self.wx.balances().get(info["base"], (0, 0))[1]
        qty = floor_qty(min(qty, free_base), info["qty_dp"])   # buy fee may be taken in base asset
        if qty <= 0:
            return None
        return self._market(symbol, "SELL", qty, price)
