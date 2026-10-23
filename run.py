import argparse
import json
import os
import re
import sys
import time

from pilot.config import load_config


def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)


def main():
    load_env()
    ap = argparse.ArgumentParser(description="wallex-pilot")
    ap.add_argument("cmd", choices=["discover", "check", "scan-once", "run", "status", "report",
                                    "export", "reset-halt"])
    ap.add_argument("--live", action="store_true", help="real orders (needs mode: live in config too)")
    ap.add_argument("--all", action="store_true", help="discover: list every market")
    ap.add_argument("--config", default="config.yaml")
    a = ap.parse_args()
    cfg = load_config(a.config)

    from pilot.engine import Engine
    eng = Engine(cfg, live=a.live)

    if a.cmd == "discover":
        kw = re.compile("|".join(cfg["discover"]["keywords"]), re.I)
        print(f"{'SYMBOL':14}{'QUOTE':8}{'LAST':>16}  NAME")
        for s, m in sorted(eng.wx.markets().items()):
            hay = s + " " + " ".join(str(v) for v in m.values() if isinstance(v, (str, int, float)))
            if a.all or kw.search(hay):
                info = eng.wx.info(s)
                last = (m.get("stats") or {}).get("lastPrice")
                print(f"{s:14}{info['quote']:8}{str(last):>16}  {m.get('faBaseAsset') or m.get('enBaseAsset') or ''}")
    elif a.cmd == "check":
        from pilot.trend import trend_gate
        prices = eng.wx.prices()
        print(f"mode={'LIVE' if eng.live else 'PAPER'}  equity={eng.equity(prices):,.0f} TMN")
        for s in cfg["universe"]:
            try:
                t = trend_gate(eng.wx, s, cfg["trend"])
                print(f"{s:12} {'UP  ' if t['up'] else 'no  '} {json.dumps(t['detail'])}")
            except Exception as e:
                print(f"{s:12} ERROR {e!r}   <- probably wrong symbol name; run `discover`")
    elif a.cmd == "scan-once":
        prices = eng.wx.prices()
        eng.scan(prices, dry=True)
    elif a.cmd == "run":
        try:
            eng.run()
        except KeyboardInterrupt:
            print("stopped")
    elif a.cmd == "status":
        prices = eng.wx.prices()
        eq = eng.equity(prices)
        print(f"equity={eq:,.0f} TMN  halted={eng.risk.halted}  daily_blocked={eng.risk.daily_blocked(eq)}")
        for t in eng.j.open_trades():
            p = prices.get(t["symbol"], 0)
            print(f"#{t['id']} {t['symbol']} qty={t['qty']} entry={t['entry']} now={p} stop={t['stop']} tp={t['tp']}")
        print(eng.j.stats())
    elif a.cmd == "report":
        for t in eng.j.closed_trades()[-20:]:
            print(f"#{t['id']} {t['symbol']} {t['exit_reason']:14} pnl={t['pnl_tmn']:>12,.0f}  R={t['r_mult']:.2f}  {t['reason']}")
        print(eng.j.stats())
    elif a.cmd == "export":
        n = eng.j.export_csv("data/journal.csv")
        print(f"{n} trades -> data/journal.csv")
    elif a.cmd == "reset-halt":
        eng.j.kv_set("halted", False)
        eng.j.kv_set("peak_equity", eng.equity(eng.wx.prices()))
        print("halt cleared, peak equity reset")


if __name__ == "__main__":
    sys.exit(main())
