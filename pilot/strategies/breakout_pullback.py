from ..indicators import atr
from ..models import Signal
from .base import Strategy


class BreakoutPullback(Strategy):
    """Close breaks above the prior `lookback`-bar high, then the first retest of that
    level holds (wick into the zone, bullish close back above it) => long."""
    name = "breakout_pullback"
    defaults = {"lookback": 20, "min_age": 1, "max_age": 12, "retest_tol": 0.003,
                "rr": 2.0, "stop_buffer_atr": 0.2, "first_retest_only": True, "atr_period": 14}

    def scan(self, symbol, candles):
        p, n = self.p, len(candles)
        if n < p["lookback"] + p["max_age"] + p["atr_period"] + 2:
            return None
        a = atr(candles, p["atr_period"])[-1]
        last, tol = candles[-1], p["retest_tol"]
        for age in range(p["min_age"], p["max_age"] + 1):
            bi = n - 1 - age
            level = max(c.h for c in candles[bi - p["lookback"]:bi])
            if candles[bi].c <= level:
                continue
            since = candles[bi + 1:]
            if any(c.c < level * (1 - tol) for c in since):
                continue                                  # breakout failed
            if p["first_retest_only"] and any(c.l <= level * (1 + tol) for c in since[:-1]):
                continue                                  # not the first retest
            if last.l <= level * (1 + tol) and last.c > level and last.c > last.o:
                stop = min(min(c.l for c in since), level) - p["stop_buffer_atr"] * a
                entry = last.c
                if stop >= entry:
                    continue
                tp = entry + p["rr"] * (entry - stop)
                return Signal(symbol, self.name, entry, stop, tp,
                              f"breakout above {level:.6g} ({age} bars ago), first retest held",
                              {"level": level, "age": age, "atr": a})
        return None
