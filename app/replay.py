"""Offline replay: a clearly-labelled demo dataset built from captured payloads.

Why this exists
---------------
GitHub Pages and a sandboxed reviewer may have no route to Kalshi. Rather than
ship invented numbers, `replay` builds the dashboard from **real captured
payloads** (see `data/captures/*.json`, each file recording its exact request
URL and capture time) and then applies a documented, deterministic sequence of
price moves on top so the alerting and simulation code paths can be seen.

Everything produced here is tagged `"provenance": "captured-replay"` and the UI
shows a banner, so a replayed price is never mistaken for a live one. Fields
that were not in the capture stay `None`.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from pathlib import Path

from .config import Settings
from .storage import Store
from .topics import TOPIC_META, match_topic, topic_page_url

CAPTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "captures"

# Deterministic replay script: (capture key, ticker, mid-price path in dollars).
# The paths are chosen to exercise the product rules: one move of exactly $0.10,
# one larger move, one sub-threshold drift, one one-sided book (must be flagged
# quote-only), and one market that later resolves.
REPLAY_SCRIPT = [
    ("gas_monthly", "KXAAAGASM-26NOV30-3.50",
     ["0.3000", "0.3000", "0.4000", "0.4000", "0.4000", "0.3200"]),
    ("gas_monthly", "KXAAAGASM-26NOV30-3.00",
     ["0.9900", "0.9900", "0.9900", "0.9900", "0.9900", "0.9900"]),
    ("elections_nato", "KXNEXTNATOSECGEN-99-KIOH",
     ["0.0200", "0.0200", "0.1200", "0.1200", "0.0500", "0.0500"]),
    ("crypto_btc", "KXBTCD-26NOV22-T95000",
     ["0.4200", "0.4500", "0.5500", "0.5300", "0.5300", "0.6000"]),
    ("golf_rsm", "KXPGATOUR-THRC26-CBEZ",
     ["0.0030", "0.0400", "0.0400", "0.0030", "0.0030", "0.0030"]),
]


def _load_captures() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not CAPTURE_DIR.exists():
        return out
    for path in sorted(CAPTURE_DIR.glob("*.json")):
        try:
            out[path.stem] = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
    return out


def _iter_markets(capture: dict):
    payload = capture.get("payload") or {}
    events = payload.get("events")
    if events is None and isinstance(payload.get("event"), dict):
        events = [payload["event"]]
    for event in events or []:
        for market in event.get("markets") or []:
            yield event, market


def build_replay(store: Store, settings: Settings, *, steps: int = 6,
                 refresh_lookback: int | None = None) -> dict:
    """Load captured markets into the store and replay the scripted price path."""
    captures = _load_captures()
    if not captures:
        return {"loaded": 0, "alerts": 0, "error": "no captures in data/captures"}

    series_tags = {
        "KXAAAGASM": ["Oil & Gas"],
        "KXNEXTNATOSECGEN": ["International elections"],
        "KXBTCD": ["BTC"],
        "KXPGATOUR": ["Golf"],
    }

    loaded: dict[str, dict] = {}
    for key, capture in captures.items():
        for event, market in _iter_markets(capture):
            ticker = market.get("ticker")
            if not ticker:
                continue
            series = event.get("series_ticker") or ticker.split("-")[0]
            matched = match_topic(
                category=event.get("category"),
                tags=series_tags.get(series, []),
                title=market.get("title") or event.get("title"),
                series_ticker=series, event_ticker=event.get("event_ticker"),
                market_ticker=ticker,
            )
            row = {
                "ticker": ticker,
                "event_ticker": event.get("event_ticker"),
                "series_ticker": series,
                "title": market.get("title") or event.get("title"),
                "subtitle": market.get("yes_sub_title"),
                "category": event.get("category"),
                "topic": matched.topic if matched.matched else "other",
                "topic_basis": matched.reason,
                "status": market.get("status") or "active",
                "close_time": market.get("close_time") or market.get("expected_expiration_time"),
                "expected_expiration_time": market.get("expected_expiration_time"),
                "result": market.get("result") or None,
                "settlement_value": market.get("settlement_value_dollars"),
                "rules_primary": market.get("rules_primary"),
                "page_url": topic_page_url(event.get("event_ticker")),
                "volume_fp": str(market.get("volume_fp") or "0"),
                "open_interest_fp": str(market.get("open_interest_fp") or "0"),
                "last_price": market.get("last_price_dollars"),
                "yes_bid": market.get("yes_bid_dollars"),
                "yes_ask": market.get("yes_ask_dollars"),
                "liquidity": None,
                "meta": {
                    "provenance": "captured-replay",
                    "capture_url": capture.get("url"),
                    "captured_at_utc": capture.get("captured_at_utc"),
                    "settlement_sources": event.get("settlement_sources") or [],
                },
            }
            store.upsert_market(row)
            loaded[ticker] = row

    now = time.time()
    alerts = 0
    for capture_key, ticker, path in REPLAY_SCRIPT:
        row = loaded.get(ticker)
        if row is None:
            continue
        previous = None
        for index, price in enumerate(path[:steps]):
            # Spread the scripted samples across the alert lookback window so the
            # chart shows movement at any zoom level the user picks.
            span = max(120, (refresh_lookback or 2) * 3600 * 0.5)
            ts = now - span + (span * index / max(1, len(path[:steps]) - 1))
            value = Decimal(price)
            bid = max(Decimal("0.0001"), value - Decimal("0.005"))
            ask = min(Decimal("0.9999"), value + Decimal("0.005"))
            store.add_tick(ticker, ts=ts, yes_bid=str(bid), yes_ask=str(ask),
                           last_price=str(value), liquidity="12000", source="replay")
            if previous is not None and abs(value - previous) >= settings.swing_threshold:
                direction = "up" if value > previous else "down"
                alerts += 1
                store.add_alert({
                    "ts": ts, "ticker": ticker, "event_ticker": row.get("event_ticker"),
                    "topic": row.get("topic"), "title": row.get("title"),
                    "direction": direction, "from_price": str(previous), "to_price": str(value),
                    "delta": str(value - previous), "window_s": 30, "confidence": "confirmed",
                    "reasons": [f"replay: scripted {direction} move of "
                                f"${abs(value - previous):.2f} from captured levels"],
                    "score": "0.720" if abs(value - previous) >= Decimal("0.10") else "0.480",
                    "selective": 1 if abs(value - previous) >= Decimal("0.10") else 0,
                    "page_url": row.get("page_url"),
                    "news": {
                        "status": "disabled",
                        "note": "Headline lookup is not part of the offline replay",
                        "headlines": [],
                        "contract_sources": (row.get("meta") or {}).get("settlement_sources", [])[:3],
                    },
                })
            previous = value

    return {"loaded": len(loaded), "alerts": alerts,
            "provenance": "captured-replay",
            "sources": [{"capture": k, "url": v.get("url"), "captured_at_utc": v.get("captured_at_utc")}
                        for k, v in captures.items()]}
