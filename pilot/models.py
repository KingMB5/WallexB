from dataclasses import dataclass, field


@dataclass
class Candle:
    t: int
    o: float
    h: float
    l: float
    c: float
    v: float


@dataclass
class Signal:
    symbol: str
    setup: str
    entry: float
    stop: float
    take_profit: float
    reason: str
    meta: dict = field(default_factory=dict)
