"""The ONLY file that talks to the Wallex HTTP API. If an endpoint or field
differs from the official docs, fix it here (or in config.yaml `paths`)."""
import os
import time

import requests

from .models import Candle

TF_SECONDS = {"1": 60, "5": 300, "15": 900, "30": 1800, "60": 3600, "120": 7200,
              "180": 10800, "240": 14400, "720": 43200, "1D": 86400}


class WallexError(Exception):
    pass


class Wallex:
    def __init__(self, cfg):
        self.base = cfg["base_url"].rstrip("/")
        self.paths = cfg["paths"]
        self.s = requests.Session()
        key = os.environ.get(cfg.get("api_key_env", "WALLEX_API_KEY"), "")
        if key:
            self.s.headers["x-api-key"] = key
        self._m = None
        self._mt = 0.0

    def _req(self, method, path, **kw):
        last = None
        for i in range(3):
            try:
                r = self.s.request(method, self.base + path, timeout=15, **kw)
                if r.status_code == 429:
                    time.sleep(2 * (i + 1))
                    continue
                data = r.json()
                if r.status_code >= 400 or (isinstance(data, dict) and data.get("success") is False):
                    raise WallexError(f"{method} {path} -> {r.status_code} {str(data)[:300]}")
                return data.get("result", data) if isinstance(data, dict) else data
            except (requests.RequestException, ValueError) as e:
                last = e
                time.sleep(1 + i)
        raise WallexError(f"{method} {path} failed: {last}")

    # ---- market data ----
    def markets(self, max_age=10):
        if self._m is None or time.time() - self._mt > max_age:
            res = self._req("GET", self.paths["markets"])
            syms = res.get("symbols", res) if isinstance(res, dict) else res
            if isinstance(syms, list):
                syms = {m.get("symbol"): m for m in syms}
            self._m, self._mt = syms, time.time()
        return self._m

    def prices(self):
        out = {}
        for s, m in self.markets().items():
            try:
                p = float((m.get("stats") or {}).get("lastPrice") or 0)
            except (TypeError, ValueError):
                p = 0
            if p > 0:
                out[s] = p
        return out

    def info(self, symbol):
        m = self.markets().get(symbol)
        if not m:
            raise WallexError(f"unknown market {symbol}")
        quote = m.get("quoteAsset") or m.get("quote_asset") or (
            "TMN" if symbol.endswith("TMN") else "USDT" if symbol.endswith("USDT") else "")
        base = m.get("baseAsset") or m.get("base_asset") or symbol[: -len(quote)] if quote else symbol
        return {
            "quote": quote, "base": base,
            "qty_dp": int(m.get("amount_precision") or m.get("amountPrecision") or m.get("stepSize") or 6),
            "min_notional": float(m.get("minNotional") or m.get("min_notional") or 0),
        }

    def candles(self, symbol, tf, n=250):
        sec = TF_SECONDS[tf]
        now = int(time.time())
        res = self._req("GET", self.paths["history"], params={
            "symbol": symbol, "resolution": tf, "from": now - sec * (n + 5), "to": now})
        if res.get("s") != "ok":
            raise WallexError(f"no candles for {symbol} {tf}: {str(res)[:200]}")
        cs = [Candle(int(t), float(o), float(h), float(l), float(c), float(v))
              for t, o, h, l, c, v in zip(res["t"], res["o"], res["h"], res["l"], res["c"], res["v"])]
        if cs and cs[-1].t + sec > now:      # drop the still-forming candle
            cs = cs[:-1]
        return cs

    # ---- account ----
    def balances(self):
        """-> {asset: (total, free)}"""
        res = self._req("GET", self.paths["balances"])
        b = res.get("balances", res)
        out = {}
        for k, v in b.items():
            total = float(v.get("value") or 0)
            out[k] = (total, total - float(v.get("locked") or 0))
        return out

    def place_market(self, symbol, side, qty, client_id):
        return self._req("POST", self.paths["orders"], json={
            "symbol": symbol, "type": "MARKET", "side": side,
            "quantity": str(qty), "client_id": client_id})

    def get_order(self, client_id):
        return self._req("GET", self.paths["order"].format(client_id=client_id))

    def cancel(self, client_id):
        return self._req("DELETE", self.paths["orders"], params={"clientOrderId": client_id})
