"""Bounded, source-linked PUBLIC demo observations. Never reads account credentials.

Published snapshots are explicitly not live, not a complete ranking, and never
substitute a price×volume estimate for reported dollars. Last-known observations
retain their original timestamps when a refresh fails.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Use the same explicit series classifier as the demo service (stdlib-only module).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.kalshi.kalshi_demo.domain import classify_series  # noqa: E402

BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
OUT = Path("docs/data/snapshot.json")
TOPICS = ("gas", "elections", "culture", "crypto", "golf")
FIELDS = (
    "ticker", "event_ticker", "title", "yes_sub_title", "status", "result", "market_type",
    "last_price_dollars", "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars",
    "yes_bid_size_fp", "yes_ask_size_fp", "volume_24h_fp", "volume_fp", "open_interest_fp",
    "notional_value_dollars", "dollar_volume", "dollar_open_interest", "close_time", "updated_time",
    "settlement_value_dollars", "settlement_ts", "settlement_bounds_type", "rules_primary", "rules_secondary",
)


def utc():
    return datetime.now(timezone.utc).isoformat()


def activity(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number >= 0 else Decimal(-1)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(-1)


def fetch(path, params):
    query = urllib.parse.urlencode(params)
    url = BASE + path + ("?" + query if query else "")
    for attempt in range(3):
        time.sleep(.35)
        request = urllib.request.Request(url, headers={"User-Agent": "Tradebot1-public-research/2.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.load(response)
                if not isinstance(payload, dict):
                    raise ValueError("Response is not an object")
                return payload
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise ValueError("Read retries exhausted")


def add_event(events, event, series):
    metadata = series.get(event.get("series_ticker"))
    if not metadata:
        return
    topic, rule = classify_series(metadata)
    ticker, markets = event.get("event_ticker"), event.get("markets")
    if topic not in TOPICS or not ticker or not isinstance(markets, list):
        return
    received = utc()
    existing = events.get(ticker, {"markets": []})
    record = {key: event[key] for key in ("event_ticker", "series_ticker", "title", "settlement_sources") if key in event}
    record.update(topic=topic, topic_rule=rule,
                  settlement_sources=event.get("settlement_sources") or metadata.get("settlement_sources") or [],
                  settlement_sources_from="event" if event.get("settlement_sources") else "series",
                  series_metadata={key: metadata.get(key) for key in ("title", "category", "tags")},
                  series_source_url=BASE + "/series/" + urllib.parse.quote(metadata["ticker"], safe=""),
                  source_url=BASE + "/events/" + urllib.parse.quote(ticker, safe=""),
                  observed_at=received, markets=existing["markets"])
    known = {market["ticker"] for market in record["markets"]}
    for market in markets:
        if not isinstance(market, dict) or not market.get("ticker") or market["ticker"] in known:
            continue
        row = {key: market[key] for key in FIELDS if key in market}
        row.update(source_url=BASE + "/markets/" + urllib.parse.quote(market["ticker"], safe=""),
                   observed_at=received, verification="official_public_demo_api_observation")
        record["markets"].append(row)
        known.add(market["ticker"])
    events[ticker] = record


def collect():
    series_payload = fetch("/series", {"include_volume": "true"})
    raw_series = series_payload.get("series")
    if not isinstance(raw_series, list):
        raise ValueError("series field missing")
    series = {row["ticker"]: row for row in raw_series if isinstance(row, dict) and row.get("ticker")}
    events, failures, pages, sampled_series = {}, [], 0, []
    # Six highest reported cumulative CONTRACT-volume series per topic. This selects a
    # bounded discovery sample; it is not a highest-dollar or complete exchange scan.
    for topic in TOPICS:
        candidates = [row for row in series.values() if classify_series(row)[0] == topic]
        candidates.sort(key=lambda row: activity(row.get("volume_fp")), reverse=True)
        for metadata in candidates[:6]:
            sampled_series.append(metadata["ticker"])
            try:
                data = fetch("/events", {"series_ticker": metadata["ticker"], "status": "open",
                                         "with_nested_markets": "true", "limit": 200})
                pages += 1
                if not isinstance(data.get("events"), list):
                    raise ValueError("events field missing")
                for event in data["events"]:
                    add_event(events, event, series)
            except (OSError, ValueError) as error:
                failures.append({"series": metadata["ticker"], "error": type(error).__name__,
                                 "source_url": BASE + "/series/" + urllib.parse.quote(metadata["ticker"], safe="")})
    # Also discover newly-created/highly-active markets that a lifetime-series-volume
    # preference might miss; raw contract volume is only a scan priority, never dollars.
    newest = fetch("/markets", {"status": "open", "mve_filter": "exclude", "limit": 1000})
    candidate_rows = newest.get("markets")
    if not isinstance(candidate_rows, list):
        raise ValueError("markets field missing")
    candidate_rows.sort(key=lambda row: activity(row.get("volume_24h_fp")), reverse=True)
    event_ids = list(dict.fromkeys(row.get("event_ticker") for row in candidate_rows[:250] if row.get("event_ticker")))
    for start in range(0, len(event_ids), 50):
        data = fetch("/events", {"tickers": ",".join(event_ids[start:start + 50]), "with_nested_markets": "true", "limit": 200})
        pages += 1
        for event in data.get("events", []):
            add_event(events, event, series)
    kept = []
    for topic in TOPICS:
        matching = [event for event in events.values() if event["topic"] == topic]
        matching.sort(key=lambda event: sum((max(Decimal(0), activity(market.get("volume_24h_fp")))
                                              for market in event["markets"]), Decimal(0)), reverse=True)
        for event in matching[:8]:
            # Preserve event grouping and disclose child-market truncation explicitly.
            event["total_scanned_markets"] = len(event["markets"])
            event["markets"] = sorted(event["markets"], key=lambda row: activity(row.get("volume_24h_fp")), reverse=True)[:8]
            event["markets_partial"] = len(event["markets"]) < event["total_scanned_markets"]
            if event["markets"]:
                kept.append(event)
    # A small, explicit historical fallback keeps the chart useful without fabricating
    # samples. These depth/candle snapshots retain their own original source timestamps.
    for topic in TOPICS:
        candidates = [(market, event) for event in kept if event["topic"] == topic
                      for market in event["markets"] if market.get("status") == "active"]
        candidates.sort(key=lambda pair: (Decimal("0.02") < activity(pair[0].get("last_price_dollars")) < Decimal("0.98"),
                                          activity(pair[0].get("volume_24h_fp"))), reverse=True)
        for market, event in candidates[:2]:
            ticker = urllib.parse.quote(market["ticker"], safe="")
            series_ticker = urllib.parse.quote(event["series_ticker"], safe="")
            market["history_snapshots"] = {}
            for name, period, seconds in (("minutes", 1, 3600), ("hours", 60, 86400)):
                end = int(time.time())
                path = f"/series/{series_ticker}/markets/{ticker}/candlesticks"
                params = {"start_ts": end - seconds, "end_ts": end, "period_interval": period}
                try:
                    candles = fetch(path, params)
                    if not isinstance(candles.get("candlesticks"), list):
                        raise ValueError("candlesticks field missing")
                    market["history_snapshots"][name] = {
                        "candlesticks": [{"end_period_ts": row.get("end_period_ts"),
                                          "price": {"close_dollars": row.get("price", {}).get("close_dollars")}}
                                         for row in candles["candlesticks"]],
                        "observed_at": utc(), "source_url": BASE + path + "?" + urllib.parse.urlencode(params),
                    }
                except (OSError, ValueError, TypeError) as error:
                    failures.append({"ticker": market["ticker"], "error": type(error).__name__, "source_url": BASE + path})
            try:
                path = f"/markets/{ticker}/orderbook"
                book = fetch(path, {"depth": 7})
                if isinstance(book.get("orderbook_fp"), dict):
                    market["orderbook_snapshot"] = {"orderbook_fp": book["orderbook_fp"],
                        "observed_at": utc(), "source_url": BASE + path + "?depth=7"}
            except (OSError, ValueError) as error:
                failures.append({"ticker": market["ticker"], "error": type(error).__name__, "source_url": BASE + path})
    return {
        "generated_at": utc(), "partial": True, "mode": "published_official_demo_snapshot_not_live",
        "scanned_event_pages": pages, "scanned_series": len(sampled_series), "errors": failures,
        "coverage_note": "Bounded series/new-market sample; max 8 events per topic and 8 contracts per event. Not a complete exchange ranking.",
        "ranking_note": "REST snapshot sorts by reported 24h contract count. Reported dollar notional is blank unless supplied; no price×volume turnover estimate.",
        "source_url": BASE + "/events", "events": kept,
    }


def main():
    try:
        result = collect()
    except (OSError, ValueError, KeyError, TypeError) as error:
        try:
            result = json.loads(OUT.read_text())
        except (OSError, ValueError):
            result = {"generated_at": None, "partial": True, "events": []}
        result.update(last_refresh_error=type(error).__name__, attempted_at=utc(), partial=True)
        print("Public snapshot refresh unavailable; retaining original observation times:", type(error).__name__)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    print("Snapshot:", len(result.get("events", [])), "events; timestamp:", result.get("generated_at"), "; partial:", result["partial"])


if __name__ == "__main__":
    main()
