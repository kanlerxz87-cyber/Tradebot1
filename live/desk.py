"""Live desk engine: one process, no third-party dependencies.

The desk does four things, all of them automatic:

1. **Tracks** open markets in the five requested topics (gas prices, elections, culture,
   crypto, golf), grouped by event inside each topic.
2. **Detects** a swing when the mid-price of a tracked contract moves by $0.10 or more
   between two observations. The threshold is inclusive, symmetric, and measured on the
   mid of a two-sided book; when a book is one-sided the engine falls back to the last
   trade and labels the observation as quote-only.
3. **Trades** the same signals with four published rules (momentum, fade, cheap upside,
   late favourite) in a simulated book that starts at $1,000, risks 2% of equity per
   trade, caps itself at 12 open positions, pays the spread and the fee, and closes on a
   published exit rule so that results can be grouped by strategy, topic, price band and
   exit reason.
4. **Tracks resolution** until Kalshi finalises a market, then records the exchange's own
   ``result`` (``yes``/``no``/``scalar``) — never a guess.

Data modes
----------
``live``
    Polls the official demo REST API for quotes and books. Every price shown came from a
    response. Requires network egress to Kalshi.
``simulated``
    The engine has no egress (common in a locked-down runner), so it replays a *seeded*
    random walk anchored to the committed snapshot. The walk is deterministic, bounded in
    $0.01-$0.99, and **every surface that shows its output is labelled SIMULATED**. It is
    a mechanics demo: the alerts it produces are not Kalshi events and never claim to be.

Official sources for every rule in this file
--------------------------------------------
* Environments and hosts — https://docs.kalshi.com/getting_started/api_environments
* Order book is bids-only; implied ask = 1 - best opposite bid; best bid is the last,
  highest level — https://docs.kalshi.com/getting_started/orderbook_responses
* Market statuses and ``result`` values (yes/no/scalar), finalisation —
  https://docs.kalshi.com/getting_started/market_lifecycle
* Fee schedule — https://docs.kalshi.com/getting_started/fees
"""

from __future__ import annotations

import datetime as dt
import json
import math
from decimal import Decimal, ROUND_CEILING
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent

THRESHOLD = 0.10
STARTING_CASH = 1000.0
RISK_FRACTION = 0.02
MAX_POSITIONS = 12
TOPICS = ("gas", "elections", "culture", "crypto", "golf")
TOPIC_LABELS = {
    "gas": "Gas prices",
    "elections": "Elections",
    "culture": "Culture",
    "crypto": "Crypto",
    "golf": "Golf",
}
DEMO_REST = "https://external-api.demo.kalshi.co/trade-api/v2"
DEMO_WS = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
DOCS = {
    "environments": "https://docs.kalshi.com/getting_started/api_environments",
    "orderbook": "https://docs.kalshi.com/getting_started/orderbook_responses",
    "lifecycle": "https://docs.kalshi.com/getting_started/market_lifecycle",
    "fees": "https://docs.kalshi.com/getting_started/fees",
    "markets": "https://docs.kalshi.com/api-reference/market/get-markets",
    "candles": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
    "websockets": "https://docs.kalshi.com/getting_started/quick_start_websockets",
}

# Kalshi's published fee constants for the general (non-S&P) schedule: fee =
# ceil_to_cent(rate * contracts * price * (1 - price)). The rate is taken from the
# documentation page above; when that page cannot be read the engine reports the fee as
# unverified in /api/meta rather than presenting it as confirmed.
FEE_RATE_TAKER = 0.07
FEE_RATE_MAKER = 0.0175
FEE_VERIFIED = False  # flipped by a human after re-reading the official schedule


def utc_now() -> float:
    return time.time()


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# market model
# --------------------------------------------------------------------------- #

@dataclass
class Market:
    ticker: str
    event_ticker: str
    series_ticker: str
    topic: str
    title: str
    event_title: str
    subtitle: str
    status: str
    result: str | None
    close_time: str | None
    rules: str
    series_url: str
    api_url: str
    yes_bid: float
    yes_ask: float | None
    mid: float
    last: float | None
    volume_24h: float
    open_interest: float
    yes_bids: list[tuple[float, float]] = field(default_factory=list)
    yes_asks: list[tuple[float, float]] = field(default_factory=list)
    anchor: float = 0.5
    prev_mid: float | None = None
    updated_ts: float = 0.0
    observations: int = 0
    quote_only: bool = False

    def book_contracts(self, within: float = 0.05) -> float:
        """Contracts resting on the YES bid side within ``within`` of the best bid."""
        if not self.yes_bids:
            return 0.0
        best = self.yes_bids[0][0]
        return round(sum(size for price, size in self.yes_bids if best - price <= within + 1e-9), 2)

    def buy_price(self) -> float | None:
        """Price a simulated buyer actually pays: the implied YES ask."""
        return self.yes_ask

    def sell_price(self) -> float:
        return self.yes_bid

    def public(self, *, series_len: int = 0) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "eventTicker": self.event_ticker,
            "seriesTicker": self.series_ticker,
            "topic": self.topic,
            "title": self.title,
            "eventTitle": self.event_title,
            "subtitle": self.subtitle,
            "status": self.status,
            "result": self.result,
            "closeTime": self.close_time,
            "rules": self.rules,
            "seriesUrl": self.series_url,
            "apiUrl": self.api_url,
            "yesBid": round(self.yes_bid, 4) if self.yes_bid is not None else None,
            "yesAsk": round(self.yes_ask, 4) if self.yes_ask is not None else None,
            "mid": round(self.mid, 4),
            "last": round(self.last, 4) if self.last is not None else None,
            "spread": round(self.yes_ask - self.yes_bid, 4) if self.yes_ask is not None else None,
            "volume24h": round(self.volume_24h, 2),
            "openInterest": round(self.open_interest, 2),
            "notional24h": round(self.volume_24h * self.mid, 2),
            "bestBidSize": self.yes_bids[0][1] if self.yes_bids else 0.0,
            "bestAskSize": self.yes_asks[0][1] if self.yes_asks else 0.0,
            "contractsWithin5c": self.book_contracts(0.05),
            "quoteOnly": self.quote_only,
            "observations": self.observations,
            "updatedAt": iso(self.updated_ts),
            "spark": [],
        }


@dataclass
class Position:
    id: int
    ticker: str
    topic: str
    strategy: str
    side: str
    contracts: float
    entry_price: float
    entry_ts: float
    fee: float
    exit_price: float | None = None
    exit_ts: float | None = None
    exit_reason: str | None = None
    realized: float | None = None
    peak: float = 0.0

    def public(self, market: Market | None = None) -> dict[str, Any]:
        # A NO position is marked at $1 - YES mid, the same complement Kalshi documents
        # for the order book (https://docs.kalshi.com/getting_started/orderbook_responses).
        if market is None:
            mark = self.entry_price
        elif self.side == "YES":
            mark = market.mid
        else:
            mark = round(1.0 - market.mid, 4)
        value = mark * self.contracts
        unreal = (mark - self.entry_price) * self.contracts - self.fee
        return {
            "id": self.id,
            "ticker": self.ticker,
            "topic": self.topic,
            "strategy": self.strategy,
            "side": self.side,
            "contracts": round(self.contracts, 2),
            "entryPrice": round(self.entry_price, 4),
            "entryTs": iso(self.entry_ts),
            "mark": round(mark, 4),
            "markValue": round(value, 2),
            "unrealized": round(unreal, 2),
            "fee": round(self.fee, 4),
            "maxFavorable": round(self.peak, 4),
            "open": self.exit_ts is None,
            "exitPrice": round(self.exit_price, 4) if self.exit_price is not None else None,
            "exitTs": iso(self.exit_ts),
            "exitReason": self.exit_reason,
            "realized": round(self.realized, 2) if self.realized is not None else None,
            "priceBand": price_band(self.entry_price),
            "holdHours": round(((self.exit_ts or time.time()) - self.entry_ts) / 3600, 3),
        }


def price_band(price: float) -> str:
    if price < 0.15:
        return "00-15c"
    if price < 0.35:
        return "15-35c"
    if price < 0.65:
        return "35-65c"
    if price < 0.85:
        return "65-85c"
    return "85-100c"


def taker_fee(contracts: float, price: float, rate: float = FEE_RATE_TAKER) -> float:
    """Fee in dollars, rounded up to the next cent like the exchange does.

    fee = ceil_to_cent(rate * C * P * (1 - P)); at P=0 or P=1 the fee is zero.

    Decimal arithmetic, not float: 0.07 * 100 * 0.5 * 0.5 is exactly 1.75 and must not
    become 1.76 through binary rounding.
    """
    if contracts <= 0 or price <= 0 or price >= 1:
        return 0.0
    c = Decimal(str(contracts))
    p = Decimal(str(price))
    r = Decimal(str(rate))
    raw = r * c * p * (Decimal(1) - p)
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING))


# --------------------------------------------------------------------------- #
# strategies
# --------------------------------------------------------------------------- #

STRATEGIES: dict[str, dict[str, Any]] = {
    "momentum": {
        "label": "Momentum",
        "rule": "After a move of $0.10 or more, buy YES in the direction of the move when the "
                "model score is at least 55 and the implied ask is between $0.12 and $0.88.",
        "takeProfit": 0.15,
        "stopLoss": 0.10,
        "timeStopMin": 45,
    },
    "fade": {
        "label": "Fade",
        "rule": "After a move of $0.10 or more, buy the opposite side (YES when the move was down, "
                "NO when it was up) when the move is at least $0.20 and the book is two-sided.",
        "takeProfit": 0.12,
        "stopLoss": 0.12,
        "timeStopMin": 60,
    },
    "cheap-upside": {
        "label": "Cheap upside",
        "rule": "Buy YES on an upswing priced at or below $0.12 — the payoff is capped at $1.00, so the "
                "asymmetry is the whole edge. Sized like every other strategy.",
        "takeProfit": 0.05,
        "stopLoss": 0.05,
        "timeStopMin": 30,
    },
    "late-favourite": {
        "label": "Late favourite",
        "rule": "Buy YES on an upswing that lands at or above $0.85, where the contract is near certain "
                "and the remaining move is small. Exits on a $0.04 adverse move.",
        "takeProfit": 0.08,
        "stopLoss": 0.04,
        "timeStopMin": 90,
    },
}


# --------------------------------------------------------------------------- #
# snapshot loading
# --------------------------------------------------------------------------- #

def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _levels(raw: Iterable[Any]) -> list[tuple[float, float]]:
    out = []
    for level in raw or []:
        if isinstance(level, dict):
            price, size = level.get("price"), level.get("contracts")
        else:
            try:
                price, size = level[0], level[1]
            except (TypeError, IndexError):
                continue
        price, size = _f(price, -1), _f(size, -1)
        if 0 < price <= 1 and size >= 0:
            out.append((round(price, 4), round(size, 2)))
    return out


def clean_title(text: str | None) -> str:
    """Kalshi titles carry markdown emphasis (``**gas prices**``); display them as plain text."""
    return (text or "").replace("**", "")


def load_from_desk(path: Path) -> tuple[dict[str, list[Market]], dict[str, Any]]:
    """Read the research desk's committed capture (300 markets across five topics)."""
    payload = json.loads(path.read_text())
    markets: dict[str, list[Market]] = {topic: [] for topic in TOPICS}
    for topic, block in (payload.get("topics") or {}).items():
        if topic not in markets:
            continue
        for row in block.get("markets") or []:
            book = row.get("orderbook") or {}
            yes_bids = _levels(book.get("yes_bids"))
            yes_asks = _levels(book.get("yes_asks"))
            yes_bid = _f(row.get("yes_bid"), 0.0)
            yes_ask = row.get("yes_ask")
            yes_ask = _f(yes_ask, 0.0) if yes_ask is not None else None
            mid = _f(row.get("mid") or row.get("price"), yes_bid)
            market = Market(
                ticker=row.get("ticker") or "",
                event_ticker=row.get("event_ticker") or row.get("ticker") or "",
                series_ticker=row.get("series_ticker") or "",
                topic=topic,
                title=clean_title(row.get("title")) or "",
                event_title=clean_title(row.get("event_title") or row.get("title")),
                subtitle=row.get("subtitle") or "",
                status=row.get("status") or "active",
                result=(row.get("result") or None),
                close_time=row.get("close_time"),
                rules=row.get("rules_primary") or "",
                series_url=row.get("series_page_url") or "",
                api_url=row.get("api_url") or f"{DEMO_REST}/markets/{row.get('ticker')}",
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                mid=mid,
                last=row.get("last"),
                volume_24h=_f(row.get("volume_24h")),
                open_interest=_f(row.get("open_interest")),
                yes_bids=yes_bids,
                yes_asks=yes_asks,
                anchor=mid if 0.02 < mid < 0.98 else min(0.97, max(0.03, mid)),
                prev_mid=mid,
                updated_ts=utc_now(),
            )
            markets[topic].append(market)
    meta = {
        "source": str(path.relative_to(ROOT)),
        "capturedAt": payload.get("generated_at"),
        "captureEnvironment": payload.get("data_env") or "unknown",
        "markets": sum(len(v) for v in markets.values()),
        "topicCounts": {k: len(v) for k, v in markets.items()},
        "upstream": {
            "restBase": payload.get("rest_base"),
            "wsUrl": payload.get("ws_url"),
            "environment": payload.get("data_env"),
        },
    }
    return markets, meta


def load_from_board(path: Path) -> tuple[dict[str, list[Market]], dict[str, Any]]:
    payload = json.loads(path.read_text())
    markets: dict[str, list[Market]] = {topic: [] for topic in TOPICS}
    rows = (payload.get("markets") or {}).values()
    for row in rows:
        topic = row.get("topic")
        if topic not in markets:
            continue
        raw = ((row.get("orderbook") or {}).get("raw") or "")
        yes_bids: list[tuple[float, float]] = []
        yes_asks: list[tuple[float, float]] = []
        if raw:
            try:
                book = json.loads(raw).get("orderbook_fp") or {}
                yes_bids = sorted(_levels(book.get("yes_dollars")), reverse=True)
                no_bids = sorted(_levels(book.get("no_dollars")), reverse=True)
                yes_asks = sorted(((round(1 - p, 4), s) for p, s in no_bids), reverse=False)
            except json.JSONDecodeError:
                pass
        bid = _f(row.get("yesBid"))
        ask = row.get("yesAsk")
        mid = round((bid + _f(ask, bid)) / 2, 4) if ask is not None else bid
        markets[topic].append(Market(
            ticker=row.get("ticker") or "",
            event_ticker=row.get("eventTicker") or row.get("ticker") or "",
            series_ticker=row.get("seriesTicker") or "",
            topic=topic,
            title=clean_title(row.get("title")),
            event_title=clean_title(row.get("title")),
            subtitle=row.get("yesSubTitle") or "",
            status=row.get("status") or "active",
            result=(row.get("result") or None),
            close_time=row.get("closeTime"),
            rules=row.get("rulesPrimary") or "",
            series_url=f"https://kalshi.com/markets/{(row.get('seriesTicker') or '').lower()}",
            api_url=row.get("sourceUrl") or "",
            yes_bid=bid,
            yes_ask=_f(ask, bid) if ask is not None else None,
            mid=mid,
            last=row.get("lastPrice"),
            volume_24h=_f(row.get("volume24h")),
            open_interest=_f(row.get("openInterest")),
            yes_bids=yes_bids,
            yes_asks=yes_asks,
            anchor=mid,
            prev_mid=mid,
            updated_ts=utc_now(),
        ))
    meta = {
        "source": str(path.relative_to(ROOT)),
        "capturedAt": (payload.get("meta") or {}).get("capturedAt"),
        "captureEnvironment": "demo" if "demo" in ((payload.get("meta") or {}).get("root") or "") else "unknown",
        "markets": sum(len(v) for v in markets.values()),
        "topicCounts": {k: len(v) for k, v in markets.items()},
        "upstream": {"restBase": (payload.get("meta") or {}).get("root")},
    }
    return markets, meta


def load_snapshot() -> tuple[dict[str, list[Market]], dict[str, Any]]:
    """Prefer the widest committed capture available on this branch."""
    desk = ROOT / "docs/desk/data/latest.json"
    board = ROOT / "data/snapshot.json"
    if desk.exists():
        try:
            markets, meta = load_from_desk(desk)
            if meta["markets"]:
                return markets, meta
        except (json.JSONDecodeError, OSError):
            pass
    if board.exists():
        return load_from_board(board)
    raise SystemExit("No committed snapshot found: expected docs/desk/data/latest.json or data/snapshot.json")


# --------------------------------------------------------------------------- #
# live poller (official demo REST; unauthenticated market data only)
# --------------------------------------------------------------------------- #

class KalshiPoller:
    """Unauthenticated market-data poller for the official demo REST root.

    Only public endpoints are used (``/markets`` and ``/markets/{ticker}/orderbook``),
    because both are documented as requiring no authentication. No order is ever sent and
    no credential is read.
    """

    def __init__(self, base: str = DEMO_REST, timeout: float = 4.0) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.last_error: str | None = None
        self.last_ok: float | None = None

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.base}{path}"
        req = urllib.request.Request(url, headers={"User-Agent": "tradebot1-live-desk/1.0"})
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode())

    def fetch_markets(self, ticker_prefix: str, limit: int = 60) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"status": "open", "limit": limit, "series_ticker": ticker_prefix})
        data = self._get(f"/markets?{query}")
        self.last_ok = utc_now()
        self.last_error = None
        return data.get("markets") or []

    def fetch_orderbook(self, ticker: str, depth: int = 10) -> dict[str, Any] | None:
        try:
            data = self._get(f"/markets/{urllib.parse.quote(ticker)}/orderbook?depth={depth}")
            self.last_ok = utc_now()
            self.last_error = None
            return data.get("orderbook_fp") or data.get("orderbook") or {}
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def probe(self) -> bool:
        try:
            self._get("/exchange/status")
            self.last_ok = utc_now()
            self.last_error = None
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False




def read_quote(row: dict[str, Any]) -> tuple[float, float, float | None, float | None] | None:
    """Turn one ``GET /markets`` row into ``(mid, bid, ask, last)`` or ``None``.

    Field names are the ones the demo API actually returns (checked against a live
    response on 2026-11-22): ``yes_bid_dollars``, ``yes_ask_dollars``,
    ``last_price_dollars``, all fixed-point strings.

    A quote is only usable when the book is two-sided, uncrossed, away from the 0/1
    placeholder states, and no wider than 20 cents. Otherwise the last trade is used and
    the market is marked quote-only; if there is no last trade either, nothing is
    published. This is what stops a 0.00 x 1.00 placeholder from firing a false alarm on
    every poll.
    """
    bid = _f(row.get("yes_bid_dollars"), _f(row.get("yes_bid"), 0) / 100)
    ask_raw = row.get("yes_ask_dollars")
    ask = _f(ask_raw, _f(row.get("yes_ask"), 0) / 100) if ask_raw is not None else None
    last_raw = row.get("last_price_dollars")
    last = _f(last_raw, _f(row.get("last_price"), 0) / 100) if last_raw is not None else None
    last = last if last and 0 < last < 1 else None
    two_sided = ask is not None and 0 < bid < 1 and 0 < ask < 1 and ask > bid and (ask - bid) <= 0.20
    if two_sided:
        return round((bid + ask) / 2, 4), round(bid, 4), round(ask, 4), last
    if last is not None:
        return last, round(bid, 4), None, last
    return None


# --------------------------------------------------------------------------- #
# the desk
# --------------------------------------------------------------------------- #

class Desk:
    def __init__(self, *, mode: str = "auto", interval: float = 1.0, seed: int = 20261122,
                 poller: KalshiPoller | None = None) -> None:
        self.markets_by_topic, self.snapshot_meta = load_snapshot()
        self.markets: dict[str, Market] = {
            m.ticker: m for rows in self.markets_by_topic.values() for m in rows
        }
        self.mode_requested = mode
        self.mode = "simulated" if mode in ("auto", "simulated") else "live"
        self.interval = interval
        self.poller = poller or KalshiPoller()
        self.rng = random.Random(seed)
        self.lock = threading.RLock()
        self.started_ts = utc_now()
        self.last_tick_ts: float | None = None
        self.ticks = 0
        self.live_ok = 0
        self.live_errors = 0
        self.history: dict[str, deque[tuple[float, float]]] = {
            t: deque(maxlen=7200) for t in self.markets
        }
        self.alerts: deque[dict[str, Any]] = deque(maxlen=600)
        self.filtered_ids: deque[str] = deque(maxlen=600)
        self.positions: dict[int, Position] = {}
        self.closed: list[Position] = []
        self.next_position_id = 1
        self.cash = STARTING_CASH
        self.equity_curve: deque[tuple[float, float]] = deque(maxlen=3600)
        self.resolutions: list[dict[str, Any]] = []
        self.causes: dict[str, list[dict[str, Any]]] = {}
        for market in self.markets.values():
            self.history[market.ticker].append((market.updated_ts, market.mid))
        self.equity_curve.append((utc_now(), STARTING_CASH))
        if mode == "live" and not self.poller.probe():
            self.mode = "simulated"
            self.mode_requested = "live-unavailable"

    # -- helpers ----------------------------------------------------------- #

    @property
    def simulated(self) -> bool:
        return self.mode == "simulated"

    def _score(self, market: Market, delta: float) -> tuple[float, dict[str, float]]:
        """Published six-component screen. Not a forecast, not a probability of profit."""
        spread = (market.yes_ask - market.yes_bid) if market.yes_ask is not None else None
        components = {
            "move": min(1.0, abs(delta) / 0.30) * 30,
            "depth": min(1.0, market.book_contracts(0.05) / 5000) * 20,
            "spread": (min(1.0, max(0.0, (0.10 - spread) / 0.10)) * 20) if spread is not None else 0.0,
            "volume": min(1.0, market.volume_24h / 50000) * 20,
            "price": (1.0 - abs(market.mid - 0.5) * 2) * 5,
            "freshness": 5.0,
        }
        return round(sum(components.values()), 1), {k: round(v, 1) for k, v in components.items()}

    def _record_alert(self, market: Market, delta: float, now: float) -> dict[str, Any]:
        score, parts = self._score(market, delta)
        alert = {
            "id": f"{market.ticker}@{int(now)}",
            "ts": now,
            "at": iso(now),
            "ticker": market.ticker,
            "eventTicker": market.event_ticker,
            "title": market.title,
            "eventTitle": market.event_title,
            "topic": market.topic,
            "direction": "up" if delta > 0 else "down",
            "from": round(market.prev_mid if market.prev_mid is not None else market.mid - delta, 4),
            "to": round(market.mid, 4),
            "delta": round(delta, 4),
            "absDelta": round(abs(delta), 4),
            "threshold": THRESHOLD,
            "score": score,
            "scoreParts": parts,
            "selected": score >= 55,
            "quoteOnly": market.quote_only,
            "contractsWithin5c": market.book_contracts(0.05),
            "spread": round(market.yes_ask - market.yes_bid, 4) if market.yes_ask is not None else None,
            "volume24h": round(market.volume_24h, 2),
            "mid": round(market.mid, 4),
            "seriesUrl": market.series_url,
            "apiUrl": market.api_url,
            "rules": market.rules,
            "closeTime": market.close_time,
            "simulated": self.simulated,
        }
        self.alerts.appendleft(alert)
        if alert["selected"]:
            self.filtered_ids.appendleft(alert["id"])
        return alert

    # -- price updates ------------------------------------------------------ #

    def _simulate_step(self, market: Market) -> float:
        """One deterministic, bounded random-walk step. Mechanics only."""
        rng = self.rng
        roll = rng.random()
        if roll < 0.70:
            step = 0.0
        elif roll < 0.94:
            step = rng.choice((-0.01, 0.01, -0.02, 0.02))
        elif roll < 0.995:
            step = rng.choice((-0.03, 0.03, -0.04, 0.04, -0.05, 0.05))
        else:
            step = rng.choice((-0.11, -0.10, 0.10, 0.12, -0.13, 0.14))
        pull = (market.anchor - market.mid) * 0.015
        new_mid = min(0.985, max(0.015, market.mid + step + pull))
        new_mid = round(new_mid, 2)
        if new_mid == market.mid and step:
            new_mid = round(min(0.985, max(0.015, market.mid + math.copysign(0.01, step))), 2)
        return new_mid

    def _apply_mid(self, market: Market, new_mid: float, now: float, *, source: str = "simulated") -> None:
        """Move a market to a new mid and keep the book consistent with it."""
        old_mid = market.mid
        half_spread = 0.01 if new_mid < 0.9 else 0.005
        market.prev_mid = old_mid
        market.mid = round(new_mid, 4)
        market.yes_bid = round(max(0.01, min(0.99, new_mid - half_spread)), 4)
        market.yes_ask = round(min(0.99, max(0.01, new_mid + half_spread)), 4)
        market.last = market.mid
        market.updated_ts = now
        market.observations += 1
        market.quote_only = False
        if source == "simulated":
            # Depth thins as the price stretches: mechanically plausible, still simulated.
            pressure = 1.0 + abs(new_mid - market.anchor) * 4
            bid_size = max(5.0, round((market.volume_24h / (24 * 3600)) * 900 * self.rng.uniform(0.3, 2.0) / pressure, 2))
            ask_size = max(5.0, round(bid_size * self.rng.uniform(0.5, 1.8), 2))
            market.yes_bids = [(market.yes_bid, bid_size), (round(max(0.01, market.yes_bid - 0.01), 2), round(bid_size * 0.7, 2))]
            market.yes_asks = [(market.yes_ask, ask_size), (round(min(0.99, market.yes_ask + 0.01), 2), round(ask_size * 0.6, 2))]
        self.history[market.ticker].append((now, market.mid))
        delta = market.mid - old_mid
        if abs(delta) >= THRESHOLD - 1e-9:
            self._record_alert(market, delta, now)
            self._auto_trade(market, delta, now)

    # -- trading ------------------------------------------------------------ #

    def _auto_trade(self, market: Market, delta: float, now: float) -> None:
        open_count = sum(1 for p in self.positions.values() if p.exit_ts is None)
        if open_count >= MAX_POSITIONS or self.cash <= 5:
            return
        if any(p.ticker == market.ticker and p.exit_ts is None for p in self.positions.values()):
            return
        ask = market.yes_ask
        if ask is None or market.quote_only:
            return
        score, _ = self._score(market, delta)
        candidates: list[tuple[str, float]] = []
        if abs(delta) >= 0.10 and score >= 55 and 0.12 <= ask <= 0.88:
            candidates.append(("momentum", ask))
        if abs(delta) >= 0.20:
            opposite = 1.0 - market.yes_bid  # buying NO at 1 - yes_bid
            if 0.05 <= opposite <= 0.95:
                candidates.append(("fade", opposite))
        if delta > 0 and ask <= 0.12:
            candidates.append(("cheap-upside", ask))
        if delta > 0 and ask >= 0.85 and ask <= 0.97:
            candidates.append(("late-favourite", ask))
        for strategy, price in candidates:
            open_count = sum(1 for p in self.positions.values() if p.exit_ts is None)
            if open_count >= MAX_POSITIONS:
                break
            budget = STARTING_CASH * 0 + self.equity() * RISK_FRACTION
            contracts = max(1.0, math.floor((budget / max(price, 0.01)) * 100) / 100)
            cost = contracts * price
            fee = taker_fee(contracts, price)
            if cost + fee > self.cash - 1:
                continue
            side = "NO" if strategy == "fade" and delta > 0 else "YES"
            position = Position(
                id=self.next_position_id,
                ticker=market.ticker,
                topic=market.topic,
                strategy=strategy,
                side=side,
                contracts=contracts,
                entry_price=round(price, 4),
                entry_ts=now,
                fee=fee,
                peak=price,
            )
            self.next_position_id += 1
            self.positions[position.id] = position
            self.cash = round(self.cash - cost - fee, 2)

    def _close(self, position: Position, price: float, now: float, reason: str) -> None:
        proceeds = position.contracts * price
        fee = taker_fee(position.contracts, price)
        position.exit_price = round(price, 4)
        position.exit_ts = now
        position.exit_reason = reason
        position.realized = round(proceeds - fee - position.contracts * position.entry_price - position.fee, 2)
        self.cash = round(self.cash + proceeds - fee, 2)
        self.closed.append(position)
        del self.positions[position.id]

    def _manage_positions(self, now: float) -> None:
        for position in list(self.positions.values()):
            market = self.markets.get(position.ticker)
            if not market:
                continue
            rules = STRATEGIES[position.strategy]
            if position.side == "YES":
                mark, exit_at = market.mid, market.sell_price()
            else:
                mark = 1.0 - market.mid
                exit_at = 1.0 - market.yes_ask if market.yes_ask is not None else None
            position.peak = max(position.peak, round(mark, 4))
            gain = mark - position.entry_price
            held_min = (now - position.entry_ts) / 60
            if gain >= rules["takeProfit"] and exit_at is not None:
                self._close(position, exit_at, now, "take-profit")
            elif gain <= -rules["stopLoss"] and exit_at is not None:
                self._close(position, exit_at, now, "stop-loss")
            elif held_min >= rules["timeStopMin"] and exit_at is not None:
                self._close(position, exit_at, now, "time-stop")
            elif market.status in ("finalized", "determined") and market.result in ("yes", "no"):
                won = (market.result == "yes") == (position.side == "YES")
                payout = 1.0 if won else 0.0
                proceeds = position.contracts * payout
                position.exit_price = payout
                position.exit_ts = now
                position.exit_reason = "settled"
                position.realized = round(proceeds - position.contracts * position.entry_price - position.fee, 2)
                self.cash = round(self.cash + proceeds, 2)
                self.closed.append(position)
                del self.positions[position.id]

    # -- resolution --------------------------------------------------------- #

    def _sync_resolutions(self) -> None:
        for market in self.markets.values():
            if market.status not in ("finalized", "determined") or market.result not in ("yes", "no", "scalar"):
                continue
            if any(r["ticker"] == market.ticker for r in self.resolutions):
                continue
            self.resolutions.append({
                "ticker": market.ticker,
                "title": market.title,
                "topic": market.topic,
                "status": market.status,
                "result": market.result,
                "closeTime": market.close_time,
                "recordedAt": iso(market.updated_ts),
                "apiUrl": market.api_url,
                "seriesUrl": market.series_url,
            })

    # -- public state ------------------------------------------------------- #

    def equity(self) -> float:
        value = self.cash
        for position in self.positions.values():
            market = self.markets.get(position.ticker)
            mark = market.mid if market else position.entry_price
            value += position.contracts * (mark if position.side == "YES" else 1 - mark)
        return round(value, 2)

    def portfolio(self) -> dict[str, Any]:
        realized = round(sum(p.realized or 0 for p in self.closed), 2)
        positions = [p.public(self.markets.get(p.ticker)) for p in self.positions.values()]
        # Equity must reconcile with the marks actually published below, or a trader who adds up
        # the position table gets a different number from the headline. self.equity() rounds the
        # unrounded sum once; the report sums the per-position rounded marks, and the two drift by
        # a cent once enough positions are open.
        equity = round(self.cash + sum(p["markValue"] for p in positions), 2)
        # Cost basis of what is still open, including the entry fee already paid.
        open_cost = round(sum(p.contracts * p.entry_price + p.fee for p in self.positions.values()), 2)
        unreal = round(equity - self.cash - open_cost, 2)
        trades = [p.public(self.markets.get(p.ticker)) for p in self.closed]
        wins = [t for t in trades if (t["realized"] or 0) > 0]
        losses = [t for t in trades if (t["realized"] or 0) < 0]
        gross_win = round(sum(t["realized"] for t in wins), 2)
        gross_loss = round(sum(t["realized"] for t in losses), 2)
        curve = [{"ts": iso(ts), "equity": round(value, 2)} for ts, value in list(self.equity_curve)[-600:]]

        def group(key: str) -> list[dict[str, Any]]:
            buckets: dict[str, list[dict[str, Any]]] = {}
            for trade in trades:
                buckets.setdefault(str(trade.get(key) or "—"), []).append(trade)
            rows = []
            for name, items in buckets.items():
                w = sum(1 for t in items if (t["realized"] or 0) > 0)
                rows.append({
                    "name": name,
                    "trades": len(items),
                    "wins": w,
                    "losses": sum(1 for t in items if (t["realized"] or 0) < 0),
                    "winRate": round(100 * w / len(items), 1) if items else None,
                    "pnl": round(sum(t["realized"] or 0 for t in items), 2),
                    "avgPnl": round(sum(t["realized"] or 0 for t in items) / len(items), 2) if items else None,
                    "avgHoldHours": round(sum(t["holdHours"] or 0 for t in items) / len(items), 2) if items else None,
                })
            return sorted(rows, key=lambda r: r["pnl"], reverse=True)

        return {
            "startingCash": STARTING_CASH,
            "cash": self.cash,
            "equity": equity,
            "realized": realized,
            "unrealized": unreal,
            "totalPnl": round(equity - STARTING_CASH, 2),
        "roundingNote": "Cent-level differences between realized + unrealized and total P&L are display "
                        "rounding of marked positions; the equity figure is cash plus marks.",
            "roiPct": round(100 * (equity - STARTING_CASH) / STARTING_CASH, 2),
            "openPositions": len(positions),
            "closedTrades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "winRate": round(100 * len(wins) / len(trades), 1) if trades else None,
            "profitFactor": round(gross_win / abs(gross_loss), 2) if gross_loss else None,
            "expectancy": round(sum(t["realized"] or 0 for t in trades) / len(trades), 2) if trades else None,
            "feesPaid": round(sum((t["fee"] or 0) for t in trades + positions), 4),
            "openCost": open_cost,
            "positions": positions,
            "trades": trades[-120:][::-1],
            "byStrategy": group("strategy"),
            "byTopic": group("topic"),
            "byPriceBand": group("priceBand"),
            "byExitReason": group("exitReason"),
            "equityCurve": curve,
            "feeModel": {
                "rate": FEE_RATE_TAKER if not self.simulated else FEE_RATE_TAKER,
                "formula": "ceil_to_cent(rate * contracts * price * (1 - price))",
                "verified": FEE_VERIFIED,
                "source": DOCS["fees"],
            },
        }

    def tick(self, now: float | None = None) -> dict[str, Any]:
        now = now or utc_now()
        changed: list[dict[str, Any]] = []
        new_alerts: list[dict[str, Any]] = []
        with self.lock:
            self.ticks += 1
            self.last_tick_ts = now
            if self.mode == "live":
                self._poll_live()
            else:
                for market in self.markets.values():
                    before = len(self.alerts)
                    new_mid = self._simulate_step(market)
                    if new_mid != market.mid:
                        self._apply_mid(market, new_mid, now)
                    if len(self.alerts) > before:
                        new_alerts.append(self.alerts[0])
                    changed.append({
                        "ticker": market.ticker,
                        "mid": round(market.mid, 4),
                        "bid": market.yes_bid,
                        "ask": market.yes_ask,
                        "bidSize": market.yes_bids[0][1] if market.yes_bids else 0,
                        "askSize": market.yes_asks[0][1] if market.yes_asks else 0,
                    })
            self._manage_positions(now)
            self._sync_resolutions()
            equity = self.equity()
            if not self.equity_curve or now - self.equity_curve[-1][0] >= 1.0:
                self.equity_curve.append((now, equity))
        return {
            "ts": now,
            "at": iso(now),
            "updates": changed if self.mode != "live" else self._live_updates,
            "alerts": new_alerts,
            "equity": equity,
            "mode": self.mode,
        }

    _live_updates: list[dict[str, Any]] = []

    def _poll_live(self) -> None:
        """Refresh quotes from the official demo REST API, one series at a time."""
        updates: list[dict[str, Any]] = []
        now = utc_now()
        series = sorted({m.series_ticker for m in self.markets.values() if m.series_ticker})
        for prefix in series[:12]:
            try:
                rows = self.poller.fetch_markets(prefix, limit=40)
                self.live_ok += 1
            except Exception as exc:  # noqa: BLE001 - a poll failure must never kill the desk
                self.live_errors += 1
                self.poller.last_error = f"{type(exc).__name__}: {exc}"
                continue
            for row in rows:
                ticker = row.get("ticker")
                market = self.markets.get(ticker)
                if not market:
                    continue
                quote = read_quote(row)
                if quote is None:
                    # A placeholder or one-sided book: 0.00 bid beside a 1.00 ask is not a
                    # 100-cent collapse, and this engine will not report it as one.
                    market.quote_only = True
                    continue
                mid, bid, ask, last = quote
                market.prev_mid = market.mid
                market.mid = mid
                market.yes_bid = bid
                market.yes_ask = ask
                market.last = last if last is not None else market.last
                market.volume_24h = _f(row.get("volume_24h_fp"), market.volume_24h)
                market.open_interest = _f(row.get("open_interest_fp"), market.open_interest)
                market.status = row.get("status") or market.status
                market.result = row.get("result") or market.result
                market.updated_ts = now
                market.observations += 1
                market.quote_only = ask is None
                delta = market.mid - (market.prev_mid or market.mid)
                if abs(delta) >= THRESHOLD - 1e-9:
                    self._record_alert(market, delta, now)
                    self._auto_trade(market, delta, now)
                updates.append({"ticker": ticker, "mid": mid, "bid": bid, "ask": ask,
                                "bidSize": market.yes_bids[0][1] if market.yes_bids else 0,
                                "askSize": market.yes_asks[0][1] if market.yes_asks else 0})
            for market in self.markets.values():
                if market.series_ticker != prefix:
                    continue
                book = self.poller.fetch_orderbook(market.ticker, depth=10)
                if not book:
                    continue
                yes = _levels(book.get("yes_dollars") or book.get("yes") or [])
                no = _levels(book.get("no_dollars") or book.get("no") or [])
                if yes:
                    market.yes_bids = sorted(yes, reverse=True)[:10]
                if no:
                    market.yes_asks = sorted(((round(1 - p, 4), s) for p, s in no))[:10]
        self._live_updates = updates

    def meta(self) -> dict[str, Any]:
        with self.lock:
            return {
                "mode": self.mode,
                "modeRequested": self.mode_requested,
                "simulated": self.simulated,
                "disclosure": (
                    "SIMULATED prices. This process has no network path to Kalshi, so a seeded, bounded "
                    "random walk anchored to the committed capture is driving the ticks. Alerts here are "
                    "mechanics demonstrations, not Kalshi events."
                    if self.simulated else
                    "LIVE prices polled from the official Kalshi demo REST API (unauthenticated market data)."
                ),
                "intervalSeconds": self.interval,
                "threshold": THRESHOLD,
                "thresholdRule": "abs(mid - previous mid) >= $0.10, inclusive, either direction",
                "startedAt": iso(self.started_ts),
                "lastTickAt": iso(self.last_tick_ts),
                "ticks": self.ticks,
                "liveOk": self.live_ok,
                "liveErrors": self.live_errors,
                "liveError": self.poller.last_error,
                "snapshot": self.snapshot_meta,
                "topics": [{"id": t, "label": TOPIC_LABELS[t], "markets": len(self.markets_by_topic[t])} for t in TOPICS],
                "strategies": STRATEGIES,
                "fees": {
                    "model": "ceil_to_cent(rate * contracts * price * (1 - price))",
                    "takerRate": FEE_RATE_TAKER,
                    "makerRate": FEE_RATE_MAKER,
                    "verified": FEE_VERIFIED,
                    "source": DOCS["fees"],
                    "note": "Rate constants are the published general schedule; the page could not be re-read "
                            "from this sandbox, so the model is labelled unverified rather than asserted.",
                },
                "endpoints": {
                    "rest": self.poller.base,
                    "restAlternate": "https://demo-api.kalshi.co/trade-api/v2",
                    "websocket": DEMO_WS,
                    "websocketAlternate": "wss://demo-api.kalshi.co/trade-api/ws/v2",
                },
                "sources": DOCS,
                "limits": [
                    "No order is ever sent: there is no production or demo order path in this process.",
                    "No credential is read. Market data endpoints are public.",
                    "The fallback simulation mean-reverts to the captured mid. That mechanically punishes "
                    "momentum rules, so strategy P&L here tests the plumbing, not the edge.",
                    f"Anchor capture provenance: {self.snapshot_meta.get('source', 'unknown')} "
                    f"({self.snapshot_meta.get('captureEnvironment', 'unknown')} environment, "
                    f"{self.snapshot_meta.get('capturedAt', 'timestamp missing')}). The live poller targets the "
                    "demo root; check the badge before reading a quote as demo data.",
                    "A swing between two polls can be missed; the WebSocket channel would catch every tick.",
                    "News is not attributed. Each alert links to the market's own rules and a search for the "
                    "event title; neither is a claim about the cause of the move.",
                    "Resolution is shown only from Kalshi's own status/result fields.",
                ],
            }

    def state(self) -> dict[str, Any]:
        with self.lock:
            rows = {}
            for topic, markets in self.markets_by_topic.items():
                events: dict[str, dict[str, Any]] = {}
                for market in markets:
                    item = market.public()
                    event = events.setdefault(market.event_ticker, {
                        "eventTicker": market.event_ticker,
                        "title": market.event_title,
                        "topic": topic,
                        "seriesTicker": market.series_ticker,
                        "seriesUrl": market.series_url,
                        "closeTime": market.close_time,
                        "markets": [],
                        "notional24h": 0.0,
                    })
                    event["markets"].append(item)
                    event["notional24h"] = round(event["notional24h"] + item["notional24h"], 2)
                ordered = sorted(events.values(), key=lambda e: e["notional24h"], reverse=True)
                for event in ordered:
                    event["markets"].sort(key=lambda m: m["notional24h"], reverse=True)
                rows[topic] = ordered
            return {
                "meta": self.meta(),
                "topics": rows,
                "alerts": list(self.alerts)[:120],
                "filteredIds": list(self.filtered_ids)[:120],
                "portfolio": self.portfolio(),
                "resolutions": self.resolutions[-60:][::-1],
                "resolvingSoon": self._resolving_soon(),
            }

    def _resolving_soon(self) -> list[dict[str, Any]]:
        soon = []
        for market in self.markets.values():
            if not market.close_time or market.status in ("finalized", "determined"):
                continue
            try:
                close = dt.datetime.fromisoformat(market.close_time.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            soon.append({
                "ticker": market.ticker,
                "title": market.title,
                "topic": market.topic,
                "status": market.status,
                "closeTime": market.close_time,
                "closesInSeconds": close - utc_now(),
                "result": market.result,
                "apiUrl": market.api_url,
            })
        soon.sort(key=lambda r: r["closesInSeconds"])
        return soon[:40]

    def series(self, ticker: str, seconds: int) -> dict[str, Any]:
        market = self.markets.get(ticker)
        if not market:
            return {"ticker": ticker, "points": [], "error": "unknown ticker"}
        cutoff = utc_now() - seconds
        points = [(ts, mid) for ts, mid in self.history[ticker] if ts >= cutoff]
        return {
            "ticker": ticker,
            "title": market.title,
            "topic": market.topic,
            "rangeSeconds": seconds,
            "points": [{"ts": iso(ts), "t": round(ts, 3), "mid": mid} for ts, mid in points],
            "book": {
                "yesBids": [{"price": p, "contracts": c} for p, c in market.yes_bids],
                "yesAsks": [{"price": p, "contracts": c} for p, c in market.yes_asks],
            },
            "source": market.api_url,
            "rules": market.rules,
            "seriesUrl": market.series_url,
        }

    def book(self, ticker: str) -> dict[str, Any]:
        market = self.markets.get(ticker)
        if not market:
            return {"error": "unknown ticker"}
        return {
            "ticker": ticker,
            "yesBids": [{"price": p, "contracts": c} for p, c in market.yes_bids],
            "yesAsks": [{"price": p, "contracts": c} for p, c in market.yes_asks],
            "bestBid": market.yes_bid,
            "bestAsk": market.yes_ask,
            "contractsWithin5c": market.book_contracts(0.05),
            "source": f"{DEMO_REST}/markets/{ticker}/orderbook",
            "docs": DOCS["orderbook"],
        }
