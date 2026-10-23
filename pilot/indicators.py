def ema(values, period):
    """EMA aligned with input (leading None until `period` values exist)."""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    s = sum(values[:period]) / period
    out = [None] * (period - 1) + [s]
    for v in values[period:]:
        s = v * k + s * (1 - k)
        out.append(s)
    return out


def atr(candles, period=14):
    if len(candles) < period + 1:
        return []
    trs = [max(c.h - c.l, abs(c.h - p.c), abs(c.l - p.c)) for p, c in zip(candles, candles[1:])]
    a = sum(trs[:period]) / period
    out = [a]
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
        out.append(a)
    return out
