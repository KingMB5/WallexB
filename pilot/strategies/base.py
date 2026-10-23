from abc import ABC, abstractmethod


class Strategy(ABC):
    """Drop a new file in pilot/strategies/, subclass this, set `name`, add it to config.yaml.
    The strategy only FINDS setups. Sizing, limits and exits are handled by the engine."""
    name = ""
    defaults = {}

    def __init__(self, params):
        self.p = {**self.defaults, **params}
        self.timeframe = str(self.p.get("timeframe", "60"))

    @abstractmethod
    def scan(self, symbol, candles):
        """candles: closed candles, oldest->newest. Return a Signal or None."""
