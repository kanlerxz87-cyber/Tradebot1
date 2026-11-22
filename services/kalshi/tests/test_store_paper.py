"""Persistent-ledger invariants with explicitly synthetic cash and orderbooks."""

from decimal import Decimal as D
import sqlite3

import pytest

from services.kalshi.kalshi_demo.domain import OrderBook
from services.kalshi.kalshi_demo.paper import PaperEngine, screen
from services.kalshi.kalshi_demo.store import Store


def make_book(ticker, timestamp, yes=None, no=None):
    book = OrderBook(ticker)
    book.snapshot(yes if yes is not None else [["0.48", "100"]],
                  no if no is not None else [["0.48", "100"]], timestamp, "https://docs.kalshi.com")
    return book


@pytest.mark.parametrize("old_version", [0, 1])
def test_legacy_timestamp_schema_migrates_without_losing_history(tmp_path, old_version):
    path = str(tmp_path / "legacy.sqlite3")
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE observations (
            ticker TEXT NOT NULL, ts_ms INTEGER NOT NULL, price TEXT NOT NULL,
            source_url TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY(ticker, ts_ms)
        );
        CREATE INDEX observations_time ON observations(ticker, ts_ms);
        INSERT INTO observations VALUES ('TEST', 1000, '0.4', 'synthetic-source', 'rest_sample');
        INSERT INTO observations VALUES ('TEST', 1001, '0.5', 'synthetic-source', 'rest_sample');
    """)
    db.execute(f"PRAGMA user_version={old_version}")
    db.close()
    store = Store(path)
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 2
    assert [row["price_dollars"] for row in store.history("TEST", 0)] == ["0.4", "0.5"]
    assert store.observation("TEST", 1001, "0.6", "synthetic-source", "trade", "trade-1")
    assert store.observation("TEST", 1001, "0.7", "synthetic-source", "trade", "trade-2")
    assert not store.observation("TEST", 1001, "0.6", "synthetic-source", "trade", "trade-1")
    store.close()
    store = Store(path)
    assert len(store.history("TEST", 0)) == 4
    assert len(list(store.db.execute("PRAGMA index_list(observations)"))) == 2
    store.close()


def test_event_id_schema_with_old_version_is_preserved(tmp_path):
    path = str(tmp_path / "early-event-ids.sqlite3")
    store = Store(path)
    store.observation("TEST", 1000, "0.4", "synthetic-source", "trade", "existing-id")
    store.db.execute("PRAGMA user_version=1")
    store.close()
    store = Store(path)
    assert store.db.execute("SELECT event_id FROM observations").fetchone()[0] == "existing-id"
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 2
    store.close()


def test_newer_database_cannot_be_silently_downgraded(tmp_path):
    path = str(tmp_path / "future.sqlite3")
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=99")
    db.close()
    with pytest.raises(ValueError, match="newer"):
        Store(path)
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == 99
    db.close()


def test_observations_deduplicate_trade_ids_not_milliseconds(store):
    assert store.observation("TEST", 1000, "0.4", "source", "trade", "a")
    assert store.observation("TEST", 1000, "0.5", "source", "trade", "b")
    assert not store.observation("TEST", 1001, "0.5", "source", "trade", "b")
    assert len(store.history("TEST", 0)) == 2


def test_orders_survive_restart_and_block_ambiguous_retries(tmp_path):
    path = str(tmp_path / "private.sqlite3")
    store = Store(path)
    assert store.reserve_order("a", {"test": 1}, D(10), D(15), 1000) is None
    store.finish_order("a", "ambiguous", {"error": "timeout"})
    store.close()
    store = Store(path)
    assert store.reserve_order("a", {"test": 1}, D(10), D(15), 2000)["state"] == "ambiguous"
    with pytest.raises(ValueError, match="different_request"):
        store.reserve_order("a", {"test": 2}, D(10), D(15), 2000)
    with pytest.raises(ValueError, match="cap_exceeded"):
        store.reserve_order("b", {"test": 1}, D(6), D(15), 2000)
    assert len(store.journal()) == 1
    store.close()


def test_buy_fills_at_opposing_depth_not_last_and_cash_conserved(store, market):
    engine = PaperEngine(store)
    book = make_book(market["ticker"], market["observed_ms"], no=[["0.48", "3"], ["0.45", "2"]])
    trade = engine.buy("momentum", market, "yes", D(10), D("0.55"), book, market["observed_ms"], "test-trigger")
    assert D(trade["count"]) == 5  # only five contracts were displayed
    assert D(trade["cost"]) == 3 * D("0.52") + 2 * D("0.55")
    assert D(engine.state["accounts"]["momentum"]["cash"]) + D(trade["cost"]) == 1000
    assert trade["fees"] is None
    assert trade["execution"].startswith("hypothetical")
    assert engine.buy("momentum", market, "yes", D(10), D("0.55"), book, market["observed_ms"], "test-trigger") is None


def test_never_crosses_limit_or_uses_stale_book(store, market):
    engine = PaperEngine(store)
    book = make_book(market["ticker"], market["observed_ms"])
    assert engine.buy("momentum", market, "yes", D(10), D("0.51"), book, market["observed_ms"], "a") is None
    assert engine.buy("momentum", market, "yes", D(10), D("0.55"), book, market["observed_ms"] + 10_001, "b") is None


@pytest.mark.parametrize("result,payout", [("yes", "10"), ("no", "0")])
def test_binary_settlement_is_finalized_and_idempotent(store, market, result, payout):
    engine = PaperEngine(store)
    book = make_book(market["ticker"], market["observed_ms"])
    engine.buy("momentum", market, "yes", D(10), D("0.52"), book, market["observed_ms"], "a")
    account = engine.state["accounts"]["momentum"]
    before = account["cash"]
    engine.settle({**market, "status": "determined", "result": result})
    assert account["cash"] == before
    final = {**market, "status": "finalized", "result": result, "settlement_ts": "synthetic-test-time"}
    engine.settle(final)
    assert D(account["cash"]) == D(before) + D(payout)
    engine.settle(final)
    assert len(account["settlements"]) == 1
    assert D(account["realized_gross_pnl"]) == D(payout) - D("5.20")
    restored = PaperEngine(store)
    assert restored.state == engine.state


def test_no_side_settlement_and_scalar_rejection(store, market):
    engine = PaperEngine(store)
    book = make_book(market["ticker"], market["observed_ms"])
    engine.buy("mean_reversion", market, "no", D(10), D("0.52"), book, market["observed_ms"], "a")
    account = engine.state["accounts"]["mean_reversion"]
    engine.settle({**market, "status": "finalized", "result": "scalar"})
    assert not account["settlements"]
    engine.settle({**market, "status": "finalized", "result": "no"})
    assert account["settlements"][0]["payout"] == "10.00"


def test_stale_mark_is_null_and_net_roi_unknown(store, market):
    engine = PaperEngine(store)
    book = make_book(market["ticker"], market["observed_ms"])
    engine.buy("momentum", market, "yes", D(10), D("0.52"), book, market["observed_ms"], "a")
    summary = engine.summary({market["ticker"]: market}, market["observed_ms"] + 46_000)
    assert summary["accounts"]["momentum"]["gross_equity"] is None
    assert summary["accounts"]["momentum"]["net_roi"] is None


def test_new_trade_cannot_refresh_a_stale_quote_mark(store, market):
    engine = PaperEngine(store)
    at = market["observed_ms"]
    engine.buy("momentum", market, "yes", D(10), D("0.52"), make_book(market["ticker"], at), at, "a")
    stale = {**market, "price_observed_ms": at, "quote_observed_ms": at - 46_000}
    account = engine.summary({market["ticker"]: stale}, at)["accounts"]["momentum"]
    assert account["gross_equity"] is None
    assert account["positions"][0]["gross_pnl"] is None
    fresh = {**market, "quote_observed_ms": at}
    account = engine.summary({market["ticker"]: fresh}, at)["accounts"]["momentum"]
    assert D(account["positions"][0]["gross_pnl"]) == D("-0.4")
    assert engine.state["accounts"]["momentum"]["positions"][0]["realized_gross_pnl"] is None


def test_screen_needs_prior_samples_fresh_depth_and_reports_only_hypothesis(market):
    at = market["observed_ms"]
    book = make_book(market["ticker"], at, yes=[["0.44", "100"]], no=[["0.54", "100"]])
    alert = {"timestamp_ms": at, "to_price": "0.45"}
    history = [{"timestamp_ms": at - 1000 * (i + 1), "price_dollars": "0.60"} for i in range(20)]
    assert screen(alert, history[:19], market, book, at) is None
    model = screen(alert, history, market, book, at)
    assert model["strategy"] == "mean_reversion" and model["outcome"] == "yes"
    assert model["net_roi"] is None and model["fees"] is None
    assert "Unvalidated" in model["label"]
    assert screen(alert, history, market, book, at + 10_001) is None
    assert screen(alert, [{"timestamp_ms": at + i + 1, "price_dollars": "0.60"} for i in range(30)], market, book, at) is None


def test_screen_rejects_wide_spread_and_thin_book(market):
    at = market["observed_ms"]
    alert = {"timestamp_ms": at, "to_price": "0.45"}
    history = [{"timestamp_ms": at - i - 1, "price_dollars": "0.60"} for i in range(20)]
    wide = make_book(market["ticker"], at, yes=[["0.40", "100"]], no=[["0.50", "100"]])
    assert screen(alert, history, market, wide, at) is None
    thin = make_book(market["ticker"], at, yes=[["0.44", "2"]], no=[["0.54", "2"]])
    assert screen(alert, history, market, thin, at) is None


def test_cumulative_event_exposure_is_capped(store, market):
    engine = PaperEngine(store)
    at = market["observed_ms"]
    first = engine.buy("momentum", market, "yes", D(100), D("0.52"), make_book(market["ticker"], at), at, "a")
    assert D(first["cost"]) <= 20
    other = {**market, "ticker": "SYNTHETIC-SAME-EVENT"}
    second = engine.buy("momentum", other, "yes", D(100), D("0.52"), make_book(other["ticker"], at), at, "b")
    total = D(first["cost"]) + (D(second["cost"]) if second else 0)
    assert total <= 20
