import unittest
from adaptive_hybrid_strategy import StrategyConfig, Regime, ema, atr, risk_budget, position_quantity, classify_regime, valid_candles

def candles(n=350, start=100.0, step=0.15, volume=1000.0):
    out=[]; p=start
    for i in range(n):
        o=p; p+=step; c=p
        out.append({"timestamp":i,"open":o,"high":max(o,c)+0.15,"low":min(o,c)-0.15,"close":c,"volume":volume})
    return out

class Tests(unittest.TestCase):
    def test_ema(self):
        x=ema([1,2,3,4,5],3); self.assertIsNone(x[1]); self.assertAlmostEqual(x[2],2)
    def test_atr_positive(self): self.assertGreater(atr(candles(30))[-1],0)
    def test_risk_budget(self): self.assertAlmostEqual(risk_budget(1_000_000),2500)
    def test_quantity_limits(self):
        q=position_quantity(1_000_000,100,98,available_quote_balance=10_000)
        self.assertLessEqual(q*100,10_000); self.assertLessEqual(q*100,300_000)
    def test_short_history_no_trade(self): self.assertEqual(classify_regime(candles(100)),Regime.NO_TRADE)
    def test_invalid_candle_rejected(self):
        x=candles(); x[-1]["high"]=0; self.assertFalse(valid_candles(x)); self.assertEqual(classify_regime(x),Regime.NO_TRADE)
if __name__=="__main__": unittest.main(verbosity=2)
