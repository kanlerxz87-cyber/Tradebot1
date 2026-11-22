"""One autonomous collection cycle.

The cycle is the whole product loop and runs unchanged in three places:

* GitHub Actions cron (every 15 minutes) — refreshes the public site data and advances the
  simulated book, then commits the JSON under ``docs/data/``.
* The local server — same code, on demand, with a faster cadence.
* The CLI (``python -m kalshi_trader.cli collect``) — for manual runs and tests.

Steps
-----
1. Exchange status.
2. Series catalogue (cached ≈20h) built from the five topic categories/tags.
3. Active series discovery from open events (one light ``/events`` sweep).
4. Markets per active series, normalised and classified.
5. Price history + swing alerts (≥ $0.10) versus the previous cycle.
6. Model scoring and the high-ROI shortlist.
7. Simulated trading: settle, exit, enter, mark to market.
8. Resolution tracking for markets that have settled (YES/NO).
9. Optional demo-account read (only when credentials exist).
10. Write the JSON the site consumes.

The cycle never raises on a single API failure: every stage records its error and the rest
continues, so a transient Kalshi outage cannot corrupt the ledger.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from . import fees as fee_mod
from . import model as model_mod
from . import store
from . import topics as topics_mod
from .client import RestClient, public_client
from .config import Settings, load_settings
from .kalshi_demo import DemoAccount
from .marketdata import aggregate_events, normalize_market, normalize_orderbook
from .paper import PaperLedger, run_cycle as paper_cycle
from .portfolio import summarize
from .swings import detect as detect_swings

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MAX_SERIES_PER_TOPIC = 40
MAX_PAGES_PER_SERIES = 2
MAX_EVENT_PAGES = 30
TRACKED_SERIES_LIMIT = 60


def _iso(ts: int | float | None = None) -> str:
    ts = int(ts or time.time())
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _is_stale(value: str | None, hours: float) -> bool:
    ts = _parse_iso(value)
    return ts is None or (time.time() - ts) > hours * 3600


# --------------------------------------------------------------------- catalogue
def refresh_catalogue(client: RestClient, settings: Settings, *, force: bool = False) -> dict[str, Any]:
    path = settings.data_dir / "series.json"
    cached = store.read_json(path)
    if cached and cached.get("series") and not force and not _is_stale(cached.get("generated_at"), 20):
        return cached

    series: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for queries in topics_mod.discovery_queries().values():
        for query in queries:
            try:
                payload = client.series(**query["params"])
            except Exception as exc:  # keep going with the topics we already have
                errors.append(f"series {query['params']}: {type(exc).__name__}: {exc}")
                continue
            for raw in payload:
                ticker = raw.get("ticker")
                if not ticker:
                    continue
                classified = topics_mod.topic_for_series(raw)
                if not classified:
                    continue
                entry = topics_mod.compact_series(raw, classified)
                previous = series.get(ticker)
                if previous is None:
                    series[ticker] = entry
                else:  # merge the richer of the two records
                    previous["volume"] = max(previous.get("volume") or 0.0, entry.get("volume") or 0.0)
                    if not previous.get("tags") and entry.get("tags"):
                        previous["tags"] = entry["tags"]

    totals = _counts(series)
    # A full Sports/Entertainment sweep returns thousands of series (megabytes). Only the most
    # active ones are rendered, so the published catalogue is trimmed; totals stay exact.
    by_topic: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for ticker, entry in series.items():
        by_topic.setdefault(entry.get("topic") or "other", []).append((ticker, entry))
    trimmed: dict[str, dict[str, Any]] = {}
    for topic_id, items in by_topic.items():
        items.sort(key=lambda kv: kv[1].get("volume") or 0.0, reverse=True)
        for ticker, entry in items[:150]:
            trimmed[ticker] = entry

    catalog = {
        "generated_at": _iso(),
        "schema": SCHEMA_VERSION,
        "series": trimmed,
        "totals": totals,
        "by_topic": _counts(trimmed),
        "errors": errors,
        "documentation": "https://docs.kalshi.com/getting_started/terms",
    }
    store.write_json(path, catalog)
    log.info("series catalogue refreshed: %d series (%s), %d published", len(series), totals, len(trimmed))
    return catalog


def _counts(series: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for entry in series.values():
        if entry.get("topic"):
            counts[entry["topic"]] += 1
    return dict(counts)


# --------------------------------------------------------------------- discovery
def discover_active_series(
    client: RestClient,
    catalog: dict[str, Any],
    settings: Settings,
) -> tuple[dict[str, list[str]], list[str], list[dict[str, Any]]]:
    """Return (series tickers per topic, errors, raw events used)."""
    errors: list[str] = []
    series_meta: dict[str, dict[str, Any]] = catalog.get("series", {})
    by_topic: dict[str, set[str]] = defaultdict(set)
    events: list[dict[str, Any]] = []

    try:
        events = client.paginate("/events", "events", {"status": "open"}, page_size=200, max_pages=MAX_EVENT_PAGES)
    except Exception as exc:
        errors.append(f"events: {type(exc).__name__}: {exc}")

    for event in events:
        series_ticker = event.get("series_ticker")
        if not series_ticker:
            continue
        meta = series_meta.get(series_ticker)
        topic = (meta or {}).get("topic") or _topic_from_event(event)
        if topic:
            by_topic[topic].add(series_ticker)

    # Fallback / top-up: catalogue entries with real volume that the event sweep missed.
    for ticker, meta in series_meta.items():
        topic = meta.get("topic")
        if not topic:
            continue
        if (meta.get("volume") or 0) > 0:
            by_topic[topic].add(ticker)

    result: dict[str, list[str]] = {}
    for topic, tickers in by_topic.items():
        ranked = sorted(tickers, key=lambda t: (series_meta.get(t, {}).get("volume") or 0), reverse=True)
        result[topic] = ranked[:MAX_SERIES_PER_TOPIC]
    return result, errors, events


def _topic_from_event(event: dict[str, Any]) -> str | None:
    category = str(event.get("category") or "").strip().lower()
    title = str(event.get("title") or event.get("sub_title") or "")
    if "golf" in title.lower() or any(k in title.lower() for k in ("pga", "ryder cup", "liv golf")):
        return "golf"
    mapping = {
        "elections": "elections",
        "crypto": "crypto",
        "entertainment": "culture",
        "social": "culture",
    }
    if category in mapping:
        return mapping[category]
    gas = topics_mod.TOPIC_INDEX["gas"].pattern_regex()
    if category in {"economics", "commodities"} and gas and gas.search(title):
        return "gas"
    return None


# ------------------------------------------------------------------------ markets
def fetch_markets(
    client: RestClient,
    series_by_topic: dict[str, list[str]],
    catalog: dict[str, Any],
    settings: Settings,
    *,
    errors: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch every open market for the discovered series, grouped by topic."""
    errors = errors if errors is not None else []
    series_meta: dict[str, dict[str, Any]] = catalog.get("series", {})
    api_base = settings.rest_base
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    seen_series: list[str] = []

    for topic, series_list in series_by_topic.items():
        for series_ticker in series_list:
            seen_series.append(series_ticker)
            try:
                raw_markets = client.paginate(
                    "/markets",
                    "markets",
                    {"series_ticker": series_ticker, "status": "open"},
                    page_size=200,
                    max_pages=MAX_PAGES_PER_SERIES,
                )
            except Exception as exc:
                errors.append(f"markets {series_ticker}: {type(exc).__name__}: {exc}")
                continue
            meta = series_meta.get(series_ticker) or {}
            for raw in raw_markets:
                ticker = raw.get("ticker")
                if not ticker:
                    continue
                market = normalize_market(
                    raw,
                    topic=topic,
                    series_ticker=series_ticker,
                    series_title=meta.get("title"),
                    event_title=raw.get("title"),
                    api_base=api_base,
                )
                if market.get("price", 0) <= 0 and not market.get("yes_bid"):
                    continue  # no observable price yet
                grouped[topic][ticker] = market

    out: dict[str, list[dict[str, Any]]] = {}
    for topic, markets in grouped.items():
        ranked = sorted(markets.values(), key=lambda m: m.get("notional_24h_est") or 0.0, reverse=True)
        out[topic] = ranked[: settings.max_markets_per_topic]
    return out


def enrich_orderbooks(client: RestClient, markets: list[dict[str, Any]], limit: int = 12) -> None:
    """Attach a depth ladder to the top markets (best effort, per market)."""
    for market in markets[:limit]:
        ticker = market.get("ticker")
        if not ticker:
            continue
        try:
            raw = client.orderbook(ticker, depth=10)
        except Exception as exc:
            market["orderbook_error"] = f"{type(exc).__name__}: {exc}"
            continue
        market["orderbook"] = normalize_orderbook(raw, depth=8)


# --------------------------------------------------------------------------- run
def run_cycle(
    settings: Settings | None = None,
    *,
    client: RestClient | None = None,
    now: int | None = None,
    samples: int | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Execute one full cycle. Returns the summary that was written to disk."""
    settings = settings or load_settings()
    now = now or int(time.time())
    client = client or public_client(settings)
    errors: list[str] = []
    started = time.time()

    # 1. exchange status -------------------------------------------------
    exchange: dict[str, Any] = {}
    try:
        exchange = client.exchange_status()
    except Exception as exc:
        errors.append(f"exchange/status: {type(exc).__name__}: {exc}")

    # 2-3. catalogue + discovery ----------------------------------------
    catalog = refresh_catalogue(client, settings)
    series_by_topic, discovery_errors, events = discover_active_series(client, catalog, settings)
    errors.extend(discovery_errors)

    # 4. markets ---------------------------------------------------------
    market_map = fetch_markets(client, series_by_topic, catalog, settings, errors=errors)
    all_markets = [m for markets in market_map.values() for m in markets]
    market_by_ticker = {m["ticker"]: m for m in all_markets}

    # optional second sample inside the same cycle for finer chart resolution
    samples = settings.cycle_samples if samples is None else samples
    extra_samples: list[dict[str, float]] = []
    if samples > 1 and all_markets:
        for _ in range(samples - 1):
            time.sleep(max(0.0, settings.sample_gap_s))
            try:
                refresh = fetch_markets(client, series_by_topic, catalog, settings, errors=errors)
                ticker_prices = {
                    m["ticker"]: m["price"] for markets in refresh.values() for m in markets
                }
                extra_samples.append(ticker_prices)
                for ticker, price in ticker_prices.items():
                    current = market_by_ticker.get(ticker)
                    if current is not None:
                        current["price"] = price
            except Exception as exc:
                errors.append(f"sample: {type(exc).__name__}: {exc}")

    # 5. history + alerts ------------------------------------------------
    history_path = settings.data_dir / "history.json"
    history: dict[str, list[list[float]]] = store.read_json(history_path, {}) or {}
    meta_path = settings.data_dir / "meta.json"
    meta: dict[str, Any] = store.read_json(meta_path, {}) or {}
    last_prices: dict[str, list[float]] = meta.get("last_prices", {})
    tracked_series: list[str] = meta.get("tracked_series", [])

    alerts = detect_swings(
        all_markets,
        {t: [p[0]] for t, p in last_prices.items() if p},
        now,
        threshold=0.10,
    )

    # 6. model -----------------------------------------------------------
    scored_by_ticker: dict[str, dict[str, Any]] = {}
    for market in all_markets:
        scored_by_ticker[market["ticker"]] = model_mod.score_market(
            market, history.get(market["ticker"], []), now
        )

    picks: list[dict[str, Any]] = []
    for alert in alerts:
        verdict = scored_by_ticker.get(alert["ticker"])
        if verdict is None:
            continue
        alert["model"] = {
            "score": verdict["score"],
            "roi_pct_est": verdict["roi_pct_est"],
            "direction": verdict["direction"],
            "components": verdict["components"],
            "reasons": verdict["reasons"],
            "model_version": verdict["model_version"],
            "eligible": verdict["eligible"],
            "note": "heuristic score, not a validated forecast",
        }
        if verdict["eligible"]:
            picks.append(model_mod.pick_from_alert(alert, verdict))

    watchlist = sorted(
        (
            {
                "ticker": m["ticker"],
                "topic": m.get("topic"),
                "title": m.get("title"),
                "price": m.get("price"),
                "score": scored_by_ticker[m["ticker"]]["score"],
                "roi_pct_est": scored_by_ticker[m["ticker"]]["roi_pct_est"],
                "direction": scored_by_ticker[m["ticker"]]["direction"],
                "spread": m.get("spread"),
                "volume_24h": m.get("volume_24h"),
                "api_url": m.get("api_url"),
                "series_page_url": m.get("series_page_url"),
            }
            for m in all_markets
            if scored_by_ticker[m["ticker"]]["score"] > 0
        ),
        key=lambda w: w["score"],
        reverse=True,
    )[:25]

    # 7. simulated book ---------------------------------------------------
    ledger = PaperLedger.load(settings)
    cycle_result = paper_cycle(ledger, all_markets, scored_by_ticker, alerts, now)
    ledger.save()
    paper_snapshot = ledger.snapshot(now)
    performance = summarize(paper_snapshot)

    # 8. resolutions -------------------------------------------------------
    resolved_path = settings.data_dir / "resolved.json"
    resolved_state: dict[str, Any] = store.read_json(resolved_path, {}) or {}
    resolved_items: list[dict[str, Any]] = list(resolved_state.get("items", []))
    resolved_items = _collect_resolutions(
        client, market_by_ticker, series_by_topic, resolved_items, errors, now
    )

    # 9. demo account ------------------------------------------------------
    demo = DemoAccount(settings)
    demo_state = demo.snapshot() if demo.configured else {
        "connected": False,
        "status": demo.status(),
        "summary": summarize(paper_snapshot)["headline"],
    }

    # 10. orderbook depth for the most active markets ----------------------
    top_markets = sorted(all_markets, key=lambda m: m.get("notional_24h_est") or 0, reverse=True)[:10]
    enrich_orderbooks(client, top_markets, limit=8)

    # ---------------------------------------------------------------- write
    topic_blocks: dict[str, Any] = {}
    for topic in topics_mod.TOPICS:
        markets = market_map.get(topic.id, [])
        events_block = aggregate_events(markets)[:30]
        topic_blocks[topic.id] = {
            "id": topic.id,
            "label": topic.label,
            "blurb": topic.blurb,
            "page": topic.page,
            "series_count": len(series_by_topic.get(topic.id, [])),
            "markets_count": len(markets),
            "notional_24h_est": round(sum(m.get("notional_24h_est") or 0 for m in markets), 2),
            "volume_24h": round(sum(m.get("volume_24h") or 0 for m in markets), 2),
            "open_interest": round(sum(m.get("open_interest") or 0 for m in markets), 2),
            "markets": [_publish_market(m) for m in markets],
            "events": events_block,
            "top_market": (_publish_market(max(markets, key=lambda m: m.get("notional_24h_est") or 0)) if markets else None),
        }

    previous_alerts = store.read_json(settings.data_dir / "alerts.json", {}) or {}
    merged_alerts = store.append_bounded(
        previous_alerts.get("items", []), alerts, settings.max_alerts
    )

    latest = {
        "schema": SCHEMA_VERSION,
        "generated_at": _iso(now),
        "generated_ts": now,
        "cycle_seconds": round(time.time() - started, 1),
        "data_env": settings.data_env,
        "rest_base": settings.rest_base,
        "ws_url": settings.ws_url,
        "exchange": exchange,
        "topics": topic_blocks,
        "market_count": len(all_markets),
        "event_count": len(events),
        "alerts": alerts,
        "picks": picks,
        "watchlist": watchlist,
        "paper": paper_snapshot,
        "performance": performance,
        "resolved": resolved_items[:120],
        "demo": demo_state,
        "fees": fee_mod.metadata(),
        "model": {
            "version": "heuristic-v1",
            "thresholds": {
                "min_score": model_mod.PICK_MIN_SCORE,
                "min_roi_pct": model_mod.PICK_MIN_ROI_PCT,
                "max_spread": model_mod.PICK_MAX_SPREAD,
                "min_volume_24h": model_mod.PICK_MIN_VOLUME_24H,
            },
            "weights": model_mod.WEIGHTS,
        },
        "errors": errors[:20],
        "sources": {
            "markets": f"{settings.rest_base}/markets",
            "events": f"{settings.rest_base}/events",
            "series": f"{settings.rest_base}/series",
            "orderbook": f"{settings.rest_base}/markets/{{ticker}}/orderbook",
            "docs": "https://docs.kalshi.com",
        },
    }

    if write:
        store.write_json(settings.data_dir / "latest.json", latest)
        store.write_json(
            settings.data_dir / "alerts.json",
            {"generated_at": _iso(now), "threshold": 0.10, "items": merged_alerts},
        )
        store.write_json(
            settings.data_dir / "resolved.json",
            {"generated_at": _iso(now), "items": resolved_items[:400]},
        )
        store.write_json(settings.data_dir / "paper.json", performance)
        _update_history(settings, history, all_markets, alerts, now, extra_samples)
        store.write_json(
            settings.data_dir / "meta.json",
            {
                "generated_at": _iso(now),
                "schema": SCHEMA_VERSION,
                "last_prices": {
                    m["ticker"]: [m.get("price"), now] for m in all_markets if m.get("price") is not None
                },
                "tracked_series": sorted(
                    {m.get("series_ticker") for m in all_markets if m.get("series_ticker")}
                    | set(tracked_series)
                )[:TRACKED_SERIES_LIMIT],
                "request_count": client.request_count,
                "errors": errors[:20],
            },
        )

    log.info(
        "cycle done: %d markets, %d alerts, %d picks, equity $%.2f, %d errors",
        len(all_markets),
        len(alerts),
        len(picks),
        paper_snapshot["equity"],
        len(errors),
    )
    return latest


def _update_history(
    settings: Settings,
    history: dict[str, list[list[float]]],
    markets: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    now: int,
    extra_samples: list[dict[str, float]],
) -> None:
    alert_tickers = {a["ticker"] for a in alerts}
    ranked = sorted(markets, key=lambda m: m.get("notional_24h_est") or 0, reverse=True)
    keep = {m["ticker"] for m in ranked[: settings.history_markets]} | alert_tickers
    ledger = PaperLedger.load(settings)
    keep |= {p["ticker"] for p in ledger.positions.values()}

    for market in markets:
        ticker = market["ticker"]
        if ticker not in keep:
            continue
        points = history.setdefault(ticker, [])
        for index, sample in enumerate(extra_samples):
            if ticker in sample:
                offset = int(settings.sample_gap_s * (len(extra_samples) - index))
                points.append(
                    [now - offset, round(float(sample[ticker]), 4), None, None, None, None]
                )
        points.append(
            [
                now,
                round(float(market.get("price") or 0), 4),
                market.get("yes_bid"),
                market.get("yes_ask"),
                market.get("volume_24h"),
                market.get("open_interest"),
            ]
        )
    trimmed = store.trim_history(history, keep, settings.history_points)
    store.write_json(settings.data_dir / "history.json", {"generated_at": _iso(now), "series": trimmed})


PUBLISH_DROP = (
    "series_title",
    "event_title",
    "yes_sub_title",
    "no_sub_title",
    "expected_expiration_time",
    "previous",
    "no_bid",
    "no_ask",
    "oi_dollars_est",
    "top_book_dollars_est",
    "orderbook_url",
)


def _publish_market(market: dict[str, Any]) -> dict[str, Any]:
    """Drop duplicated/derived fields from the published snapshot (bisected against the site)."""
    return {k: v for k, v in market.items() if k not in PUBLISH_DROP}


def _collect_resolutions(
    client: RestClient,
    current_markets: dict[str, dict[str, Any]],
    series_by_topic: dict[str, list[str]],
    existing: list[dict[str, Any]],
    errors: list[str],
    now: int,
) -> list[dict[str, Any]]:
    items = {item.get("ticker"): item for item in existing if item.get("ticker")}

    # markets that settled while we were watching them
    for market in current_markets.values():
        if market.get("result") in {"yes", "no"}:
            items[market["ticker"]] = _resolution_row(market)

    # settled markets for the series we follow (bounded sweep)
    series = sorted({s for lst in series_by_topic.values() for s in lst})[:10]
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=21)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for series_ticker in series:
        try:
            raw = client.paginate(
                "/markets",
                "markets",
                {"series_ticker": series_ticker, "status": "settled", "min_close_ts": int(_parse_iso(cutoff) or 0)},
                page_size=100,
                max_pages=1,
            )
        except Exception as exc:
            errors.append(f"settled {series_ticker}: {type(exc).__name__}: {exc}")
            continue
        for market in raw:
            if market.get("result") not in {"yes", "no"}:
                continue
            items[market.get("ticker")] = _resolution_row(
                normalize_market(market, api_base="")
            )
    rows = sorted(items.values(), key=lambda r: r.get("settled_ts") or r.get("close_time") or "", reverse=True)
    # keep the payload bounded; the newest 400 settlements are plenty for the tracker
    return rows[:400]


def _resolution_row(market: dict[str, Any]) -> dict[str, Any]:
    result = (market.get("result") or "").lower()
    return {
        "ticker": market.get("ticker"),
        "title": market.get("title"),
        "topic": market.get("topic"),
        "series_ticker": market.get("series_ticker"),
        "result": result,
        "resolution": "YES" if result == "yes" else ("NO" if result == "no" else None),
        "close_time": market.get("close_time"),
        "settled_ts": market.get("settlement_ts") or market.get("close_time"),
        "found_at": _iso(),
        "settlement_value": market.get("settlement_value_dollars"),
        "api_url": market.get("api_url"),
        "series_page_url": market.get("series_page_url"),
        "source": "https://docs.kalshi.com/getting_started/market_settlement",
    }
