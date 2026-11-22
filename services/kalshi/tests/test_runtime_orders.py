"""Mocked integration tests; no live Kalshi account or order is involved."""

from dataclasses import replace
from decimal import Decimal as D
import json
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import ed25519
import httpx
import pytest

from services.kalshi.kalshi_demo.auth import Signer
from services.kalshi.kalshi_demo.client import KalshiClient, UpstreamError
from services.kalshi.kalshi_demo.domain import BookError, SequenceGuard
from services.kalshi.kalshi_demo.orders import OrderIntent, on_price_grid, submit_order
from services.kalshi.kalshi_demo.runtime import Runtime, now_ms


def make_runtime(settings, store, handler, signed=False):
    signer = Signer("test-only-not-a-real-key", ed25519.Ed25519PrivateKey.generate()) if signed else None
    return Runtime(settings, KalshiClient(settings, signer, httpx.MockTransport(handler)), store)


def test_grid_cannot_be_guessed():
    assert not on_price_grid(D("0.50"), None)
    assert not on_price_grid(D("0.505"), [{"start": "0.01", "end": "0.99", "step": "0.01"}])
    assert on_price_grid(D("0.50"), [{"start": "0.01", "end": "0.99", "step": "0.01"}])


async def test_discovery_groups_only_supported_topics_and_keeps_closed_market(settings, store, raw_market):
    cycles = [0]
    def handler(request):
        path = request.url.path
        if path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        if path.endswith("/series"):
            return httpx.Response(200, json={"series": [{"ticker": "SYNTHETIC-SERIES", "category": "Crypto", "title": "Synthetic"}]})
        if path.endswith("/events"):
            if cycles[0]:
                return httpx.Response(200, json={"events": [], "cursor": ""})
            return httpx.Response(200, json={"events": [{"event_ticker": raw_market["event_ticker"],
                "series_ticker": "SYNTHETIC-SERIES", "title": "Synthetic event", "markets": [raw_market]}], "cursor": ""})
        return httpx.Response(200, json={"market": {**raw_market, "status": "finalized", "result": "no"}})
    runtime = make_runtime(settings, store, handler)
    await runtime.poll_once()
    assert len(runtime.markets) == 1 and runtime.state["discovery_complete"]
    assert runtime.snapshot()["events"][0]["cumulative_dollar_notional"] is None
    cycles[0] = 1
    await runtime.poll_once()
    assert runtime.markets[raw_market["ticker"]]["result"] == "no"
    assert len(runtime.events) == 1
    await runtime.client.close()


async def test_archive_fallback_keeps_real_source(settings, store, raw_market):
    def handler(request):
        if "/historical/" in request.url.path:
            return httpx.Response(200, json={"market": {**raw_market, "status": "finalized", "result": "yes"}})
        return httpx.Response(404, json={"error": "not_found"})
    runtime = make_runtime(settings, store, handler)
    runtime.ingest_market(raw_market, "crypto")
    await runtime.refresh_market(raw_market["ticker"])
    assert runtime.markets[raw_market["ticker"]]["result"] == "yes"
    assert "/historical/markets/" in runtime.markets[raw_market["ticker"]]["source_url"]
    await runtime.client.close()


async def test_rest_does_not_regress_stream_price(settings, store, raw_market):
    runtime = make_runtime(settings, store, lambda request: httpx.Response(200, json={}))
    runtime.ingest_market(raw_market, "crypto")
    ticker = raw_market["ticker"]
    runtime.state["websocket"] = "connected"
    runtime.markets[ticker].update(last_price_dollars="0.70", price_source="websocket_trade")
    runtime.ingest_market({**raw_market, "last_price_dollars": "0.40"}, "crypto")
    assert runtime.markets[ticker]["last_price_dollars"] == "0.70"
    assert not store.alerts()
    await runtime.client.close()


async def test_unified_yes_price_stream_book_and_gap_recovery(settings, store, raw_market):
    runtime = make_runtime(settings, store, lambda request: httpx.Response(200, json={}))
    runtime.ingest_market(raw_market, "crypto")
    ticker = raw_market["ticker"]
    guard = SequenceGuard()
    runtime.process_frame({"type": "orderbook_snapshot", "sid": 1, "seq": 1,
                           "msg": {"market_ticker": ticker, "yes_dollars_fp": [["0.40", "10"]],
                                   "no_dollars_fp": [["0.45", "20"]]}}, guard)
    # use_yes_price=true: a NO book level 0.45 is an ask for YES at 0.45, not 0.55.
    assert runtime.books[ticker].asks("yes") == [(D("0.45"), D(20))]
    runtime.process_frame({"type": "orderbook_delta", "sid": 1, "seq": 2,
                           "msg": {"market_ticker": ticker, "side": "no", "price_dollars": "0.45", "delta_fp": "-3"}}, guard)
    assert runtime.books[ticker].asks("yes") == [(D("0.45"), D(17))]
    with pytest.raises(BookError):
        runtime.process_frame({"type": "orderbook_delta", "sid": 1, "seq": 4,
                               "msg": {"market_ticker": ticker, "side": "no", "price_dollars": "0.45", "delta_fp": "1"}}, guard)
    assert not runtime.books[ticker].valid
    await runtime.client.close()


async def test_trade_feed_keeps_same_millisecond_moves_and_no_account_leak(settings, store, raw_market):
    runtime = make_runtime(settings, store, lambda request: httpx.Response(200, json={}))
    runtime.ingest_market(raw_market, "crypto")
    runtime.detector.reset()
    runtime.state["websocket"] = "connected"
    ticker = raw_market["ticker"]
    stamp = now_ms()
    guard = SequenceGuard()
    for index, price in enumerate(["0.40", "0.50", "0.40"], start=1):
        runtime.process_frame({"type": "trade", "sid": 2, "seq": index, "msg": {
            "market_ticker": ticker, "trade_id": f"synthetic-{index}", "ts_ms": stamp,
            "yes_price_dollars": price, "client_order_id": "PRIVATE-SHOULD-NOT-LEAK",
        }}, guard)
    assert len(store.alerts()) == 2
    assert "PRIVATE-SHOULD-NOT-LEAK" not in json.dumps(runtime.snapshot())
    await runtime.client.close()


async def test_trade_notifications_are_not_lost_to_newer_ticker_flush(settings, store, raw_market):
    runtime = make_runtime(settings, store, lambda request: httpx.Response(200, json={}))
    runtime.ingest_market(raw_market, "crypto")
    runtime.detector.reset()
    runtime.state["websocket"] = "connected"
    ticker, stamp = raw_market["ticker"], now_ms()
    guard = SequenceGuard()
    runtime.process_frame({"type": "ticker", "sid": 1, "msg": {
        "market_ticker": ticker, "ts_ms": stamp, "price_dollars": "0.6"}}, guard)
    for index, price in enumerate(["0.4", "0.5"], start=1):
        runtime.process_frame({"type": "trade", "sid": 2, "seq": index, "msg": {
            "market_ticker": ticker, "trade_id": f"late-{index}", "ts_ms": stamp - 10 + index,
            "yes_price_dollars": price}}, guard)
    assert len(store.alerts()) == 1
    assert runtime.markets[ticker]["last_price_dollars"] == "0.6"  # don't regress displayed latest
    await runtime.client.close()


def intent(ticker, outcome="yes"):
    return OrderIntent(ticker=ticker, outcome=outcome, count="1.00", limit_price="0.40", client_order_id=str(uuid4()))


def enabled(settings):
    return replace(settings, api_key_id="test-not-real", private_key_path="test.key",
                   operator_token="test-operator-token-" + "x" * 32, enable_demo_orders=True)


@pytest.mark.parametrize("outcome,side,price", [("yes", "bid", "0.4000"), ("no", "ask", "0.6000")])
async def test_v2_order_shape_no_retries_and_local_duplicate_guard(settings, store, raw_market, outcome, side, price):
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        if "/markets/" in request.url.path:
            return httpx.Response(200, json={"market": raw_market})
        body = json.loads(request.content)
        assert request.url.path == "/trade-api/v2/portfolio/events/orders"
        assert body["side"] == side and body["price"] == price
        assert body["time_in_force"] == "immediate_or_cancel" and body["exchange_index"] == -1
        return httpx.Response(201, json={"order_id": "synthetic-order", "fill_count": "0.00", "remaining_count": "0.00", "ts_ms": 1000})
    runtime = make_runtime(enabled(settings), store, handler, signed=True)
    runtime.ingest_market(raw_market, "crypto")
    order = intent(raw_market["ticker"], outcome)
    result = await submit_order(runtime, order)
    assert result["status"] == "accepted" and result["response"]["fill_count"] == "0.00"
    assert (await submit_order(runtime, order))["duplicate_suppressed"]
    assert sum(request.method == "POST" for request in calls) == 1
    assert len(calls) == 3
    await runtime.client.close()


async def test_disabled_kill_cap_and_unknown_grid_never_submit(settings, store, raw_market):
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        return httpx.Response(200, json={"market": {**raw_market, "price_ranges": None}})
    runtime = make_runtime(settings, store, handler)
    runtime.ingest_market(raw_market, "crypto")
    order = intent(raw_market["ticker"])
    with pytest.raises(UpstreamError, match="disabled"):
        await submit_order(runtime, order)
    assert not calls
    runtime.settings = enabled(settings)
    runtime.client.signer = Signer("test-only", ed25519.Ed25519PrivateKey.generate())
    runtime.kill_switch = True
    with pytest.raises(UpstreamError, match="disabled"):
        await submit_order(runtime, order)
    runtime.kill_switch = False
    with pytest.raises(UpstreamError, match="cap_exceeded"):
        await submit_order(runtime, order.model_copy(update={"count": "100"}))
    with pytest.raises(UpstreamError, match="price_grid"):
        await submit_order(runtime, order)
    assert all(request.method != "POST" for request in calls)
    await runtime.client.close()


async def test_ambiguous_write_stays_reserved_and_not_resubmitted(settings, store, raw_market):
    count = [0]
    def handler(request):
        if request.method == "POST":
            count[0] += 1
            raise httpx.ReadTimeout("synthetic", request=request)
        if request.url.path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        return httpx.Response(200, json={"market": raw_market})
    runtime = make_runtime(enabled(settings), store, handler, signed=True)
    runtime.ingest_market(raw_market, "crypto")
    order = intent(raw_market["ticker"])
    with pytest.raises(UpstreamError) as error:
        await submit_order(runtime, order)
    assert error.value.ambiguous
    duplicate = await submit_order(runtime, order)
    assert "ambiguous" in duplicate["status"] and count[0] == 1
    await runtime.client.close()


async def test_private_portfolio_is_cached_sourced_and_not_public(settings, store):
    calls = []
    def handler(request):
        calls.append(request)
        path = request.url.path
        if path.endswith("/balance"):
            return httpx.Response(200, json={"balance": 12345, "portfolio_value": 2345, "updated_ts": 1000})
        key = "market_positions" if path.endswith("/positions") else path.split("/")[-1]
        return httpx.Response(200, json={key: [{"ticker": "SYNTHETIC-PRIVATE-POSITION"}], "cursor": ""})
    runtime = make_runtime(settings, store, handler, signed=True)
    portfolio = await runtime.portfolio()
    assert portfolio["balance"]["balance"] == 12345  # exact units, not silently converted to dollars
    assert portfolio["positions"][0]["source_url"].endswith("/portfolio/positions")
    assert portfolio["account_scope"].startswith("primary")
    assert len(calls) == 8
    assert await runtime.portfolio() == portfolio
    assert len(calls) == 8
    assert "SYNTHETIC-PRIVATE-POSITION" not in json.dumps(runtime.snapshot())
    await runtime.client.close()
