#!/usr/bin/env python3
"""Wallex Adaptive Lab: read-only M15/M1 backtest and shadow scanner.

This tool never submits orders. It only calls Wallex market-history endpoints.
It is a research prototype, not evidence of profitability.
"""
from __future__ import annotations
import argparse, json, math, statistics, sys, time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import requests
    import yaml
except ImportError as exc:
    print(f"Missing dependency: {exc}. Install with: python -m pip install requests PyYAML", file=sys.stderr)
    raise SystemExit(2)

@dataclass(frozen=True)
class Candle:
    t: int; o: float; h: float; l: float; c: float; v: float

def utc(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()

def load_config(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg.get("wallex"), dict):
        raise ValueError("config.yaml must contain a 'wallex' mapping")
    return cfg

class HistoryClient:
    def __init__(self, cfg: dict):
        w = cfg["wallex"]
        self.base = str(w.get("base_url", "https://api.wallex.ir")).rstrip("/")
        paths = w.get("paths", {}) or {}
        self.path = paths.get("history", "/v1/udf/history")
        self.timeout = 20
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Wallex-Adaptive-Lab/0.1 read-only research"})

    def fetch_range(self, symbol: str, resolution: str, start: int, end: int) -> list[Candle]:
        url = self.base + self.path
        r = self.session.get(url, params={"symbol": symbol, "resolution": resolution, "from": start, "to": end}, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        # Wallex UDF may return {result:{...}} or direct UDF payload.
        if isinstance(data, dict) and isinstance(data.get("result"), dict):
            data = data["result"]
        if not isinstance(data, dict) or data.get("s") != "ok":
            raise RuntimeError(f"History rejected symbol={symbol} resolution={resolution}: {str(data)[:240]}")
        fields = [data.get(k, []) for k in ("t", "o", "h", "l", "c", "v")]
        if not all(isinstance(x, list) for x in fields):
            raise RuntimeError("Unexpected UDF response: expected t/o/h/l/c/v arrays")
        n = min(map(len, fields)) if fields else 0
        out = []
        for i in range(n):
            try:
                ts = int(fields[0][i])
                if start <= ts < end:
                    vals = [float(fields[j][i]) for j in range(1, 6)]
                    o, h, l, c, v = vals
                    if all(math.isfinite(x) for x in vals) and min(o,h,l,c) > 0 and h >= max(o,c,l) and l <= min(o,c,h) and v >= 0:
                        out.append(Candle(ts,o,h,l,c,v))
            except (TypeError, ValueError, OverflowError):
                continue
        return out

    def fetch(self, symbol: str, resolution: str, seconds: int, days: int) -> list[Candle]:
        end = int(time.time())
        start = end - days * 86400
        # Small chunks avoid silently trusting APIs that cap rows or ignore long ranges.
        chunk = 86400 if resolution == "1" else 7 * 86400
        rows: dict[int, Candle] = {}
        cursor = start
        while cursor < end:
            nxt = min(end, cursor + chunk)
            batch = self.fetch_range(symbol, resolution, cursor, nxt)
            for c in batch:
                rows[c.t] = c
            cursor = nxt
            time.sleep(0.08)
        candles = [rows[k] for k in sorted(rows)]
        # Keep only fully closed candles and verify API actually honors the requested interval.
        now = int(time.time())
        candles = [c for c in candles if c.t + seconds <= now]
        if len(candles) < 10:
            raise RuntimeError(f"Only {len(candles)} valid closed candles for {symbol} resolution={resolution}")
        deltas = [b.t-a.t for a,b in zip(candles, candles[1:])]
        exact = sum(1 for d in deltas if d == seconds)
        ratio = exact / len(deltas) if deltas else 0
        print(f"DATA {symbol} TF={resolution}: candles={len(candles)}, exact_interval_ratio={ratio:.1%}, first={utc(candles[0].t)}, last={utc(candles[-1].t)}")
        if ratio < 0.75:
            raise RuntimeError(f"Data interval validation failed for {symbol} TF={resolution}: expected {seconds}s; do not backtest questionable candles")
        return candles

def aggregate_m15_from_m1(m1: list[Candle]) -> list[Candle]:
    """Build only complete UTC-aligned 15m candles from verified M1 candles."""
    buckets: dict[int, list[Candle]] = {}
    for c in m1:
        start = (c.t // 900) * 900
        buckets.setdefault(start, []).append(c)
    out = []
    for start in sorted(buckets):
        group = sorted(buckets[start], key=lambda x: x.t)
        # Never fill gaps or synthesize missing minute bars.
        if len(group) != 15 or [x.t for x in group] != [start + k*60 for k in range(15)]:
            continue
        out.append(Candle(start, group[0].o, max(x.h for x in group), min(x.l for x in group), group[-1].c, sum(x.v for x in group)))
    if len(out) < 56:
        raise RuntimeError(f"Only {len(out)} complete M15 bars could be aggregated from M1; need at least 56")
    print(f"DATA derived M15 from M1: candles={len(out)}, only complete 15-bar UTC buckets retained")
    return out

def ema(values: list[float], period: int) -> list[float]:
    if not values: return []
    alpha = 2.0 / (period + 1)
    out = [values[0]]
    for x in values[1:]: out.append(alpha*x + (1-alpha)*out[-1])
    return out

def atr(cs: list[Candle], period: int = 14) -> list[float]:
    trs=[]
    for i,c in enumerate(cs):
        prev = cs[i-1].c if i else c.c
        trs.append(max(c.h-c.l, abs(c.h-prev), abs(c.l-prev)))
    return ema(trs, period)

def percentile_median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0

def regime_at(m15: list[Candle], i: int) -> str:
    if i < 55: return "unknown"
    closes=[c.c for c in m15[:i+1]]
    e20, e50 = ema(closes,20), ema(closes,50)
    aa=atr(m15[:i+1],14)
    c=m15[i]
    slope=e20[i]-e20[i-4]
    if e20[i] > e50[i] and slope > 0:
        return "trend_up"
    if aa[i] > 0 and abs(e20[i]-e50[i]) <= 0.5*aa[i] and abs(slope) <= 0.1*aa[i]:
        return "range"
    # A breakout is recognized only on a closed M15 candle and prior bars only.
    prior=m15[i-20:i]
    if len(prior)==20 and aa[i] > 0:
        prior_high=max(x.h for x in prior)
        med=percentile_median([x.v for x in prior])
        if c.c >= prior_high + 0.1*aa[i] and med > 0 and c.v >= 1.5*med:
            return "breakout"
    return "neutral"

SIG_REJECTS = __import__('collections').Counter()
RISK_PCTS = []
RISK_BUDGET_FRACTION = 0.08  # target 8% account risk; spot exposure capped at 100%

def make_signal(m15: list[Candle], m1: list[Candle], i15: int, i1: int, fee_pct: float, slip_pct: float) -> dict | None:
    # Decisions use only candles whose close timestamp is <= the M1 decision close.
    c1=m1[i1]
    if i1 < 30 or i15 < 55: SIG_REJECTS["insufficient_history"] += 1; return None
    prev1=m1[i1-1]
    # M1 confirmation: bullish candle closes above previous candle close.
    regime=regime_at(m15, i15)
    c15=m15[i15]
    a15=atr(m15[:i15+1],14)[-1]
    if a15 <= 0: SIG_REJECTS["atr_m15"] += 1; return None
    # M1 structure stop; no future bars are used.
    a1=atr(m1[:i1+1],14)[-1]
    if a1 <= 0: SIG_REJECTS["atr_m1"] += 1; return None
    structural_low=min(x.l for x in m1[i1-10:i1+1])
    stop=structural_low - 0.2*a1
    entry=c1.c
    risk=entry-stop
    risk_pct=risk/entry*100 if entry else 999
    if risk > 0:
        RISK_PCTS.append(risk_pct)
    if risk <= 0: SIG_REJECTS["risk_filter"] += 1; return None
    # A conservative estimated round-trip cost is applied to minimum net R:R.
    round_cost=2*(fee_pct+slip_pct)/100
    reward=1.8*risk
    net_rr=(reward-round_cost*entry)/(risk+round_cost*entry)
    if net_rr <= 0:
        SIG_REJECTS["net_rr_filter"] += 1
        return None
    setup=None
    if regime == "trend_up" and c15.c > 0:
        setup="trend_pullback_m15_m1"
    elif regime == "range":
        window=m15[max(0,i15-19):i15+1]
        lo=min(x.l for x in window); hi=max(x.h for x in window)
        if hi > lo and c15.c <= lo + 0.25*(hi-lo): setup="range_bottom_bounce_m1"
    elif regime == "breakout":
        # Do not chase: only enter if M1 close remains within 0.5 M15 ATR of breakout level.
        prior=m15[i15-20:i15]
        if prior and c1.c <= max(x.h for x in prior)+0.5*a15: setup="breakout_confirmation_m1"
    if not setup: SIG_REJECTS["setup_not_matched"] += 1; return None
    return {"setup":setup,"regime":regime,"entry":entry,"stop":stop,"target":entry+1.8*risk,"risk_pct":risk_pct,"net_rr_est":net_rr,"signal_time":c1.t+60}

def run_backtest(cfg: dict, args: argparse.Namespace) -> int:
    client=HistoryClient(cfg)
    fee_pct=args.fee_pct
    slip_pct=args.slippage_pct
    trades=[]; per_symbol={}
    for symbol in args.symbols:
        print(f"\n=== BACKTEST {symbol} | M15 + M1 | {args.days} days ===")
        m1=client.fetch(symbol,"1",60,args.days)
        m15=aggregate_m15_from_m1(m1)
        # Only complete candles; use close-time availability to prevent lookahead.
        j15=0; equity=1.0; peak=1.0; max_dd=0.0; position=None; symbol_trades=[]
        for i,c in enumerate(m1):
            decision_close=c.t+60
            while j15+1 < len(m15) and m15[j15+1].t+900 <= decision_close:
                j15 += 1
            if j15 < 55: continue
            if position:
                # Stop is checked before target when both are touched within one candle (conservative).
                exit_price=None; reason=None
                if c.l <= position["stop"]:
                    # A gap below the stop can produce a worse fill than the stop price.
                    raw_exit=min(position["stop"],c.o)
                    exit_price=raw_exit*(1-slip_pct/100); reason="stop"
                elif c.h >= position["target"]:
                    # Simplified limit fill at target; no favorable price improvement assumed.
                    exit_price=position["target"]; reason="target"
                elif decision_close-position["entry_time"] >= 12*3600:
                    # Market exit: apply adverse sell-side slippage.
                    exit_price=c.c*(1-slip_pct/100); reason="time_exit"
                if exit_price is not None:
                    gross=(exit_price-position["entry"])/position["entry"]
                    # Entry slippage is already embedded in entry; exit slippage is embedded
                    # in exit_price. Subtract trading fees only to avoid double-counting slippage.
                    cost=2*fee_pct/100
                    net=(gross-cost)*position["exposure_fraction"]
                    equity *= max(0.0,1+net)
                    trade={**position,"exit_time":decision_close,"exit":exit_price,"exit_reason":reason,"gross_return_pct":gross*100,"net_return_pct":net*100,"equity_after":equity}
                    trades.append(trade); symbol_trades.append(trade)
                    position=None
                    peak=max(peak,equity); max_dd=max(max_dd,(peak-equity)/peak if peak else 0)
                continue
            sig=make_signal(m15,m1,j15,i,fee_pct,slip_pct)
            if not sig or i+1>=len(m1): continue
            # Enter at next candle open to avoid filling at the signal candle's close.
            nxt=m1[i+1]
            entry=nxt.o*(1+slip_pct/100)
            risk=entry-sig["stop"]
            if risk <= 0: continue

            # Recheck net reward/risk using the actual next-candle entry.
            # Entry slippage is already included in entry; estimate one exit slippage plus two fees.
            round_cost=(2*fee_pct+slip_pct)/100
            actual_net_rr=(1.8*risk-round_cost*entry)/(risk+round_cost*entry)
            if actual_net_rr <= 0:
                SIG_REJECTS["entry_net_rr_filter"] += 1
                continue

            risk_fraction=risk/entry if entry > 0 else 0.0
            exposure_fraction=min(RISK_BUDGET_FRACTION/risk_fraction,1.0) if risk_fraction > 0 else 0.0
            actual_risk_pct=exposure_fraction*risk_fraction*100
            position={**sig,"symbol":symbol,"signal_time":sig["signal_time"],"entry_time":nxt.t,"entry":entry,"stop":sig["stop"],"target":entry+1.8*risk,"exposure_fraction":exposure_fraction,"risk_budget_pct":8.0,"actual_risk_pct":actual_risk_pct}
        per_symbol[symbol]={"trades":len(symbol_trades),"ending_equity_x":equity,"max_drawdown_pct":max_dd*100}
        if position: print("NOTE: final open position excluded from closed-trade stats")
    _rs = sorted(RISK_PCTS)
    def _pct(q):
        return round(_rs[min(len(_rs)-1, int((len(_rs)-1)*q))], 4) if _rs else None
    print("RISK_PCT_STATS:", json.dumps({
        "count": len(_rs),
        "min": _pct(0),
        "median": _pct(0.5),
        "p90": _pct(0.9),
        "max": _pct(1)
    }, sort_keys=True))
    print("SIGNAL_REJECTIONS:", json.dumps(dict(SIG_REJECTS), sort_keys=True))
    closed=trades
    wins=[t for t in closed if t["net_return_pct"]>0]
    losses=[t for t in closed if t["net_return_pct"]<=0]
    gross_profit=sum(max(0,t["net_return_pct"]) for t in closed)
    gross_loss=abs(sum(min(0,t["net_return_pct"]) for t in closed))
    pf=gross_profit/gross_loss if gross_loss else (float("inf") if gross_profit else 0)
    avg=sum(t["net_return_pct"] for t in closed)/len(closed) if closed else 0
    print("\n===== RESULTS (closed trades only) =====")
    print(json.dumps({"mode":"BACKTEST_READ_ONLY","orders_placed":False,"symbols":per_symbol,"trades":len(closed),"win_rate_pct":100*len(wins)/len(closed) if closed else 0,"net_expectancy_pct_per_trade":avg,"profit_factor":pf,"sum_positive_trade_returns_pct":gross_profit,"sum_negative_trade_returns_pct":gross_loss,"fees_pct_per_side":fee_pct,"slippage_pct_per_side":slip_pct,"warning":"Research prototype; simplified position sizing and equity accounting. Not a profitability claim."},indent=2))
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text("\n".join(json.dumps(t,ensure_ascii=False) for t in trades)+("\n" if trades else ""),encoding="utf-8")
    print(f"Saved closed trades JSONL: {out.resolve()}")
    return 0

def run_shadow(cfg: dict, args: argparse.Namespace) -> int:
    client=HistoryClient(cfg)
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("a",encoding="utf-8") as f:
        for symbol in args.symbols:
            try:
                m1=client.fetch(symbol,"1",60,3)
                m15=aggregate_m15_from_m1(m1)
                now=int(time.time())
                closed1=[c for c in m1 if c.t+60<=now]
                closed15=[c for c in m15 if c.t+900<=now]
                if len(closed1)<31 or len(closed15)<56: raise RuntimeError("insufficient closed candles")
                decision=closed1[-1]
                available=[c for c in closed15 if c.t+900 <= decision.t+60]
                if not available: raise RuntimeError("no M15 candle available as of latest M1 close")
                i15=len(available)-1
                sig=make_signal(available,closed1,len(available)-1,len(closed1)-1,args.fee_pct,args.slippage_pct)
                record={"logged_at":utc(now),"symbol":symbol,"mode":"SHADOW_READ_ONLY","orders_placed":False,"spread_pct":None,"spread_status":"UNAVAILABLE_FROM_THIS_HISTORY_ENDPOINT","signal":sig,"note":"Signal candidate only; not an order or trade approval."}
                f.write(json.dumps(record,ensure_ascii=False)+"\n"); f.flush()
                print(json.dumps(record,ensure_ascii=False))
            except Exception as e:
                record={"logged_at":utc(int(time.time())),"symbol":symbol,"mode":"SHADOW_READ_ONLY","orders_placed":False,"error":str(e)}
                f.write(json.dumps(record,ensure_ascii=False)+"\n"); f.flush(); print(json.dumps(record,ensure_ascii=False))
    print(f"Shadow log: {out.resolve()}")
    return 0

def main() -> int:
    p=argparse.ArgumentParser(description="Wallex Adaptive Lab (read-only, M15+M1)", allow_abbrev=False)
    p.add_argument("--config",default="config.yaml")
    p.add_argument("--symbols",nargs="+",choices=["USDTTMN"],default=["USDTTMN"])
    p.add_argument("--days",type=int,default=14)
    p.add_argument("--fee-pct",type=float,default=0.30,help="fee per side in percent; default 0.30 percent for TMN markets")
    p.add_argument("--slippage-pct",type=float,default=0.05,help="assumed slippage per side in percent")
    p.add_argument("--output",default="reports/adaptive_trades.jsonl")
    sub=p.add_subparsers(dest="command",required=True)
    sub.add_parser("backtest",help="Historical read-only backtest")
    sh=sub.add_parser("shadow",help="One-pass read-only shadow scan; no orders")
    sh.add_argument("--config", default=argparse.SUPPRESS)
    sh.add_argument("--output",default="reports/shadow.jsonl")
    args=p.parse_args()
    if args.days < 2 or args.days > 365: p.error("--days must be between 2 and 365")
    if args.fee_pct < 0 or args.slippage_pct < 0: p.error("fee/slippage cannot be negative")
    try:
        cfg=load_config(args.config)
        return run_backtest(cfg,args) if args.command=="backtest" else run_shadow(cfg,args)
    except KeyboardInterrupt:
        print("Interrupted; no orders were submitted.",file=sys.stderr); return 130
    except Exception as e:
        print(f"ERROR: {e}",file=sys.stderr); return 1

if __name__=="__main__": raise SystemExit(main())




