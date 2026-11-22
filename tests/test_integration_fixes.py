"""Regression tests for three defects found during the integration review (2026-11-22).

Each test fails against the code that was on `main` before this session's fix, and passes now:

1. ``history.json`` was read as the whole file envelope (``{"generated_at", "series"}``) instead
   of its ``series`` map, so every cycle started with an empty history. The chart therefore never
   held more than one cycle of samples and the "hours" range could never fill. Verified against
   two consecutive live cycles on `main`, both of which stored exactly 2 points per market
   (commits ``521e795`` and ``73ef9dd``).
2. Resolution rows were written with ``topic = None`` for the bounded settled sweep, so
   ``tools/build_site.py`` (which filters ``r["topic"] == topic_id``) rendered "No settled markets
   recorded yet" on all five topic pages even though 308 settled markets were in the snapshot.
3. The sweep took the alphabetically first ten series across all topics. Series are named by
   ticker, so ``KXAAAGAS*``/elections consumed the budget and golf, culture and crypto were never
   swept. It now takes a fixed number of series *per topic*.
"""

from __future__ import annotations

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
from kalshi_trader import store

TOPICS = {"gas", "elections", "culture", "crypto", "golf"}


def _settings(tmp_path):
    return Settings(
        bankroll=1000.0,
        data_dir=tmp_path,
        state_dir=tmp_path,
        paper_ledger=tmp_path / "ledger.json",
        cycle_samples=1,
        max_markets_per_topic=10,
    )


def _client(settled=None):
    series = [GAS_SERIES, GOLF_SERIES, CRYPTO_SERIES, ELECTION_SERIES, CULTURE_SERIES]
    events = [
        {"event_ticker": "KXAAAGASM-26NOV30", "series_ticker": "KXAAAGASM", "category": "Economics", "title": "Gas price"},
        {"event_ticker": "KXPGAELEAGLE-26NOV22", "series_ticker": "KXPGAEAGLE", "category": "Sports", "title": "PGA eagle"},
        {"event_ticker": "KXBTCHIT90K-26DEC31", "series_ticker": "KXBTCHIT90K", "category": "Crypto", "title": "Bitcoin"},
        {"event_ticker": "KXNEXTNATOSECGEN-99", "series_ticker": "KXNEXTNATOSECGEN", "category": "Elections", "title": "NATO"},
        {"event_ticker": "KXOSCARS-27", "series_ticker": "KXOSCARS", "category": "Entertainment", "title": "Oscars"},
    ]
    markets = {
        "KXAAAGASM": [GAS_MARKET_345],
        "KXPGAEAGLE": [],
        "KXBTCHIT90K": [],
        "KXNEXTNATOSECGEN": [],
        "KXOSCARS": [],
    }
    return FakeClient(series=series, events=events, markets_by_series=markets, settled=settled or {})


def test_history_accumulates_across_cycles(tmp_path):
    settings = _settings(tmp_path)
    now = 1_760_000_000
    for index in range(3):
        run_cycle(settings, client=_client(), now=now + index * 900, samples=1)

    stored = store.read_json(tmp_path / "history.json")
    points = stored["series"]["KXAAAGASM-26NOV30-3.45"]
    assert len(points) == 3, f"expected 3 accumulated points, got {len(points)}"
    assert [p[0] for p in points] == [now, now + 900, now + 1800]
    # the stored envelope must still be the documented shape
    assert set(stored) == {"generated_at", "series"}


def test_resolution_rows_have_topic_and_own_market_url(tmp_path):
    settings = _settings(tmp_path)
    settled = {
        "KXAAAGASM": [
            {**GAS_MARKET_345, "ticker": "KXAAAGASM-26OCT31-3.50", "result": "yes",
             "status": "settled", "settlement_ts": "2026-11-01T15:00:00Z"}
        ]
    }
    latest = run_cycle(settings, client=_client(settled=settled), now=1_760_000_000, samples=1)

    rows = latest["resolved"]
    assert rows, "settled sweep must record rows"
    for row in rows:
        assert row["topic"] in TOPICS, row
        assert row["api_url"] and row["api_url"].endswith(f"/markets/{row['ticker']}"), row
    gas = [r for r in rows if r["ticker"] == "KXAAAGASM-26OCT31-3.50"]
    assert gas and gas[0]["topic"] == "gas" and gas[0]["resolution"] == "YES"


def test_sweep_reaches_every_topic_not_only_the_alphabetically_first(tmp_path):
    """Twelve gas series must not crowd golf out of the settled sweep."""
    many_gas = [{**GAS_SERIES, "ticker": f"KXAAAGAS{i:02d}T"} for i in range(12)]
    series = many_gas + [GOLF_SERIES]
    events = [
        {"event_ticker": f"KXAAAGAS{i:02d}T-26NOV30", "series_ticker": f"KXAAAGAS{i:02d}T",
         "category": "Economics", "title": "Gas price"}
        for i in range(12)
    ] + [{"event_ticker": "KXPGAELEAGLE-26NOV22", "series_ticker": "KXPGAEAGLE",
          "category": "Sports", "title": "PGA eagle"}]
    settled = {
        "KXPGAEAGLE": [
            {"ticker": "KXPGAEAGLE-26NOV21-SCOTTIE", "event_ticker": "KXPGAELEAGLE-26NOV21",
             "title": "Will Scottie Scheffler record an eagle?", "status": "settled", "result": "no",
             "close_time": "2026-11-21T23:00:00Z", "settlement_ts": "2026-11-22T01:00:00Z"}
        ]
    }
    client = FakeClient(series=series, events=events, markets_by_series={}, settled=settled)
    latest = run_cycle(_settings(tmp_path), client=client, now=1_760_000_000, samples=1)

    golf = [r for r in latest["resolved"] if r["series_ticker"] == "KXPGAEAGLE"]
    assert golf, "the golf series must be swept even when twelve gas series sort earlier"
    assert golf[0]["topic"] == "golf"
    assert golf[0]["resolution"] == "NO"


def test_published_resolutions_are_capped_per_topic():
    """One busy topic must not push the other four out of latest["resolved"]."""
    from kalshi_trader.collector import cap_resolved_per_topic

    rows = ([{"ticker": f"GAS{i}", "topic": "gas"} for i in range(200)]
            + [{"ticker": "ELEC1", "topic": "elections"}, {"ticker": "GOLF1", "topic": "golf"}]
            + [{"ticker": "NONE1", "topic": None}])
    kept = cap_resolved_per_topic(rows, per_topic=60, unattributed=20)
    tickers = [r["ticker"] for r in kept]
    assert len([t for t in tickers if t.startswith("GAS")]) == 60
    assert "ELEC1" in tickers and "GOLF1" in tickers and "NONE1" in tickers
    # order is preserved (newest first)
    assert tickers.index("GAS0") < tickers.index("GAS59")
