"""Public data collection, continuing lifecycle reconciliation, and private account reads."""

import asyncio
from contextlib import suppress
import json
import random
import re
import time

import websockets

from .client import KalshiClient, TICKER_PATTERN, UpstreamError
from .config import Settings
from .domain import (
    BookError, D, ONE, AlertDetector, OrderBook, SequenceGuard, classify_series,
    decimal, group_events, iso_time, normalize_market, number, source_url,
)
from .paper import PaperEngine, screen
from .store import Store


def now_ms() -> int:
    return int(time.time() * 1000)


class Runtime:
    def __init__(self, settings: Settings, client: KalshiClient, store: Store):
        self.settings, self.client, self.store = settings, client, store
        self.markets = {row["ticker"]: row for row in store.all("markets")}
        self.events = {row["event_ticker"]: row for row in store.all("events")}
        self.series: dict[str, dict] = {}
        self.books: dict[str, OrderBook] = {}
        self.detector = AlertDetector()
        self.paper = PaperEngine(store)
        self.listeners: set[asyncio.Queue] = set()
        self._tasks: list[asyncio.Task] = []
        self._series_checked_ms = 0
        self._portfolio_cache: tuple[int, dict] | None = None
        self._portfolio_lock = asyncio.Lock()
        self._lifecycle_pending: set[str] = set()
        self._reconcile_offset = 0
        self.kill_switch = False
        self.state = {
            "mode": "demo_only", "rest": "not_connected", "websocket": "not_connected",
            "last_rest_success": None, "last_stream_message": None,
            "exchange_status": None, "discovery_complete": False,
            "discovery_pages": 0, "excluded_series": 0, "ambiguous_series": 0,
            "errors": {}, "reconciliation_backlog": 0,
        }

    def health(self) -> dict:
        latest = max((market.get("price_observed_ms", 0) for market in self.markets.values()), default=0)
        return {
            **self.state,
            "server_time": iso_time(now_ms()),
            "credentials_configured": bool(self.client.signer),
            "demo_order_execution": "enabled" if self.settings.enable_demo_orders and not self.kill_switch else "disabled",
            "paper_automation": self.settings.paper_automation,
            "market_count": len(self.markets),
            "data_stale": not latest or now_ms() - latest > self.settings.stale_seconds * 1000,
            "rest_url": self.settings.rest_url, "websocket_url": self.settings.ws_url,
            "limitations": [
                "This is demo data; demo prices need not match production.",
                "No fabricated fallback; missing values remain null.",
                "REST is sampled/cached; only an authenticated trade stream can observe intrapoll moves.",
                "Dollar ranking is cumulative notional, not cash spent or 24-hour turnover.",
                "Selected alerts are unvalidated pre-fee research hypotheses, not high-ROI promises.",
                "No causal news claim is made without evidence.",
                "Local paper accounting is hypothetical, independent of the demo account.",
                "Topic membership uses explicit local metadata rules; unmatched series are excluded.",
            ],
            "source_url": "https://docs.kalshi.com/getting_started/demo_env",
        }

    def snapshot(self) -> dict:
        return {
            "health": self.health(), "events": group_events(list(self.events.values()), self.markets),
            "markets": list(self.markets.values()), "alerts": self.store.alerts(),
            "selected_alerts": self.store.alerts(True),
            "paper": self.paper.summary(self.markets, now_ms()),
        }

    def publish(self):
        # Queue a notification only, rather than copying private state or unbounded messages.
        for listener in tuple(self.listeners):
            if listener.full():
                with suppress(asyncio.QueueEmpty):
                    listener.get_nowait()
            listener.put_nowait(True)

    async def start(self):
        self._tasks = [asyncio.create_task(self.poll_loop(), name="public-market-poll")]
        if self.client.signer:
            self._tasks.append(asyncio.create_task(self.stream_loop(), name="demo-websocket"))
        else:
            self.state["websocket"] = "credentials_required"

    async def stop(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.client.close()
        self.store.close()

    async def poll_loop(self):
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except (UpstreamError, ValueError, KeyError, TypeError) as exc:
                self.state["rest"] = "disconnected"
                self.state["errors"]["poll"] = exc.code if isinstance(exc, UpstreamError) else "invalid_upstream_payload"
            self.publish()
            await asyncio.sleep(self.settings.poll_seconds)

    async def poll_once(self):
        exchange = await self.client.get("/exchange/status")
        self.state["exchange_status"] = {
            "exchange_active": exchange.get("exchange_active"),
            "trading_active": exchange.get("trading_active"),
            "source_url": self.settings.rest_url + "/exchange/status", "observed_at": iso_time(now_ms()),
        }
        if not self.series or now_ms() - self._series_checked_ms > 3_600_000:
            raw_series = (await self.client.get("/series")).get("series")
            if not isinstance(raw_series, list):
                raise ValueError("Missing series")
            self.series = {row["ticker"]: row for row in raw_series if isinstance(row, dict) and row.get("ticker")}
            self._series_checked_ms = now_ms()
            classifications = [classify_series(row) for row in self.series.values()]
            self.state["excluded_series"] = sum(topic is None for topic, reason in classifications)
            self.state["ambiguous_series"] = sum(reason == "ambiguous" for topic, reason in classifications)
        result = await self.client.pages("/events", "events", {"status": "open", "with_nested_markets": "true"})
        self.state["discovery_complete"] = result.complete
        self.state["discovery_pages"] = result.pages
        if result.error:
            self.state["errors"]["discovery"] = result.error
        else:
            self.state["errors"].pop("discovery", None)
        observed_tickers = set()
        for event in result.rows:
            series = self.series.get(event.get("series_ticker"))
            if not series:
                continue
            topic, reason = classify_series(series)
            event_ticker = event.get("event_ticker")
            if not topic or not isinstance(event_ticker, str):
                continue
            record = {
                "event_ticker": event_ticker, "series_ticker": event.get("series_ticker"),
                "title": event.get("title"), "topic": topic, "topic_rule": reason,
                "category": series.get("category"),
                "settlement_sources": event.get("settlement_sources") or series.get("settlement_sources"),
                "settlement_sources_from": "event" if event.get("settlement_sources") else "series",
                "series_source_url": source_url("series", series["ticker"], self.settings.rest_url),
                "source_url": source_url("events", event_ticker, self.settings.rest_url),
                "observed_at": iso_time(now_ms()),
            }
            self.events[event_ticker] = record
            self.store.put("events", event_ticker, record)
            children = event.get("markets")
            if not isinstance(children, list):
                self.state["errors"][f"event:{event_ticker}"] = "nested_markets_missing"
                continue
            for raw in children:
                if not isinstance(raw, dict) or not re.fullmatch(TICKER_PATTERN, str(raw.get("ticker", ""))):
                    continue
                self.ingest_market(raw, topic)
                observed_tickers.add(raw["ticker"])
        # Never drop an event just because it disappeared from the open listing. Reconcile
        # every tracked unresolved market, including historical fallback, in fair round-robin batches.
        pending = sorted({ticker for ticker, market in self.markets.items()
                          if market.get("status") != "finalized" and ticker not in observed_tickers}
                         | self._lifecycle_pending)
        self.state["reconciliation_backlog"] = len(pending)
        if pending:
            offset = self._reconcile_offset % len(pending)
            batch = (pending[offset:] + pending[:offset])[:50]
            self._reconcile_offset += len(batch)
            for ticker in batch:
                try:
                    await self.refresh_market(ticker)
                    self._lifecycle_pending.discard(ticker)
                except UpstreamError as exc:
                    self.state["errors"][f"market:{ticker}"] = exc.code
        self.state["rest"] = "polling" if result.complete else "partial"
        self.state["last_rest_success"] = iso_time(now_ms())
        self.state["errors"].pop("poll", None)

    def ingest_market(self, raw: dict, topic: str, observed_ms: int | None = None,
                      source_path: str | None = None):
        received_ms = observed_ms if observed_ms is not None else now_ms()
        normalized = normalize_market(raw, topic, received_ms, self.settings.rest_url)
        if source_path:
            normalized["source_url"] = self.settings.rest_url + source_path
        old = self.markets.get(normalized["ticker"], {})
        # REST snapshots may be cached. Do not overwrite a current WebSocket price with them.
        if self.state["websocket"] == "connected" and old.get("price_source", "").startswith("websocket"):
            for key in ("last_price_dollars", "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars",
                        "no_ask_dollars", "price_observed_ms", "price_source", "volume_fp", "open_interest_fp",
                        "yes_bid_size_fp", "yes_ask_size_fp", "dollar_volume", "dollar_open_interest",
                        "quote_observed_ms", "notional_observed_ms"):
                normalized[key] = old.get(key)
        else:
            # Keep an explicitly timestamped last WS notional value without claiming it is fresh.
            for key in ("dollar_volume", "dollar_open_interest", "notional_observed_ms"):
                if normalized.get(key) is None and old.get(key) is not None:
                    normalized[key] = old[key]
        self.markets[normalized["ticker"]] = normalized
        self.store.put("markets", normalized["ticker"], normalized)
        if self.state["websocket"] != "connected":
            self.price_observation(normalized, received_ms, "rest_sample")
        self.paper.settle(normalized)

    async def refresh_market(self, ticker: str):
        if ticker not in self.markets:
            return
        path = f"/markets/{ticker}"
        try:
            data = await self.client.get(path)
        except UpstreamError as exc:
            if exc.status != 404:
                raise
            path = f"/historical/markets/{ticker}"
            data = await self.client.get(path)
        raw = data.get("market")
        if not isinstance(raw, dict):
            raise UpstreamError("missing_market_object")
        self.ingest_market(raw, self.markets[ticker]["topic"], source_path=path)
        self.state["errors"].pop(f"market:{ticker}", None)

    def price_observation(self, market: dict, timestamp_ms: int, kind: str, event_id: str | None = None):
        price = decimal(market.get("last_price_dollars"), D(0), ONE)
        if price is None:
            return
        if not self.store.observation(market["ticker"], timestamp_ms, str(price), market["source_url"], kind, event_id):
            return
        alert = self.detector.observe(market["ticker"], price, timestamp_ms, event_id)
        if not alert:
            return
        alert.update(topic=market["topic"], title=market.get("title"), source_url=market["source_url"],
                     observation_kind=kind, source_status="observed_official_demo_data")
        book = self.books.get(market["ticker"])
        history = self.store.history(market["ticker"], timestamp_ms - 900_000)
        alert["model"] = screen(alert, history, market, book, now_ms())
        alert["selected"] = alert["model"] is not None
        self.store.alert(alert)
        if self.settings.paper_automation:
            self.paper.on_alert(alert, market, book, now_ms())
        self.publish()

    async def get_book(self, ticker: str) -> OrderBook:
        if ticker not in self.markets:
            raise UpstreamError("untracked_market", 404)
        book = self.books.get(ticker)
        if book and book.valid and book.observed_ms and now_ms() - book.observed_ms < 2000:
            return book
        payload = (await self.client.get(f"/markets/{ticker}/orderbook", {"depth": 0})).get("orderbook_fp")
        if not isinstance(payload, dict):
            raise UpstreamError("orderbook_fixed_point_fields_missing")
        # Do not replace a streaming book mid-sequence with a cached REST snapshot.
        rest_book = OrderBook(ticker)
        rest_book.snapshot(payload.get("yes_dollars"), payload.get("no_dollars"), now_ms(),
                           self.settings.rest_url + f"/markets/{ticker}/orderbook")
        if self.state["websocket"] != "connected":
            self.books[ticker] = rest_book
        return rest_book

    def process_frame(self, frame: dict, guard: SequenceGuard):
        kind = frame.get("type")
        message = frame.get("msg", {})
        if not isinstance(message, dict):
            raise ValueError("Malformed stream payload")
        if kind == "error":
            raise UpstreamError("websocket_subscription_error")
        if kind in {"orderbook_snapshot", "orderbook_delta", "trade"}:
            sid, seq = frame.get("sid"), frame.get("seq")
            if not isinstance(sid, int) or not isinstance(seq, int) or not guard.accept(sid, seq):
                # Reconnect rebuilds every book from snapshots. Repeated subscribe is NOT recovery.
                for book in self.books.values():
                    book.valid = False
                raise BookError("websocket_sequence_gap")
        ticker = message.get("market_ticker")
        if ticker not in self.markets:
            return
        market = self.markets[ticker]
        received = now_ms()
        if kind in {"market_lifecycle_v2", "market_lifecycle"}:
            self._lifecycle_pending.add(ticker)
        elif kind == "orderbook_snapshot":
            book = self.books.setdefault(ticker, OrderBook(ticker))
            # We explicitly subscribe with use_yes_price=true. Convert unified NO book prices
            # back to NO-leg bids for a single canonical two-leg representation.
            no_levels = []
            for price, count in message.get("no_dollars_fp", []):
                parsed = decimal(price, D(0), ONE)
                if parsed is None:
                    raise BookError("invalid_no_level")
                no_levels.append([str(ONE - parsed), count])
            book.snapshot(message.get("yes_dollars_fp", []), no_levels, received,
                          self.settings.rest_url + f"/markets/{ticker}/orderbook")
        elif kind == "orderbook_delta":
            book = self.books.setdefault(ticker, OrderBook(ticker))
            price = decimal(message.get("price_dollars"), D(0), ONE)
            if price is None:
                raise BookError("invalid_delta_price")
            if message.get("side") == "no":
                price = ONE - price
            book.delta(message.get("side"), price, message.get("delta_fp"), received)
        elif kind in {"ticker", "trade"}:
            stamp = message.get("ts_ms")
            if not isinstance(stamp, int) or stamp > received + 30_000:
                raise ValueError("Missing or future exchange timestamp")
            # Quote flushes and trade notifications are different channels. A later ticker
            # must not suppress an earlier-arriving trade's alert, nor regress the current price.
            if kind == "ticker" and stamp >= market.get("quote_observed_ms", 0):
                market["quote_observed_ms"] = stamp
                for key in ("yes_bid_dollars", "yes_ask_dollars", "volume_fp", "open_interest_fp",
                            "yes_bid_size_fp", "yes_ask_size_fp", "dollar_volume", "dollar_open_interest"):
                    market[key] = number(message.get(key), D(0), ONE if "_dollars" in key else None)
                market["notional_observed_ms"] = stamp
                # Complement conversion is documented; it is not a fabricated quote.
                ask, bid = decimal(market.get("yes_ask_dollars")), decimal(market.get("yes_bid_dollars"))
                market["no_bid_dollars"] = str(ONE - ask) if ask is not None else None
                market["no_ask_dollars"] = str(ONE - bid) if bid is not None else None
                market["no_quote_derivation"] = "$1 minus opposing YES quote"
            price_key = "yes_price_dollars" if kind == "trade" else "price_dollars"
            price = number(message.get(price_key), D(0), ONE)
            if price is not None:
                if kind == "trade":
                    trade_id = message.get("trade_id")
                    if not isinstance(trade_id, str) or not trade_id:
                        raise ValueError("Missing trade ID")
                    trade_market = {**market, "last_price_dollars": price, "price_observed_ms": stamp,
                                    "price_source": "websocket_trade"}
                    self.price_observation(trade_market, stamp, "websocket_trade", trade_id)
                if (stamp >= market.get("price_observed_ms", 0)
                        or not market.get("price_source", "").startswith("websocket")):
                    market["last_price_dollars"] = price
                    market["price_observed_ms"] = stamp
                    market["price_source"] = "websocket_" + kind
            market["observed_at"], market["observed_ms"] = iso_time(received), received
            self.store.put("markets", ticker, market)
        self.state["last_stream_message"] = iso_time(received)
        self.publish()

    async def stream_loop(self):
        failures = 0
        while True:
            selected = sorted(ticker for ticker, market in self.markets.items() if market.get("status") != "finalized")
            if not selected:
                self.state["websocket"] = "waiting_for_market_discovery"
                await asyncio.sleep(5)
                continue
            self.detector.reset()
            for book in self.books.values():
                book.valid = False
            try:
                headers = self.client.signer.headers("GET", "/trade-api/ws/v2")
                async with websockets.connect(
                    self.settings.ws_url, additional_headers=headers, open_timeout=10,
                    ping_interval=20, ping_timeout=20, max_size=4 * 1024 * 1024,
                    max_queue=128, proxy=None,
                ) as websocket:
                    guard = SequenceGuard()
                    command_id = 1
                    for start in range(0, len(selected), 1000):
                        tickers = selected[start:start + 1000]
                        for channels in (["ticker"], ["trade"], ["orderbook_delta"]):
                            params = {"channels": channels, "market_tickers": tickers}
                            if channels == ["orderbook_delta"]:
                                params["use_yes_price"] = True
                            await websocket.send(json.dumps({"id": command_id, "cmd": "subscribe", "params": params}))
                            command_id += 1
                    await websocket.send(json.dumps({"id": command_id, "cmd": "subscribe",
                                                      "params": {"channels": ["market_lifecycle_v2"]}}))
                    self.state["websocket"] = "connected"
                    self.state["errors"].pop("websocket", None)
                    failures = 0
                    subscription_check = time.monotonic()
                    while True:
                        try:
                            payload = await asyncio.wait_for(websocket.recv(), timeout=15)
                            frame = json.loads(payload)
                            if not isinstance(frame, dict):
                                raise ValueError("Invalid WebSocket frame")
                            self.process_frame(frame, guard)
                        except asyncio.TimeoutError:
                            # Keepalive is handled by websockets; no data is not proof of failure.
                            pass
                        if time.monotonic() - subscription_check > 30:
                            current = sorted(t for t, m in self.markets.items() if m.get("status") != "finalized")
                            if current != selected:
                                break  # Reconnect and obtain fresh snapshots for the new selection.
                            subscription_check = time.monotonic()
            except asyncio.CancelledError:
                raise
            except (websockets.WebSocketException, OSError, TimeoutError, ValueError, UpstreamError, BookError):
                failures += 1
                self.state["errors"]["websocket"] = "stream_unavailable_or_resynchronizing"
            finally:
                self.state["websocket"] = "disconnected"
                self.detector.reset()
                for book in self.books.values():
                    book.valid = False
                self.publish()
            await asyncio.sleep(min(60, 2 ** min(failures, 6)) + random.uniform(0, 1))

    async def portfolio(self) -> dict:
        if not self.client.signer:
            return {"status": "credentials_required", "balance": None, "positions": [], "fills": [],
                    "orders": [], "settlements": [], "source_url": self.settings.rest_url + "/portfolio/balance"}
        async with self._portfolio_lock:
            if self._portfolio_cache and now_ms() - self._portfolio_cache[0] < 15_000:
                return self._portfolio_cache[1]
            result = {"mode": "kalshi_demo_account", "status": "connected", "balance": None,
                      "coverage": {}, "errors": {}, "source_url": self.settings.rest_url + "/portfolio/balance"}
            try:
                balance = await self.client.get("/portfolio/balance", authenticated=True)
                result["balance"] = {**balance, "source_url": self.settings.rest_url + "/portfolio/balance"}
            except UpstreamError as exc:
                result["errors"]["balance"] = exc.code
            # Keep current and archive records separate: they are not atomic snapshots, and
            # historical position/settlement shapes differ. Coverage is explicitly scoped to primary subaccount.
            endpoints = (
                ("positions", "/portfolio/positions", "market_positions", {"settlement_status": "all", "subaccount": 0}),
                ("orders", "/portfolio/orders", "orders", {"subaccount": 0}),
                ("fills", "/portfolio/fills", "fills", {"subaccount": 0}),
                ("settlements", "/portfolio/settlements", "settlements", {"subaccount": 0}),
                ("historical_positions", "/historical/positions", "market_positions", {"subaccount": 0}),
                ("historical_orders", "/historical/orders", "orders", {"subaccount": 0}),
                ("historical_fills", "/historical/fills", "fills", {"subaccount": 0}),
            )
            for name, path, key, params in endpoints:
                page = await self.client.pages(path, key, params, authenticated=True)
                result[name] = [{**row, "source_url": self.settings.rest_url + path,
                                 "observed_at": iso_time(now_ms()),
                                 "topic": self.markets.get(row.get("ticker"), {}).get("topic")}
                                for row in page.rows]
                result["coverage"][name] = {"complete": page.complete, "pages": page.pages}
                if page.error:
                    result["errors"][name] = page.error
            if result["errors"]:
                result["status"] = "partial_or_disconnected"
            result["account_scope"] = "primary subaccount only; all exchange shards; live/archive reads are not atomic"
            result["performance_note"] = "No ROI is inferred from balance changes: deposits, transfers and archive overlap require reconciliation."
            result["observed_at"] = iso_time(now_ms())
            self._portfolio_cache = (now_ms(), result)
            self.store.put("private_portfolio", "latest", result)
            return result
