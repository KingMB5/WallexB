"""
client.py — thin, defensive wrapper over the Wallex REST API.

VERIFIED (live-probed from this repo's scripts/check_api.py, 2026-10-23):
  GET /v1/markets                     -> {"result": {"symbols": {SYM: {..., "stats": {...}}}}}
  GET /v1/depth?symbol=SYM            -> {"result": {"ask": [{"price","quantity","sum"}], "bid": [...]}}
  GET /v1/udf/history?symbol=SYM&resolution=R&from=U&to=U
                                      -> {"s":"ok","t":[..],"o":[..],"h":[..],"l":[..],"c":[..],"v":[..]}

UNVERIFIED (documented by Wallex; verified interactively via `check_api.py --private`):
  header "x-api-key: <key>"
  GET    /v1/account/balances
  GET    /v1/account/orders?symbol=SYM
  POST   /v1/account/orders   {symbol, type: MARKET|LIMIT, side: BUY|SELL, price?, quantity | quoteQuantity}
  DELETE /v1/account/orders/{clientOrderId}

The client never logs, never stores, and never returns the API key. Errors are
raised as WallexApiError with the status code and a redacted body snippet.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .redact import mask

log = logging.getLogger("wallexbot.client")


class WallexApiError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        snippet = (body or "")[:300]
        super().__init__(f"Wallex API {status} on {url}: {snippet}")
        self.status = status
        self.body = body or ""


class WallexClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 15.0, retries: int = 2):
        self.base = base_url.rstrip("/")
        self.api_key = api_key or None
        self.timeout = timeout
        self.retries = retries
        self._session = requests.Session()
        self._last_get = 0.0
        self._min_interval = 0.25  # be polite to the public API

    # ------------------------------------------------------------------
    def _headers(self) -> dict:
        # NOTE: the key is only attached to private requests, never logged.
        return {"x-api-key": self.api_key} if self.api_key else {}

    def _get(self, path: str, params: dict | None = None, private: bool = False) -> Any:
        url = f"{self.base}{path}"
        wait = self._min_interval - (time.monotonic() - self._last_get)
        if wait > 0:
            time.sleep(wait)
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self._last_get = time.monotonic()
                r = self._session.get(
                    url,
                    params=params,
                    headers=self._headers() if private else {},
                    timeout=self.timeout,
                )
                if r.status_code >= 500 and attempt < self.retries:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                if r.status_code >= 400:
                    raise WallexApiError(r.status_code, r.text, url)
                return r.json()
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < self.retries:
                    time.sleep(0.8 * (attempt + 1))
        raise WallexApiError(0, f"connection failed: {type(last_exc).__name__}", url)

    def _private_request(self, method: str, path: str, json_body: dict | None = None, params: dict | None = None) -> Any:
        if not self.api_key:
            raise PermissionError("WALLEX_API_KEY is not set — private endpoint unavailable")
        url = f"{self.base}{path}"
        r = self._session.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=self._headers(),
            timeout=self.timeout,
        )
        if r.status_code >= 400:
            # body may echo account data — keep only the first short, redacted chunk
            raise WallexApiError(r.status_code, r.text[:300], url)
        return r.json()

    # ------------------------------------------------------------------ public (VERIFIED)
    def markets(self) -> dict:
        data = self._get("/v1/markets")
        return (data.get("result") or {}).get("symbols") or {}

    def market(self, symbol: str) -> dict:
        symbols = self.markets()
        if symbol not in symbols:
            raise KeyError(f"unknown symbol {symbol!r} — see /v1/markets")
        return symbols[symbol]

    def depth(self, symbol: str) -> dict:
        data = self._get("/v1/depth", params={"symbol": symbol})
        return data.get("result") or {}

    def best_prices(self, symbol: str) -> tuple[float | None, float | None]:
        """(best_bid, best_ask) from the order book."""
        book = self.depth(symbol)
        bid = ask = None
        if book.get("bid"):
            bid = float(book["bid"][0]["price"])
        if book.get("ask"):
            ask = float(book["ask"][0]["price"])
        return bid, ask

    def candles(self, symbol: str, resolution: str, count: int) -> list[dict]:
        """Return the last `count` candles as dicts: ts, open, high, low, close, volume."""
        import datetime as _dt

        now = int(_dt.datetime.now(_dt.timezone.utc).timestamp())
        span = count * int(resolution) * 60
        data = self._get(
            "/v1/udf/history",
            params={"symbol": symbol, "resolution": resolution, "from": now - span, "to": now},
        )
        if data.get("s") != "ok" or not data.get("t"):
            return []

        def num(x: Any) -> float | None:
            if x is None:
                return None
            try:
                return float(x)  # Wallex UDF returns numeric fields as strings
            except (TypeError, ValueError):
                return None

        out = []
        for i in range(len(data["t"])):
            out.append(
                {
                    "ts": data["t"][i],
                    "open": num(data.get("o", [None] * len(data["t"]))[i]),
                    "high": num(data.get("h", [None] * len(data["t"]))[i]),
                    "low": num(data.get("l", [None] * len(data["t"]))[i]),
                    "close": num(data.get("c", [None] * len(data["t"]))[i]),
                    "volume": num(data.get("v", [None] * len(data["t"]))[i]),
                }
            )
        return out[-count:]

    # ------------------------------------------------------------------ private (UNVERIFIED — verify with scripts/check_api.py --private)
    def balances(self) -> dict:
        return self._private_request("GET", "/v1/account/balances")

    def open_orders(self, symbol: str | None = None) -> dict:
        params = {"symbol": symbol} if symbol else None
        return self._private_request("GET", "/v1/account/orders", params=params)

    def place_order(self, symbol: str, side: str, order_type: str, quantity: float | None = None,
                    quote_quantity: float | None = None, price: float | None = None) -> dict:
        body: dict[str, Any] = {"symbol": symbol, "type": order_type, "side": side}
        if price is not None:
            body["price"] = price
        if quantity is not None:
            body["quantity"] = quantity
        if quote_quantity is not None:
            body["quoteQuantity"] = quote_quantity
        log.info("placing order %s %s type=%s qty=%s quote=%s (key=%s)",
                 side, symbol, order_type, quantity, quote_quantity, mask(self.api_key))
        return self._private_request("POST", "/v1/account/orders", json_body=body)

    def cancel_order(self, client_order_id: str) -> dict:
        return self._private_request("DELETE", f"/v1/account/orders/{client_order_id}")
