"""
Minimal client for Kalshi Trade API v2 public (unauthenticated) market-data
endpoints, used against the demo environment.

Endpoint shapes are per docs/API_VERIFICATION.md section B, sourced from
https://docs.kalshi.com/getting_started/quick_start_market_data and
https://docs.kalshi.com/getting_started/demo_env (both fetched 2026-11-22).

This client deliberately implements ONLY public GET endpoints (series,
events, markets, orderbook). It never signs a request and never calls
/portfolio/* or any order-placement endpoint, by design (see
docs/FLAGGED_FOR_REVIEW.md item 3) — there is no code path in this repo that
can place a real order.
"""
import time
import urllib.error
import urllib.parse
import urllib.request
import json

from . import config


class KalshiAPIError(Exception):
    pass


class KalshiClient:
    def __init__(self, base_url=None, timeout=None):
        self.base_url = base_url or config.REST_BASE_PRIMARY
        self.fallback_url = config.REST_BASE_FALLBACK
        self.timeout = timeout or config.HTTP_TIMEOUT_SECONDS
        self._last_request_ts = 0.0

    def _throttle(self):
        elapsed = time.monotonic() - self._last_request_ts
        wait = config.HTTP_MIN_INTERVAL_SECONDS - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.monotonic()

    def _get(self, path, params=None, base_override=None):
        base = base_override or self.base_url
        url = base + path
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            if query:
                url = f"{url}?{query}"

        last_err = None
        for attempt in range(1, config.MAX_RETRIES + 1):
            self._throttle()
            try:
                req = urllib.request.Request(
                    url,
                    headers={"Accept": "application/json", "User-Agent": "Tradebot1-Dashboard/1.0"},
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                    return json.loads(body.decode("utf-8")), url
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    last_err = e
                    time.sleep(2 ** attempt)
                    continue
                last_err = e
                break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = e
                time.sleep(1.5 ** attempt)
                continue

        # Try the documented fallback host once if the primary failed entirely
        # and we weren't already using it.
        if base == self.base_url and self.fallback_url and base != self.fallback_url:
            try:
                return self._get(path, params=params, base_override=self.fallback_url)
            except KalshiAPIError:
                pass

        raise KalshiAPIError(f"GET {url} failed after retries: {last_err}")

    def list_series(self, limit=200, cursor=None):
        data, url = self._get("/series", {"limit": limit, "cursor": cursor})
        return data, url

    def list_events(self, status=None, limit=200, cursor=None, with_nested_markets=True):
        params = {
            "status": status,
            "limit": limit,
            "cursor": cursor,
            "with_nested_markets": "true" if with_nested_markets else None,
        }
        data, url = self._get("/events", params)
        return data, url

    def list_markets(self, series_ticker=None, event_ticker=None, status="open", limit=200, cursor=None):
        params = {
            "series_ticker": series_ticker,
            "event_ticker": event_ticker,
            "status": status,
            "limit": limit,
            "cursor": cursor,
        }
        data, url = self._get("/markets", params)
        return data, url

    def get_market(self, ticker):
        data, url = self._get(f"/markets/{ticker}")
        return data, url

    def get_orderbook(self, ticker, depth=10):
        data, url = self._get(f"/markets/{ticker}/orderbook", {"depth": depth})
        return data, url

    def iter_all_markets(self, status="open", max_pages=50):
        """Yield every market across all pages for a given status."""
        cursor = None
        for _ in range(max_pages):
            data, _url = self.list_markets(status=status, cursor=cursor, limit=200)
            for m in data.get("markets", []):
                yield m
            cursor = data.get("cursor")
            if not cursor:
                break
