"""Restricted V2 demo buys with durable local idempotency and a hard kill switch."""

from decimal import Decimal
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from .client import TICKER_PATTERN, UpstreamError
from .domain import ONE, decimal
from .runtime import Runtime, now_ms


class OrderIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    outcome: Literal["yes", "no"]
    count: str
    limit_price: str
    client_order_id: str

    @field_validator("ticker")
    @classmethod
    def ticker_is_safe(cls, value):
        if not re.fullmatch(TICKER_PATTERN, value):
            raise ValueError("Invalid ticker")
        return value

    @field_validator("count")
    @classmethod
    def count_is_fixed_point(cls, value):
        parsed = decimal(value)
        if not re.fullmatch(r"\d{1,8}(?:\.\d{1,2})?", value) or parsed is None or parsed <= 0:
            raise ValueError("Count must be a positive fixed-point string with at most two decimals")
        return value

    @field_validator("limit_price")
    @classmethod
    def price_is_fixed_point(cls, value):
        parsed = decimal(value)
        if not re.fullmatch(r"0\.\d{1,4}", value) or parsed is None or not 0 < parsed < 1:
            raise ValueError("Price must be between $0 and $1 with at most four decimal places")
        return value

    @field_validator("client_order_id")
    @classmethod
    def id_is_uuid(cls, value):
        parsed = UUID(value)
        if parsed.version != 4:
            raise ValueError("Use a fresh UUID4 for each order intent")
        return str(parsed)


def on_price_grid(price: Decimal, ranges) -> bool:
    if not isinstance(ranges, list) or not ranges:
        return False
    for band in ranges:
        if not isinstance(band, dict):
            continue
        start, end, step = (decimal(band.get(key)) for key in ("start", "end", "step"))
        if start is None or end is None or step is None or step <= 0:
            continue
        if start <= price <= end and (price - start) % step == 0:
            return True
    return False


async def submit_order(runtime: Runtime, intent: OrderIntent) -> dict:
    settings = runtime.settings
    if runtime.kill_switch or not settings.enable_demo_orders:
        raise UpstreamError("demo_orders_disabled", 403)
    if not runtime.client.signer:
        raise UpstreamError("demo_credentials_not_configured", 503)
    if intent.ticker not in runtime.markets:
        raise UpstreamError("market_not_in_tracked_topics", 422)
    count, outcome_price = Decimal(intent.count), Decimal(intent.limit_price)
    # Reserve maximum payout notional rather than assuming last price is an executable cost.
    # Fees are unknown, so this is explicitly NOT a fee-inclusive account cash cap.
    reserve = count * ONE
    if reserve > settings.max_order_dollars:
        raise UpstreamError("per_order_notional_cap_exceeded", 422)
    yes_price = outcome_price if intent.outcome == "yes" else ONE - outcome_price
    body = {
        "ticker": intent.ticker, "side": "bid" if intent.outcome == "yes" else "ask",
        "count": format(count, ".2f"), "price": format(yes_price, ".4f"),
        "time_in_force": "immediate_or_cancel", "self_trade_prevention_type": "taker_at_cross",
        "cancel_order_on_pause": True, "client_order_id": intent.client_order_id,
        "exchange_index": -1,
    }
    # A repeated intent is NEVER resubmitted, even if the original order already filled,
    # disappeared upstream, or the service restarted. Upstream IDs alone are not durable idempotency.
    for existing in runtime.store.journal():
        if existing["client_order_id"] == intent.client_order_id:
            if existing["request"] != body:
                raise UpstreamError("client_order_id_reused_with_different_request", 409)
            return {"status": existing["state"], "duplicate_suppressed": True, "journal": existing}
    exchange = await runtime.client.get("/exchange/status")
    if exchange.get("trading_active") is not True or exchange.get("exchange_active") is not True:
        raise UpstreamError("exchange_not_confirmed_active", 409)
    payload = await runtime.client.get(f"/markets/{intent.ticker}")
    market = payload.get("market", {})
    if market.get("status") != "active" or market.get("market_type") != "binary":
        raise UpstreamError("market_not_confirmed_active_binary", 409)
    if decimal(market.get("notional_value_dollars")) != ONE or market.get("settlement_bounds_type") not in {None, "", "default"}:
        raise UpstreamError("unsupported_nonstandard_contract", 422)
    if not on_price_grid(yes_price, market.get("price_ranges")):
        raise UpstreamError("price_grid_unverified_or_limit_off_grid", 422)
    # Check the kill switch again immediately before reservation/write, after all awaits.
    if runtime.kill_switch:
        raise UpstreamError("kill_switch_active", 403)
    try:
        previous = runtime.store.reserve_order(intent.client_order_id, body, reserve,
                                               settings.max_session_dollars, now_ms())
    except ValueError as exc:
        raise UpstreamError(str(exc), 409) from exc
    if previous:
        return {"status": previous["state"], "duplicate_suppressed": True, "journal": previous}
    try:
        response = await runtime.client.request("POST", "/portfolio/events/orders", body=body, authenticated=True)
    except UpstreamError as exc:
        state = "ambiguous_reconcile_before_any_new_intent" if exc.ambiguous else "rejected"
        runtime.store.finish_order(intent.client_order_id, state, {"error": exc.code})
        raise
    required = ("order_id", "fill_count", "remaining_count", "ts_ms")
    if any(field not in response for field in required):
        runtime.store.finish_order(intent.client_order_id, "ambiguous_response", {"error": "missing_order_response_fields"})
        raise UpstreamError("missing_order_response_fields", ambiguous=True)
    # Preserve exact exchange acceptance/fill counters; do not turn accepted into 'filled'.
    runtime.store.finish_order(intent.client_order_id, "accepted", response)
    runtime._portfolio_cache = None
    return {"status": "accepted", "response": response, "environment": "demo",
            "source_url": "https://docs.kalshi.com/api-reference/orders/create-order-v2",
            "note": "Accepted is not a fill guarantee. Reconcile fills/positions before computing performance."}
