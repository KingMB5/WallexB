"""Standalone, long-only Wallex spot strategy scaffold. Closed candles only; never places orders."""
from dataclasses import dataclass, asdict
from enum import Enum
from math import isfinite
from statistics import median
from typing import Any, Mapping, Optional, Sequence

class Regime(str, Enum):
    TREND="trend"
    RANGE="range"
    BREAKOUT="breakout"
    NO_TRADE="no_trade"

class SetupType(str, Enum):
    TREND_PULLBACK="trend_pullback"
    RANGE_BOUNCE="range_bounce"
    BREAKOUT_RETEST="breakout_retest"

@dataclass(frozen=True)
class StrategyConfig:
    ema_fast:int=20
    ema_slow:int=50
    ema_slope_bars:int=4
    atr_period:int=14
    breakout_lookback:int=20
    breakout_atr_buffer:float=0.10
    breakout_volume_multiple:float=1.50
    range_lookback:int=20
    range_ema_gap_atr_max:float=0.50
    range_slope_atr_max:float=0.10
    range_bottom_fraction:float=0.20
    pullback_level_atr:float=0.25
    stop_buffer_atr:float=0.20
    min_stop_pct:float=0.003
    max_stop_pct:float=0.02
    min_net_rr:float=1.50
    m1_trigger_lookback:int=3
    setup_expiry_m1_bars:int=5
    max_entry_extension_atr:float=1.0
    max_spread_pct:float=0.0015
    max_holding_hours:int=12
    base_risk_pct:float=0.0025
    hard_risk_cap_pct:float=0.005
    daily_loss_limit_pct:float=0.02
    max_positions:int=3
    max_total_exposure_pct:float=0.30
    min_m15_candles:int=300
    min_m5_candles:int=100
    min_m1_candles:int=100

@dataclass(frozen=True)
class Signal:
    symbol:str
    setup:SetupType
    regime:Regime
    entry:float
    stop:float
    target:float
    risk_per_unit:float
    reward_risk_gross:float
    reason:str
    timestamp:Any=None
    def to_dict(self):
        d=asdict(self); d["setup"]=self.setup.value; d["regime"]=self.regime.value
        return d

def valid_candles(cs:Sequence[Mapping[str,Any]])->bool:
    if not cs: return False
    for c in cs:
        try: o,h,l,cl,v=(float(c[k]) for k in ("open","high","low","close","volume"))
        except (KeyError,TypeError,ValueError): return False
        if not all(isfinite(x) for x in (o,h,l,cl,v)) or h<max(o,l,cl) or l>min(o,h,cl) or v<0: return False
    return True

def ema(xs:Sequence[float], n:int)->list[Optional[float]]:
    out=[None]*len(xs)
    if n<1: raise ValueError("period must be >= 1")
    if len(xs)<n: return out
    prev=sum(xs[:n])/n; out[n-1]=prev; alpha=2/(n+1)
    for i in range(n,len(xs)):
        prev=alpha*xs[i]+(1-alpha)*prev; out[i]=prev
    return out

def atr(cs:Sequence[Mapping[str,Any]], n:int=14)->list[Optional[float]]:
    trs=[]; prev=None
    for c in cs:
        h,l,cl=float(c["high"]),float(c["low"]),float(c["close"])
        trs.append(h-l if prev is None else max(h-l,abs(h-prev),abs(l-prev)))
        prev=cl
    out=[None]*len(trs)
    for i in range(n-1,len(trs)): out[i]=sum(trs[i-n+1:i+1])/n
    return out

def bullish_structure(cs:Sequence[Mapping[str,Any]], window:int=30)->bool:
    xs=cs[-window:]
    if len(xs)<12:return False
    highs=[float(c["high"]) for c in xs]; lows=[float(c["low"]) for c in xs]
    ph=[];pl=[]
    for i in range(2,len(xs)-2):
        if highs[i]>max(highs[i-2:i]) and highs[i]>=max(highs[i+1:i+3]): ph.append(highs[i])
        if lows[i]<min(lows[i-2:i]) and lows[i]<=min(lows[i+1:i+3]): pl.append(lows[i])
    return len(ph)>=2 and len(pl)>=2 and ph[-1]>ph[-2] and pl[-1]>pl[-2]

def classify_regime(m15:Sequence[Mapping[str,Any]], cfg:StrategyConfig=StrategyConfig())->Regime:
    if len(m15)<max(cfg.min_m15_candles,cfg.ema_slow+cfg.ema_slope_bars+2) or not valid_candles(m15):
        return Regime.NO_TRADE
    closes=[float(c["close"]) for c in m15]; ef=ema(closes,cfg.ema_fast); es=ema(closes,cfg.ema_slow); aa=atr(m15,cfg.atr_period)
    i=len(m15)-1; a=aa[i]
    if a is None or a<=0 or ef[i] is None or es[i] is None or ef[i-cfg.ema_slope_bars] is None:return Regime.NO_TRADE
    slope=ef[i]-ef[i-cfg.ema_slope_bars]
    prior=m15[-cfg.breakout_lookback-1:-1]
    vol=median([float(c["volume"]) for c in prior]) if prior else 0
    prior_high=max(float(c["high"]) for c in prior) if prior else float("inf")
    last=m15[-1]
    if float(last["close"])>prior_high+cfg.breakout_atr_buffer*a and vol>0 and float(last["volume"])>=cfg.breakout_volume_multiple*vol:
        return Regime.BREAKOUT
    gap=abs(ef[i]-es[i])/a; slope_atr=abs(slope)/a
    if gap<=cfg.range_ema_gap_atr_max and slope_atr<=cfg.range_slope_atr_max:
        rg=m15[-cfg.range_lookback:]; lo=min(float(c["low"]) for c in rg); hi=max(float(c["high"]) for c in rg)
        if hi>lo and float(last["close"])<=lo+cfg.range_bottom_fraction*(hi-lo):return Regime.RANGE
    if ef[i]>es[i] and slope>0 and bullish_structure(m15) and float(last["close"])<=ef[i]+1.5*a:return Regime.TREND
    return Regime.NO_TRADE

def _m1_trigger(m1:Sequence[Mapping[str,Any]], n:int)->bool:
    return len(m1)>=n+1 and valid_candles(m1) and float(m1[-1]["close"])>max(float(c["high"]) for c in m1[-n-1:-1])

def generate_signal(symbol:str,m15,m5,m1,*,spread_pct:float,estimated_round_trip_cost_pct:float,cfg:StrategyConfig=StrategyConfig())->Optional[Signal]:
    """Return a candidate only. Caller must enforce stale-data, depth, risk, orders, and 12h exits."""
    if len(m15)<cfg.min_m15_candles or len(m5)<cfg.min_m5_candles or len(m1)<cfg.min_m1_candles:return None
    if not all(valid_candles(x) for x in (m15,m5,m1)):return None
    if not isfinite(spread_pct) or spread_pct<0 or spread_pct>cfg.max_spread_pct:return None
    if not isfinite(estimated_round_trip_cost_pct) or estimated_round_trip_cost_pct<0:return None
    regime=classify_regime(m15,cfg)
    if regime==Regime.NO_TRADE or not _m1_trigger(m1,cfg.m1_trigger_lookback):return None
    aa=atr(m5,cfg.atr_period)
    if aa[-1] is None or aa[-1]<=0:return None
    a=aa[-1]; entry=float(m5[-1]["close"]); last1=float(m1[-1]["close"])
    a1=atr(m1,cfg.atr_period)[-1]
    if a1 and entry-last1>cfg.max_entry_extension_atr*a1:return None
    recent=m5[-20:]; structural_low=min(float(c["low"]) for c in recent)
    resistance=max(float(c["high"]) for c in recent)
    if regime==Regime.TREND:
        ef=ema([float(c["close"]) for c in m15],cfg.ema_fast)
        if ef[-1] is None or abs(entry-ef[-1])>cfg.pullback_level_atr*a:return None
        setup=SetupType.TREND_PULLBACK
    elif regime==Regime.RANGE:
        rg=m15[-cfg.range_lookback:]; lo=min(float(c["low"]) for c in rg); hi=max(float(c["high"]) for c in rg)
        if hi<=lo or entry>lo+cfg.range_bottom_fraction*(hi-lo):return None
        setup=SetupType.RANGE_BOUNCE
    else:
        prior=m15[-cfg.breakout_lookback-1:-1]
        if not prior or entry<max(float(c["high"]) for c in prior):return None
        setup=SetupType.BREAKOUT_RETEST
    stop=structural_low-cfg.stop_buffer_atr*a
    stop_pct=(entry-stop)/entry if entry>0 else 1
    if stop>=entry or not cfg.min_stop_pct<=stop_pct<=cfg.max_stop_pct:return None
    risk=entry-stop
    # Target is at least min R; structural resistance is a minimum target only if farther away.
    target=max(entry+risk*cfg.min_net_rr,resistance if resistance>entry else 0)
    net_rr=(target-entry-entry*estimated_round_trip_cost_pct)/(risk+entry*estimated_round_trip_cost_pct)
    if net_rr<cfg.min_net_rr:return None
    return Signal(symbol,setup,regime,entry,stop,target,risk,(target-entry)/risk,
                  f"{setup.value}; closed M1 trigger; estimated net RR={net_rr:.2f}",m1[-1].get("timestamp"))

def risk_budget(equity:float,cfg:StrategyConfig=StrategyConfig())->float:
    if not isfinite(equity) or equity<=0:return 0.0
    return equity*min(cfg.base_risk_pct,cfg.hard_risk_cap_pct)

def position_quantity(equity:float,entry:float,stop:float,*,available_quote_balance:float,estimated_cost_per_unit:float=0.0,cfg:StrategyConfig=StrategyConfig())->float:
    if min(equity,entry,available_quote_balance)<=0 or stop<=0 or stop>=entry:return 0.0
    unit_risk=entry-stop+max(0.0,estimated_cost_per_unit)
    if unit_risk<=0:return 0.0
    return max(0.0,min(risk_budget(equity,cfg)/unit_risk,available_quote_balance/entry,equity*cfg.max_total_exposure_pct/entry))
