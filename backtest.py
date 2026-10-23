import argparse
import csv
import os
import sys
import time
from pathlib import Path

from pilot.config import load_config
from pilot.models import Candle
from pilot.strategies import load_strategies
from pilot.wallex import Wallex, TF_SECONDS


def fetch_history(wx, symbol, tf, bars):
    """Fetch historical candles in bounded chunks; never accesses order endpoints."""
    sec = TF_SECONDS[tf]
    end = int(time.time())
    start = end - sec * (bars + 5)
    rows = {}

    while start < end:
        stop = min(end, start + sec * 200)
        result = wx._req(
            "GET",
            wx.paths["history"],
            params={
                "symbol": symbol,
                "resolution": tf,
                "from": start,
                "to": stop,
            },
        )

        if not isinstance(result, dict) or result.get("s") != "ok":
            raise RuntimeError(
                f"Historical data unavailable for {symbol}/{tf}: "
                f"{str(result)[:250]}"
            )

        arrays = [result.get(k, []) for k in ("t", "o", "h", "l", "c", "v")]
        if len({len(a) for a in arrays}) != 1:
            raise RuntimeError("Historical API returned inconsistent candle arrays")

        for t, o, h, l, c, v in zip(*arrays):
            candle = Candle(int(t), float(o), float(h), float(l), float(c), float(v))
            if candle.t + sec <= end:
                if not all(map(lambda x: x == x and abs(x) != float("inf"),
                               (candle.o, candle.h, candle.l, candle.c, candle.v))):
                    raise RuntimeError("Historical API returned non-finite OHLCV")
                if min(candle.o, candle.h, candle.l, candle.c) <= 0:
                    raise RuntimeError("Historical API returned non-positive prices")
                if candle.h < max(candle.o, candle.c, candle.l):
                    raise RuntimeError("Invalid candle high")
                if candle.l > min(candle.o, candle.c, candle.h):
                    raise RuntimeError("Invalid candle low")
                rows[candle.t] = candle

        if stop <= start:
            break
        start = stop

    candles = [rows[k] for k in sorted(rows)]
    if len(candles) > bars:
        candles = candles[-bars:]

    if len(candles) < 100:
        raise RuntimeError(
            f"Only {len(candles)} closed candles received. "
            "Need at least 100; reduce timeframe or check symbol/API."
        )

    gaps = sum(
        1 for a, b in zip(candles, candles[1:])
        if b.t - a.t > sec
    )
    print(f"Historical candles: {len(candles)} | gaps: {gaps}")
    print(f"From UTC epoch: {candles[0].t} | to: {candles[-1].t}")
    return candles


def backtest(candles, strategy, cfg, symbol, initial_cash, fee, slippage):
    risk_cfg = cfg["risk"]
    risk_fraction = float(risk_cfg["risk_per_trade"])
    max_exposure = float(risk_cfg["max_exposure"])
    min_order = float(risk_cfg.get("min_order_tmn", 0))
    rr = float(strategy.p.get("rr", 2.0))
    breakeven_r = float(risk_cfg.get("breakeven_r", 1.0))
    trail_r = float(risk_cfg.get("trail_r", 1.0))
    time_stop_bars = max(
        1, int(float(risk_cfg.get("time_stop_hours", 24)) * 3600
               / TF_SECONDS[strategy.timeframe])
    )

    cash = float(initial_cash)
    position = None
    pending = None
    trades = []
    equity_curve = []
    peak_equity = cash
    max_drawdown = 0.0

    def close_position(price, timestamp, reason):
        nonlocal cash, position
        p = position
        exit_fill = price * (1 - slippage)
        proceeds = p["qty"] * exit_fill * (1 - fee)
        cash += proceeds
        net_pnl = proceeds - p["cost"]
        risk_amount = p["qty"] * (p["entry"] - p["initial_stop"])
        trades.append({
            "symbol": symbol,
            "entry_time": p["entry_time"],
            "exit_time": timestamp,
            "entry": round(p["entry"], 10),
            "exit": round(exit_fill, 10),
            "qty": round(p["qty"], 10),
            "initial_stop": round(p["initial_stop"], 10),
            "exit_reason": reason,
            "pnl_net": round(net_pnl, 8),
            "R": round(net_pnl / risk_amount, 4) if risk_amount > 0 else 0,
            "fees_estimated": round(
                p["qty"] * p["entry"] * fee
                + p["qty"] * exit_fill * fee, 8
            ),
        })
        position = None

    for i, candle in enumerate(candles):
        was_open = position is not None

        # A signal from the previous closed candle can only fill at this bar's open.
        if position is None and pending is not None:
            sig = pending
            pending = None
            entry = candle.o * (1 + slippage)
            stop = float(sig.stop)

            # Do not enter if the next open has already invalidated the setup.
            if entry > stop and stop > 0:
                r = entry - stop
                target_distance = max(0.0, float(sig.take_profit) - float(sig.entry))
                equity_at_open = cash
                risk_budget = equity_at_open * risk_fraction
                qty_by_risk = risk_budget / (r + entry * fee + stop * fee)
                qty_by_exposure = equity_at_open * max_exposure / entry
                qty_by_cash = cash / (entry * (1 + fee))
                qty = min(qty_by_risk, qty_by_exposure, qty_by_cash)

                if qty > 0 and qty * entry >= min_order:
                    cost = qty * entry * (1 + fee)
                    cash -= cost
                    position = {
                        "entry": entry,
                        "initial_stop": stop,
                        "stop": stop,
                        "target": entry + target_distance if target_distance else entry + rr * r,
                        "r": r,
                        "qty": qty,
                        "cost": cost,
                        "entry_time": candle.t,
                        "bars_held": 0,
                        "highest": entry,
                    }

        if position is not None:
            p = position
            p["bars_held"] += 1

            # Conservative OHLC rule: if the old stop and a favorable trigger
            # are both touched in one candle, assume the stop was hit first.
            if candle.o <= p["stop"]:
                close_position(candle.o, candle.t, "stop_gap")
            elif candle.l <= p["stop"]:
                close_position(p["stop"], candle.t, "stop")
            else:
                high = max(p["highest"], candle.h)
                p["highest"] = high

                if high >= p["entry"] + breakeven_r * p["r"]:
                    p["stop"] = max(p["stop"], p["entry"] * (1 + 2 * fee))

                if high >= p["target"]:
                    p["stop"] = max(p["stop"], high - trail_r * p["r"])

                # If the updated trailing stop lies inside this candle's range,
                # conservatively assume high first, then retracement to the stop.
                if candle.l <= p["stop"]:
                    close_position(p["stop"], candle.t, "trailing_stop")
                elif p["bars_held"] >= time_stop_bars:
                    close_position(candle.c, candle.t, "time_stop")

        mark = cash
        if position is not None:
            mark += position["qty"] * candle.c
        peak_equity = max(peak_equity, mark)
        dd = (peak_equity - mark) / peak_equity if peak_equity else 0
        max_drawdown = max(max_drawdown, dd)
        equity_curve.append({
            "time": candle.t,
            "equity": mark,
            "drawdown_pct": dd * 100,
        })

        # Only create a signal from candles already closed. Fill on the next bar.
        if not was_open and position is None and pending is None and i < len(candles) - 1:
            history = candles[:i + 1]
            signal = strategy.scan(symbol, history)
            if signal is not None:
                pending = signal

    if position is not None:
        close_position(candles[-1].c, candles[-1].t, "end_of_test")

    pnls = [t["pnl_net"] for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [-x for x in pnls if x < 0]
    total = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    final_equity = cash

    stats = {
        "symbol": symbol,
        "bars": len(candles),
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else 0,
        "initial_equity": round(initial_cash, 4),
        "final_equity": round(final_equity, 4),
        "net_pnl": round(total, 4),
        "return_pct": round(100 * (final_equity / initial_cash - 1), 3),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
        "avg_R": round(sum(t["R"] for t in trades) / len(trades), 3) if trades else 0,
        "max_drawdown_pct": round(max_drawdown * 100, 3),
        "fee_rate_each_side": fee,
        "slippage_each_side": slippage,
        "note": "Strategy-only test; trend gate and LLM are not simulated.",
    }
    return stats, trades, equity_curve


def main():
    parser = argparse.ArgumentParser(
        description="Offline-only Wallex spot strategy backtest; never places orders."
    )
    parser.add_argument("--symbol", default="BTCTMN")
    parser.add_argument("--timeframe", default="60", choices=sorted(TF_SECONDS))
    parser.add_argument("--bars", type=int, default=2000)
    parser.add_argument("--initial-equity", type=float, default=None)
    parser.add_argument("--slippage", type=float, default=None)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    if args.bars < 100 or args.bars > 20000:
        parser.error("--bars must be between 100 and 20000")

    cfg = load_config(args.config)
    if args.symbol not in cfg.get("universe", []):
        print(f"WARNING: {args.symbol} is not in configured universe.")

    wx = Wallex(cfg["wallex"])
    info = wx.info(args.symbol)
    if info["quote"] != "TMN":
        raise SystemExit(
            "Version 1 supports TMN-quoted pairs only, to keep equity units consistent."
        )

    strategy_cfgs = [
        {**c, "params": {**c.get("params", {}), "timeframe": args.timeframe}}
        for c in cfg["strategies"]
        if c.get("enabled", True)
    ]
    strategies = load_strategies(strategy_cfgs)
    if not strategies:
        raise SystemExit("No enabled strategies found.")
    if len(strategies) != 1:
        raise SystemExit(
            "Version 1 supports one enabled strategy at a time to keep results attributable."
        )
    strategy = strategies[0]

    initial = (
        args.initial_equity
        if args.initial_equity is not None
        else float(cfg["paper_equity_tmn"])
    )
    if initial <= 0:
        raise SystemExit("--initial-equity must be positive")

    fee_cfg = cfg["fees"].get(info["quote"], {})
    fee = float(fee_cfg.get("taker", 0))
    slippage = (
        float(args.slippage)
        if args.slippage is not None
        else float(cfg.get("paper_slippage", 0.001))
    )
    if not 0 <= fee < 1 or not 0 <= slippage < 0.1:
        raise SystemExit("Invalid fee or slippage setting")

    candles = fetch_history(wx, args.symbol, args.timeframe, args.bars)
    stats, trades, equity = backtest(
        candles, strategy, cfg, args.symbol, initial, fee, slippage
    )

    outdir = Path("data")
    outdir.mkdir(parents=True, exist_ok=True)
    tag = f"{args.symbol}_{args.timeframe}_{len(candles)}"
    trade_path = outdir / f"backtest_trades_{tag}.csv"
    equity_path = outdir / f"backtest_equity_{tag}.csv"
    stats_path = outdir / f"backtest_summary_{tag}.json"

    if trades:
        with trade_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(trades[0]))
            writer.writeheader()
            writer.writerows(trades)
    else:
        trade_path.write_text("no trades\n", encoding="utf-8")

    with equity_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(equity[0]))
        writer.writeheader()
        writer.writerows(equity)

    import json
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print("\n========== BACKTEST SUMMARY ==========")
    for key, value in stats.items():
        print(f"{key}: {value}")
    print("\nFiles written:")
    print(trade_path)
    print(equity_path)
    print(stats_path)


if __name__ == "__main__":
    sys.exit(main())
