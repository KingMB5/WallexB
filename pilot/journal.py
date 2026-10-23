import csv
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS trades(
 id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT, symbol TEXT, quote TEXT, setup TEXT, tf TEXT,
 opened_at REAL, entry REAL, qty REAL, init_stop REAL, stop REAL, tp REAL, highest REAL,
 risk_tmn REAL, fx_entry REAL, fee REAL, reason TEXT, trend TEXT, llm TEXT,
 status TEXT DEFAULT 'open', closed_at REAL, exit_price REAL, exit_reason TEXT,
 pnl_tmn REAL, r_mult REAL);
CREATE TABLE IF NOT EXISTS equity(ts REAL, equity REAL);
CREATE TABLE IF NOT EXISTS events(ts REAL, level TEXT, msg TEXT, data TEXT);
"""


class Journal:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # key/value state (peak equity, halted flag, paper cash, ...)
    def kv_get(self, k, default=None):
        r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else default

    def kv_set(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, json.dumps(v)))
        self.db.commit()

    def event(self, level, msg, **data):
        self.db.execute("INSERT INTO events VALUES(?,?,?,?)",
                        (time.time(), level, msg, json.dumps(data, ensure_ascii=False, default=str)))
        self.db.commit()
        print(f"[{time.strftime('%H:%M:%S')}] {level.upper():6} {msg} {data if data else ''}", flush=True)

    def log_equity(self, eq):
        self.db.execute("INSERT INTO equity VALUES(?,?)", (time.time(), eq))
        self.db.commit()

    def open_trade(self, **f):
        cols = ",".join(f)
        cur = self.db.execute(f"INSERT INTO trades({cols}) VALUES({','.join('?' * len(f))})", list(f.values()))
        self.db.commit()
        return cur.lastrowid

    def update_trade(self, tid, **f):
        sets = ",".join(f"{k}=?" for k in f)
        self.db.execute(f"UPDATE trades SET {sets} WHERE id=?", [*f.values(), tid])
        self.db.commit()

    def open_trades(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM trades WHERE status='open'")]

    def closed_trades(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM trades WHERE status='closed' ORDER BY id")]

    def export_csv(self, path):
        rows = [dict(r) for r in self.db.execute("SELECT * FROM trades ORDER BY id")]
        if not rows:
            return 0
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        return len(rows)

    def stats(self):
        cl = self.closed_trades()
        if not cl:
            return {"trades": 0}
        pnl = [t["pnl_tmn"] for t in cl]
        wins = [p for p in pnl if p > 0]
        losses = [-p for p in pnl if p <= 0]
        return {
            "trades": len(cl), "win_rate": round(len(wins) / len(cl), 3),
            "total_pnl_tmn": round(sum(pnl)), "avg_R": round(sum(t["r_mult"] for t in cl) / len(cl), 2),
            "profit_factor": round(sum(wins) / sum(losses), 2) if losses and sum(losses) else None,
        }
