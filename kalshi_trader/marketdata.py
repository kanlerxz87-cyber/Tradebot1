"""Normalisation of Kalshi payloads into the flat shape the dashboard consumes.

Field names verified against ``GET /markets`` (responses in this session showed
``yes_bid_dollars``, ``yes_ask_dollars``, ``no_bid_dollars``, ``no_ask_dollars``,
``last_price_dollars``, ``previous_price_dollars``, ``volume_fp``, ``volume_24h_fp``,
``open_interest_fp``, ``yes_bid_size_fp``, ``yes_ask_size_fp``, ``result``, ``status``)
and against https://docs.kalshi.com/getting_started/orderbook_responses for the book.

All prices are dollars in ``[0, 1]``. All sizes are contract counts.
Derived values are marked with a ``*_est`` suffix or listed in ``DERIVED_FIELDS`` so the
site never presents a computed number as an exchange-reported one.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

#: Fields computed by this repository (not returned by Kalshi verbatim).
DERIVED_FIELDS = {
    "mid": "midpoint of best YES bid and best YES ask",
    "spread": "best YES ask − best YES bid",
    "notional_24h_est": "volume_24h × last price (estimated 24h traded notional)",
    "oi_dollars_est": "open interest × last price (estimated open-interest notional)",
    "top_book_contracts": "yes_bid_size + yes_ask_size at top of book",
    "top_book_dollars_est": "size-weighted top-of-book notional",
}


def to_float(value: Any) -> float | None:
    """Parse a fixed-point string/number, returning ``None`` for empty values."""
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def first_float(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in payload:
            value = to_float(payload.get(key))
            if value is not None:
                return value
    return None


def price_from_cents(payload: dict[str, Any], *keys: str) -> float | None:
    """Fallback for legacy cent-denominated fields (``yes_bid`` = 42 → $0.42)."""
    for key in keys:
        raw = payload.get(key)
        if raw is None or raw == "":
            continue
        value = to_float(raw)
        if value is not None:
            return round(value / 100.0, 4)
    return None


def normalize_market(
    market: dict[str, Any],
    *,
    topic: str | None = None,
    series_ticker: str | None = None,
    series_title: str | None = None,
    event_title: str | None = None,
    api_base: str = "",
) -> dict[str, Any]:
    """Flatten one market object into the dashboard schema."""
    yes_bid = first_float(market, "yes_bid_dollars") or price_from_cents(market, "yes_bid") or 0.0
    yes_ask = first_float(market, "yes_ask_dollars") or price_from_cents(market, "yes_ask")
    no_bid = first_float(market, "no_bid_dollars") or price_from_cents(market, "no_bid")
    no_ask = first_float(market, "no_ask_dollars") or price_from_cents(market, "no_ask")
    last = first_float(market, "last_price_dollars") or price_from_cents(market, "last_price")
    prev = first_float(market, "previous_price_dollars") or price_from_cents(market, "previous_price")

    # Implied ask from the opposite side of the book when the API omits it.
    if yes_ask is None and no_bid is not None:
        yes_ask = round(1.0 - no_bid, 4)
    if no_ask is None and yes_bid is not None:
        no_ask = round(1.0 - yes_bid, 4)

    # An empty side is quoted as an extreme, not omitted. A YES offer can only rest
    # against a NO bid (yes_ask = 1 - best no_bid), so when there is no NO bid the
    # reported 1.0000 is the empty-side sentinel. Left in place it would put the
    # midpoint halfway to $1.00: every one of the eight markets in this repository's
    # committed demo capture (data/snapshot.json) reports yes_ask 1.0000 with an
    # empty NO book, so the phantom midpoint is the normal case here.
    # Source: https://docs.kalshi.com/getting_started/orderbook_responses
    if yes_ask is not None and yes_ask >= 1.0 and not no_bid:
        yes_ask = None
    if no_ask is not None and no_ask >= 1.0 and not yes_bid:
        no_ask = None

    if yes_ask is not None and yes_bid is not None and yes_ask >= yes_bid:
        mid = round((yes_ask + yes_bid) / 2.0, 4)
    elif last is not None:
        mid = last
    else:
        mid = yes_bid if yes_bid is not None else None

    price = mid if mid is not None else (last or 0.0)
    spread = None
    if yes_ask is not None and yes_bid is not None:
        spread = round(max(0.0, yes_ask - yes_bid), 4)

    volume = first_float(market, "volume_fp", "volume") or 0.0
    volume_24h = first_float(market, "volume_24h_fp", "volume_24h") or 0.0
    open_interest = first_float(market, "open_interest_fp", "open_interest") or 0.0
    yes_bid_size = first_float(market, "yes_bid_size_fp", "yes_bid_size") or 0.0
    yes_ask_size = first_float(market, "yes_ask_size_fp", "yes_ask_size") or 0.0

    ticker = str(market.get("ticker") or "")
    series = series_ticker or str(market.get("series_ticker") or "") or _series_from_ticker(ticker)
    return {
        "ticker": ticker,
        "event_ticker": market.get("event_ticker"),
        "series_ticker": series,
        "series_title": series_title,
        "event_title": event_title,
        "market_type": market.get("market_type") or "binary",
        "title": market.get("title") or event_title or ticker,
        "subtitle": market.get("subtitle") or market.get("yes_sub_title") or "",
        "yes_sub_title": market.get("yes_sub_title") or "",
        "no_sub_title": market.get("no_sub_title") or "",
        "topic": topic,
        "status": market.get("status"),
        "result": (market.get("result") or "").lower() or None,
        "open_time": market.get("open_time"),
        "close_time": market.get("close_time"),
        "expected_expiration_time": market.get("expected_expiration_time"),
        "settlement_ts": market.get("settlement_ts"),
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "last": last,
        "previous": prev,
        "mid": mid,
        "price": round(price, 4),
        "spread": spread,
        "yes_bid_size": yes_bid_size,
        "yes_ask_size": yes_ask_size,
        "volume": volume,
        "volume_24h": volume_24h,
        "open_interest": open_interest,
        "notional_24h_est": round(volume_24h * price, 2),
        "oi_dollars_est": round(open_interest * price, 2),
        "top_book_contracts": round(yes_bid_size + yes_ask_size, 2),
        "top_book_dollars_est": round(yes_bid_size * (yes_bid or price) + yes_ask_size * (yes_ask or price), 2),
        "rules_primary": market.get("rules_primary") or "",
        "strike_type": market.get("strike_type"),
        "floor_strike": market.get("floor_strike"),
        "cap_strike": market.get("cap_strike"),
        "series_page_url": _series_page_url(series),
        "api_url": f"{api_base}/markets/{ticker}" if api_base and ticker else None,
        "orderbook_url": f"{api_base}/markets/{ticker}/orderbook" if api_base and ticker else None,
    }


def _series_from_ticker(ticker: str) -> str:
    """Best-effort series prefix (never used as a classification source)."""
    return ticker.split("-")[0] if ticker else ""


def _series_page_url(series_ticker: str | None) -> str | None:
    """Series landing page. Pattern documented by Kalshi:
    https://kalshi.com/markets/kxhighny (docs.kalshi.com/getting_started/quick_start_market_data).
    """
    if not series_ticker:
        return None
    return f"https://kalshi.com/markets/{series_ticker.lower()}"


def normalize_orderbook(book: dict[str, Any], *, depth: int = 12) -> dict[str, Any]:
    """Convert ``orderbook_fp`` into explicit bid/ask ladders.

    Kalshi returns bids only; asks are the complement of the opposite side's bid, i.e.
    ``yes_ask = 1 - no_bid`` (https://docs.kalshi.com/getting_started/orderbook_responses).
    Arrays are ascending by price, best bid last.
    """
    yes = _levels(book.get("yes_dollars") or book.get("yes") or [])
    no = _levels(book.get("no_dollars") or book.get("no") or [])
    yes_bids = sorted(yes, key=lambda lvl: lvl["price"])
    no_bids = sorted(no, key=lambda lvl: lvl["price"])

    yes_asks = [
        {"price": round(1.0 - lvl["price"], 4), "contracts": lvl["contracts"]} for lvl in sorted(no_bids, key=lambda x: -x["price"])
    ]
    no_asks = [
        {"price": round(1.0 - lvl["price"], 4), "contracts": lvl["contracts"]} for lvl in sorted(yes_bids, key=lambda x: -x["price"])
    ]

    best_yes_bid = yes_bids[-1] if yes_bids else None
    best_yes_ask = yes_asks[0] if yes_asks else None
    return {
        "yes_bids": list(reversed(yes_bids))[:depth],
        "yes_asks": yes_asks[:depth],
        "no_bids": list(reversed(no_bids))[:depth],
        "no_asks": no_asks[:depth],
        "best_yes_bid": best_yes_bid,
        "best_yes_ask": best_yes_ask,
        "spread": (
            round(best_yes_ask["price"] - best_yes_bid["price"], 4)
            if best_yes_bid and best_yes_ask
            else None
        ),
        "yes_depth_contracts": round(sum(lvl["contracts"] for lvl in yes_bids), 2),
        "no_depth_contracts": round(sum(lvl["contracts"] for lvl in no_bids), 2),
    }


def _levels(raw: Iterable[Any]) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for level in raw or []:
        try:
            price, count = level[0], level[1]
        except (TypeError, IndexError):
            continue
        price_f = to_float(price)
        count_f = to_float(count)
        if price_f is None or count_f is None or price_f <= 0:
            continue
        # Legacy cent format (integers 1..99) — convert to dollars.
        if price_f > 1.0:
            price_f = price_f / 100.0
        out.append({"price": round(price_f, 4), "contracts": round(count_f, 2)})
    return out


def aggregate_events(markets: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group markets by event and rank by estimated traded notional."""
    events: dict[str, dict[str, Any]] = {}
    for market in markets:
        key = market.get("event_ticker") or market.get("ticker")
        bucket = events.setdefault(
            key,
            {
                "event_ticker": key,
                "topic": market.get("topic"),
                "title": market.get("event_title") or market.get("title"),
                "series_ticker": market.get("series_ticker"),
                "series_page_url": market.get("series_page_url"),
                "markets": [],
                "volume_24h": 0.0,
                "notional_24h_est": 0.0,
                "open_interest": 0.0,
                "close_time": market.get("close_time"),
            },
        )
        bucket["markets"].append(market["ticker"])
        bucket["volume_24h"] += market.get("volume_24h") or 0.0
        bucket["notional_24h_est"] += market.get("notional_24h_est") or 0.0
        bucket["open_interest"] += market.get("open_interest") or 0.0
        close_time = market.get("close_time")
        if close_time and (not bucket["close_time"] or close_time < bucket["close_time"]):
            bucket["close_time"] = close_time
    out = list(events.values())
    for item in out:
        item["markets_count"] = len(item["markets"])
        item["notional_24h_est"] = round(item["notional_24h_est"], 2)
        item["volume_24h"] = round(item["volume_24h"], 2)
        item["open_interest"] = round(item["open_interest"], 2)
    out.sort(key=lambda e: e["notional_24h_est"], reverse=True)
    return out
