"""Thin, dependency-light REST client for the Kalshi Trade API.

Only the standard library is used for transport (urllib) so the collector can run in a
minimal GitHub Actions job. Signing is delegated to :mod:`kalshi_trader.signing` and is
only used when credentials are configured.

Behaviour that matters for correctness:

* Public endpoints are called without auth headers (official: no key required).
* ``429`` responses are retried with exponential backoff; ``5xx`` too. The ``Retry-After``
  header is honoured when present (Kalshi documents that 429s may not carry it).
* Every request passes through a token-bucket style pacer so unauthenticated rate limits are
  respected (https://docs.kalshi.com/getting_started/rate_limits).
* Cursor pagination helper follows the ``cursor`` field documented for list endpoints.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from .config import Settings
from .signing import SigningKey, SigningUnavailable, load_signing_key

log = logging.getLogger(__name__)

USER_AGENT = "Tradebot1-kalshi-dashboard/1.0 (+https://github.com/kanlerxz87-cyber/Tradebot1)"


class KalshiAPIError(RuntimeError):
    """Non-retryable API error (4xx other than 429)."""

    def __init__(self, status: int, body: str, path: str) -> None:
        super().__init__(f"HTTP {status} on {path}: {body[:400]}")
        self.status = status
        self.body = body
        self.path = path


class RestClient:
    def __init__(
        self,
        base_url: str,
        *,
        settings: Settings | None = None,
        signing_key: SigningKey | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.settings = settings or Settings()
        self._signing_key = signing_key
        self._last_request = 0.0
        self.request_count = 0
        self.errors: list[str] = []

    # ------------------------------------------------------------------ auth
    @property
    def signing_key(self) -> SigningKey | None:
        if self._signing_key is None and self.settings.has_credentials():
            try:
                self._signing_key = load_signing_key(
                    self.settings.key_id,
                    self.settings.private_key_pem or None,
                    self.settings.private_key_path or None,
                )
            except SigningUnavailable as exc:
                self.errors.append(str(exc))
                return None
        return self._signing_key

    # -------------------------------------------------------------- pacing
    def _pace(self) -> None:
        gap = self.settings.request_interval_s
        if gap <= 0:
            return
        wait = gap - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    # ------------------------------------------------------------- request
    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        *,
        auth: bool = False,
    ) -> Any:
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"

        body = None
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        if auth:
            key = self.signing_key
            if key is None:
                raise SigningUnavailable("signed request requested but no usable credentials are configured")
            headers.update(key.headers(method, url))

        last_error = ""
        for attempt in range(self.settings.max_retries + 1):
            self._pace()
            req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
            try:
                with urllib.request.urlopen(req, timeout=self.settings.timeout_s) as resp:
                    self.request_count += 1
                    raw = resp.read()
                    if not raw:
                        return {}
                    return json.loads(raw)
            except urllib.error.HTTPError as exc:
                self.request_count += 1
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")
                except Exception:  # pragma: no cover
                    pass
                last_error = f"HTTP {exc.code} {method} {path}: {detail[:300]}"
                if exc.code == 429 or 500 <= exc.code < 600:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 20)
                    log.warning("%s — retrying in %.1fs (attempt %d)", last_error, delay, attempt + 1)
                    time.sleep(delay)
                    continue
                raise KalshiAPIError(exc.code, detail, path) from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = f"{type(exc).__name__} {method} {path}: {exc}"
                delay = min(2 ** attempt, 20)
                log.warning("%s — retrying in %.1fs", last_error, delay)
                time.sleep(delay)

        self.errors.append(last_error)
        raise KalshiAPIError(0, last_error, path)

    # -------------------------------------------------------------- helpers
    def get(self, path: str, params: dict[str, Any] | None = None, *, auth: bool = False) -> Any:
        return self.request("GET", path, params=params, auth=auth)

    def post(self, path: str, body: dict[str, Any], *, auth: bool = True) -> Any:
        return self.request("POST", path, json_body=body, auth=auth)

    def delete(self, path: str, *, auth: bool = True) -> Any:
        return self.request("DELETE", path, auth=auth)

    def paginate(
        self,
        path: str,
        key: str,
        params: dict[str, Any] | None = None,
        *,
        page_size: int = 200,
        max_pages: int = 25,
    ) -> list[dict[str, Any]]:
        """Follow ``cursor`` pagination and return the concatenated ``key`` list."""
        out: list[dict[str, Any]] = []
        cursor = None
        for _ in range(max_pages):
            query = dict(params or {})
            query["limit"] = page_size
            if cursor:
                query["cursor"] = cursor
            payload = self.get(path, query)
            if not isinstance(payload, dict):
                break
            chunk = payload.get(key) or []
            if isinstance(chunk, dict):  # defensive: some endpoints nest objects
                chunk = list(chunk.values())
            out.extend(chunk)
            cursor = payload.get("cursor")
            if not cursor or not chunk:
                break
        return out

    # ------------------------------------------------------- public endpoints
    def exchange_status(self) -> dict[str, Any]:
        return self.get("/exchange/status")

    def series(self, **params: Any) -> list[dict[str, Any]]:
        payload = self.get("/series", params)
        return payload.get("series", []) if isinstance(payload, dict) else []

    def series_one(self, ticker: str) -> dict[str, Any]:
        payload = self.get(f"/series/{urllib.parse.quote(ticker)}")
        return payload.get("series", {}) if isinstance(payload, dict) else {}

    def events(self, **params: Any) -> list[dict[str, Any]]:
        return self.paginate("/events", "events", params)

    def markets(self, **params: Any) -> list[dict[str, Any]]:
        return self.paginate("/markets", "markets", params)

    def market(self, ticker: str) -> dict[str, Any]:
        payload = self.get(f"/markets/{urllib.parse.quote(ticker)}")
        return payload.get("market", {}) if isinstance(payload, dict) else {}

    def orderbook(self, ticker: str, depth: int | None = None) -> dict[str, Any]:
        payload = self.get(
            f"/markets/{urllib.parse.quote(ticker)}/orderbook",
            {"depth": depth} if depth else None,
        )
        return payload.get("orderbook_fp", payload.get("orderbook", {})) if isinstance(payload, dict) else {}

    def candlesticks(
        self,
        series_ticker: str,
        market_ticker: str,
        start_ts: int,
        end_ts: int,
        period_interval: int = 1,
    ) -> list[dict[str, Any]]:
        path = f"/series/{urllib.parse.quote(series_ticker)}/markets/{urllib.parse.quote(market_ticker)}/candlesticks"
        payload = self.get(
            path,
            {"start_ts": int(start_ts), "end_ts": int(end_ts), "period_interval": int(period_interval)},
        )
        return payload.get("candlesticks", []) if isinstance(payload, dict) else []

    # ---------------------------------------------------- private endpoints
    def balance(self) -> dict[str, Any]:
        return self.get("/portfolio/balance", auth=True)

    def positions(self) -> list[dict[str, Any]]:
        payload = self.get("/portfolio/positions", auth=True)
        return payload.get("market_positions", []) if isinstance(payload, dict) else []

    def orders(self, **params: Any) -> list[dict[str, Any]]:
        payload = self.get("/portfolio/orders", params, auth=True)
        return payload.get("orders", []) if isinstance(payload, dict) else []

    def create_order(
        self,
        ticker: str,
        side: str,
        count: str,
        price: str,
        client_order_id: str,
        time_in_force: str = "good_till_canceled",
    ) -> dict[str, Any]:
        """Place an order on the exchange the client points at.

        Body fields verified against
        https://docs.kalshi.com/getting_started/quick_start_create_order
        """
        return self.post(
            "/portfolio/events/orders",
            {
                "ticker": ticker,
                "side": side,
                "count": count,
                "price": price,
                "time_in_force": time_in_force,
                "self_trade_prevention_type": "taker_at_cross",
                "client_order_id": client_order_id,
            },
        )


def public_client(settings: Settings) -> RestClient:
    """Client for unauthenticated market data (the default data path)."""
    return RestClient(settings.rest_base, settings=settings)


def demo_client(settings: Settings) -> RestClient:
    """Signed client pointed at the demo environment."""
    return RestClient(settings.demo_rest_base, settings=settings)


def flatten(trades: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in trades if isinstance(t, dict)]
