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
from app.simulator import SPECS
from app.storage import Store
from app.topics import TOPIC_META, TOPIC_ORDER
from engine.verification import build_registry

REPO_ROOT = Path(__file__).resolve().parent.parent


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


def _strategy_catalog() -> list[dict]:
    return [
        {
            "key": spec.key,
            "name": spec.name,
            "category": spec.category,
            "description": spec.thesis,
            "maker": bool(spec.maker_entry),
            "source_url": "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
        }
        for spec in SPECS
    ]


def _load_demo_live_artifacts() -> dict:
    """Read committed Kalshi Demo API collector snapshots from data/live/ if present."""
    state_path = REPO_ROOT / "data" / "live" / "state.json"
    feed_path = REPO_ROOT / "data" / "live" / "feed.json"
    port_path = REPO_ROOT / "data" / "live" / "portfolio.json"

    resolutions_out: list[dict] = []
    live_swings_out: list[dict] = []
    portfolio_out: list[dict] = []
    orderbook_levels: dict[str, list[dict]] = {}

    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            state = {}
        tracked = state.get("tracked") or {}
        for ticker, r in (state.get("resolutions") or {}).items():
            res = str(r.get("result") or "").lower()
            if res not in ("yes", "no", "scalar"):
                continue
            tr = tracked.get(ticker) or {}
            topic = tr.get("topic") or "other"
            if topic not in TOPIC_META:
                continue
            series_t = tr.get("seriesTicker") or ticker.split("-")[0]
            resolutions_out.append({
                "ticker": ticker,
                "event_ticker": tr.get("eventTicker"),
                "series_ticker": series_t,
                "title": _plain(tr.get("title") or ticker),
                "topic": topic,
                "result": res,
                "settlement_value": r.get("settlementValue"),
                "determined_utc": r.get("settlementTs") or r.get("checkedAt"),
                "page_url": r.get("sourceUrl") or f"https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}",
                "note": f"Kalshi Demo status={r.get('status')}",
                "source": "GET /markets/{ticker} (Kalshi Demo API)",
                "source_url": r.get("sourceUrl") or f"https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}",
            })
        resolutions_out.sort(key=lambda x: str(x.get("determined_utc") or ""), reverse=True)

    if feed_path.exists():
        try:
            feed = json.loads(feed_path.read_text())
        except json.JSONDecodeError:
            feed = {}
        for idx, a in enumerate(feed.get("alerts") or [], start=1000):
            if a.get("topic") not in TOPIC_META:
                continue
            obs_str = a.get("observedAt") or ""
            try:
                obs_ts = datetime.fromisoformat(obs_str.replace("Z", "+00:00")).timestamp()
            except ValueError:
                obs_ts = float(idx)
            live_swings_out.append({
                "id": idx,
                "ts": obs_ts,
                "time_utc": obs_str,
                "ticker": a.get("marketTicker"),
                "event_ticker": a.get("eventTicker"),
                "series_ticker": (a.get("marketTicker") or "").split("-")[0] or None,
                "title": _plain(a.get("title")),
                "topic": a.get("topic"),
                "direction": a.get("direction"),
                "from_price": f"{float(a.get('from') or 0):.4f}",
                "to_price": f"{float(a.get('to') or 0):.4f}",
                "delta": f"{float(a.get('delta') or 0):+.4f}",
                "window_s": None,
                "confidence": "demo-poll",
                "score": f"{float(a.get('score') or 0) / 100.0:.3f}",
                "selective": bool(a.get("eligibleForFilteredFeed")),
                "page_url": a.get("marketUrl") or "https://docs.kalshi.com/getting_started/orderbook_responses",
                "orderbook_url": a.get("orderbookUrl"),
                "cross_depth": a.get("crossDepthContracts"),
                "reasons": [a.get("note") or "observed >= $0.10 mid-price swing on Kalshi Demo API"],
                "news": {"status": "settlement_sources", "contract_sources": a.get("settlementSources") or []},
            })

    if port_path.exists():
        try:
            port = json.loads(port_path.read_text())
        except json.JSONDecodeError:
            port = {}
        for p in port.get("positions") or []:
            if p.get("topic") not in TOPIC_META:
                continue
            portfolio_out.append({
                "ticker": p.get("ticker"),
                "event_ticker": p.get("eventTicker"),
                "series_ticker": p.get("seriesTicker"),
                "title": _plain(p.get("title")),
                "topic": p.get("topic"),
                "strategy": p.get("strategyId"),
                "category": "tail" if p.get("strategyId") == "longshot" else p.get("strategyId"),
                "side": p.get("side"),
                "contracts": p.get("contracts"),
                "entry_price": f"{float(p.get('entryPrice') or 0):.4f}",
                "entry_fee": f"{float(p.get('entryFee') or 0):.4f}",
                "fee_multiplier": p.get("feeMultiplier"),
                "status": p.get("status"),
                "opened_utc": p.get("openedAt"),
                "reason": p.get("reason"),
                "source_url": p.get("feeSource") or "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
                "market_url": f"https://external-api.demo.kalshi.co/trade-api/v2/markets/{p.get('ticker')}",
            })

    desk_snap = REPO_ROOT / "demo-desk" / "data" / "verified_snapshot.json"
    if desk_snap.exists():
        try:
            ds = json.loads(desk_snap.read_text())
        except json.JSONDecodeError:
            ds = {}
        for ticker, ob in (ds.get("orderbooks") or {}).items():
            fp = (ob or {}).get("orderbook_fp") or {}
            yes_levels = [{"side": "yes_bid", "price": str(lv[0]), "contracts": str(lv[1])}
                          for lv in (fp.get("yes_dollars") or []) if isinstance(lv, list) and len(lv) >= 2]
            no_levels = [{"side": "no_bid", "price": str(lv[0]), "contracts": str(lv[1]),
                          "implied_yes_ask": f"{max(0.0, 1.0 - float(lv[0])):.4f}"}
                         for lv in (fp.get("no_dollars") or []) if isinstance(lv, list) and len(lv) >= 2]
            if yes_levels or no_levels:
                orderbook_levels[ticker] = {
                    "source_url": f"https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}/orderbook",
                    "yes_bids": yes_levels,
                    "no_bids": no_levels,
                }

    return {
        "resolutions": resolutions_out[:60],
        "live_swings": live_swings_out,
        "portfolio": portfolio_out,
        "orderbooks": orderbook_levels,
    }


def _export_tick_series(store: Store, tickers: list[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for ticker in tickers:
        rows = store.ticks(ticker, since_ts=0, limit=120)
        if rows:
            out[ticker] = [
                {
                    "ts": r.get("ts"),
                    "time_utc": _iso(r.get("ts")),
                    "yes_bid": r.get("yes_bid"),
                    "yes_ask": r.get("yes_ask"),
                    "last_price": r.get("last_price"),
                    "liquidity": r.get("liquidity"),
                    "source": r.get("source"),
                }
                for r in rows
            ]
    return out


def export_from_store(db_path: str | Path, *, limit: int = 400) -> dict:
    store = Store(db_path)
    try:
        markets = store.list_markets(limit=limit)
        alerts = list(reversed(store.list_alerts(limit=200)))
        resolutions = store.list_resolutions(limit=200)
        counts = store.counts()
        tick_series = _export_tick_series(store, [m.get("ticker") for m in markets if m.get("ticker")])
    finally:
        store.close()

    by_topic: dict[str, list[dict]] = {t: [] for t in TOPIC_ORDER}
    for row in markets:
        topic = row.get("topic") or "other"
        by_topic.setdefault(topic, []).append(_market_record(row))

    live_art = _load_demo_live_artifacts()
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
        "resolutions": [_resolution_record(r) for r in resolutions] or live_art["resolutions"],
        "portfolio": live_art["portfolio"],
        "strategy_trades": [],
        "strategy_catalog": _strategy_catalog(),
        "tick_series": tick_series,
        "orderbooks": live_art["orderbooks"],
        "demo_endpoints": {
            "rest_primary": "https://external-api.demo.kalshi.co/trade-api/v2",
            "rest_fallback": "https://demo-api.kalshi.co/trade-api/v2",
            "ws_primary": "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
            "ws_fallback": "wss://demo-api.kalshi.co/trade-api/ws/v2",
        },
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
        counts = store.counts()
        tick_series = _export_tick_series(store, [m.get("ticker") for m in markets if m.get("ticker")])
    finally:
        store.close()

    by_topic: dict[str, list[dict]] = {t: [] for t in TOPIC_ORDER}
    for row in markets:
        by_topic.setdefault(row.get("topic") or "other", []).append(_market_record(row))

    live_art = _load_demo_live_artifacts()
    all_alerts = live_art["live_swings"] + [_alert_record(a) for a in alerts]
    selective_alerts = [a for a in all_alerts if a.get("selective")]
    resolutions = live_art["resolutions"]
    counts["alerts"] = len(all_alerts)
    counts["selective_alerts"] = len(selective_alerts)
    counts["resolutions"] = len(resolutions)
    counts["sim_trades"] = len(live_art["portfolio"])

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
        "alerts": all_alerts,
        "selective_alerts": selective_alerts,
        "resolutions": resolutions,
        "portfolio": live_art["portfolio"],
        "strategy_trades": live_art["portfolio"],
        "strategy_catalog": _strategy_catalog(),
        "tick_series": tick_series,
        "orderbooks": live_art["orderbooks"],
        "demo_endpoints": {
            "rest_primary": "https://external-api.demo.kalshi.co/trade-api/v2",
            "rest_fallback": "https://demo-api.kalshi.co/trade-api/v2",
            "ws_primary": "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
            "ws_fallback": "wss://demo-api.kalshi.co/trade-api/ws/v2",
        },
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
