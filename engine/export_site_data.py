"""Export the app's state as static JSON for the GitHub Pages site.

GitHub Pages cannot run Python, and it must not hold Kalshi credentials, so the
site is built from exported JSON. Two exporters exist:

    export_from_store()  reads a live/replay SQLite database produced by the app
    export_from_replay() builds the dataset from data/captures with no DB at all

Both label every record with its provenance. The site prints those labels, so a
replayed or captured row can never be mistaken for a live tick.

Usage:
    python -m engine.export_site_data --out docs/data --db data/state/kalshi.sqlite3
    python -m engine.export_site_data --out docs/data --replay
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.config import load_settings
from app.replay import CAPTURE_DIR, REPLAY_SCRIPT, build_replay, series_catalog
from app.storage import Store
from app.topics import TOPIC_META, TOPIC_ORDER
from engine.verification import build_registry


def _plain(text):
    """Kalshi titles contain markdown emphasis, e.g. "Will average **gas prices** be above $3.50?".
    Strip the markers so the table shows clean text; the value itself is unchanged."""
    if not text:
        return text
    return str(text).replace("**", "").strip()


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _market_record(row: dict, meta: dict | None = None) -> dict:
    """Build one site row. Provenance comes from the row's own stored meta, so a
    captured row can never be labelled live (or vice versa)."""
    if meta is None:
        try:
            meta = json.loads(row.get("meta_json") or "{}")
        except (json.JSONDecodeError, TypeError, AttributeError):
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return {
        "ticker": row.get("ticker"),
        "event_ticker": row.get("event_ticker"),
        "series_ticker": row.get("series_ticker"),
        "title": _plain(row.get("title")),
        "subtitle": row.get("subtitle"),
        "category": row.get("category"),
        "topic": row.get("topic"),
        "topic_basis": row.get("topic_basis"),
        "status": row.get("status"),
        "close_time": row.get("close_time"),
        "result": row.get("result"),
        "settlement_value": row.get("settlement_value"),
        "page_url": row.get("page_url"),
        "rules_primary": row.get("rules_primary"),
        "yes_bid": row.get("yes_bid"),
        "yes_ask": row.get("yes_ask"),
        "last_price": row.get("last_price"),
        "volume_fp": row.get("volume_fp"),
        "open_interest_fp": row.get("open_interest_fp"),
        "liquidity": row.get("liquidity"),
        "company_link": row.get("page_url"),
        "provenance": meta.get("provenance") or "live",
        "capture_url": meta.get("capture_url"),
        "captured_at_utc": meta.get("captured_at_utc"),
        "settlement_sources": meta.get("settlement_sources") or [],
        "flags": meta.get("flags") or [],
    }


def _alert_record(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "ts": row.get("ts"),
        "time_utc": _iso(row.get("ts")),
        "ticker": row.get("ticker"),
        "event_ticker": row.get("event_ticker"),
        "series_ticker": row.get("series_ticker"),
        "title": _plain(row.get("title")),
        "topic": row.get("topic"),
        "direction": row.get("direction"),
        "from_price": row.get("from_price"),
        "to_price": row.get("to_price"),
        "delta": row.get("delta"),
        "window_s": row.get("window_s"),
        "confidence": row.get("confidence"),
        "score": row.get("score"),
        "selective": bool(row.get("selective")),
        "page_url": row.get("page_url"),
        "reasons": row.get("reasons") or [],
        "news": row.get("news") or [],
    }


def _resolution_record(row: dict) -> dict:
    return {
        "ticker": row.get("ticker"),
        "event_ticker": row.get("event_ticker"),
        "series_ticker": row.get("series_ticker"),
        "title": _plain(row.get("title")),
        "topic": row.get("topic"),
        "result": row.get("result"),
        "settlement_value": row.get("settlement_value"),
        "determined_ts": row.get("determined_ts"),
        "determined_utc": _iso(row.get("determined_ts")) if row.get("determined_ts") else None,
        "page_url": row.get("page_url"),
        "note": row.get("note"),
        "source": "GET /markets/{ticker} (result, settlement_value_dollars)",
        "source_url": "https://docs.kalshi.com/api-reference/market/get-market",
    }


def export_from_store(db_path: str | Path, *, limit: int = 400) -> dict:
    store = Store(db_path)
    try:
        markets = store.list_markets(limit=limit)
        alerts = list(reversed(store.list_alerts(limit=200)))
        resolutions = store.list_resolutions(limit=200)
        counts = store.counts()
    finally:
        store.close()

    by_topic: dict[str, list[dict]] = {t: [] for t in TOPIC_ORDER}
    for row in markets:
        topic = row.get("topic") or "other"
        by_topic.setdefault(topic, []).append(_market_record(row))

    return {
        "generated_utc": _iso(),
        "provenance": "live",
        "counts": counts,
        "topics": [
            {"key": key, "label": TOPIC_META[key]["label"], "blurb": TOPIC_META[key]["blurb"],
             "basis": TOPIC_META[key]["basis"], "markets": by_topic.get(key, [])}
            for key in TOPIC_ORDER
        ],
        "alerts": [_alert_record(a) for a in alerts],
        "selective_alerts": [_alert_record(a) for a in alerts if a.get("selective")],
        "resolutions": [_resolution_record(r) for r in resolutions],
        "portfolio": [],
        "strategy_trades": [],
        "series_catalog": series_catalog(),
    }


def export_from_replay(*, settings=None) -> dict:
    """Build the dataset with no database: captures -> topics -> scripted swings."""
    import tempfile

    settings = settings or load_settings()
    tmp = Path(tempfile.mkdtemp()) / "replay.sqlite3"
    store = Store(tmp)
    try:
        info = build_replay(store, settings, refresh_lookback=settings.news_lookback_hours)
        markets = store.list_markets(limit=400)
        alerts = list(reversed(store.list_alerts(limit=200)))
        resolutions = []
        counts = store.counts()
    finally:
        store.close()

    by_topic: dict[str, list[dict]] = {t: [] for t in TOPIC_ORDER}
    for row in markets:
        by_topic.setdefault(row.get("topic") or "other", []).append(_market_record(row))

    return {
        "generated_utc": _iso(),
        "provenance": "captured-replay",
        "replay_info": info,
        "counts": counts,
        "topics": [
            {"key": key, "label": TOPIC_META[key]["label"], "blurb": TOPIC_META[key]["blurb"],
             "basis": TOPIC_META[key]["basis"], "markets": by_topic.get(key, [])}
            for key in TOPIC_ORDER
        ],
        "alerts": [_alert_record(a) for a in alerts],
        "selective_alerts": [_alert_record(a) for a in alerts if a.get("selective")],
        "resolutions": resolutions,
        "portfolio": [],
        "strategy_trades": [],
        "series_catalog": series_catalog(),
    }


def write(out_dir: str | Path, *, db_path: str | Path | None = None, replay: bool = False) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    payload = export_from_replay() if (replay or db_path is None) else export_from_store(db_path)
    (out / "dashboard.json").write_text(json.dumps(payload, indent=2) + "\n")

    registry = build_registry()
    (out / "verification.json").write_text(json.dumps(registry, indent=2) + "\n")

    captures = []
    if CAPTURE_DIR.exists():
        for path in sorted(CAPTURE_DIR.glob("*.json")):
            doc = json.loads(path.read_text())
            captures.append({
                "key": path.stem,
                "url": doc.get("url"),
                "captured_at_utc": doc.get("captured_at_utc"),
                "method": doc.get("method"),
                "markets": [
                    {
                        "ticker": m.get("ticker"),
                        "title": _plain(m.get("title")),
                        "note": m.get("note_for_review"),
                    }
                    for ev in (doc.get("payload") or {}).get("events", [])
                    for m in ev.get("markets", [])
                ],
            })
    (out / "captures.json").write_text(json.dumps({"captures": captures}, indent=2) + "\n")
    return {"dashboard": payload, "verification": registry, "captures": captures}


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/data")
    parser.add_argument("--db", default=None)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    result = write(args.out, db_path=args.db, replay=args.replay)
    counts = result["dashboard"]["counts"]
    print(f"wrote site data to {args.out}: {counts}, "
          f"{len(result['verification']['facts'])} verified facts")


if __name__ == "__main__":  # pragma: no cover
    main()
