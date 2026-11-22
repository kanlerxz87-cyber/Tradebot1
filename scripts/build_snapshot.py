"""Bounded public demo-API snapshot for the market monitor (docs/).

Design rules, learned from the first version of this script:
  * A single failed request must never throw away the events already collected.
  * An empty result must never be published in place of a good snapshot.
  * Both documented demo hosts are tried, because either may be unreachable from a runner.
  * Every failure is reported (`::warning::` / `error` field) instead of swallowed.

Public endpoints only: no API key, no secrets, no authenticated call is made here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Both hosts are published by Kalshi as valid for the demo environment:
# https://docs.kalshi.com/getting_started/api_environments
BASES = (
    "https://external-api.demo.kalshi.co/trade-api/v2",
    "https://demo-api.kalshi.co/trade-api/v2",
)
OUT = Path("docs/data/snapshot.json")

PATTERNS = [
    r"\b(gasoline|gas prices?|gallon of gas|pump prices?)\b",
    r"\b(bitcoin|ethereum|ether|crypto|dogecoin|solana|btc|eth)\b",
    r"\b(golf|pga|masters|ryder cup|us open golf|open championship)\b",
    r"\b(grammy|oscar|emmy|movie|film|music|album|artist|celebrity|box office|tv show|television|tiktok|youtube)\b",
]
ELECTION = r"\b(elect\w*|vot\w*|ballot|presiden\w*|senat\w*|governor\w*|mayor\w*|congress\w*|primary|party)\b"
FIELDS = (
    "ticker", "event_ticker", "title", "status", "result", "last_price_dollars",
    "yes_bid_dollars", "yes_ask_dollars", "yes_bid_size_fp", "yes_ask_size_fp",
    "volume_24h_fp", "volume_fp", "close_time", "rules_primary",
)
EVENT_FIELDS = ("event_ticker", "series_ticker", "title", "category", "settlement_sources")

MAX_EVENT_PAGES = 4
MAX_MARKET_PAGES = 2
MAX_CANDIDATES = 400
EVENT_BATCH = 50
TIMEOUT = 25
RETRIES = 2
RETRY_SLEEP = 0.6  # seconds between attempts; tests set this to 0


def matches(event: dict) -> bool:
    title = str(event.get("title") or "").lower()
    if any(re.search(pattern, title) for pattern in PATTERNS):
        return True
    return event.get("category", "").lower() == "elections" and bool(re.search(ELECTION, title))


def request(base: str, path: str, params: dict) -> dict:
    """One GET with a bounded retry. Raises the last error if every attempt fails."""
    url = base + path + "?" + urllib.parse.urlencode(params)
    last: Exception | None = None
    for attempt in range(RETRIES + 1):
        req = urllib.request.Request(url, headers={"User-Agent": "Tradebot1-public-research/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code < 500:  # a 4xx will not improve on retry
                break
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
        if attempt < RETRIES:
            time.sleep(RETRY_SLEEP * (attempt + 1))
    raise RuntimeError(f"{path} failed after {RETRIES + 1} attempt(s): {last}")


def add_event(events: dict, event: dict, markets: list) -> None:
    if not matches(event) or not markets:
        return
    ticker = event.get("event_ticker")
    if not ticker:
        return
    if ticker not in events:
        events[ticker] = {key: event[key] for key in EVENT_FIELDS if key in event} | {"markets": []}
    known = {m["ticker"] for m in events[ticker]["markets"]}
    events[ticker]["markets"].extend(
        {key: m[key] for key in FIELDS if key in m}
        for m in markets if m.get("ticker") and m["ticker"] not in known
    )


def collect(base: str) -> dict:
    """Scan one host. Returns collected events plus counters and any request errors."""
    events: dict = {}
    errors: list[str] = []
    event_cursor = ""
    market_cursor = ""
    event_pages = 0
    market_pages = 0
    partial = False

    try:
        while event_pages < MAX_EVENT_PAGES:
            params = {"limit": 200, "status": "open", "with_nested_markets": "true"}
            if event_cursor:
                params["cursor"] = event_cursor
            data = request(base, "/events", params)
            event_pages += 1
            for event in data.get("events", []):
                add_event(events, event, event.get("markets", []))
            event_cursor = data.get("cursor") or ""
            if not event_cursor:
                break
            time.sleep(0.25)
    except Exception as exc:  # noqa: BLE001 - reported, never raised past this function
        errors.append(f"/events: {exc}")
        partial = True

    newest: list = []
    try:
        while market_pages < MAX_MARKET_PAGES:
            params = {"limit": 1000, "status": "open"}
            if market_cursor:
                params["cursor"] = market_cursor
            try:
                data = request(base, "/markets", params | {"mve_filter": "exclude"})
            except RuntimeError:
                # Some deployments reject the optional filter; retry once without it rather than
                # losing the whole page of markets.
                data = request(base, "/markets", params)
            market_pages += 1
            newest.extend(data.get("markets", []))
            market_cursor = data.get("cursor") or ""
            if not market_cursor:
                break
            time.sleep(0.25)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"/markets: {exc}")
        partial = True

    def activity(market: dict) -> float:
        try:
            return float(market.get("last_price_dollars") or 0) * float(market.get("volume_24h_fp") or 0)
        except (TypeError, ValueError):
            return 0.0

    candidates = sorted(newest, key=activity, reverse=True)[:MAX_CANDIDATES]
    if candidates:
        by_event: dict[str, list] = {}
        for market in candidates:
            by_event.setdefault(market.get("event_ticker"), []).append(market)
        ids = [key for key in dict.fromkeys(by_event) if key]
        for start in range(0, len(ids), EVENT_BATCH):
            batch = ids[start:start + EVENT_BATCH]
            try:
                data = request(base, "/events", {"tickers": ",".join(batch)})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"/events(tickers): {exc}")
                partial = True
                continue
            for event in data.get("events", []):
                add_event(events, event, by_event.get(event.get("event_ticker"), []))
            time.sleep(0.25)

    return {
        "events": events,
        "event_pages": event_pages,
        "market_pages": market_pages,
        "more_events": bool(event_cursor),
        "more_markets": bool(market_cursor),
        "partial": partial,
        "errors": errors,
    }


def build(bases=BASES) -> dict:
    """Try each documented host in order and keep the first that returns any event."""
    errors: list[str] = []
    result = None
    for base in bases:
        outcome = collect(base)
        errors.extend(f"{base} {message}" for message in outcome["errors"])
        if result is None or (not result["events"] and outcome["events"]):
            result = outcome
        if outcome["events"]:
            break
    result = result or {"events": {}, "event_pages": 0, "market_pages": 0,
                        "more_events": False, "more_markets": False, "partial": True, "errors": []}

    events = list(result["events"].values())
    partial = bool(result["partial"] or result["more_events"] or result["more_markets"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat() if events else None,
        "partial": partial,
        "scanned_event_pages": result["event_pages"],
        "scanned_market_pages": result["market_pages"],
        "hosts_tried": list(bases),
        "error": errors[0] if errors else None,
        "errors": errors,
        "events": events,
    }


def read_previous(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT), help="output JSON path")
    parser.add_argument("--require-data", action="store_true",
                        help="exit non-zero when no event was collected (for a dedicated check step)")
    args = parser.parse_args(argv)

    out = Path(args.out)
    snapshot = build()
    previous = read_previous(out)

    if snapshot["events"]:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"Snapshot: {snapshot['scanned_event_pages']} event pages, "
              f"{snapshot['scanned_market_pages']} market pages, {len(snapshot['events'])} matching events, "
              f"partial={snapshot['partial']}, errors={len(snapshot['errors'])}")
    elif previous.get("events"):
        # Keep the last good snapshot. Publishing an empty page would look like a working site
        # with no markets, which is worse than slightly stale data with an honest timestamp.
        print("::warning::no events collected this run — keeping the previous snapshot "
              f"({len(previous['events'])} events, generated {previous.get('generated_at')})")
        for message in snapshot["errors"]:
            print(f"::warning::{message}")
    else:
        stub = dict(snapshot)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(stub, separators=(",", ":")) + "\n", encoding="utf-8")
        print("::error::no events collected and no previous snapshot to fall back on")
        for message in snapshot["errors"]:
            print(f"::error::{message}")

    if args.require_data and not snapshot["events"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
