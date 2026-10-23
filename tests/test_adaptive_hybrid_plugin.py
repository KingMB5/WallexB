import unittest
from dataclasses import dataclass

from pilot.strategies.adaptive_hybrid import AdaptiveHybrid


@dataclass
class Candle:
    t: int
    o: float
    h: float
    l: float
    c: float
    v: float


class AdaptivePluginTests(unittest.TestCase):
    def test_strategy_registers_with_expected_name(self):
        strategy = AdaptiveHybrid({})
        self.assertEqual(strategy.name, "adaptive_hybrid")

    def test_single_timeframe_scan_never_fabricates_signal(self):
        strategy = AdaptiveHybrid({})
        self.assertIsNone(strategy.scan("BTCTMN", []))

    def test_invalid_spread_fails_closed(self):
        strategy = AdaptiveHybrid({})
        self.assertIsNone(
            strategy.generate_mtf("BTCTMN", [], [], [], float("nan"), 0.01)
        )


if __name__ == "__main__":
    unittest.main()
