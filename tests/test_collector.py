import json

from kalshi_trader import store
from kalshi_trader.collector import run_cycle
from kalshi_trader.config import Settings

from tests.fixtures import (
    CRYPTO_SERIES,
    CULTURE_SERIES,
    ELECTION_SERIES,
    GAS_MARKET_345,
    GAS_SERIES,
    GOLF_SERIES,
    FakeClient,
)

GOLF_MARKET = {
    "ticker": "KXPGAEAGLE-26NOV22-SCOTTIE",
    "event_ticker": "KXPGAELEAGLE-26NOV22",
    "title": "Will Scottie Scheffler record an eagle in round 1?",
    "status": "active",
    "close_time": "2026-11-23T00:00:00Z",
    "yes_bid_dollars": "0.4000",
    "yes_ask_dollars": "0.4400",
    "no_bid_dollars": "0.5600",
    "no_ask_dollars": "0.6000",
    "last_price_dollars": "0.4200",
    "volume_fp": "12000.00",
    "volume_24h_fp": "4000.00",
    "open_interest_fp": "15000.00",
    "result": "",
}

CRYPTO_MARKET = {
    "ticker": "KXBTCHIT90K-26DEC31",
    "event_ticker": "KXBTCHIT90K-26DEC31",
    "title": "Will bitcoin be above $90,000 on Dec 31, 2026?",
    "status": "active",
    "close_time": "2026-12-31T23:59:00Z",
    "yes_bid_dollars": "0.5200",
    "yes_ask_dollars": "0.5400",
    "no_bid_dollars": "0.4600",
    "no_ask_dollars": "0.4800",
    "last_price_dollars": "0.5300",
    "volume_fp": "8000.00",
    "volume_24h_fp": "3000.00",
    "open_interest_fp": "9000.00",
    "result": "",
}


def _settings(tmp_path):
    return Settings(
        bankroll=1000.0,
        data_dir=tmp_path,
        state_dir=tmp_path,
        paper_ledger=tmp_path / "ledger.json",
        cycle_samples=1,
        sample_gap_s=0.0,
        max_markets_per_topic=10,
    )


def _client(gas_market=None):
    series = [GAS_SERIES, GOLF_SERIES, CRYPTO_SERIES, ELECTION_SERIES, CULTURE_SERIES]
    events = [
        {"event_ticker": "KXAAAGASM-26NOV30", "series_ticker": "KXAAAGASM", "category": "Economics", "title": "Gas price"},
        {"event_ticker": "KXPGAELEAGLE-26NOV22", "series_ticker": "KXPGAEAGLE", "category": "Sports", "title": "PGA eagle"},
        {"event_ticker": "KXBTCHIT90K-26DEC31", "series_ticker": "KXBTCHIT90K", "category": "Crypto", "title": "Bitcoin"},
        {"event_ticker": "KXNEXTNATOSECGEN-99", "series_ticker": "KXNEXTNATOSECGEN", "category": "Elections", "title": "NATO"},
        {"event_ticker": "KXOSCARS-27", "series_ticker": "KXOSCARS", "category": "Entertainment", "title": "Oscars"},
    ]
    markets = {
        "KXAAAGASM": [gas_market or GAS_MARKET_345],
        "KXPGAEAGLE": [GOLF_MARKET],
        "KXBTCHIT90K": [CRYPTO_MARKET],
        "KXNEXTNATOSECGEN": [],
        "KXOSCARS": [],
    }
    return FakeClient(series=series, events=events, markets_by_series=markets,
                      settled={"KXAAAGASM": [{**GAS_MARKET_345, "ticker": "KXAAAGASM-26OCT31-3.50", "result": "yes",
                                              "status": "settled", "settlement_ts": "2026-11-01T15:00:00Z"}]})


def test_cycle_writes_expected_files_and_topics(tmp_path):
    settings = _settings(tmp_path)
    latest = run_cycle(settings, client=_client(), now=1_760_000_000, samples=1)

    for name in ("latest.json", "alerts.json", "history.json", "meta.json", "paper.json", "series.json", "resolved.json"):
        assert (tmp_path / name).exists(), name

    assert latest["market_count"] == 3
    assert set(latest["topics"]) == {"gas", "elections", "culture", "crypto", "golf"}
    assert latest["topics"]["gas"]["markets_count"] == 1
    assert latest["topics"]["golf"]["markets_count"] == 1
    assert latest["topics"]["crypto"]["markets_count"] == 1
    # elections/culture have no markets but must still render
    assert latest["topics"]["elections"]["markets_count"] == 0

    gas = latest["topics"]["gas"]["markets"][0]
    assert gas["api_url"].endswith("/markets/KXAAAGASM-26NOV30-3.45")
    assert gas["series_page_url"].startswith("https://kalshi.com/markets/")


def test_second_cycle_emits_swing_alert(tmp_path):
    settings = _settings(tmp_path)
    start = dict(GAS_MARKET_345)
    start.update({"yes_bid_dollars": "0.4500", "yes_ask_dollars": "0.4700", "last_price_dollars": "0.4600"})
    run_cycle(settings, client=_client(gas_market=start), now=1_760_000_000, samples=1)

    moved = dict(GAS_MARKET_345)
    moved.update({"yes_bid_dollars": "0.6100", "yes_ask_dollars": "0.6300", "last_price_dollars": "0.6200"})
    latest = run_cycle(settings, client=_client(gas_market=moved), now=1_760_000_900, samples=1)

    assert latest["alerts"], "a $0.155 move must fire an alert"
    alert = latest["alerts"][0]
    assert alert["ticker"] == "KXAAAGASM-26NOV30-3.45"
    assert alert["direction"] == "up"
    assert alert["abs_delta"] >= 0.10

    stored = store.read_json(tmp_path / "alerts.json")
    assert stored["threshold"] == 0.1
    assert stored["items"][0]["id"] == alert["id"]


def test_history_records_tracked_markets(tmp_path):
    settings = _settings(tmp_path)
    run_cycle(settings, client=_client(), now=1_760_000_000, samples=1)
    history = store.read_json(tmp_path / "history.json")
    assert "KXAAAGASM-26NOV30-3.45" in history["series"]
    point = history["series"]["KXAAAGASM-26NOV30-3.45"][-1]
    assert point[0] == 1_760_000_000
    assert point[1] == 0.965


def test_resolutions_captured_with_source(tmp_path):
    settings = _settings(tmp_path)
    latest = run_cycle(settings, client=_client(), now=1_760_000_000, samples=1)
    resolved = latest["resolved"]
    assert resolved, "settled markets must be recorded"
    row = next(r for r in resolved if r["result"] == "yes")
    assert row["resolution"] == "YES"
    assert row["source"].startswith("https://docs.kalshi.com")


def test_demo_block_is_explicit_when_not_configured(tmp_path):
    settings = _settings(tmp_path)
    latest = run_cycle(settings, client=_client(), now=1_760_000_000, samples=1)
    assert latest["demo"]["connected"] is False
    assert latest["demo"]["status"]["required_env"] == ["KALSHI_API_KEY_ID", "KALSHI_PRIVATE_KEY"]


def test_settled_sweep_uses_the_documented_status_and_timestamp_pair():
    """`min_close_ts` is only valid with status=closed; `min_settled_ts` pairs with status=settled.

    Verified against the compatibility table at
    https://docs.kalshi.com/api-reference/market/get-markets — the previous build sent
    min_close_ts with status=settled and every cycle failed with HTTP 400.
    """
    from kalshi_trader.collector import _collect_resolutions

    captured: list[dict] = []

    class SweepClient:
        def paginate(self, path, key, params=None, page_size=200, max_pages=25):
            captured.append(dict(params or {}))
            return []

    errors: list[str] = []
    _collect_resolutions(
        SweepClient(),
        current_markets={},
        series_by_topic={"gas": ["KXAAAGASW"]},
        existing=[],
        errors=errors,
        now=1_790_000_000,
    )
    assert captured, "the settled sweep must issue at least one request"
    params = captured[0]
    assert params["status"] == "settled"
    assert "min_settled_ts" in params
    assert "min_close_ts" not in params, "min_close_ts is incompatible with status=settled"
    value = params["min_settled_ts"]
    assert isinstance(value, int), f"min_settled_ts must be an int, got {type(value).__name__}"
    assert value > 1_700_000_000
    assert errors == []


class TwoSampleClient(FakeClient):
    """FakeClient whose gas market changes between two fetches in one cycle."""

    def __init__(self, *args, second=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._second = second
        self._gas_calls = 0

    def paginate(self, path, key, params=None, page_size=200, max_pages=25):
        params = params or {}
        if (
            path == "/markets"
            and params.get("series_ticker") == "KXAAAGASM"
            and params.get("status", "open") != "settled"
        ):
            self._gas_calls += 1
            if self._gas_calls >= 2 and self._second:
                self.request_count += 1
                return [self._second]
        return super().paginate(path, key, params, page_size=page_size, max_pages=max_pages)


def test_second_sample_replaces_a_whole_row_not_just_its_price(tmp_path):
    """A mid-cycle refresh must not leave one row quoting a fresh price beside a stale mid.

    Regression: the collector used to assign only ``price`` from the refresh, so the
    published row kept the first sample's ``mid``/``yes_bid``/``yes_ask`` and a
    ``notional_24h_est`` computed from the old price. A 14-cent move inside a cycle was
    then invisible to the swing detector, which reads ``mid``.
    """
    settings = _settings(tmp_path)
    earlier = dict(GAS_MARKET_345)
    earlier.update({"yes_bid_dollars": "0.4200", "yes_ask_dollars": "0.4600", "last_price_dollars": "0.4400"})
    later = dict(GAS_MARKET_345)
    later.update({"yes_bid_dollars": "0.2700", "yes_ask_dollars": "0.3100", "last_price_dollars": "0.2900"})

    client = TwoSampleClient(
        series=[GAS_SERIES, GOLF_SERIES, CRYPTO_SERIES, ELECTION_SERIES, CULTURE_SERIES],
        events=[
            {"event_ticker": "KXAAAGASM-26NOV30", "series_ticker": "KXAAAGASM", "category": "Economics", "title": "Gas price"},
        ],
        markets_by_series={"KXAAAGASM": [earlier]},
        second=later,
    )
    latest = run_cycle(settings, client=client, now=1_760_000_000, samples=2)
    row = latest["topics"]["gas"]["markets"][0]

    # Every price field now comes from the same (second) response.
    assert row["mid"] == 0.29
    assert row["yes_bid"] == 0.27
    assert row["yes_ask"] == 0.31
    assert row["price"] == 0.29
    # ...and the derived notional follows it instead of the first sample's price.
    assert abs(row["notional_24h_est"] - round(row["volume_24h"] * row["price"], 2)) < 0.02


class SettlementLookupClient(FakeClient):
    """FakeClient that serves GET /markets/{ticker} for closed/finalized open positions."""

    def __init__(self, *args, by_ticker=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._by_ticker = by_ticker or {}

    def market(self, ticker):
        self.request_count += 1
        return self._by_ticker[ticker]


def test_open_paper_position_settles_after_market_leaves_open_list(tmp_path):
    from kalshi_trader.paper import PaperLedger

    settings = _settings(tmp_path)
    open_mkt = dict(CRYPTO_MARKET)
    open_mkt.update({
        "yes_bid_dollars": "0.9000",
        "yes_ask_dollars": "0.9100",
        "no_bid_dollars": "0.0900",
        "no_ask_dollars": "0.1000",
        "last_price_dollars": "0.9000",
    })
    ledger = PaperLedger(settings)
    pos = ledger.open_position(
        {
            "ticker": CRYPTO_MARKET["ticker"],
            "topic": "crypto",
            "title": CRYPTO_MARKET["title"],
            "series_ticker": "KXBTCHIT90K",
            "yes_bid": 0.90,
            "yes_ask": 0.91,
            "top_book_contracts": 500,
        },
        "late_favorite",
        "yes",
        "test",
        now=1_760_000_000,
    )
    assert pos is not None
    ledger.save()

    settled_mkt = {
        **open_mkt,
        "status": "finalized",
        "result": "yes",
        "settlement_value_dollars": "1.0000",
        "settlement_ts": "2026-11-23T00:02:00Z",
    }
    client = SettlementLookupClient(
        series=[GAS_SERIES, GOLF_SERIES, CRYPTO_SERIES, ELECTION_SERIES, CULTURE_SERIES],
        events=[{"event_ticker": "KXAAAGASM-26NOV30", "series_ticker": "KXAAAGASM", "category": "Economics", "title": "Gas price"}],
        markets_by_series={"KXAAAGASM": [GAS_MARKET_345]},
        by_ticker={CRYPTO_MARKET["ticker"]: settled_mkt},
    )
    latest = run_cycle(settings, client=client, now=1_760_000_900, samples=1)
    assert latest["paper"]["open_positions"] == []
    assert latest["performance"]["headline"]["open_positions"] == 0
    assert latest["performance"]["summary"]["trades"] == 1
    assert latest["paper"]["trades"][0]["settled_result"] == "yes"
    assert any(r["ticker"] == CRYPTO_MARKET["ticker"] and r["resolution"] == "YES" for r in latest["resolved"])
