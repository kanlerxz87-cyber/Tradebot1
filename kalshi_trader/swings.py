"""Sudden-swing detection.

Rule (from the brief): an alert fires when a contract price moves **at least $0.10** in
either direction. The comparison basis is the market midpoint (best YES bid/ask midpoint)
because Kalshi's REST snapshot can lag several seconds and the midpoint is the most stable
observable price; when a midpoint cannot be formed the last traded price is used and the
alert records ``basis="last"``.

Floating point note: comparisons use a tolerance so that exactly $0.10 (e.g. 0.55 → 0.65,
which is 0.09999999999999998 in binary floating point) still fires.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Iterable

from . import catalysts

TOLERANCE = 1e-9


def _alert_id(ticker: str, ts: int, direction: str) -> str:
    raw = f"{ticker}|{ts}|{direction}".encode()
    return hashlib.sha1(raw).hexdigest()[:12]


def iso(ts: int | float) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_alert(
    market: dict[str, Any],
    from_price: float,
    to_price: float,
    ts: int,
    *,
    threshold: float = 0.10,
    basis: str = "mid",
    series_meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return an alert dict when ``|to_price - from_price| >= threshold``, else ``None``."""
    if from_price is None or to_price is None:
        return None
    delta = round(to_price - from_price, 4)
    if abs(delta) + TOLERANCE < threshold:
        return None
    direction = "up" if delta > 0 else "down"
    pct = (delta / from_price * 100.0) if from_price else None
    return {
        "id": _alert_id(market.get("ticker", ""), ts, direction),
        "ts": ts,
        "iso": iso(ts),
        "ticker": market.get("ticker"),
        "topic": market.get("topic"),
        "title": market.get("title"),
        "subtitle": market.get("subtitle"),
        "series_ticker": market.get("series_ticker"),
        "direction": direction,
        "from_price": round(from_price, 4),
        "to_price": round(to_price, 4),
        "delta": delta,
        "abs_delta": abs(delta),
        "pct_change": round(pct, 2) if pct is not None else None,
        "basis": basis,
        "price": market.get("price"),
        "yes_bid": market.get("yes_bid"),
        "yes_ask": market.get("yes_ask"),
        "spread": market.get("spread"),
        "volume_24h": market.get("volume_24h"),
        "open_interest": market.get("open_interest"),
        "top_book_contracts": market.get("top_book_contracts"),
        "close_time": market.get("close_time"),
        "api_url": market.get("api_url"),
        "series_page_url": market.get("series_page_url"),
        "threshold": threshold,
        # Links a reader can open next to the move: Kalshi's own contract links, plus
        # time-boxed search queries. Never a claim about what caused the move.
        "catalysts": catalysts.for_market(market, series_meta, iso=iso(ts)),
    }


def detect(
    markets: Iterable[dict[str, Any]],
    last_points: dict[str, list[float]],
    ts: int,
    *,
    threshold: float = 0.10,
    series_meta: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Compare each market's current price to the last recorded price.

    ``last_points`` maps ``ticker -> [price, basis_used]`` and is the state carried between
    collection cycles, so a swing that happens between two runs is still caught.
    """
    alerts: list[dict[str, Any]] = []
    for market in markets:
        ticker = market.get("ticker")
        if not ticker:
            continue
        previous = last_points.get(ticker)
        if not previous:
            continue
        from_price = previous[0]
        basis = "mid" if market.get("mid") is not None else "last"
        to_price = market.get("mid") if market.get("mid") is not None else market.get("last")
        meta = (series_meta or {}).get(str(market.get("series_ticker") or ""))
        alert = build_alert(
            market, from_price, to_price, ts, threshold=threshold, basis=basis, series_meta=meta
        )
        if alert:
            alerts.append(alert)
    alerts.sort(key=lambda a: a["abs_delta"], reverse=True)
    return alerts
