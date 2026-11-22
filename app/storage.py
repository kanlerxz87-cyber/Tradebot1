"""SQLite persistence: price ticks, alerts, resolutions, and simulated portfolios.

One file, WAL mode, no ORM. Every write goes through a lock because the
collector task and the HTTP handlers share the connection. The schema is
created on first use and is safe to run repeatedly.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    ticker           TEXT PRIMARY KEY,
    event_ticker     TEXT,
    series_ticker    TEXT,
    title            TEXT,
    subtitle         TEXT,
    category         TEXT,
    topic            TEXT,
    topic_basis      TEXT,
    status           TEXT,
    close_time       TEXT,
    expected_expiration_time TEXT,
    result           TEXT,
    settlement_value TEXT,
    rules_primary    TEXT,
    page_url         TEXT,
    first_seen_ts    REAL,
    last_seen_ts     REAL,
    volume_fp        TEXT,
    open_interest_fp TEXT,
    last_price       TEXT,
    yes_bid          TEXT,
    yes_ask          TEXT,
    liquidity        TEXT,
    meta_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_markets_topic ON markets(topic);

CREATE TABLE IF NOT EXISTS ticks (
    ticker     TEXT NOT NULL,
    ts         REAL NOT NULL,
    yes_bid    TEXT,
    yes_ask    TEXT,
    last_price TEXT,
    liquidity  TEXT,
    source     TEXT,
    PRIMARY KEY (ticker, ts)
);
CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(ts);

CREATE TABLE IF NOT EXISTS series_cache (
    ticker      TEXT PRIMARY KEY,
    category    TEXT,
    tags_json   TEXT,
    title       TEXT,
    fetched_ts  REAL
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    ticker      TEXT NOT NULL,
    event_ticker TEXT,
    topic       TEXT,
    title       TEXT,
    direction   TEXT,
    from_price  TEXT,
    to_price    TEXT,
    delta       TEXT,
    window_s    INTEGER,
    confidence  TEXT,
    reasons     TEXT,
    score       TEXT,
    selective   INTEGER DEFAULT 0,
    page_url    TEXT,
    news_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);
CREATE INDEX IF NOT EXISTS idx_alerts_selective ON alerts(selective, ts);

CREATE TABLE IF NOT EXISTS resolutions (
    ticker           TEXT PRIMARY KEY,
    event_ticker     TEXT,
    topic            TEXT,
    title            TEXT,
    result           TEXT,
    settlement_value TEXT,
    determined_ts    REAL,
    recorded_ts      REAL,
    page_url         TEXT,
    note             TEXT
);

CREATE TABLE IF NOT EXISTS strategies (
    key         TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    params_json TEXT,
    enabled     INTEGER DEFAULT 1,
    created_ts  REAL
);

CREATE TABLE IF NOT EXISTS sim_accounts (
    strategy       TEXT PRIMARY KEY,
    starting_cash  TEXT NOT NULL,
    cash           TEXT NOT NULL,
    realized_pnl   TEXT DEFAULT '0',
    fees_paid      TEXT DEFAULT '0',
    trades         INTEGER DEFAULT 0,
    wins           INTEGER DEFAULT 0,
    losses         INTEGER DEFAULT 0,
    created_ts     REAL,
    updated_ts     REAL
);

CREATE TABLE IF NOT EXISTS sim_positions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy     TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    topic        TEXT,
    side         TEXT NOT NULL,
    contracts    TEXT NOT NULL,
    cost_basis   TEXT NOT NULL,
    opened_ts    REAL,
    updated_ts   REAL,
    UNIQUE(strategy, ticker, side)
);

CREATE TABLE IF NOT EXISTS sim_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy    TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    event_ticker TEXT,
    topic       TEXT,
    title       TEXT,
    side        TEXT,
    action      TEXT,
    contracts   TEXT,
    price       TEXT,
    fee         TEXT,
    ts          REAL,
    mode        TEXT,
    reason      TEXT,
    order_id    TEXT,
    status      TEXT
);
CREATE INDEX IF NOT EXISTS idx_sim_trades_strategy ON sim_trades(strategy, ts);

CREATE TABLE IF NOT EXISTS sim_equity (
    ts          REAL NOT NULL,
    strategy    TEXT NOT NULL,
    cash        TEXT,
    positions_value TEXT,
    equity      TEXT,
    PRIMARY KEY (ts, strategy)
);
"""

TOPIC_LABELS = {
    "gas": "Gas prices", "elections": "Elections", "culture": "Culture",
    "crypto": "Crypto", "golf": "Golf", "other": "Other",
}


def _d(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ #
    # Markets
    # ------------------------------------------------------------------ #
    def upsert_market(self, row: dict) -> None:
        now = time.time()
        fields = {
            "ticker": row.get("ticker"),
            "event_ticker": row.get("event_ticker"),
            "series_ticker": row.get("series_ticker"),
            "title": row.get("title"),
            "subtitle": row.get("subtitle"),
            "category": row.get("category"),
            "topic": row.get("topic"),
            "topic_basis": row.get("topic_basis"),
            "status": row.get("status"),
            "close_time": row.get("close_time"),
            "expected_expiration_time": row.get("expected_expiration_time"),
            "result": row.get("result"),
            "settlement_value": row.get("settlement_value"),
            "rules_primary": row.get("rules_primary"),
            "page_url": row.get("page_url"),
            "volume_fp": row.get("volume_fp"),
            "open_interest_fp": row.get("open_interest_fp"),
            "last_price": row.get("last_price"),
            "yes_bid": row.get("yes_bid"),
            "yes_ask": row.get("yes_ask"),
            "liquidity": row.get("liquidity"),
            "meta_json": json.dumps(row.get("meta") or {}),
        }
        if not fields["ticker"]:
            return
        cols = ", ".join(fields)
        placeholders = ", ".join(["?"] * len(fields))
        updates = ", ".join(f"{k}=excluded.{k}" for k in fields if k not in ("ticker",))
        with self._lock:
            self._conn.execute(
                f"INSERT INTO markets ({cols}, first_seen_ts, last_seen_ts) "
                f"VALUES ({placeholders}, ?, ?) "
                f"ON CONFLICT(ticker) DO UPDATE SET {updates}, last_seen_ts=excluded.last_seen_ts",
                list(fields.values()) + [now, now],
            )
            self._conn.commit()

    def get_market(self, ticker: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM markets WHERE ticker=?", (ticker,)).fetchone()
        return dict(row) if row else None

    def list_markets(self, *, topic: str | None = None, status: str | None = None,
                     limit: int = 500, search: str | None = None) -> list[dict]:
        clauses, params = [], []
        if topic and topic != "all":
            clauses.append("topic = ?")
            params.append(topic)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if search:
            clauses.append("(title LIKE ? OR ticker LIKE ?)")
            params += [f"%{search}%", f"%{search}%"]
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT * FROM markets {} ORDER BY "
            "CAST(COALESCE(volume_fp,'0') AS REAL) DESC LIMIT ?"
        ).format(where)
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def set_resolution(self, row: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO resolutions (ticker, event_ticker, topic, title, result, settlement_value,"
                " determined_ts, recorded_ts, page_url, note) VALUES (?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(ticker) DO UPDATE SET result=excluded.result,"
                " settlement_value=excluded.settlement_value, determined_ts=excluded.determined_ts,"
                " recorded_ts=excluded.recorded_ts, note=excluded.note",
                (
                    row["ticker"], row.get("event_ticker"), row.get("topic"), row.get("title"),
                    row.get("result"), row.get("settlement_value"), row.get("determined_ts"),
                    time.time(), row.get("page_url"), row.get("note"),
                ),
            )
            self._conn.execute(
                "UPDATE markets SET result=?, settlement_value=?, status=COALESCE(status,'settled') WHERE ticker=?",
                (row.get("result"), row.get("settlement_value"), row["ticker"]),
            )
            self._conn.commit()

    def list_resolutions(self, *, topic: str | None = None, limit: int = 500) -> list[dict]:
        clauses, params = [], []
        if topic and topic != "all":
            clauses.append("topic = ?")
            params.append(topic)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM resolutions {where} ORDER BY COALESCE(determined_ts, recorded_ts) DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Ticks
    # ------------------------------------------------------------------ #
    def add_tick(self, ticker: str, *, ts: float | None = None, yes_bid: str | None = None,
                 yes_ask: str | None = None, last_price: str | None = None,
                 liquidity: str | None = None, source: str = "rest") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO ticks (ticker, ts, yes_bid, yes_ask, last_price, liquidity, source)"
                " VALUES (?,?,?,?,?,?,?)",
                (ticker, ts if ts is not None else time.time(), yes_bid, yes_ask, last_price, liquidity, source),
            )
            self._conn.commit()

    def ticks(self, ticker: str, *, since_ts: float | None = None, limit: int = 5000) -> list[dict]:
        params: list[Any] = [ticker]
        clause = ""
        if since_ts is not None:
            clause = "AND ts >= ?"
            params.append(since_ts)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT ts, yes_bid, yes_ask, last_price, liquidity, source FROM ticks "
                f"WHERE ticker=? {clause} ORDER BY ts ASC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

    def prune_ticks(self, older_than_ts: float) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM ticks WHERE ts < ?", (older_than_ts,))
            self._conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------ #
    # Series metadata (tags live on the series, not on the event)
    # ------------------------------------------------------------------ #
    def get_series(self, ticker: str, *, max_age_seconds: float = 86400) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM series_cache WHERE ticker=?", (ticker,)).fetchone()
        if not row:
            return None
        if max_age_seconds and time.time() - float(row["fetched_ts"] or 0) > max_age_seconds:
            return None
        data = dict(row)
        data["tags"] = json.loads(data.get("tags_json") or "[]")
        return data

    def put_series(self, ticker: str, *, category: str | None, tags: list[str], title: str | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO series_cache (ticker, category, tags_json, title, fetched_ts)"
                " VALUES (?,?,?,?,?)",
                (ticker, category, json.dumps(list(tags or [])), title, time.time()),
            )
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # Alerts
    # ------------------------------------------------------------------ #
    def add_alert(self, alert: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO alerts (ts, ticker, event_ticker, topic, title, direction, from_price,"
                " to_price, delta, window_s, confidence, reasons, score, selective, page_url, news_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    alert["ts"], alert["ticker"], alert.get("event_ticker"), alert.get("topic"),
                    alert.get("title"), alert.get("direction"), alert.get("from_price"),
                    alert.get("to_price"), alert.get("delta"), alert.get("window_s"),
                    alert.get("confidence"), json.dumps(alert.get("reasons") or []),
                    alert.get("score"), int(bool(alert.get("selective"))), alert.get("page_url"),
                    json.dumps(alert.get("news") or []),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_alerts(self, *, since_id: int = 0, limit: int = 200, selective: bool | None = None,
                    topic: str | None = None) -> list[dict]:
        clauses, params = ["id > ?"], [since_id]
        if selective is not None:
            clauses.append("selective = ?")
            params.append(int(selective))
        if topic and topic != "all":
            clauses.append("topic = ?")
            params.append(topic)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM alerts WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["reasons"] = json.loads(d.get("reasons") or "[]")
            d["news"] = json.loads(d.get("news_json") or "[]")
            out.append(d)
        return out

    # ------------------------------------------------------------------ #
    # Strategies and simulated portfolios
    # ------------------------------------------------------------------ #
    def upsert_strategy(self, key: str, name: str, description: str, params: dict, enabled: bool = True) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO strategies (key, name, description, params_json, enabled, created_ts)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET name=excluded.name,"
                " description=excluded.description, params_json=excluded.params_json,"
                " enabled=excluded.enabled",
                (key, name, description, json.dumps(params), int(enabled), time.time()),
            )
            self._conn.commit()

    def list_strategies(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM strategies ORDER BY key").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d.get("params_json") or "{}")
            out.append(d)
        return out

    def ensure_account(self, strategy: str, starting_cash: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO sim_accounts (strategy, starting_cash, cash, realized_pnl,"
                " fees_paid, trades, wins, losses, created_ts, updated_ts) VALUES (?,?,?,?,?,0,0,0,?,?)",
                (strategy, starting_cash, starting_cash, "0", "0", time.time(), time.time()),
            )
            self._conn.commit()

    def account(self, strategy: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sim_accounts WHERE strategy=?", (strategy,)).fetchone()
        return dict(row) if row else None

    def accounts(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sim_accounts ORDER BY strategy").fetchall()
        return [dict(r) for r in rows]

    def update_account(self, strategy: str, *, cash: Decimal, realized_delta: Decimal = Decimal("0"),
                       fee_delta: Decimal = Decimal("0"), trades_delta: int = 0,
                       wins_delta: int = 0, losses_delta: int = 0) -> None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sim_accounts WHERE strategy=?", (strategy,)).fetchone()
            if row is None:
                return
            realized = _d(row["realized_pnl"]) or Decimal("0")
            fees = _d(row["fees_paid"]) or Decimal("0")
            self._conn.execute(
                "UPDATE sim_accounts SET cash=?, realized_pnl=?, fees_paid=?, trades=trades+?,"
                " wins=wins+?, losses=losses+?, updated_ts=? WHERE strategy=?",
                (str(cash), str(realized + realized_delta), str(fees + fee_delta),
                 int(row["trades"]) + trades_delta, int(row["wins"]) + wins_delta,
                 int(row["losses"]) + losses_delta, time.time(), strategy),
            )
            self._conn.commit()

    def positions(self, strategy: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sim_positions WHERE strategy=? ORDER BY ticker", (strategy,)
            ).fetchall()
        return [dict(r) for r in rows]

    def position(self, strategy: str, ticker: str, side: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sim_positions WHERE strategy=? AND ticker=? AND side=?",
                (strategy, ticker, side),
            ).fetchone()
        return dict(row) if row else None

    def save_position(self, strategy: str, ticker: str, side: str, *, topic: str | None,
                      contracts: Decimal, cost_basis: Decimal) -> None:
        now = time.time()
        with self._lock:
            if contracts <= 0:
                self._conn.execute(
                    "DELETE FROM sim_positions WHERE strategy=? AND ticker=? AND side=?",
                    (strategy, ticker, side),
                )
            else:
                self._conn.execute(
                    "INSERT INTO sim_positions (strategy, ticker, topic, side, contracts, cost_basis,"
                    " opened_ts, updated_ts) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(strategy, ticker, side)"
                    " DO UPDATE SET contracts=excluded.contracts, cost_basis=excluded.cost_basis,"
                    " updated_ts=excluded.updated_ts",
                    (strategy, ticker, topic, side, str(contracts), str(cost_basis), now, now),
                )
            self._conn.commit()

    def add_sim_trade(self, trade: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sim_trades (strategy, ticker, event_ticker, topic, title, side, action,"
                " contracts, price, fee, ts, mode, reason, order_id, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    trade["strategy"], trade["ticker"], trade.get("event_ticker"), trade.get("topic"),
                    trade.get("title"), trade.get("side"), trade.get("action"), trade.get("contracts"),
                    trade.get("price"), trade.get("fee"), trade.get("ts", time.time()),
                    trade.get("mode", "paper"), trade.get("reason"), trade.get("order_id"), trade.get("status"),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def sim_trades(self, *, strategy: str | None = None, limit: int = 500) -> list[dict]:
        clause, params = "", []
        if strategy:
            clause = "WHERE strategy=?"
            params.append(strategy)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM sim_trades {clause} ORDER BY ts DESC LIMIT ?", params + [limit]
            ).fetchall()
        return [dict(r) for r in rows]

    def record_equity(self, strategy: str, *, cash: Decimal, positions_value: Decimal) -> None:
        ts = round(time.time(), 0)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sim_equity (ts, strategy, cash, positions_value, equity)"
                " VALUES (?,?,?,?,?)",
                (ts, strategy, str(cash), str(positions_value), str(cash + positions_value)),
            )
            self._conn.commit()

    def equity_curve(self, strategy: str, limit: int = 2000) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, cash, positions_value, equity FROM sim_equity WHERE strategy=?"
                " ORDER BY ts ASC LIMIT ?", (strategy, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Reporting helpers
    # ------------------------------------------------------------------ #
    def alert_stats(self, *, limit: int = 5000) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT topic, direction, delta, score, selective FROM alerts ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        stats: dict[str, dict] = {}
        for r in rows:
            topic = r["topic"] or "other"
            bucket = stats.setdefault(topic, {"count": 0, "selective": 0, "up": 0, "down": 0,
                                              "avg_delta": 0.0})
            bucket["count"] += 1
            bucket["selective"] += int(r["selective"] or 0)
            bucket["up" if r["direction"] == "up" else "down"] += 1
            bucket["avg_delta"] += abs(float(r["delta"] or 0))
        for bucket in stats.values():
            if bucket["count"]:
                bucket["avg_delta"] = round(bucket["avg_delta"] / bucket["count"], 4)
        return stats

    def counts(self) -> dict:
        with self._lock:
            def one(sql: str, params: Sequence[Any] = ()) -> int:
                row = self._conn.execute(sql, params).fetchone()
                return int(row[0]) if row else 0
            return {
                "markets": one("SELECT COUNT(*) FROM markets"),
                "alerts": one("SELECT COUNT(*) FROM alerts"),
                "selective_alerts": one("SELECT COUNT(*) FROM alerts WHERE selective=1"),
                "ticks": one("SELECT COUNT(*) FROM ticks"),
                "resolutions": one("SELECT COUNT(*) FROM resolutions"),
                "sim_trades": one("SELECT COUNT(*) FROM sim_trades"),
            }
