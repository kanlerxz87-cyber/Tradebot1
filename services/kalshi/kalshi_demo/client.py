"""Bounded, demo-only REST transport. Writes are NEVER automatically retried."""

import asyncio
from dataclasses import dataclass
import re
import time
from urllib.parse import urlsplit

import httpx

from .auth import Signer
from .config import Settings

TICKER_PATTERN = r"[A-Za-z0-9_.:-]{1,200}"
PUBLIC_PATHS = tuple(re.compile(pattern) for pattern in (
    r"/exchange/status",
    r"/(events|series|markets)",
    rf"/(events|series|markets)/{TICKER_PATTERN}",
    rf"/markets/{TICKER_PATTERN}/orderbook",
    rf"/series/{TICKER_PATTERN}/markets/{TICKER_PATTERN}/candlesticks",
    r"/markets/trades",
))
# No arbitrary upstream URL, auth forwarding, user-specified headers, or private paths.
PUBLIC_QUERY_KEYS = frozenset({
    "limit", "cursor", "status", "with_nested_markets", "series_ticker", "event_ticker",
    "tickers", "category", "tags", "include_product_metadata", "depth", "ticker",
    "min_ts", "max_ts", "start_ts", "end_ts", "period_interval", "min_close_ts",
    "max_close_ts", "min_created_ts", "max_created_ts", "min_updated_ts", "mve_filter",
})


def public_path(path: str) -> bool:
    return any(pattern.fullmatch(path) for pattern in PUBLIC_PATHS)


class UpstreamError(Exception):
    def __init__(self, code: str, status: int = 502, ambiguous: bool = False):
        super().__init__(code)
        self.code = code
        self.status = status
        self.ambiguous = ambiguous


@dataclass
class PageResult:
    rows: list[dict]
    complete: bool
    pages: int
    error: str | None = None


class KalshiClient:
    def __init__(self, settings: Settings, signer: Signer | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.signer = signer
        self.http = httpx.AsyncClient(
            timeout=settings.request_timeout,
            follow_redirects=False,
            transport=transport,
            trust_env=False,
            headers={"User-Agent": "Tradebot1-demo-research/1.0", "Accept": "application/json"},
        )
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def close(self):
        await self.http.aclose()

    async def _rate_limit(self):
        async with self._lock:
            delay = self.settings.read_interval_seconds - (time.monotonic() - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request = time.monotonic()

    async def request(self, method: str, path: str, *, params: dict | None = None,
                      body: dict | None = None, authenticated: bool = False) -> dict:
        method = method.upper()
        if not path.startswith("/") or ".." in path or "//" in path or "?" in path or "%" in path:
            raise ValueError("Invalid upstream path")
        if authenticated and not self.signer:
            raise UpstreamError("demo_credentials_not_configured", 503)
        url = self.settings.rest_url + path
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            await self._rate_limit()
            headers = self.signer.headers(method, urlsplit(url).path) if authenticated else {}
            try:
                response = await self.http.request(method, url, params=params, json=body, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if method == "GET" and attempt < attempts - 1:
                    await asyncio.sleep(0.25 * (2 ** attempt))
                    continue
                raise UpstreamError("upstream_network_unavailable", ambiguous=method != "GET") from exc
            if (response.status_code == 429 or response.status_code >= 500) and attempt < attempts - 1:
                try:
                    retry_after = min(30.0, max(0.25, float(response.headers.get("retry-after", "1"))))
                except ValueError:
                    retry_after = 1.0
                await asyncio.sleep(retry_after * (attempt + 1))
                continue
            if response.status_code >= 300:
                # Don't return raw upstream error bodies, which may contain account identifiers.
                raise UpstreamError(f"upstream_http_{response.status_code}",
                                    status=response.status_code,
                                    ambiguous=method != "GET" and response.status_code >= 500)
            try:
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Expected an object")
            except (ValueError, TypeError) as exc:
                raise UpstreamError("upstream_invalid_json", ambiguous=method != "GET") from exc
            return data
        raise UpstreamError("upstream_retry_exhausted")

    async def get(self, path: str, params: dict | None = None, authenticated: bool = False) -> dict:
        return await self.request("GET", path, params=params, authenticated=authenticated)

    async def pages(self, path: str, key: str, params: dict | None = None,
                    authenticated: bool = False) -> PageResult:
        query = dict(params or {})
        query.setdefault("limit", 200)
        seen_cursors: set[str] = set()
        rows: list[dict] = []
        # Cursor loops / bounded coverage are visible, not claimed as an exhaustive listing.
        for page in range(1, self.settings.max_pages + 1):
            try:
                data = await self.get(path, query, authenticated)
            except UpstreamError as exc:
                return PageResult(rows, False, page - 1, exc.code)
            batch = data.get(key)
            if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
                return PageResult(rows, False, page, "missing_or_invalid_result_array")
            rows.extend(batch)
            cursor = data.get("cursor")
            if cursor is None:
                # Series listings are not cursor paginated; other endpoints must explicitly finish.
                if path == "/series":
                    return PageResult(rows, True, page)
                return PageResult(rows, False, page, "missing_cursor")
            if cursor == "":
                return PageResult(rows, True, page)
            if not isinstance(cursor, str) or cursor in seen_cursors:
                return PageResult(rows, False, page, "repeated_or_invalid_cursor")
            seen_cursors.add(cursor)
            query["cursor"] = cursor
        return PageResult(rows, False, self.settings.max_pages, "page_limit_reached")
