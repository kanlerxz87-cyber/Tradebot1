"""V2-compliant Kalshi Demo REST & WebSocket client.

Verified against official Kalshi documentation (2026-11-22):
- Environments: https://docs.kalshi.com/getting_started/api_environments.md
  * REST primary:   https://external-api.demo.kalshi.co/trade-api/v2
  * REST alternate: https://demo-api.kalshi.co/trade-api/v2
  * WS primary:     wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2
  * WS alternate:   wss://demo-api.kalshi.co/trade-api/ws/v2
- Signing: https://docs.kalshi.com/getting_started/api_keys.md
  * Sign `timestamp_ms + METHOD + full_url_path_without_query`
    (e.g. `1795329000000GET/trade-api/v2/portfolio/balance` or `.../trade-api/ws/v2`)
  * Ed25519 (RFC 8032) or RSA-2048 PSS/SHA-256 (salt_length = digest_length)
- V2 Event Orders: https://docs.kalshi.com/getting_started/quick_start_create_order.md
  * `POST /trade-api/v2/portfolio/events/orders` (legacy `/portfolio/orders` returns 410 Gone)
- Orderbook reciprocal math: https://docs.kalshi.com/getting_started/orderbook_responses.md
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal
from typing import Any

DEMO_REST_PRIMARY = "https://external-api.demo.kalshi.co/trade-api/v2"
DEMO_REST_ALT = "https://demo-api.kalshi.co/trade-api/v2"
DEMO_WS_PRIMARY = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
DEMO_WS_ALT = "wss://demo-api.kalshi.co/trade-api/ws/v2"
DEMO_USER_WS_PRIMARY = "wss://user-ws.demo.kalshi.co/trade-api/ws/v2"
DEMO_EXTERNAL_FEEDS_WS = "wss://external-feeds.demo.kalshi.co/trade-api/v2/external-feeds"


def canonical_sign_path(base_url: str, endpoint_path: str) -> str:
    """Return the exact URL path from host root without query parameters.

    Example:
        canonical_sign_path(DEMO_REST_PRIMARY, '/portfolio/balance?subaccount=0')
        -> '/trade-api/v2/portfolio/balance'
    """
    joined = base_url.rstrip("/") + "/" + endpoint_path.lstrip("/")
    return urllib.parse.urlsplit(joined).path


def build_presign_message(timestamp_ms: str, method: str, sign_path: str) -> str:
    """Concatenate timestamp (ms), uppercase HTTP method, and query-stripped root path."""
    clean_path = sign_path.split("?", 1)[0]
    if not clean_path.startswith("/"):
        clean_path = "/" + clean_path
    return f"{timestamp_ms}{method.upper()}{clean_path}"


def load_private_key_pem(pem_bytes: bytes, password: bytes | None = None):
    """Load PEM private key via `cryptography` if installed, else retain raw PEM bytes for OpenSSL fallback."""
    try:
        from cryptography.hazmat.primitives import serialization

        return serialization.load_pem_private_key(pem_bytes, password=password)
    except ImportError:
        return pem_bytes


def _sign_with_openssl(pem_bytes: bytes, payload: bytes) -> bytes:
    """Zero-dependency OpenSSL 3.x fallback supporting both Ed25519 and RSA-PSS/SHA-256."""
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as kf, tempfile.NamedTemporaryFile(mode="wb", delete=False) as mf:
        kf.write(pem_bytes)
        key_path = kf.name
        mf.write(payload)
        msg_path = mf.name
    try:
        info = subprocess.run(
            ["openssl", "pkey", "-in", key_path, "-noout", "-text"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        if "ED25519" in info.upper():
            cmd = ["openssl", "pkeyutl", "-sign", "-inkey", key_path, "-rawin", "-in", msg_path]
        else:
            cmd = [
                "openssl", "dgst", "-sha256",
                "-sigopt", "rsa_padding_mode:pss",
                "-sigopt", "rsa_pss_saltlen:digest",
                "-sigopt", "rsa_mgf1_md:sha256",
                "-sign", key_path,
                msg_path,
            ]
        return subprocess.run(cmd, capture_output=True, check=True).stdout
    finally:
        for p in (key_path, msg_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def sign_kalshi_message(private_key: Any, message: str) -> str:
    """Sign pre-sign string with Ed25519 or RSA-PSS/SHA-256 per Kalshi API Keys spec."""
    payload = message.encode("utf-8")
    if callable(private_key):
        raw_sig = private_key(payload)
        return base64.b64encode(raw_sig).decode("ascii")
    if isinstance(private_key, (bytes, bytearray)):
        raw_sig = _sign_with_openssl(bytes(private_key), payload)
        return base64.b64encode(raw_sig).decode("ascii")

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if isinstance(private_key, Ed25519PrivateKey):
        raw_sig = private_key.sign(payload)
    else:
        raw_sig = private_key.sign(
            payload,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
    return base64.b64encode(raw_sig).decode("ascii")


def summarize_orderbook(orderbook_resp: dict[str, Any]) -> dict[str, Any]:
    """Compute best bids, implied executable asks, spread, and sorted ladders.

    Per https://docs.kalshi.com/getting_started/orderbook_responses.md:
    - `yes_dollars` and `no_dollars` are sorted ascending; LAST item is best bid.
    - Implied YES Ask = $1.00 - NO Bid (quantity = NO Bid contracts).
    - Implied NO Ask  = $1.00 - YES Bid (quantity = YES Bid contracts).
    """
    fp = (orderbook_resp or {}).get("orderbook_fp") or {}
    yes_raw = fp.get("yes_dollars") or []
    no_raw = fp.get("no_dollars") or []

    yes_bids_desc = [
        {"price": float(Decimal(p)), "price_str": p, "contracts": float(Decimal(q)), "contracts_str": q}
        for p, q in reversed(yes_raw)
    ]
    no_bids_desc = [
        {"price": float(Decimal(p)), "price_str": p, "contracts": float(Decimal(q)), "contracts_str": q}
        for p, q in reversed(no_raw)
    ]
    yes_asks_asc = [
        {
            "price": float(Decimal("1.0000") - Decimal(p)),
            "price_str": f"{Decimal('1.0000') - Decimal(p):.4f}",
            "contracts": float(Decimal(q)),
            "contracts_str": q,
            "implied_from_no_bid": p,
        }
        for p, q in reversed(no_raw)
    ]
    no_asks_asc = [
        {
            "price": float(Decimal("1.0000") - Decimal(p)),
            "price_str": f"{Decimal('1.0000') - Decimal(p):.4f}",
            "contracts": float(Decimal(q)),
            "contracts_str": q,
            "implied_from_yes_bid": p,
        }
        for p, q in reversed(yes_raw)
    ]

    best_yes_bid = yes_bids_desc[0]["price"] if yes_bids_desc else None
    best_yes_ask = yes_asks_asc[0]["price"] if yes_asks_asc else None
    spread = round(best_yes_ask - best_yes_bid, 4) if (best_yes_bid is not None and best_yes_ask is not None) else None

    return {
        "best_yes_bid": best_yes_bid,
        "best_yes_ask": best_yes_ask,
        "yes_spread": spread,
        "yes_bids": yes_bids_desc,
        "no_bids": no_bids_desc,
        "implied_yes_asks": yes_asks_asc,
        "implied_no_asks": no_asks_asc,
        "total_yes_bid_contracts": round(sum(x["contracts"] for x in yes_bids_desc), 2),
        "total_no_bid_contracts": round(sum(x["contracts"] for x in no_bids_desc), 2),
    }


def estimate_orderbook_vwap(
    raw_orderbook: dict[str, Any],
    outcome: str = "yes",
    count: float | int = 10,
) -> dict[str, Any]:
    """Walk implied executable asks ascending to estimate VWAP fill price, depth, and slippage."""
    summary = summarize_orderbook(raw_orderbook)
    side = outcome.strip().lower()
    if side not in ("yes", "no"):
        raise ValueError(f"outcome must be 'yes' or 'no', got {outcome!r}")
    asks = summary["implied_yes_asks"] if side == "yes" else summary["implied_no_asks"]
    requested = max(0.0, float(count))
    remaining = requested
    filled = 0.0
    notional = 0.0
    worst_price: float | None = None
    levels_walked = 0
    total_resting = round(sum(float(lv["contracts"]) for lv in asks), 2)

    for lv in asks:
        if remaining <= 1e-9:
            break
        sz = float(lv["contracts"])
        px = float(lv["price"])
        if sz <= 0:
            continue
        take = min(remaining, sz)
        filled += take
        notional += take * px
        remaining -= take
        worst_price = px
        levels_walked += 1

    vwap = round(notional / filled, 4) if filled > 0 else None
    best_ask = asks[0]["price"] if asks else None
    slippage = round(vwap - best_ask, 4) if (vwap is not None and best_ask is not None) else None
    return {
        "outcome": side,
        "requested_contracts": round(requested, 2),
        "filled_contracts": round(filled, 2),
        "unfilled_contracts": round(max(0.0, remaining), 2),
        "best_ask": best_ask,
        "vwap_price": vwap,
        "worst_price": worst_price,
        "slippage_dollars": slippage,
        "levels_walked": levels_walked,
        "total_executable_depth": total_resting,
    }


def build_v2_event_order_payload(
    ticker: str,
    outcome: str,
    action: str,
    count: int | float | str,
    price_dollars: float | str | Decimal,
    time_in_force: str = "good_till_canceled",
    client_order_id: str | None = None,
) -> dict[str, Any]:
    """Construct an official V2 `/portfolio/events/orders` request payload.

    V2 Event Orders use single-book `side` ('bid' or 'ask') on YES price grid:
    - Buy YES at P      -> side='bid', price=P
    - Sell YES at P     -> side='ask', price=P
    - Buy NO at P_no    -> equivalent to Sell YES at ($1.00 - P_no) -> side='ask', price=1-P_no
    - Sell NO at P_no   -> equivalent to Buy YES at ($1.00 - P_no)  -> side='bid', price=1-P_no
    """
    out_norm = outcome.strip().lower()
    act_norm = action.strip().lower()
    if out_norm not in ("yes", "no"):
        raise ValueError("outcome must be 'yes' or 'no'")
    if act_norm not in ("buy", "sell"):
        raise ValueError("action must be 'buy' or 'sell'")

    dec_price = Decimal(str(price_dollars))
    if dec_price <= Decimal("0") or dec_price >= Decimal("1"):
        raise ValueError("price_dollars must be strictly between 0.0000 and 1.0000")

    if out_norm == "yes":
        book_side = "bid" if act_norm == "buy" else "ask"
        yes_grid_price = dec_price
    else:
        book_side = "ask" if act_norm == "buy" else "bid"
        yes_grid_price = Decimal("1.0000") - dec_price

    return {
        "ticker": ticker,
        "side": book_side,
        "count": str(count),
        "price": f"{yes_grid_price:.4f}",
        "time_in_force": time_in_force,
        "self_trade_prevention_type": "taker_at_cross",
        "client_order_id": client_order_id or str(uuid.uuid4()),
    }


class KalshiV2Client:
    """Public + authenticated V2 client for Kalshi's Demo environment."""

    def __init__(
        self,
        key_id: str | None = None,
        private_key: Any | None = None,
        base_url: str = DEMO_REST_PRIMARY,
        ws_url: str = DEMO_WS_PRIMARY,
        timeout: int = 20,
    ) -> None:
        self.key_id = key_id
        self.private_key = private_key
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url
        self.timeout = timeout

    @classmethod
    def from_env(cls, base_url: str = DEMO_REST_PRIMARY) -> "KalshiV2Client":
        key_id = os.environ.get("KALSHI_DEMO_KEY_ID") or os.environ.get("KALSHI_KEY_ID")
        key_path = os.environ.get("KALSHI_DEMO_KEY_PATH") or os.environ.get("KALSHI_KEY_PATH")
        priv = None
        if key_path and os.path.exists(key_path):
            with open(key_path, "rb") as f:
                priv = load_private_key_pem(f.read())
        return cls(key_id=key_id, private_key=priv, base_url=base_url)

    def auth_headers(self, method: str, endpoint_path: str, timestamp_ms: str | None = None) -> dict[str, str]:
        if not self.key_id or self.private_key is None:
            raise RuntimeError(
                "Authenticated Kalshi Demo endpoint requires KALSHI_DEMO_KEY_ID and KALSHI_DEMO_KEY_PATH."
            )
        ts = timestamp_ms or str(int(time.time() * 1000))
        sign_path = canonical_sign_path(self.base_url, endpoint_path)
        presign = build_presign_message(ts, method, sign_path)
        sig = sign_kalshi_message(self.private_key, presign)
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
        }

    def ws_auth_headers(self, timestamp_ms: str | None = None) -> dict[str, str]:
        if not self.key_id or self.private_key is None:
            raise RuntimeError("WebSocket handshake requires demo API key credentials.")
        ts = timestamp_ms or str(int(time.time() * 1000))
        ws_path = urllib.parse.urlsplit(self.ws_url).path or "/trade-api/ws/v2"
        sig = sign_kalshi_message(self.private_key, build_presign_message(ts, "GET", ws_path))
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
        }

    @staticmethod
    def build_ws_subscribe(cmd_id: int, channels: list[str], market_tickers: list[str] | None = None) -> str:
        params: dict[str, Any] = {"channels": channels}
        if market_tickers:
            params["market_tickers"] = market_tickers
        return json.dumps({"id": cmd_id, "cmd": "subscribe", "params": params})

    def request(
        self,
        method: str,
        endpoint_path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        authenticated: bool = False,
    ) -> dict[str, Any]:
        candidate_bases = [self.base_url]
        if self.base_url == DEMO_REST_PRIMARY:
            candidate_bases.append(DEMO_REST_ALT)
        elif self.base_url == DEMO_REST_ALT:
            candidate_bases.append(DEMO_REST_PRIMARY)

        last_err: Exception | None = None
        for base in candidate_bases:
            url = base.rstrip("/") + "/" + endpoint_path.lstrip("/")
            if params:
                clean_params = {k: v for k, v in params.items() if v is not None and v != ""}
                if clean_params:
                    url += "?" + urllib.parse.urlencode(clean_params)
            headers = {"Accept": "application/json", "User-Agent": "Tradebot1-KalshiV2/1.1"}
            if authenticated:
                headers.update(self.auth_headers(method, endpoint_path))
            data_bytes = None
            if body is not None:
                headers["Content-Type"] = "application/json"
                data_bytes = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method.upper())
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError:
                raise
            except Exception as exc:
                last_err = exc
        assert last_err is not None
        raise last_err

    # Public endpoints
    def get_exchange_status(self) -> dict[str, Any]:
        return self.request("GET", "/exchange/status")

    def get_series(self, series_ticker: str) -> dict[str, Any]:
        return self.request("GET", f"/series/{urllib.parse.quote(series_ticker, safe='')}")

    def get_series_list(self, category: str | None = None, tags: str | None = None) -> dict[str, Any]:
        return self.request("GET", "/series", params={"category": category, "tags": tags})

    def get_events(
        self,
        status: str = "open",
        with_nested_markets: bool = True,
        series_ticker: str | None = None,
        tickers: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            "/events",
            params={
                "status": status,
                "with_nested_markets": "true" if with_nested_markets else "false",
                "series_ticker": series_ticker,
                "tickers": tickers,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def get_markets(
        self,
        status: str | None = "open",
        tickers: str | None = None,
        mve_filter: str = "exclude",
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            "/markets",
            params={"status": status, "tickers": tickers, "mve_filter": mve_filter, "limit": limit, "cursor": cursor},
        )

    def get_orderbook(self, ticker: str, depth: int = 10) -> dict[str, Any]:
        return self.request("GET", f"/markets/{urllib.parse.quote(ticker, safe='')}/orderbook", params={"depth": depth})

    def get_trades(self, ticker: str | None = None, limit: int = 50) -> dict[str, Any]:
        return self.request("GET", "/markets/trades", params={"ticker": ticker, "limit": limit})

    def get_candlesticks(
        self,
        series_ticker: str,
        market_ticker: str,
        start_ts: int,
        end_ts: int,
        period_interval: int = 1,
    ) -> dict[str, Any]:
        s = urllib.parse.quote(series_ticker, safe="")
        m = urllib.parse.quote(market_ticker, safe="")
        return self.request(
            "GET",
            f"/series/{s}/markets/{m}/candlesticks",
            params={"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval},
        )

    # Authenticated portfolio & V2 event-order endpoints
    def get_balance(self, subaccount: int | None = None) -> dict[str, Any]:
        return self.request("GET", "/portfolio/balance", params={"subaccount": subaccount}, authenticated=True)

    def get_positions(self) -> dict[str, Any]:
        return self.request("GET", "/portfolio/positions", authenticated=True)

    def get_fills(self, ticker: str | None = None, limit: int = 100) -> dict[str, Any]:
        return self.request("GET", "/portfolio/fills", params={"ticker": ticker, "limit": limit}, authenticated=True)

    def get_settlements(self, limit: int = 100) -> dict[str, Any]:
        return self.request("GET", "/portfolio/settlements", params={"limit": limit}, authenticated=True)

    def create_event_order(
        self,
        ticker: str,
        outcome: str,
        action: str,
        count: int | float | str,
        price_dollars: float | str | Decimal,
        time_in_force: str = "good_till_canceled",
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        payload = build_v2_event_order_payload(
            ticker=ticker,
            outcome=outcome,
            action=action,
            count=count,
            price_dollars=price_dollars,
            time_in_force=time_in_force,
            client_order_id=client_order_id,
        )
        return self.request("POST", "/portfolio/events/orders", body=payload, authenticated=True)

    def cancel_event_order(self, order_id: str, market_ticker: str) -> dict[str, Any]:
        return self.request(
            "DELETE",
            f"/portfolio/events/orders/{urllib.parse.quote(order_id, safe='')}",
            params={"market_ticker": market_ticker},
            authenticated=True,
        )
