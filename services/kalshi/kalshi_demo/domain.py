"""Pure normalization, categorization, decimal-safe alerts and orderbook logic."""

from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from urllib.parse import quote

from .config import DEFAULT_REST

D = Decimal
ONE = D("1")
THRESHOLD = D("0.10")


def decimal(value: Any, minimum: Decimal | None = None, maximum: Decimal | None = None) -> Decimal | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        number = D(str(value))
        if not number.is_finite() or (minimum is not None and number < minimum) or (
            maximum is not None and number > maximum
        ):
            return None
        return number
    except (InvalidOperation, ValueError, TypeError):
        return None


def number(value: Any, minimum: Decimal | None = None, maximum: Decimal | None = None) -> str | None:
    parsed = decimal(value, minimum, maximum)
    return format(parsed, "f") if parsed is not None else None


def iso_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def source_url(kind: str, ticker: str | None = None, base: str = DEFAULT_REST) -> str:
    return f"{base}/{kind}" + (f"/{quote(ticker, safe='')}" if ticker else "")


def classify_series(series: dict) -> tuple[str | None, str]:
    """Explicit local rules; an unmatched/ambiguous record is not guessed into a topic."""
    category = str(series.get("category", "")).lower()
    tags = series.get("tags") or []
    words = " ".join([str(series.get("title", "")), *[str(tag) for tag in tags]]).lower()
    matches = set()
    if category == "crypto" or re.search(r"\b(bitcoin|ethereum|cryptocurrency|crypto)\b", words):
        matches.add("crypto")
    if category == "culture":
        matches.add("culture")
    if re.search(r"\b(gasoline|gas prices?|gas price|gas at the pump)\b", words):
        matches.add("gas")
    if re.search(r"\b(elections?|electoral|presidential nominee|presidential nomination)\b", words):
        matches.add("elections")
    if re.search(r"\b(golf|pga|lpga)\b", words):
        matches.add("golf")
    if len(matches) != 1:
        return None, "unmatched" if not matches else "ambiguous"
    return matches.pop(), "local explicit-keyword rule over official series metadata; not an official taxonomy"


def normalize_market(raw: dict, topic: str, observed_ms: int, base: str = DEFAULT_REST) -> dict:
    ticker = raw.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        raise ValueError("Missing ticker")
    prices = ("last_price_dollars", "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars")
    counts = ("volume_fp", "volume_24h_fp", "open_interest_fp", "yes_bid_size_fp", "yes_ask_size_fp")
    result = {
        "ticker": ticker,
        "event_ticker": raw.get("event_ticker"),
        "title": raw.get("title"),
        "yes_sub_title": raw.get("yes_sub_title"),
        "topic": topic,
        "status": raw.get("status"),
        "reported_result": raw.get("result") or None,
        "result": raw.get("result") if raw.get("status") == "finalized"
        and raw.get("result") in {"yes", "no"} else None,
        "settlement_value_dollars": number(raw.get("settlement_value_dollars"), D(0), ONE),
        "notional_value_dollars": number(raw.get("notional_value_dollars"), D(0)),
        "close_time": raw.get("close_time"),
        "settlement_ts": raw.get("settlement_ts"),
        "price_ranges": raw.get("price_ranges"),
        "settlement_bounds_type": raw.get("settlement_bounds_type"),
        "rules_primary": raw.get("rules_primary"),
        "rules_secondary": raw.get("rules_secondary"),
        "source_url": source_url("markets", ticker, base),
        "observed_at": iso_time(observed_ms),
        "observed_ms": observed_ms,
        "price_observed_ms": observed_ms,
        "quote_observed_ms": observed_ms,
        "price_source": "rest_observation",
        "dollar_volume": number(raw.get("dollar_volume"), D(0)),
        "dollar_open_interest": number(raw.get("dollar_open_interest"), D(0)),
        "verification": "official_api_observation",
    }
    for key in prices:
        result[key] = number(raw.get(key), D(0), ONE)
    for key in counts:
        result[key] = number(raw.get(key), D(0))
    missing = [key for key in (*prices, *counts, "dollar_volume") if result.get(key) is None]
    result["unverified_fields"] = missing
    if raw.get("result") not in {"yes", "no", "", None}:
        result["settlement_review"] = "Non-binary result; not coerced into YES/NO"
    return result


def group_events(events: list[dict], markets: dict[str, dict]) -> list[dict]:
    grouped = []
    for event in events:
        children = [market for market in markets.values() if market.get("event_ticker") == event["event_ticker"]]
        values = [decimal(market.get("dollar_volume"), D(0)) for market in children]
        complete = bool(values) and all(value is not None for value in values)
        grouped.append({
            **event,
            "markets": children,
            "market_count": len(children),
            "cumulative_dollar_notional": format(sum(values, D(0)), "f") if complete else None,
            "notional_coverage": f"{sum(value is not None for value in values)}/{len(values)}",
            "ranking_metric": "exchange-reported cumulative traded dollar notional; not cash turnover",
            "resolved_count": sum(market.get("result") in {"yes", "no"} for market in children),
        })
    return sorted(grouped, key=lambda event: (
        event["cumulative_dollar_notional"] is not None,
        decimal(event["cumulative_dollar_notional"]) or D(0),
    ), reverse=True)


class AlertDetector:
    """Observed cumulative move within 60 seconds, re-anchored after each alert."""
    def __init__(self, threshold: Decimal = THRESHOLD, window_ms: int = 60_000):
        self.threshold = threshold
        self.window_ms = window_ms
        self.points: dict[str, deque] = {}
        self.last: dict[str, tuple[int, Decimal]] = {}

    def reset(self, ticker: str | None = None):
        if ticker is None:
            self.points.clear()
            self.last.clear()
        else:
            self.points.pop(ticker, None)
            self.last.pop(ticker, None)

    def observe(self, ticker: str, price: Decimal, timestamp_ms: int,
                event_id: str | None = None) -> dict | None:
        if decimal(price, D(0), ONE) is None:
            return None
        previous = self.last.get(ticker)
        if previous and (timestamp_ms < previous[0] or (timestamp_ms == previous[0] and price == previous[1])):
            return None
        points = self.points.setdefault(ticker, deque(maxlen=10_000))
        while points and timestamp_ms - points[0][0] > self.window_ms:
            points.popleft()
        self.last[ticker] = (timestamp_ms, price)
        alert = None
        if points and previous and price != previous[1]:
            baseline = min(points, key=lambda p: p[1]) if price > previous[1] else max(points, key=lambda p: p[1])
            delta = price - baseline[1]
            if abs(delta) >= self.threshold:
                alert = {
                    "id": f"{ticker}:{event_id or str(timestamp_ms) + ':' + format(price, 'f')}",
                    "ticker": ticker,
                    "timestamp_ms": timestamp_ms,
                    "timestamp": iso_time(timestamp_ms),
                    "reference_timestamp": iso_time(baseline[0]),
                    "from_price": format(baseline[1], "f"),
                    "to_price": format(price, "f"),
                    "delta_dollars": format(delta, "f"),
                    "direction": "up" if delta > 0 else "down",
                    "window_seconds": self.window_ms // 1000,
                    "comparison": "observed last YES price, re-anchored after an alert",
                    "selected": False,
                    "model": None,
                    "catalysts": [],
                    "causality": "unverified; no causal news attribution has been established",
                }
                points.clear()
        points.append((timestamp_ms, price))
        return alert


class BookError(ValueError):
    pass


class OrderBook:
    """Two bid books. Complementary asks are derived, explicitly, from opposite bids."""
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.yes: dict[Decimal, Decimal] = {}
        self.no: dict[Decimal, Decimal] = {}
        self.observed_ms: int | None = None
        self.valid = False
        self.source = ""

    @staticmethod
    def _levels(levels: Any) -> dict[Decimal, Decimal]:
        if not isinstance(levels, list):
            raise BookError("Missing book levels")
        parsed = {}
        for level in levels:
            if not isinstance(level, (list, tuple)) or len(level) != 2:
                raise BookError("Malformed price level")
            price = decimal(level[0], D(0), ONE)
            quantity = decimal(level[1], D(0))
            if price is None or quantity is None:
                raise BookError("Invalid price or quantity")
            if price in parsed:
                raise BookError("Duplicate price level")
            if quantity > 0:
                parsed[price] = quantity
        return parsed

    def snapshot(self, yes: list, no: list, timestamp_ms: int, source: str):
        # Parse both sides before mutating: an invalid frame cannot half-replace a book.
        try:
            yes_levels, no_levels = self._levels(yes), self._levels(no)
        except BookError:
            self.valid = False
            raise
        self.yes, self.no = yes_levels, no_levels
        self.observed_ms, self.source, self.valid = timestamp_ms, source, True

    def delta(self, side: str, price: Any, quantity_delta: Any, timestamp_ms: int):
        value, change = decimal(price, D(0), ONE), decimal(quantity_delta)
        if not self.valid or side not in {"yes", "no"} or value is None or change is None:
            self.valid = False
            raise BookError("Invalid delta or missing snapshot")
        levels = self.yes if side == "yes" else self.no
        quantity = levels.get(value, D(0)) + change
        if quantity < 0:
            self.valid = False
            raise BookError("Negative level: resnapshot required")
        if quantity == 0:
            levels.pop(value, None)
        else:
            levels[value] = quantity
        self.observed_ms = timestamp_ms

    def asks(self, outcome: str) -> list[tuple[Decimal, Decimal]]:
        if outcome not in {"yes", "no"}:
            raise BookError("Unknown outcome")
        opposite = self.no if outcome == "yes" else self.yes
        return sorted(((ONE - price, count) for price, count in opposite.items()), key=lambda x: x[0])

    def as_dict(self, now_ms: int, stale_seconds: int = 45) -> dict:
        def rows(levels, derived=False):
            return [{"price_dollars": format(price, "f"), "contracts": format(count, "f"),
                     "derived_complement": derived, "source_url": self.source}
                    for price, count in levels]
        return {
            "ticker": self.ticker,
            "yes_bids": rows(sorted(self.yes.items(), reverse=True)),
            "no_bids": rows(sorted(self.no.items(), reverse=True)),
            "yes_asks": rows(self.asks("yes"), True),
            "no_asks": rows(self.asks("no"), True),
            "observed_ms": self.observed_ms,
            "source_url": self.source,
            "valid": self.valid,
            "stale": not self.valid or self.observed_ms is None
            or now_ms - self.observed_ms > stale_seconds * 1000,
            "note": "Displayed aggregate contracts, not number of orders. Asks = $1 − opposite bid.",
        }


class SequenceGuard:
    """Orderbook seq is per subscription, not per market."""
    def __init__(self):
        self.last: dict[int, int] = {}

    def accept(self, sid: int, seq: int) -> bool:
        previous = self.last.get(sid)
        if previous is not None and seq != previous + 1:
            return False
        self.last[sid] = seq
        return True
