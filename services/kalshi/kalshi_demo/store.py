"""Private SQLite state. Never placed in docs/, artifacts, or the public Git history."""

from contextlib import contextmanager
from decimal import Decimal
import json
from pathlib import Path
import sqlite3


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, check_same_thread=False)
        if path != ":memory:":
            Path(path).chmod(0o600)
        self.db.row_factory = sqlite3.Row
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 2:
            self.db.close()
            raise ValueError("Database schema is newer than this service; refusing a downgrade")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                namespace TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(namespace, key)
            );
            CREATE TABLE IF NOT EXISTS observations (
                ticker TEXT NOT NULL, ts_ms INTEGER NOT NULL, price TEXT NOT NULL,
                source_url TEXT NOT NULL, kind TEXT NOT NULL, event_id TEXT NOT NULL,
                PRIMARY KEY(ticker, event_id)
            );
            CREATE INDEX IF NOT EXISTS observations_time ON observations(ticker, ts_ms);
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY, ts_ms INTEGER NOT NULL, selected INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS alerts_time ON alerts(ts_ms DESC);
            CREATE TABLE IF NOT EXISTS order_journal (
                client_id TEXT PRIMARY KEY, reserved TEXT NOT NULL, state TEXT NOT NULL,
                request TEXT NOT NULL, response TEXT, created_ms INTEGER NOT NULL
            );
        """)
        self.db.commit()
        try:
            self._migrate_observations()
        except Exception:
            self.db.close()
            raise

    def _migrate_observations(self):
        """Upgrade the early timestamp-keyed schema without losing observed history.

        Version 1 existed both before and after event_id was added. Inspect the
        columns/primary key rather than trusting that version alone. Everything,
        including the version marker, changes in a single rollback-safe transaction.
        """
        columns = list(self.db.execute("PRAGMA table_info(observations)"))
        names = {column["name"] for column in columns}
        primary = [column["name"] for column in sorted(columns, key=lambda row: row["pk"]) if column["pk"]]
        if not {"ticker", "ts_ms", "price", "source_url", "kind"}.issubset(names):
            raise ValueError("Unrecognized observations schema; preserve database for manual recovery")
        with self.transaction():
            if "event_id" not in names or primary != ["ticker", "event_id"]:
                self.db.execute("ALTER TABLE observations RENAME TO observations_legacy_v1")
                self.db.execute("""CREATE TABLE observations (
                    ticker TEXT NOT NULL, ts_ms INTEGER NOT NULL, price TEXT NOT NULL,
                    source_url TEXT NOT NULL, kind TEXT NOT NULL, event_id TEXT NOT NULL,
                    PRIMARY KEY(ticker, event_id)
                )""")
                # An old receipt timestamp is not an exchange trade ID. Label it as
                # a migration-local identity, not a source-supplied factual value.
                legacy_id = "'legacy-local:' || kind || ':' || ts_ms || ':' || rowid"
                identity = f"COALESCE(NULLIF(event_id, ''), {legacy_id})" if "event_id" in names else legacy_id
                self.db.execute("INSERT INTO observations SELECT ticker, ts_ms, price, source_url, kind, "
                                + identity + " FROM observations_legacy_v1")
                self.db.execute("DROP TABLE observations_legacy_v1")
                self.db.execute("CREATE INDEX observations_time ON observations(ticker, ts_ms)")
            self.db.execute("PRAGMA user_version=2")

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def put(self, namespace: str, key: str, value):
        self.db.execute("INSERT OR REPLACE INTO documents VALUES (?, ?, ?)", (namespace, key, encode(value)))
        self.db.commit()

    def get(self, namespace: str, key: str, default=None):
        row = self.db.execute("SELECT payload FROM documents WHERE namespace=? AND key=?", (namespace, key)).fetchone()
        return json.loads(row[0]) if row else default

    def all(self, namespace: str) -> list:
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT payload FROM documents WHERE namespace=? ORDER BY key", (namespace,)
        )]

    def observation(self, ticker: str, ts_ms: int, price: str, source_url: str, kind: str,
                    event_id: str | None = None) -> bool:
        identity = event_id or f"{kind}:{ts_ms}:{price}"
        cursor = self.db.execute("INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?, ?)",
                                 (ticker, ts_ms, price, source_url, kind, identity))
        self.db.commit()
        return cursor.rowcount == 1

    def history(self, ticker: str, since_ms: int, limit: int = 10_000) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM (SELECT * FROM observations WHERE ticker=? AND ts_ms>=? "
            "ORDER BY ts_ms DESC LIMIT ?) ORDER BY ts_ms", (ticker, since_ms, limit)
        )
        return [{"timestamp_ms": row["ts_ms"], "price_dollars": row["price"],
                 "source_url": row["source_url"], "kind": row["kind"]} for row in rows]

    def alert(self, alert: dict):
        self.db.execute("INSERT OR IGNORE INTO alerts VALUES (?, ?, ?, ?)",
                        (alert["id"], alert["timestamp_ms"], int(alert["selected"]), encode(alert)))
        self.db.commit()

    def alerts(self, selected: bool = False, limit: int = 100) -> list[dict]:
        where = "WHERE selected=1" if selected else ""
        return [json.loads(row[0]) for row in self.db.execute(
            f"SELECT payload FROM alerts {where} ORDER BY ts_ms DESC LIMIT ?", (min(limit, 1000),)
        )]

    def reserve_order(self, client_id: str, request: dict, reserve: Decimal,
                      maximum: Decimal, now_ms: int) -> dict | None:
        """Reserve BEFORE I/O; restart and ambiguous results cannot bypass the cap."""
        with self.transaction():
            existing = self.db.execute("SELECT * FROM order_journal WHERE client_id=?", (client_id,)).fetchone()
            if existing:
                if existing["request"] != encode(request):
                    raise ValueError("client_order_id_reused_with_different_request")
                return self._journal_row(existing)
            used = sum((Decimal(row[0]) for row in self.db.execute("SELECT reserved FROM order_journal")), Decimal(0))
            if used + reserve > maximum:
                raise ValueError("persistent_cumulative_order_cap_exceeded")
            self.db.execute("INSERT INTO order_journal VALUES (?, ?, ?, ?, ?, ?)",
                            (client_id, str(reserve), "pending", encode(request), None, now_ms))
        return None

    def finish_order(self, client_id: str, state: str, response: dict):
        # Conservative $1-per-contract notional reservations remain consumed even on rejects.
        # This is not a fee-inclusive cash limit. No unverified release/retry after an ambiguous write.
        self.db.execute("UPDATE order_journal SET state=?, response=? WHERE client_id=?",
                        (state, encode(response), client_id))
        self.db.commit()

    @staticmethod
    def _journal_row(row) -> dict:
        return {"client_order_id": row["client_id"], "reserved_dollars": row["reserved"],
                "state": row["state"], "request": json.loads(row["request"]),
                "response": json.loads(row["response"]) if row["response"] else None,
                "created_ms": row["created_ms"]}

    def journal(self) -> list[dict]:
        return [self._journal_row(row) for row in self.db.execute(
            "SELECT * FROM order_journal ORDER BY created_ms DESC"
        )]
