import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .broker import LiveBroker, PaperBroker
from .journal import Journal
from .llm import LLM
from .risk import Risk
from .strategies import load_strategies
from .trend import trend_gate
from .wallex import Wallex


class Engine:
    def __init__(self, cfg, live=False, wx=None):
        self.cfg = cfg
        self.live = live and cfg["mode"] == "live"      # double lock: config AND --live flag
        self.wx = wx or Wallex(cfg["wallex"])
        self.j = Journal(cfg["db_path"])
        self.broker = (LiveBroker(self.wx, cfg["wallex"]["usdt_tmn_symbol"]) if self.live
                       else PaperBroker(cfg, self.j, self.wx))
        self.risk = Risk(cfg["risk"], self.j, ZoneInfo(cfg["timezone"]))
        self.strats = load_strategies(cfg["strategies"])
        self.llm = LLM(cfg["llm"], self.j)
        self.blocked = {}          # symbol -> day, markets the exchange rejected
        self._last_eq_log = 0

    # ---------- helpers ----------
    def fx(self, quote, prices):
        if quote == "TMN":
            return 1.0
        if quote == "USDT":
            p = prices.get(self.cfg["wallex"]["usdt_tmn_symbol"])
            if not p:
                raise RuntimeError("no USDT/TMN price")
            return p
        raise RuntimeError(f"unsupported quote asset {quote}")

    def exposure(self, prices):
        return sum(t["qty"] * prices.get(t["symbol"], t["entry"]) * self.fx(t["quote"], prices)
                   for t in self.j.open_trades())

    def equity(self, prices):
        return self.broker.cash_tmn(prices) + self.exposure(prices)

    # ---------- position management (runs every manage_interval_sec) ----------
    def tick(self, prices):
        eq = self.equity(prices)
        self.risk.update(eq)
        if time.time() - self._last_eq_log > 300:
            self.j.log_equity(eq)
            self._last_eq_log = time.time()
        self.manage(prices)

    def manage(self, prices):
        r = self.cfg["risk"]
        for t in self.j.open_trades():
            p = prices.get(t["symbol"])
            if p is None:
                continue
            R = t["entry"] - t["init_stop"]
            hi = max(t["highest"] or t["entry"], p)
            stop = t["stop"]
            if hi >= t["entry"] + r["breakeven_r"] * R:
                stop = max(stop, t["entry"] * (1 + 2 * t["fee"]))
            if hi >= t["tp"]:
                stop = max(stop, hi - r["trail_r"] * R)
            upd = {}
            if hi != t["highest"]:
                upd["highest"] = hi
            if stop != t["stop"]:
                upd["stop"] = stop
                self.j.event("info", f"{t['symbol']} stop raised", stop=round(stop, 8), price=p)
            reason = None
            if p <= stop:
                reason = "stop" if stop <= t["init_stop"] else "trailing_stop"
            elif time.time() - t["opened_at"] > r["time_stop_hours"] * 3600:
                reason = "time_stop"
            elif self.risk.halted:
                reason = "kill_switch"
            if upd:
                self.j.update_trade(t["id"], **upd)
            if reason:
                self.close(t, p, reason, prices)

    def close(self, t, price, reason, prices):
        info = self.wx.info(t["symbol"])
        fx = self.fx(t["quote"], prices)
        fill = self.broker.sell(t["symbol"], t["qty"], price, fx, t["fee"], info)
        if not fill:
            self.j.event("error", f"sell failed for {t['symbol']}, will retry", reason=reason)
            return
        pnl = (fill.price * fx * (1 - t["fee"]) - t["entry"] * t["fx_entry"] * (1 + t["fee"])) * t["qty"]
        self.j.update_trade(t["id"], status="closed", closed_at=time.time(), exit_price=fill.price,
                            exit_reason=reason, pnl_tmn=pnl, r_mult=pnl / t["risk_tmn"] if t["risk_tmn"] else 0)
        self.j.event("trade", f"CLOSE {t['symbol']} ({reason})", exit=fill.price, pnl_tmn=round(pnl))

    # ---------- entry scan (runs every scan_interval_min) ----------
    def scan(self, prices, dry=False):
        eq = self.equity(prices)
        if self.risk.halted:
            self.j.event("warn", "halted by kill switch; run `python run.py reset-halt` to resume")
            return
        if self.risk.daily_blocked(eq):
            self.j.event("warn", "daily loss limit reached; no new entries today")
            return
        today = datetime.now(self.risk.tz).strftime("%Y-%m-%d")
        for sym in self.cfg["universe"]:
            open_ = self.j.open_trades()
            if len(open_) >= self.cfg["risk"]["max_positions"]:
                break
            if sym in {t["symbol"] for t in open_} or self.blocked.get(sym) == today:
                continue
            try:
                self.consider(sym, prices, eq, dry)
            except Exception as e:
                self.j.event("error", f"{sym}: {e!r}")

    def consider(self, sym, prices, eq, dry):
        trend = trend_gate(self.wx, sym, self.cfg["trend"])
        if not trend["up"]:
            print(f"  {sym}: trend not up -> skip", flush=True)
            return
        for st in self.strats:
            cs = self.wx.candles(sym, st.timeframe, 250)
            sig = st.scan(sym, cs)
            if sig:
                self.try_enter(sym, sig, trend, cs, prices, eq, dry, st.timeframe)
                return
        print(f"  {sym}: trend up, no setup", flush=True)

    def try_enter(self, sym, sig, trend, cs, prices, eq, dry, tf):
        info = self.wx.info(sym)
        fx = self.fx(info["quote"], prices)
        fee = self.cfg["fees"][info["quote"]]["taker"]
        price = prices[sym]
        stop, tp = sig.stop, sig.take_profit
        if price <= stop:
            return self.j.event("skip", f"{sym}: price already below stop")
        ok, why = self.risk.fee_gate(price, tp, fee)
        if not ok:
            return self.j.event("skip", f"{sym}: fee gate failed ({why})")
        if (price - stop) / price > self.cfg["risk"]["max_stop_pct"]:
            return self.j.event("skip", f"{sym}: stop too wide")
        qty, risk_tmn, why = self.risk.size(eq, price, stop, fx, fee, self.exposure(prices),
                                            self.broker.free_cash_tmn(info["quote"], prices), info)
        if not qty:
            return self.j.event("skip", f"{sym}: {why}")
        if dry:
            return self.j.event("signal", f"[dry] {sym} would BUY {qty}", entry=price, stop=stop,
                                tp=tp, risk_tmn=round(risk_tmn), reason=sig.reason)
        verdict = self.llm.verify(sig, trend, [c.c for c in cs[-40:]])
        # Fail closed: only an explicit, valid UP-trend approval is accepted.
        valid_approval = (
            isinstance(verdict, dict)
            and verdict.get("approve") is True
            and verdict.get("skipped") is not True
            and verdict.get("error") is not True
            and verdict.get("trend") == "up"
            and isinstance(verdict.get("reason"), str)
            and bool(verdict["reason"].strip())
        )
        if not valid_approval:
            return self.j.event(
                "skip", f"{sym}: missing or invalid LLM approval", verdict=verdict
            )
        try:
            fill = self.broker.buy(sym, qty, price, fx, fee, info)
        except Exception as e:
            self.blocked[sym] = datetime.now(self.risk.tz).strftime("%Y-%m-%d")
            return self.j.event("error", f"{sym}: order rejected, blocked for today: {e!r}")
        if not fill:
            return self.j.event("error", f"{sym}: buy not filled")
        tid = self.j.open_trade(
            mode="live" if self.live else "paper", symbol=sym, quote=info["quote"], setup=sig.setup, tf=tf,
            opened_at=time.time(), entry=fill.price, qty=fill.qty, init_stop=stop, stop=stop, tp=tp,
            highest=fill.price, risk_tmn=risk_tmn, fx_entry=fx, fee=fee, reason=sig.reason,
            trend=str(trend["detail"]), llm=str(verdict))
        self.j.event("trade", f"OPEN #{tid} {sym} {sig.setup}", entry=fill.price, qty=fill.qty,
                     stop=stop, tp=tp, risk_tmn=round(risk_tmn), why=sig.reason)

    # ---------- main loop ----------
    def run(self):
        lp = self.cfg["loop"]
        self.j.event("info", f"bot started in {'LIVE' if self.live else 'PAPER'} mode",
                     universe=self.cfg["universe"], strategies=[s.name for s in self.strats])
        next_scan = 0
        while True:
            try:
                prices = self.wx.prices()
                self.tick(prices)
                if time.time() >= next_scan:
                    self.scan(prices)
                    next_scan = time.time() + lp["scan_interval_min"] * 60
            except KeyboardInterrupt:
                raise
            except Exception as e:
                self.j.event("error", f"loop: {e!r}")
            time.sleep(lp["manage_interval_sec"])
