"""The live engine: fetch, detect, explain, score, simulate, and settle.

One `Collector` instance owns the market universe and runs three loops:

    refresh   - rebuild the tracked market list (topics, ordering, price band)
    poll      - read orderbooks/tickers, feed the swing detector, act on alerts
    lifecycle - mark positions, apply exits, settle resolved markets, snapshot equity

The topic universe is refreshed every `UNIVERSE_REFRESH_SECONDS` because Kalshi
opens and resolves markets continuously. Ordering is by traded volume, which is
the closest published proxy for "biggest dollar events" (the requirement's
"highest dollar amount live events"): `volume_fp` is contracts traded and the
ticker message also exposes `dollar_volume`.

Every external call is wrapped so a single failure cannot stop the dashboard;
the failure is recorded in `self.status` and shown in the UI rather than hidden.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .alerts import SwingAlert, SwingDetector, observed_price
from .config import Settings
from .kalshi_api import KalshiAPI, KalshiAPIError
from .money import ONE, ZERO, Orderbook, contracts as to_contracts, to_decimal
from .news import NewsFinder, contract_sources, query_from_title
from .simulator import SPECS, MarketContext, Simulator, score_for_alert
from .storage import Store
from .topics import TOPIC_ORDER, match_topic, topic_page_url
from .ws import KalshiWebSocket

log = logging.getLogger("kalshi.collector")

UNIVERSE_REFRESH_SECONDS = 300
LIFECYCLE_SECONDS = 15
MAX_NEWS_PER_CYCLE = 4
PRICE_FLOOR = Decimal("0.02")
PRICE_CEILING = Decimal("0.98")

# Status values that mean "not tradeable any more". "finalized" is what the live
# API actually returns for settled markets (verified 2026-11-22 on
# GET /markets?status=settled); the docs list closed/settled/determined.
TERMINAL_STATUSES = {"closed", "settled", "determined", "finalized", "unopened"}


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: Any) -> float | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return float(value) / (1000 if value > 1e11 else 1)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


class Collector:
    def __init__(self, settings: Settings, store: Store, *, api: KalshiAPI | None = None,
                 news: NewsFinder | None = None, ws: KalshiWebSocket | None = None):
        self.settings = settings
        self.store = store
        self.api = api
        self.news = news or NewsFinder(lookback_hours=settings.news_lookback_hours)
        self.detector = SwingDetector(
            threshold=settings.swing_threshold,
            window_seconds=settings.swing_window_seconds,
            cooldown_seconds=settings.alert_cooldown_seconds,
        )
        self.sim = Simulator(store, settings, api=api)
        self.ws = ws or KalshiWebSocket(settings, signer=None, on_message=self._on_ws_message)

        self.tracked: dict[str, dict] = {}          # ticker -> market metadata
        self.books: dict[str, Orderbook] = {}
        self.status: dict[str, Any] = {
            "running": False,
            "last_refresh_utc": None,
            "last_poll_utc": None,
            "last_error": None,
            "refresh_errors": [],
            "ws_connected": False,
            "ws_messages": 0,
            "universe_size": 0,
            "tracked_size": 0,
            "poll_ms": None,
            "cycles": 0,
        }
        self._stop = asyncio.Event()
        self._pending_news: list[dict] = []
        self._resolution_cache: dict[str, dict] = {}
        self.status["series_errors"] = []
        self._last_universe = 0.0
        self._next_refresh_at = 0.0
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------ #
    # Public control
    # ------------------------------------------------------------------ #
    async def start(self, *, own_api: bool = True) -> None:
        if self.status["running"]:
            return
        self.status["running"] = True
        self._stop.clear()
        if own_api and self.api is None:
            self.api = KalshiAPI(self.settings)
            await self.api.__aenter__()
        if self.api is not None and self.settings.has_credentials:
            from .auth import KalshiSigner
            signer = KalshiSigner.from_pem_file(self.settings.api_key_id, self.settings.private_key_path)
            self.ws.signer = signer
            self._tasks.append(asyncio.create_task(self._ws_task(), name="kalshi-ws"))
        self._tasks.append(asyncio.create_task(self._poll_loop(), name="kalshi-poll"))
        self._tasks.append(asyncio.create_task(self._lifecycle_loop(), name="kalshi-lifecycle"))

    async def stop(self) -> None:
        self._stop.set()
        self.ws.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        if self.api is not None:
            await self.api.__aexit__(None, None, None)
        self.status["running"] = False

    # ------------------------------------------------------------------ #
    # Universe
    # ------------------------------------------------------------------ #
    async def _series_tags(self, series_tickers: list[str], budget: int = 40) -> dict[str, list[str]]:
        """Published tags per series: cache first, then GET /series/{ticker}.

        Events do not carry `tags`; the series does
        (https://docs.kalshi.com/api-reference/market/get-series). Without this
        lookup, golf would only be detectable from the ticker name. `budget`
        bounds the number of live lookups so one refresh cannot stall.
        """
        out: dict[str, list[str]] = {}
        missing: list[str] = []
        for ticker in series_tickers:
            cached = self.store.get_series(ticker)
            if cached is not None:
                out[ticker] = cached["tags"]
            else:
                missing.append(ticker)
        if self.api is None:
            return out

        semaphore = asyncio.Semaphore(6)

        async def fetch(ticker: str) -> tuple[str, list[str]]:
            async with semaphore:
                try:
                    detail = await self.api.series_detail(ticker)
                except KalshiAPIError as exc:
                    self.status.setdefault("series_errors", []).append(f"{ticker}: {exc}")
                    return ticker, []
            tags = detail.get("tags") or []
            category = detail.get("category") or (detail.get("categories") or [None])[0]
            self.store.put_series(ticker, category=category, tags=tags, title=detail.get("title"))
            return ticker, tags

        results = await asyncio.gather(*(fetch(t) for t in missing[:budget]))
        for ticker, tags in results:
            out[ticker] = tags
        return out

    async def refresh_universe(self) -> dict:
        """Rebuild the tracked market list from open events."""
        if self.api is None:
            raise RuntimeError("collector started without an API client")
        errors: list[str] = []
        topics_found: dict[str, int] = {t: 0 for t in TOPIC_ORDER}
        by_topic: dict[str, list[dict]] = {t: [] for t in TOPIC_ORDER}

        # The published taxonomy is the basis for topic mapping; fetch it once
        # per refresh so a new category/tag pair is picked up automatically.
        try:
            await self.api.tags_by_categories()
        except KalshiAPIError as exc:
            errors.append(f"tags_by_categories: {exc}")

        # Pull open events across every category and map them locally. Filtering
        # by `category=` server-side is unreliable in demo (it returns events
        # from other categories), so we filter client-side from published fields.
        try:
            events = await self.api.events(status="open", limit=self.settings.max_tracked_markets * 4,
                                           with_nested_markets=True, max_pages=12)
        except KalshiAPIError as exc:
            self.status["refresh_errors"] = [str(exc)]
            self.status["last_error"] = f"events: {exc}"
            return {"tracked": 0, "errors": [str(exc)]}

        # Series tags are the authoritative source for the Sports/Golf tag.
        series_tickers: list[str] = []
        for event in events:
            series = event.get("series_ticker") or (
                (event.get("event_ticker") or "").split("-")[0] if event.get("event_ticker") else None
            )
            if series and series not in series_tickers:
                series_tickers.append(series)
        series_tags_map = await self._series_tags(series_tickers)

        for event in events:
            category = event.get("category")
            event_tags = event.get("tags") or []
            series = event.get("series_ticker") or (
                (event.get("event_ticker") or "").split("-")[0] if event.get("event_ticker") else None
            )
            series_tags = series_tags_map.get(series or "", []) if series else []
            for market in event.get("markets") or []:
                title = market.get("title") or event.get("title") or market.get("ticker")
                matched = match_topic(
                    category=category,
                    tags=[*event_tags, *(market.get("tags") or []), *series_tags],
                    title=title,
                    series_ticker=series,
                    event_ticker=event.get("event_ticker"),
                    market_ticker=market.get("ticker"),
                )
                if not matched.matched:
                    continue
                topic = matched.topic
                row = self._market_row(market, event, topic, matched.reason, series)
                if row is None:
                    continue
                row["meta"]["series_tags"] = series_tags
                topics_found[topic] += 1
                by_topic[topic].append(row)

        # Keep the biggest events per topic and rank by volume, then OI.
        tracked: dict[str, dict] = {}
        per_topic_cap = max(20, self.settings.max_tracked_markets // max(1, len(TOPIC_ORDER)))
        for topic, rows in by_topic.items():
            rows.sort(key=lambda r: (r["_volume"], r["_open_interest"]), reverse=True)
            for row in rows[:per_topic_cap]:
                tracked[row["ticker"]] = row

        self.tracked = tracked
        for row in tracked.values():
            self.store.upsert_market({k: v for k, v in row.items() if not k.startswith("_")})
        self.status.update({
            "last_refresh_utc": _iso(),
            "refresh_errors": errors,
            "universe_size": len(events),
            "tracked_size": len(tracked),
            "topics": topics_found,
        })
        self.ws.update_markets(list(tracked.keys()))
        return {"tracked": len(tracked), "universe": len(events), "topics": topics_found, "errors": errors}

    def _market_row(self, market: dict, event: dict, topic: str, basis: str,
                    series: str | None) -> dict | None:
        ticker = market.get("ticker")
        if not ticker:
            return None
        status = (market.get("status") or "").lower()
        # Observed live statuses include "active" (open) and "finalized"
        # (settled). The docs advertise unopened/open/closed/settled, so treat
        # any terminal-looking status as resolved and keep it out of the live board.
        if status in TERMINAL_STATUSES:
            return None
        # Multivariate ("combo") markets bundle several unrelated categories into
        # one ticker, so they cannot belong to a single topic. Excluded, and the
        # exclusion is stated on the site.
        if ticker.upper().startswith("KXMVE"):
            return None
        last = to_decimal(market.get("last_price_dollars"))
        yes_bid = to_decimal(market.get("yes_bid_dollars"))
        yes_ask = to_decimal(market.get("yes_ask_dollars"))
        price, two_sided, _ = observed_price(yes_bid=yes_bid, yes_ask=yes_ask, last_price=last)
        # A market with no price at all cannot produce a $0.10 swing; keep it for
        # tracking but do not inflate the live board.
        volume = to_decimal(market.get("volume_fp"), ZERO) or ZERO
        oi = to_decimal(market.get("open_interest_fp"), ZERO) or ZERO
        notional = to_decimal(market.get("notional_value_dollars"), ONE) or ONE
        source_list = contract_sources(event.get("settlement_sources"))
        return {
            "ticker": ticker,
            "event_ticker": market.get("event_ticker") or event.get("event_ticker"),
            "series_ticker": series,
            "title": market.get("title") or event.get("title"),
            "subtitle": market.get("yes_sub_title") or market.get("subtitle"),
            "category": event.get("category"),
            "topic": topic,
            "topic_basis": basis,
            "status": status or "open",
            "close_time": market.get("close_time") or market.get("expected_expiration_time"),
            "expected_expiration_time": market.get("expected_expiration_time"),
            "result": market.get("result") or None,
            "settlement_value": market.get("settlement_value_dollars") or None,
            "rules_primary": market.get("rules_primary"),
            "page_url": topic_page_url(market.get("event_ticker") or event.get("event_ticker"), series),
            "volume_fp": str(volume),
            "open_interest_fp": str(oi),
            "last_price": str(last) if last is not None else None,
            "yes_bid": str(yes_bid) if yes_bid is not None else None,
            "yes_ask": str(yes_ask) if yes_ask is not None else None,
            "price": str(price) if price is not None else None,
            "two_sided": two_sided,
            "notional": str(notional),
            "dollar_volume": str((volume * notional).quantize(Decimal("1"))),
            "meta": {
                "currency": "USD",
                "event_title": event.get("title"),
                "mutually_exclusive": event.get("mutually_exclusive"),
                "settlement_sources": source_list,
                "price_level_structure": market.get("price_level_structure"),
                "can_close_early": market.get("can_close_early"),
                "source": "GET /events?status=open&with_nested_markets=true",
                "source_url": "https://docs.kalshi.com/api-reference/events/get-events",
            },
            "_volume": volume,
            "_open_interest": oi,
        }

    # ------------------------------------------------------------------ #
    # Polling loop
    # ------------------------------------------------------------------ #
    async def _poll_loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            try:
                if self.api is None:
                    await asyncio.sleep(self.settings.poll_seconds)
                    continue
                if time.time() - self._last_universe > UNIVERSE_REFRESH_SECONDS or not self.tracked:
                    await self.refresh_universe()
                    self._last_universe = time.time()
                await self.poll_once()
                self.status["cycles"] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let the loop die
                self.status["last_error"] = f"{type(exc).__name__}: {exc}"
                log.exception("poll cycle failed")
            self.status["poll_ms"] = int((time.time() - started) * 1000)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def poll_once(self) -> dict:
        """One snapshot of every tracked market, then detect and act."""
        if self.api is None or not self.tracked:
            return {"polled": 0}
        tickers = list(self.tracked.keys())

        # Refresh the market rows cheaply for lifecycle/price changes; the
        # orderbook gives depth. Both are public and unauthenticated.
        try:
            books_raw = await self.api.orderbooks(tickers, depth=20)
        except KalshiAPIError as exc:
            self.status["last_error"] = f"orderbooks: {exc}"
            books_raw = {}

        alerts: list[dict] = []
        now = time.time()
        for ticker in tickers:
            meta = self.tracked[ticker]
            raw = books_raw.get(ticker) or {}
            book = Orderbook.from_payload(raw)
            if not book.is_empty():
                self.books[ticker] = book
            else:
                book = self.books.get(ticker, Orderbook())

            # Prefer the book for quotes; fall back to the ticker snapshot from
            # the last universe refresh.
            yes_bid = book.best_yes_bid
            yes_ask = book.best_yes_ask
            if yes_bid is None and yes_ask is None:
                yes_bid = to_decimal(meta.get("yes_bid"))
                yes_ask = to_decimal(meta.get("yes_ask"))
            last = to_decimal(meta.get("last_price"))
            liquidity = book.liquidity_dollars() if not book.is_empty() else None

            price, two_sided, used_last = observed_price(
                yes_bid=yes_bid, yes_ask=yes_ask, last_price=last,
            )
            if price is None:
                continue
            self.sim.update_price(ticker, price)
            self.store.add_tick(
                ticker, ts=now,
                yes_bid=str(yes_bid) if yes_bid is not None else None,
                yes_ask=str(yes_ask) if yes_ask is not None else None,
                last_price=str(last) if last is not None else None,
                liquidity=str(liquidity) if liquidity is not None else None,
                source="ws" if self.ws.connected else "rest",
            )

            swing = self.detector.observe(
                ticker, ts=now, yes_bid=yes_bid, yes_ask=yes_ask,
                last_price=last, liquidity=liquidity, traded=used_last,
            )
            if swing is not None:
                alert = await self._materialise_alert(swing, meta, book, price)
                alerts.append(alert)

        self.status["last_poll_utc"] = _iso()
        self.status["ws_connected"] = self.ws.connected
        self.status["ws_messages"] = self.ws.messages
        if alerts:
            await self._dispatch(alerts)
        return {"polled": len(tickers), "alerts": len(alerts)}

    async def _materialise_alert(self, swing: SwingAlert, meta: dict, book: Orderbook,
                                 price: Decimal) -> dict:
        ticker = swing.ticker
        topic = meta.get("topic") or "other"
        yes_ask = book.best_yes_ask
        yes_bid = book.best_yes_bid
        depth = book.contracts_within("yes", Decimal("0.10")) if not book.is_empty() else None

        hours_to_close = None
        close_ts = _parse_ts(meta.get("close_time")) or _parse_ts(meta.get("expected_expiration_time"))
        if close_ts:
            hours_to_close = max(0.0, (close_ts - time.time()) / 3600)

        ctx = MarketContext(
            ticker=ticker, event_ticker=meta.get("event_ticker"), topic=topic,
            title=meta.get("title") or ticker, best_bid=yes_bid, best_ask=yes_ask,
            depth_10c=depth, liquidity=book.liquidity_dollars() if not book.is_empty() else None,
            volume_24h=to_decimal(meta.get("volume_fp")), open_interest=to_decimal(meta.get("open_interest_fp")),
            hours_to_close=hours_to_close, two_sided=yes_bid is not None and yes_ask is not None,
            page_url=meta.get("page_url"),
        )
        fee = self.sim._fee(yes_ask, ONE, maker=False) if yes_ask else None

        news_payload = {"status": "pending", "headlines": [],
                        "contract_sources": (meta.get("meta") or {}).get("settlement_sources", [])}
        alert = {
            "ts": swing.ts, "ticker": ticker, "event_ticker": meta.get("event_ticker"),
            "topic": topic, "title": meta.get("title"), "direction": swing.direction,
            "from_price": str(swing.from_price), "to_price": str(swing.to_price),
            "delta": str(swing.delta), "window_s": swing.window_s,
            "confidence": swing.confidence, "reasons": swing.reasons,
            "page_url": meta.get("page_url"), "best_bid": str(yes_bid) if yes_bid else None,
            "best_ask": str(yes_ask) if yes_ask else None,
            "depth_10c": str(depth) if depth is not None else None,
            "liquidity": str(ctx.liquidity) if ctx.liquidity is not None else None,
            "hours_to_close": round(hours_to_close, 2) if hours_to_close is not None else None,
            "news": news_payload,
            "sources": [
                {"name": "Kalshi market page", "url": meta.get("page_url")},
                {"name": "GET /markets/{ticker}/orderbook",
                 "url": "https://docs.kalshi.com/api-reference/market/get-market-orderbook"},
            ],
        }
        score = score_for_alert(alert, ctx, threshold=self.settings.swing_threshold, fee=fee)
        alert["score"] = str(score["score"])
        alert["score_detail"] = score
        alert["selective"] = Decimal(score["score"]) >= self.settings.selective_min_score
        alert["id"] = self.store.add_alert(alert)
        if len(self._pending_news) < MAX_NEWS_PER_CYCLE:
            self._pending_news.append(alert)
        return alert

    async def enrich_news(self, alerts: list[dict]) -> None:
        """Attach candidate headlines after the alert is already visible.

        Keeping this off the alert path means the chat never blocks on the
        network, and a failed lookup is shown as `error` rather than fabricated.
        """
        if not alerts:
            return
        queries = {a["ticker"]: query_from_title(a.get("title") or a["ticker"]) for a in alerts}
        results = await self.news.many(queries.values())
        for alert in alerts:
            result = results.get(queries[alert["ticker"]])
            if result is None:
                continue
            alert["news"] = {
                "status": result.status,
                "note": result.note,
                "headlines": [h.as_dict() for h in result.headlines],
                "contract_sources": alert["news"].get("contract_sources", []),
            }

    async def _dispatch(self, alerts: list[dict]) -> None:
        """Run every strategy against every alert, then enrich the news."""
        for alert in alerts:
            meta = self.tracked.get(alert["ticker"], {})
            book = self.books.get(alert["ticker"], Orderbook())
            ctx = MarketContext(
                ticker=alert["ticker"], event_ticker=alert.get("event_ticker"),
                topic=alert["topic"], title=alert.get("title") or alert["ticker"],
                best_bid=book.best_yes_bid, best_ask=book.best_yes_ask,
                depth_10c=book.contracts_within("yes", Decimal("0.10")) if not book.is_empty() else None,
                liquidity=book.liquidity_dollars() if not book.is_empty() else None,
                volume_24h=to_decimal(meta.get("volume_fp")),
                open_interest=to_decimal(meta.get("open_interest_fp")),
                hours_to_close=alert.get("hours_to_close"),
                two_sided=book.best_yes_bid is not None and book.best_yes_ask is not None,
                page_url=alert.get("page_url"),
            )
            news_trusted = any(h.get("trusted") for h in (alert.get("news") or {}).get("headlines") or [])
            mode = "demo" if self.settings.live_orders_enabled else "paper"
            for spec in SPECS:
                decision = self.sim.propose(spec, alert=alert, ctx=ctx,
                                            score=alert["score_detail"], news_trusted=news_trusted)
                if decision is None:
                    continue
                await self.sim.execute(spec, decision, alert=alert, ctx=ctx, mode=mode)

        pending, self._pending_news = self._pending_news, []
        if pending:
            await self.enrich_news(pending)
            # Persist the enriched news on the stored alert.
            for alert in pending:
                self._update_alert_news(alert)

    def _update_alert_news(self, alert: dict) -> None:
        import json
        with self.store._lock:  # narrow, deliberate: single-row update
            self.store._conn.execute(
                "UPDATE alerts SET news_json=? WHERE id=?",
                (json.dumps(alert.get("news") or []), alert.get("id")),
            )
            self.store._conn.commit()

    # ------------------------------------------------------------------ #
    # Lifecycle loop
    # ------------------------------------------------------------------ #
    async def _lifecycle_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.mark_and_settle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("lifecycle failed: %s", exc)
                self.status["last_error"] = f"lifecycle: {exc}"
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=LIFECYCLE_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def mark_and_settle(self) -> dict:
        mode = "demo" if self.settings.live_orders_enabled else "paper"
        actions = await self.sim.mark_and_manage(mode=mode)
        resolutions = await self.check_resolutions()
        if resolutions:
            actions += await self.sim.settle_resolutions(resolutions, mode=mode)
        return {"actions": len(actions), "resolutions": len(resolutions)}

    async def check_resolutions(self) -> list[dict]:
        """Ask Kalshi whether any tracked or held market has been determined.

        `result` is `yes`/`no`/`""` and `settlement_value_dollars` carries the
        settlement price; both are documented on GET /markets/{ticker}.
        """
        if self.api is None:
            return []
        held = {p["ticker"] for spec in SPECS for p in self.store.positions(spec.key)}
        candidates = sorted(held | set(self.tracked.keys()))
        if not candidates:
            return []
        found: list[dict] = []
        for ticker in candidates[:120]:
            try:
                market = await self.api.market(ticker)
            except KalshiAPIError:
                continue
            result = (market.get("result") or "").lower()
            status = (market.get("status") or "").lower()
            if result in {"yes", "no"} or status in {"determined", "settled", "finalized"}:
                row = {
                    "ticker": ticker,
                    "event_ticker": market.get("event_ticker"),
                    "topic": self.tracked.get(ticker, {}).get("topic")
                             or (self.store.get_market(ticker) or {}).get("topic"),
                    "title": market.get("title"),
                    "result": result or None,
                    "settlement_value": market.get("settlement_value_dollars"),
                    "determined_ts": _parse_ts(market.get("settlement_ts")),
                    "page_url": self.tracked.get(ticker, {}).get("page_url"),
                    "note": f"GET /markets/{ticker} status={status}",
                }
                if row["result"]:
                    self.store.set_resolution(row)
                    found.append(row)
                self._resolution_cache[ticker] = row
        return found

    # ------------------------------------------------------------------ #
    # WebSocket
    # ------------------------------------------------------------------ #
    async def _ws_task(self) -> None:
        try:
            await self.ws.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.status["last_error"] = f"websocket: {exc}"

    async def _on_ws_message(self, message: dict) -> None:
        msg_type = message.get("type")
        if msg_type == "ticker":
            await self._on_ticker(message.get("msg") or {})
        elif msg_type == "market_lifecycle_v2":
            await self._on_lifecycle(message.get("msg") or {})

    async def _on_ticker(self, msg: dict) -> None:
        ticker = msg.get("market_ticker")
        if not ticker or ticker not in self.tracked:
            return
        meta = self.tracked[ticker]
        yes_bid = to_decimal(msg.get("yes_bid_dollars"))
        yes_ask = to_decimal(msg.get("yes_ask_dollars"))
        last = to_decimal(msg.get("price_dollars"))
        ts = (msg.get("ts_ms") or 0) / 1000 if msg.get("ts_ms") else time.time()
        price, two_sided, used_last = observed_price(yes_bid=yes_bid, yes_ask=yes_ask, last_price=last)
        if price is None:
            return
        self.sim.update_price(ticker, price)
        self.store.add_tick(ticker, ts=ts, yes_bid=str(yes_bid) if yes_bid else None,
                            yes_ask=str(yes_ask) if yes_ask else None,
                            last_price=str(last) if last else None, source="ws")
        swing = self.detector.observe(ticker, ts=ts, yes_bid=yes_bid, yes_ask=yes_ask,
                                      last_price=last, traded=used_last)
        if swing is not None:
            book = self.books.get(ticker, Orderbook())
            alert = await self._materialise_alert(swing, meta, book, price)
            await self._dispatch([alert])

    async def _on_lifecycle(self, msg: dict) -> None:
        ticker = msg.get("market_ticker")
        result = (msg.get("result") or "").lower()
        if not ticker or result not in {"yes", "no"}:
            return
        row = {
            "ticker": ticker, "event_ticker": None,
            "topic": self.tracked.get(ticker, {}).get("topic"),
            "title": self.tracked.get(ticker, {}).get("title"),
            "result": result, "settlement_value": msg.get("settlement_value"),
            "determined_ts": msg.get("determination_ts"),
            "page_url": self.tracked.get(ticker, {}).get("page_url"),
            "note": "market_lifecycle_v2 websocket",
        }
        self.store.set_resolution(row)
        await self.sim.settle_resolutions([row],
                                          mode="demo" if self.settings.live_orders_enabled else "paper")

    # ------------------------------------------------------------------ #
    # Views
    # ------------------------------------------------------------------ #
    def dashboard_state(self, *, topic: str | None = None, limit: int = 60) -> dict:
        """Everything the UI needs for one render."""
        markets = self._market_rows(topic=topic, limit=limit)
        return {
            "generated_utc": _iso(),
            "environment": self.settings.environment,
            "status": {**self.status, "ws_connected": self.ws.connected,
                       "ws_messages": self.ws.messages},
            "topics": list(TOPIC_ORDER),
            "alerts": self.store.list_alerts(limit=40),
            "selective_alerts": self.store.list_alerts(limit=40, selective=True),
            "markets": markets,
            "resolutions": self.store.list_resolutions(limit=40),
            "portfolio": self.sim.portfolio_summary(),
            "events": self.sim.recent_events(40),
            "counts": self.store.counts(),
            "threshold": str(self.settings.swing_threshold),
        }

    def _market_rows(self, *, topic: str | None = None, limit: int = 60) -> list[dict]:
        rows = []
        for ticker, meta in self.tracked.items():
            if topic and topic != "all" and meta.get("topic") != topic:
                continue
            book = self.books.get(ticker)
            price = self.sim.mark_price(ticker, "yes")
            rows.append({
                "ticker": ticker,
                "event_ticker": meta.get("event_ticker"),
                "title": meta.get("title"),
                "subtitle": meta.get("subtitle"),
                "topic": meta.get("topic"),
                "close_time": meta.get("close_time"),
                "page_url": meta.get("page_url"),
                "price": str(price) if price is not None else meta.get("price"),
                "yes_bid": str(book.best_yes_bid) if book and book.best_yes_bid else meta.get("yes_bid"),
                "yes_ask": str(book.best_yes_ask) if book and book.best_yes_ask else meta.get("yes_ask"),
                "spread": str(book.spread_for("yes")) if book and book.spread_for("yes") is not None else None,
                "depth_10c": str(book.contracts_within("yes", Decimal("0.10"))) if book and not book.is_empty() else None,
                "liquidity": str(book.liquidity_dollars()) if book and not book.is_empty() else None,
                "volume_fp": meta.get("volume_fp"),
                "dollar_volume": meta.get("dollar_volume"),
                "open_interest_fp": meta.get("open_interest_fp"),
                "two_sided": book is not None and book.best_yes_bid is not None and book.best_yes_ask is not None,
                "topic_basis": meta.get("topic_basis"),
            })
        rows.sort(key=lambda r: Decimal(str(r.get("dollar_volume") or 0)), reverse=True)
        return rows[:limit]

    def market_detail(self, ticker: str, *, range_seconds: int = 3600) -> dict | None:
        meta = self.tracked.get(ticker) or self.store.get_market(ticker)
        if not meta:
            return None
        since = time.time() - range_seconds
        ticks = self.store.ticks(ticker, since_ts=since, limit=20000)
        book = self.books.get(ticker)
        return {
            "market": meta,
            "ticks": ticks,
            "orderbook": book.as_dict() if book else None,
            "ladder_yes": book.cumulative("yes") if book else [],
            "ladder_no": book.cumulative("no") if book else [],
            "alerts": [a for a in self.store.list_alerts(limit=100) if a["ticker"] == ticker],
            "range_seconds": range_seconds,
            "generated_utc": _iso(),
        }
