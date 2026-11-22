"""Thin async client for the documented Kalshi Trade API v2 REST surface.

Every method names the endpoint it calls and the documentation URL that
describes it. Public market-data endpoints are unauthenticated; portfolio and
order endpoints are signed.

Implemented against these verified pages (all docs.kalshi.com, checked
2026-11-22):

    GET  /exchange/status                       api-reference/exchange/get-exchange-status
    GET  /markets                               api-reference/market/get-markets
    GET  /markets/{ticker}                      api-reference/market/get-market
    GET  /markets/{ticker}/orderbook            api-reference/market/get-market-orderbook
    GET  /markets/orderbooks?tickers=...        api-reference/market/get-multiple-market-orderbooks
    GET  /markets/trades                        api-reference/market/get-trades
    GET  /series/{series}/markets/{ticker}/candlesticks
                                                api-reference/market/get-market-candlesticks
    GET  /events                                api-reference/events/get-events
    GET  /events/{event_ticker}                 api-reference/events/get-event
    GET  /series                                api-reference/market/get-series-list
    GET  /search/tags_by_categories             (public taxonomy, used by app/topics.py)
    GET  /portfolio/balance                     api-reference/portfolio/get-balance
    GET  /portfolio/positions                   api-reference/portfolio/get-positions
    GET  /portfolio/fills                       api-reference/portfolio/get-fills
    GET  /portfolio/settlements                 api-reference/portfolio/get-settlements
    POST /portfolio/events/orders               api-reference/orders/create-order-v2
    DELETE /portfolio/events/orders/{order_id}  api-reference/orders/cancel-order-v2

Design notes
------------
* Errors are never swallowed into fake data. `KalshiAPIError` carries the HTTP
  status and Kalshi's error body.
* 429 is retried with exponential backoff, as the rate-limit page instructs:
  https://docs.kalshi.com/getting_started/rate_limits ("Apply exponential
  backoff on 429"; there is no Retry-After header).
* Prices are returned as the fixed-point strings Kalshi sends. Parsing happens
  in `app.money` so a missing price can never be confused with $0.00.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Iterable

import httpx

from .auth import KalshiSigner
from .config import Settings


class KalshiAPIError(RuntimeError):
    def __init__(self, status: int, payload: Any, url: str, method: str = "GET"):
        self.status = status
        self.payload = payload
        self.url = url
        self.method = method
        super().__init__(f"{method} {url} -> HTTP {status}: {_brief(payload)}")

    @property
    def code(self) -> str | None:
        if isinstance(self.payload, dict):
            err = self.payload.get("error")
            if isinstance(err, dict):
                return err.get("code")
            if isinstance(err, str):
                return err
        return None

    @property
    def retryable(self) -> bool:
        return self.status == 429 or self.status >= 500


def _brief(payload: Any) -> str:
    text = str(payload)
    return text[:400]


@dataclass
class Page:
    items: list[dict]
    cursor: str | None


class KalshiAPI:
    """Async REST client. Use as an async context manager."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 20.0, max_retries: int = 3):
        self.settings = settings
        self._timeout = timeout
        self._max_retries = max_retries
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._signer: KalshiSigner | None = None
        self.last_rate_limit: dict[str, str] = {}

    # -- lifecycle --------------------------------------------------------
    async def __aenter__(self) -> "KalshiAPI":
        self._client = httpx.AsyncClient(
            base_url=self.settings.rest_base,
            timeout=self._timeout,
            transport=self._transport,
            headers={"Accept": "application/json", "User-Agent": "tradebot1-kalshi-dashboard/1.0"},
        )
        if self.settings.has_credentials:
            self._signer = KalshiSigner.from_pem_file(
                self.settings.api_key_id, self.settings.private_key_path  # type: ignore[arg-type]
            )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def authenticated(self) -> bool:
        return self._signer is not None

    # -- core request -----------------------------------------------------
    async def request(self, method: str, path: str, *, params: dict | None = None,
                      json: dict | None = None, auth: bool = False,
                      raise_for_status: bool = True) -> Any:
        if self._client is None:
            raise RuntimeError("KalshiAPI must be used as an async context manager")
        if auth and self._signer is None:
            raise PermissionError("This endpoint needs KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH")

        attempt = 0
        while True:
            headers = {}
            if auth:
                # Timestamp is generated per attempt: the 30 second window is
                # measured against Kalshi's clock at send time.
                headers = self._signer.headers(method, path)  # type: ignore[union-attr]
            try:
                response = await self._client.request(method, path, params=params, json=json, headers=headers)
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise KalshiAPIError(0, f"network error: {exc}", path, method) from exc
                attempt += 1
                await asyncio.sleep(_backoff(attempt))
                continue

            for key in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset", "x-ratelimit-cost"):
                if key in response.headers:
                    self.last_rate_limit[key] = response.headers[key]

            if response.status_code < 400:
                if response.status_code == 204 or not response.content:
                    return None
                return response.json()

            payload: Any
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            error = KalshiAPIError(response.status_code, payload, path, method)
            if error.retryable and attempt < self._max_retries:
                attempt += 1
                await asyncio.sleep(_backoff(attempt))
                continue
            if not raise_for_status:
                return None
            raise error

    async def get(self, path: str, **kwargs) -> Any:
        return await self.request("GET", path, **kwargs)

    # -- exchange ---------------------------------------------------------
    async def exchange_status(self) -> dict:
        """GET /exchange/status -- no auth required."""
        return await self.get("/exchange/status")

    # -- taxonomy ---------------------------------------------------------
    async def tags_by_categories(self) -> dict:
        """GET /search/tags_by_categories -- the published category -> tag map."""
        data = await self.get("/search/tags_by_categories")
        return (data or {}).get("tags_by_categories", {})

    async def series(self, *, category: str | None = None, limit: int = 200) -> list[dict]:
        """GET /series -- paginated list of series templates."""
        params: dict[str, Any] = {"limit": min(limit, 200)}
        if category:
            params["category"] = category
        out: list[dict] = []
        cursor = None
        while True:
            if cursor:
                params["cursor"] = cursor
            data = await self.get("/series", params=params) or {}
            out.extend(data.get("series") or [])
            cursor = data.get("cursor")
            if not cursor or len(out) >= limit:
                break
        return out[:limit]

    # -- events / markets -------------------------------------------------
    async def events(self, *, status: str = "open", limit: int = 200, category: str | None = None,
                     with_nested_markets: bool = True, series_ticker: str | None = None,
                     max_pages: int = 5) -> list[dict]:
        params: dict[str, Any] = {
            "limit": min(limit, 200),
            "with_nested_markets": str(with_nested_markets).lower(),
        }
        if status:
            params["status"] = status
        if category:
            params["category"] = category
        if series_ticker:
            params["series_ticker"] = series_ticker
        out: list[dict] = []
        cursor = None
        for _ in range(max_pages):
            if cursor:
                params["cursor"] = cursor
            data = await self.get("/events", params=params or None) or {}
            out.extend(data.get("events") or [])
            cursor = data.get("cursor")
            if not cursor or len(out) >= limit:
                break
        return out[:limit]

    async def event(self, event_ticker: str, with_nested_markets: bool = True) -> dict:
        params = None
        if with_nested_markets:
            params = {"with_nested_markets": "true"}
        data = await self.get(f"/events/{event_ticker}", params=params) or {}
        return data.get("event") or data

    async def markets(self, *, status: str | None = None, series_ticker: str | None = None,
                      event_ticker: str | None = None, limit: int = 200, max_pages: int = 5,
                      tickers: Iterable[str] | None = None) -> list[dict]:
        """GET /markets -- one status filter at a time (documented constraint)."""
        params: dict[str, Any] = {"limit": min(limit, 1000)}
        if status:
            params["status"] = status
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        out: list[dict] = []
        cursor = None
        for _ in range(max_pages):
            if cursor:
                params["cursor"] = cursor
            data = await self.get("/markets", params=params) or {}
            out.extend(data.get("markets") or [])
            cursor = data.get("cursor")
            if not cursor or len(out) >= limit:
                break
        wanted = {t.upper() for t in tickers} if tickers else None
        if wanted:
            out = [m for m in out if str(m.get("ticker", "")).upper() in wanted]
        return out[:limit]

    async def market(self, ticker: str) -> dict:
        data = await self.get(f"/markets/{ticker}") or {}
        return data.get("market") or data

    async def orderbook(self, ticker: str, depth: int | None = None) -> dict:
        """GET /markets/{ticker}/orderbook -- bids only, best bid last."""
        params = {"depth": depth} if depth else None
        return await self.get(f"/markets/{ticker}/orderbook", params=params) or {}

    async def orderbooks(self, tickers: list[str], depth: int | None = None) -> dict[str, dict]:
        """GET /markets/orderbooks -- batch, documented maximum 100 tickers per call."""
        results: dict[str, dict] = {}
        for i in range(0, len(tickers), 100):
            chunk = tickers[i : i + 100]
            params: dict[str, Any] = {"tickers": ",".join(chunk)}
            if depth:
                params["depth"] = depth
            try:
                data = await self.get("/markets/orderbooks", params=params) or {}
            except KalshiAPIError:
                # The batch endpoint is newer than the per-market one; fall back
                # rather than showing a blank dashboard.
                for ticker in chunk:
                    try:
                        results[ticker] = await self.orderbook(ticker, depth)
                    except KalshiAPIError:
                        continue
                continue
            for row in data.get("orderbooks") or []:
                ticker = row.get("ticker") or row.get("market_ticker")
                if ticker:
                    results[ticker] = row
        return results

    async def trades(self, *, ticker: str | None = None, limit: int = 200,
                     min_ts: int | None = None, max_ts: int | None = None) -> list[dict]:
        params: dict[str, Any] = {"limit": min(limit, 1000)}
        if ticker:
            params["ticker"] = ticker
        if min_ts:
            params["min_ts"] = min_ts   # seconds, not milliseconds
        if max_ts:
            params["max_ts"] = max_ts
        data = await self.get("/markets/trades", params=params) or {}
        return data.get("trades") or []

    async def candlesticks(self, series_ticker: str, ticker: str, *, start_ts: int, end_ts: int,
                           period_interval: int = 1) -> list[dict]:
        """GET /series/{series}/markets/{ticker}/candlesticks.

        period_interval must be 1, 60 or 1440 minutes, and one request may span
        at most 5,000 periods.
        """
        if period_interval not in (1, 60, 1440):
            raise ValueError("period_interval must be 1, 60 or 1440 minutes")
        if (end_ts - start_ts) / 60 / period_interval > 5000:
            raise ValueError("request would exceed the documented 5,000 period limit")
        data = await self.get(
            f"/series/{series_ticker}/markets/{ticker}/candlesticks",
            params={"start_ts": int(start_ts), "end_ts": int(end_ts), "period_interval": period_interval},
        ) or {}
        return data.get("candlesticks") or []

    # -- portfolio (signed) ----------------------------------------------
    async def balance(self) -> dict:
        return await self.request("GET", "/portfolio/balance", auth=True) or {}

    async def positions(self, *, limit: int = 200, cursor: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self.request("GET", "/portfolio/positions", params=params, auth=True) or {}

    async def fills(self, *, limit: int = 200, cursor: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self.request("GET", "/portfolio/fills", params=params, auth=True) or {}

    async def settlements(self, *, limit: int = 200, cursor: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self.request("GET", "/portfolio/settlements", params=params, auth=True) or {}

    # -- orders (signed, V2 shape) ---------------------------------------
    async def create_order(self, payload: dict) -> dict:
        """POST /portfolio/events/orders

        Documented request fields: ticker, client_order_id, side ("bid"/"ask"),
        count, price, time_in_force, self_trade_prevention_type, plus optional
        post_only / reduce_only / expiration_time / subaccount / exchange_index.
        A 201 means accepted, not resting: read `remaining_count`.
        """
        return await self.request("POST", "/portfolio/events/orders", json=payload, auth=True) or {}

    async def cancel_order(self, order_id: str, *, market_ticker: str | None = None) -> dict:
        payload = {"order_id": order_id}
        if market_ticker:
            payload["market_ticker"] = market_ticker
            payload["exchange_index"] = -1
        return await self.request("DELETE", f"/portfolio/events/orders/{order_id}",
                                  json=payload, auth=True) or {}


def _backoff(attempt: int) -> float:
    return min(8.0, (2 ** (attempt - 1)) * 0.5) + random.random() * 0.25
