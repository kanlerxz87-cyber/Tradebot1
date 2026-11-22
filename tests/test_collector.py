"""End-to-end pipeline test with captured real payloads and a fake transport.

The point of these tests is that the *whole* chain runs: events -> topic mapping
-> market rows -> orderbook -> swing detection -> alert -> strategy -> ledger,
plus the two things that must never be invented: an unknown price and an
unresolved market.
"""

import asyncio
import json
from decimal import Decimal

import httpx
import pytest

from app.collector import Collector
from app.config import Settings
from app.kalshi_api import KalshiAPI
from app.storage import Store

from . import fixtures


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    params = request.url.params
    if path.endswith("/exchange/status"):
        return httpx.Response(200, json=fixtures.EXCHANGE_STATUS)
    if path.endswith("/search/tags_by_categories"):
        return httpx.Response(200, json=fixtures.TAGS_BY_CATEGORIES)
    if path.endswith("/events"):
        series = params.get("series_ticker")
        category = params.get("category")
        if series == "KXPGATOUR" or category == "Sports":
            return httpx.Response(200, json=fixtures.GOLF_EVENTS)
        if category == "Crypto":
            return httpx.Response(200, json=fixtures.CRYPTO_EVENTS)
        if category == "Elections":
            return httpx.Response(200, json=fixtures.ELECTIONS_EVENTS)
        # The engine requests open events globally; return everything it needs.
        return httpx.Response(200, json={"cursor": "", "events": (
            fixtures.GOLF_EVENTS["events"] + fixtures.CRYPTO_EVENTS["events"]
            + fixtures.ELECTIONS_EVENTS["events"])})
    if "/series/" in path and path.endswith("/candlesticks"):
        return httpx.Response(200, json={"ticker": "x", "candlesticks": []})
    if "/series/" in path:
        ticker = path.rsplit("/", 1)[-1]
        row = fixtures.SERIES.get(ticker)
        if row is None:
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        return httpx.Response(200, json={"series": row})
    if path.endswith("/orderbook"):
        return httpx.Response(200, json=fixtures.ORDERBOOK_CBEZ)
    if path.endswith("/markets/orderbooks"):
        tickers = (params.get("tickers") or "").split(",")
        return httpx.Response(200, json={"orderbooks": [
            {"ticker": t, **fixtures.ORDERBOOK_CBEZ} for t in tickers if t]})
    if path.endswith("/markets/trades"):
        return httpx.Response(200, json={"trades": [], "cursor": ""})
    if "/markets/" in path:
        ticker = path.rsplit("/", 1)[-1]
        for ev in fixtures.GOLF_EVENTS["events"]:
            for m in ev["markets"]:
                if m["ticker"] == ticker:
                    return httpx.Response(200, json={"market": m})
        return httpx.Response(200, json={"market": {"ticker": ticker, "status": "active", "result": ""}})
    return httpx.Response(200, json={})


@pytest.fixture()
def collector(tmp_path):
    store = Store(tmp_path / "s.sqlite3")
    settings = Settings(environment="demo", db_path=str(tmp_path / "s.sqlite3"),
                        max_tracked_markets=60, swing_window_seconds=60, alert_cooldown_seconds=0)
    api = KalshiAPI(settings, transport=httpx.MockTransport(_handler))
    asyncio.run(api.__aenter__())
    coll = Collector(settings, store, api=api)
    yield coll, store
    asyncio.run(api.__aexit__(None, None, None))
    store.close()


def test_universe_maps_real_golf_markets_using_series_tags(collector):
    coll, _ = collector
    result = asyncio.run(coll.refresh_universe())
    assert result["tracked"] >= 3
    topics = {m["topic"] for m in coll.tracked.values()}
    assert {"golf", "crypto", "elections"} <= topics
    golf = [m for m in coll.tracked.values() if m["topic"] == "golf"]
    assert golf, "KXPGATOUR must map to golf even though events carry no tags"
    assert all(m["page_url"].startswith("https://kalshi.com/") for m in golf)


def test_market_row_preserves_kalshi_strings_and_flags_one_sided_books(collector):
    coll, store = collector
    asyncio.run(coll.refresh_universe())
    row = coll.tracked["KXPGATOUR-THRC26-CBEZ"]
    assert row["volume_fp"] == "180379.74"
    assert row["yes_bid"] == "0.0020"
    assert row["two_sided"] is True
    # ZBAU publishes yes_ask 1.0000 with no bid: one-sided, must be flagged.
    zbau = coll.tracked["KXPGATOUR-THRC26-ZBAU"]
    assert zbau["two_sided"] is False
    saved = store.get_market("KXPGATOUR-THRC26-CBEZ")
    assert saved["topic"] == "golf"


def test_poll_produces_no_alert_below_the_threshold(collector):
    coll, store = collector
    asyncio.run(coll.refresh_universe())
    asyncio.run(coll.poll_once())
    assert store.list_alerts(limit=10) == []


def test_poll_alerts_on_a_ten_cent_swing_and_records_ticks(collector):
    coll, store = collector
    asyncio.run(coll.refresh_universe())
    # First poll establishes the reference price from the live book.
    asyncio.run(coll.poll_once())
    # Reference mid was 0.0025 (bid 0.0020 / implied ask 0.0030). The book now
    # quotes YES bid 0.1020 against a NO bid of 0.8900 (implied YES ask 0.1100),
    # so the mid is 0.1060: a 10.35c move. Note the book must stay uncrossed
    # (bid < implied ask) or the guard falls back to the last trade.
    fixtures_moved = {"orderbook_fp": {"yes_dollars": [["0.1000", "500.00"], ["0.1020", "833.00"]],
                                       "no_dollars": [["0.8870", "400.00"], ["0.8900", "2500.00"]]}}

    async def moved(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/markets/orderbooks"):
            # Move only the golf market, so the assertion below is specific.
            tickers = (request.url.params.get("tickers") or "").split(",")
            return httpx.Response(200, json={"orderbooks": [
                {"ticker": t, **(fixtures_moved if t == "KXPGATOUR-THRC26-CBEZ"
                                 else fixtures.ORDERBOOK_CBEZ)} for t in tickers if t]})
        return _handler(request)

    coll.api._client = httpx.AsyncClient(base_url=coll.settings.rest_base,
                                        transport=httpx.MockTransport(moved))
    asyncio.run(coll.poll_once())

    alerts = store.list_alerts(limit=10)
    assert alerts, "a 10c move must raise an alert"
    alert = alerts[0]
    assert abs(Decimal(alert["delta"])) >= Decimal("0.10")
    assert alert["direction"] == "up"
    assert alert["from_price"] == "0.0025"
    assert alert["topic"] == "golf"
    assert alert["page_url"]
    assert store.ticks("KXPGATOUR-THRC26-CBEZ")


def test_resolution_is_only_recorded_when_kalshi_publishes_a_result(collector):
    coll, store = collector
    asyncio.run(coll.refresh_universe())
    asyncio.run(coll.poll_once())
    # Nothing resolved yet in the fixtures.
    assert store.list_resolutions() == []
    assert asyncio.run(coll.check_resolutions()) == []


def test_engine_survives_an_upstream_failure(collector):
    coll, store = collector

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"code": "internal"}})

    coll.api._client = httpx.AsyncClient(base_url=coll.settings.rest_base,
                                        transport=httpx.MockTransport(boom))
    result = asyncio.run(coll.refresh_universe())
    assert result["tracked"] == 0
    assert coll.status["last_error"]


def test_dashboard_state_is_json_serialisable(collector):
    coll, _ = collector
    asyncio.run(coll.refresh_universe())
    asyncio.run(coll.poll_once())
    payload = coll.dashboard_state()
    json.dumps(payload)          # must not raise on Decimal or datetime
    assert payload["topics"] == ["gas", "elections", "culture", "crypto", "golf"]
    assert payload["portfolio"]["strategies"]
    assert all("equity" in s for s in payload["portfolio"]["strategies"])
