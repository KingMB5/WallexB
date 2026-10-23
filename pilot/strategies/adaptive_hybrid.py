from dataclasses import replace
from math import isfinite

from .base import Strategy
from ..models import Signal as EngineSignal
from strategy_v1_draft.adaptive_hybrid_strategy import (
    Regime,
    SetupType,
    StrategyConfig,
    atr,
    classify_regime,
    ema,
    generate_signal as draft_generate_signal,
    valid_candles,
)


class AdaptiveHybrid(Strategy):
    """Multi-timeframe, long-only candidate generator. Never places orders."""
    name = "adaptive_hybrid"
    defaults = {
        "timeframe": "15",
        "min_m15_candles": 300,
        "min_m5_candles": 100,
        "min_m1_candles": 100,
    }

    def scan(self, symbol, candles):
        # Engine must call generate_mtf() with all three timeframes.
        return None

    @staticmethod
    def _map(candles):
        return [
            {
                "timestamp": c.t,
                "open": float(c.o),
                "high": float(c.h),
                "low": float(c.l),
                "close": float(c.c),
                "volume": float(c.v),
            }
            for c in candles
        ]

    def generate_mtf(self, symbol, m15, m5, m1, spread_pct, round_trip_cost_pct):
        cfg = StrategyConfig(
            min_m15_candles=int(self.p.get("min_m15_candles", 300)),
            min_m5_candles=int(self.p.get("min_m5_candles", 100)),
            min_m1_candles=int(self.p.get("min_m1_candles", 100)),
        )
        a15, a5, a1 = self._map(m15), self._map(m5), self._map(m1)

        if not (valid_candles(a15) and valid_candles(a5) and valid_candles(a1)):
            return None
        if len(a15) < cfg.min_m15_candles or len(a5) < cfg.min_m5_candles or len(a1) < cfg.min_m1_candles:
            return None

        # Closed-candle freshness guard: reject stale market data.
        if m15[-1].t + 1800 < __import__("time").time():
            return None
        if m5[-1].t + 600 < __import__("time").time():
            return None
        if m1[-1].t + 120 < __import__("time").time():
            return None

        if not isfinite(spread_pct) or spread_pct < 0 or spread_pct > cfg.max_spread_pct:
            return None
        if not isfinite(round_trip_cost_pct) or round_trip_cost_pct < 0:
            return None

        regime = classify_regime(a15, cfg)
        if regime == Regime.NO_TRADE:
            return None

        # The M1 trigger must be a closed candle and cannot be chased far
        # above its trigger close.
        candidate = draft_generate_signal(
            symbol, a15, a5, a1,
            spread_pct=spread_pct,
            estimated_round_trip_cost_pct=round_trip_cost_pct,
            cfg=cfg,
        )
        if candidate is None:
            return None

        last5 = a5[-1]
        prev5 = a5[-2]
        atr5 = atr(a5, cfg.atr_period)[-1]
        if atr5 is None or atr5 <= 0:
            return None

        if candidate.setup == SetupType.TREND_PULLBACK:
            fast = ema([c["close"] for c in a15], cfg.ema_fast)[-1]
            # Require an actual M5 pullback/touch near the M15 EMA level,
            # not merely a close near it.
            if fast is None or abs(last5["low"] - fast) > cfg.pullback_level_atr * atr5:
                return None
            if last5["close"] <= last5["open"]:
                return None

        elif candidate.setup == SetupType.RANGE_BOUNCE:
            rg = a15[-cfg.range_lookback:]
            floor = min(c["low"] for c in rg)
            height = max(c["high"] for c in rg) - floor
            if height <= 0:
                return None
            # Require observable rejection: M5 probes below the prior low
            # and closes bullish, or leaves a meaningful lower wick.
            lower_wick = min(last5["open"], last5["close"]) - last5["low"]
            body = abs(last5["close"] - last5["open"])
            rejection = (
                last5["close"] > last5["open"]
                and (
                    last5["low"] < prev5["low"]
                    or lower_wick >= max(body, atr5 * 0.1)
                )
            )
            if not rejection or last5["close"] <= floor:
                return None

        elif candidate.setup == SetupType.BREAKOUT_RETEST:
            prior = a15[-cfg.breakout_lookback-1:-1]
            if not prior:
                return None
            level = max(c["high"] for c in prior)
            # Require a retest/hold on M5; do not buy a breakout candle
            # that has already run away from the level.
            if last5["low"] > level + cfg.pullback_level_atr * atr5:
                return None
            if last5["close"] <= level:
                return None
            if last5["close"] - level > cfg.max_entry_extension_atr * atr5:
                return None

        return EngineSignal(
            symbol=symbol,
            setup=f"adaptive_hybrid:{candidate.setup.value}",
            entry=candidate.entry,
            stop=candidate.stop,
            take_profit=candidate.target,
            reason=candidate.reason,
            meta={
                "regime": candidate.regime.value,
                "spread_pct": spread_pct,
                "round_trip_cost_pct": round_trip_cost_pct,
                "max_holding_hours": cfg.max_holding_hours,
                "risk_pct": cfg.base_risk_pct,
                "max_risk_pct": cfg.hard_risk_cap_pct,
                "max_exposure_pct": cfg.max_total_exposure_pct,
                "daily_loss_limit_pct": cfg.daily_loss_limit_pct,
                "max_stop_pct": cfg.max_stop_pct,
            },
        )
