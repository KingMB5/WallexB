import time

from .indicators import ema

_cache = {}


def trend_gate(wx, symbol, cfg):
    """Uptrend = last closed candle > EMA slow AND EMA fast > EMA slow."""
    detail, oks = {}, []
    for tf in cfg["timeframes"]:
        hit = _cache.get((symbol, tf))
        if hit and time.time() - hit[0] < cfg.get("cache_sec", 600):
            d = hit[1]
        else:
            closes = [c.c for c in wx.candles(symbol, tf, cfg["slow_ema"] + 60)]
            fast, slow = ema(closes, cfg["fast_ema"]), ema(closes, cfg["slow_ema"])
            if not slow:
                d = {"ok": False, "why": f"history too short ({len(closes)} candles)"}
            else:
                d = {"ok": closes[-1] > slow[-1] and fast[-1] > slow[-1], "close": closes[-1],
                     "ema_fast": round(fast[-1], 6), "ema_slow": round(slow[-1], 6)}
            _cache[(symbol, tf)] = (time.time(), d)
        detail[tf] = d
        oks.append(d["ok"])
    up = any(oks) if cfg["mode"] == "any" else all(oks)
    return {"up": up, "detail": detail}
