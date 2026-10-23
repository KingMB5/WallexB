"""Offline end-to-end test: fake exchange, paper broker, real engine/risk/strategy code."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from pilot.config import load_config
from pilot.engine import Engine
from pilot.models import Candle
from pilot.wallex import Wallex


def series(closes, spread=0.002):
    return [Candle(i * 3600, c, c * (1 + spread), c * (1 - spread), c, 1) for i, c in enumerate(closes)]


def uptrend(n=300):
    return series([100 * (1.004 ** i) for i in range(n)])


def setup_candles():
    base = [100 + 0.01 * i for i in range(240)]            # slow drift
    rng = [100 + (0.5 if i % 2 else -0.5) for i in range(30)]   # range, highs ~100.5*1.002
    cs = series(base + rng)
    level = max(c.h for c in cs[-20:])
    brk = Candle(len(cs) * 3600, level * 0.999, level * 1.03, level * 0.999, level * 1.025, 1)
    cs.append(brk)
    cs.append(Candle(len(cs) * 3600, level * 1.025, level * 1.04, level * 1.02, level * 1.03, 1))
    cs.append(Candle(len(cs) * 3600, level * 1.0, level * 1.015, level * 0.9995, level * 1.012, 1))  # retest, bullish
    return cs


class Fake(Wallex):
    def __init__(self):
        self.price = None
    def markets(self, max_age=10):
        cs = setup_candles()
        return {"BTCTMN": {"symbol": "BTCTMN", "quoteAsset": "TMN", "baseAsset": "BTC", "amount_precision": 6,
                           "stats": {"lastPrice": str(self.price or cs[-1].c)}}}
    def candles(self, symbol, tf, n=250):
        return uptrend() if tf in ("240", "1D") else setup_candles()


cfg = load_config(os.path.join(os.path.dirname(__file__), "..", "config.yaml"))
cfg["db_path"] = os.path.join(tempfile.mkdtemp(), "t.db")
cfg["universe"] = ["BTCTMN"]
cfg["risk"]["min_order_tmn"] = 1000
fake = Fake()
e = Engine(cfg, wx=fake)
# Offline test only: simulate a valid LLM approval; never call a real API.
e.llm.verify = lambda *args, **kwargs: {
    "approve": True, "trend": "up", "reason": "offline test approval"
}
prices = fake.prices()
e.tick(prices); e.scan(prices)
ot = e.j.open_trades()
assert len(ot) == 1, "expected one open trade"
t = ot[0]; print("opened:", t["symbol"], t["qty"], t["entry"], t["init_stop"], t["tp"])
assert t['risk_tmn'] <= 0.03 * 5_000_000 * 1.01 and t['qty'] * t['entry'] <= 0.5 * 5_000_000 * 1.01
# rally to target -> trailing -> pullback to trailing stop
R = t["entry"] - t["init_stop"]
for p in [t["entry"] + 1.1 * R, t["tp"] + 0.5 * R, t["tp"] + 1.5 * R]:
    fake.price = p; pr = fake.prices(); e.tick(pr)
assert e.j.open_trades(), "should still be open while trending"
fake.price = t["tp"] + 0.4 * R; pr = fake.prices(); e.tick(pr)
assert not e.j.open_trades(), "trailing stop should have closed it"
print(e.j.stats()); assert e.j.closed_trades()[0]["pnl_tmn"] > 0
# losing path
e2 = Engine({**cfg, "db_path": cfg["db_path"].replace("t.db", "t2.db")}, wx=fake)
# Offline test only: simulate the same valid approval for the second scenario.
e2.llm.verify = lambda *args, **kwargs: {
    "approve": True, "trend": "up", "reason": "offline test approval"
}
fake.price = None; pr = fake.prices(); e2.tick(pr); e2.scan(pr)
t2 = e2.j.open_trades()[0]; fake.price = t2["init_stop"] * 0.999; pr = fake.prices(); e2.tick(pr)
assert not e2.j.open_trades() and e2.j.closed_trades()[0]["exit_reason"] == "stop"
print("loss:", e2.j.stats()); print("SMOKE TEST OK")
