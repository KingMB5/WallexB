"""
indicators.py — pure-python technical indicators (no pandas, no numpy).

All functions take plain lists of floats and return lists of the same length
(leading values that need more history are None).
"""

from __future__ import annotations


def sma(values: list[float | None], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        if v is None:
            continue
        running += v
        if i >= period:
            prev = values[i - period]
            if prev is not None:
                running -= prev
        if i >= period - 1:
            out[i] = running / period
    return out


def rsi(values: list[float | None], period: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    out: list[float | None] = [None] * len(values)
    gains = losses = 0.0
    for i in range(1, len(values)):
        prev, cur = values[i - 1], values[i]
        if prev is None or cur is None:
            continue
        change = cur - prev
        gain, loss = max(change, 0.0), max(-change, 0.0)
        if i <= period:
            gains += gain
            losses += loss
            if i == period:
                avg_gain, avg_loss = gains / period, losses / period
                out[i] = _rsi_value(avg_gain, avg_loss)
        else:
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
            out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float | None:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
