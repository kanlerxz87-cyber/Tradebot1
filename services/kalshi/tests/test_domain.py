"""Decimal, source/null, stream sequence and lifecycle regression tests."""

from decimal import Decimal as D

import pytest

from services.kalshi.kalshi_demo.domain import (
    AlertDetector, BookError, OrderBook, SequenceGuard, classify_series, decimal,
    group_events, normalize_market,
)


@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity", "-Infinity", True, "garbage", [], {}])
def test_unknown_numbers_stay_unknown(value):
    assert decimal(value) is None


def test_zero_is_not_missing():
    assert decimal("0.0000") == 0


def test_normalization_never_fills_missing_values():
    row = normalize_market({"ticker": "SYNTHETIC-X", "status": "active"}, "gas", 1000)
    assert row["last_price_dollars"] is None
    assert row["dollar_volume"] is None
    assert row["result"] is None
    assert "last_price_dollars" in row["unverified_fields"]
    assert row["source_url"].startswith("https://external-api.demo.kalshi.co/")


@pytest.mark.parametrize("status,expected", [
    ("active", None), ("closed", None), ("determined", None), ("disputed", None),
    ("amended", None), ("finalized", "yes"), ("settled", None),
])
def test_only_finalized_is_confirmed_settlement(raw_market, status, expected):
    row = normalize_market({**raw_market, "status": status, "result": "yes"}, "crypto", 1000)
    assert row["result"] == expected
    assert row["reported_result"] == "yes"


def test_scalar_is_not_yes_or_no(raw_market):
    row = normalize_market({**raw_market, "status": "finalized", "result": "scalar"}, "crypto", 1000)
    assert row["result"] is None
    assert "Non-binary" in row["settlement_review"]


@pytest.mark.parametrize("series,topic", [
    ({"title": "Weekly gasoline prices", "category": "Economics"}, "gas"),
    ({"title": "State election winner", "category": "Politics"}, "elections"),
    ({"title": "Test", "category": "Culture"}, "culture"),
    ({"title": "Test", "category": "Crypto"}, "crypto"),
    ({"title": "PGA golf winner", "category": "Sports"}, "golf"),
    ({"title": "Basketball", "category": "Sports"}, None),
    ({"title": "Natural gas futures", "category": "Economics"}, None),
    ({"title": "Political approval", "category": "Politics"}, None),
    ({"title": "Bitcoin election", "category": "Politics"}, None),
])
def test_explicit_five_topic_scope(series, topic):
    assert classify_series(series)[0] == topic


def test_ranking_does_not_estimate_dollars_from_contract_volume(raw_market):
    market = normalize_market(raw_market, "crypto", 1000)
    event = {"event_ticker": raw_market["event_ticker"], "topic": "crypto", "source_url": "https://docs.kalshi.com"}
    rows = group_events([event], {market["ticker"]: market})
    assert rows[0]["cumulative_dollar_notional"] is None
    market["dollar_volume"] = "0"
    assert group_events([event], {market["ticker"]: market})[0]["cumulative_dollar_notional"] == "0"
    second = {**market, "ticker": "SYNTHETIC-OTHER", "dollar_volume": None}
    assert group_events([event], {market["ticker"]: market, second["ticker"]: second})[0]["cumulative_dollar_notional"] is None


@pytest.mark.parametrize("before,after,direction", [("0.40", "0.50", "up"), ("0.50", "0.40", "down")])
def test_threshold_inclusive_both_directions(before, after, direction):
    detector = AlertDetector()
    assert detector.observe("TEST", D(before), 1000) is None
    alert = detector.observe("TEST", D(after), 2000)
    assert alert["direction"] == direction
    assert abs(D(alert["delta_dollars"])) == D("0.10")
    assert alert["selected"] is False
    assert alert["catalysts"] == []


def test_threshold_below_ten_cents_does_not_fire():
    detector = AlertDetector()
    detector.observe("TEST", D("0.4000"), 1000)
    assert detector.observe("TEST", D("0.4999"), 2000) is None


def test_small_moves_accumulate_and_reanchor():
    detector = AlertDetector()
    detector.observe("TEST", D("0.40"), 1000)
    assert detector.observe("TEST", D("0.45"), 2000) is None
    assert detector.observe("TEST", D("0.50"), 3000)
    assert detector.observe("TEST", D("0.51"), 4000) is None
    assert detector.observe("TEST", D("0.41"), 5000)["direction"] == "down"


def test_no_cross_gap_or_out_of_order_alerts():
    detector = AlertDetector()
    detector.observe("TEST", D("0.40"), 1000)
    assert detector.observe("TEST", D("0.55"), 61_001) is None
    assert detector.observe("TEST", D("0.30"), 50_000) is None
    assert detector.observe("TEST", D("0.55"), 61_001) is None
    detector.reset()
    assert detector.observe("TEST", D("0.20"), 62_000) is None


def test_two_trades_can_move_ten_cents_in_same_millisecond():
    detector = AlertDetector()
    detector.observe("TEST", D("0.40"), 1000, "trade-a")
    assert detector.observe("TEST", D("0.50"), 1000, "trade-b")["id"] == "TEST:trade-b"


def test_two_sided_depth_is_complementary_not_invented():
    book = OrderBook("TEST")
    book.snapshot([["0.30", "4.25"], ["0.40", "2.00"]], [["0.55", "10.50"]], 1000, "https://docs.kalshi.com")
    assert book.asks("yes") == [(D("0.45"), D("10.50"))]
    assert book.asks("no") == [(D("0.60"), D("2.00")), (D("0.70"), D("4.25"))]
    assert book.as_dict(1000)["yes_asks"][0]["derived_complement"] is True
    assert book.as_dict(1000)["yes_asks"][0]["source_url"]
    book.delta("no", "0.55", "-10.50", 1001)
    assert book.asks("yes") == []


def test_book_replacement_negative_delta_and_missing_snapshot():
    book = OrderBook("TEST")
    with pytest.raises(BookError):
        book.delta("yes", "0.4", "1", 1000)
    book.snapshot([["0.4", "1"]], [], 1000, "source")
    with pytest.raises(BookError):
        book.delta("yes", "0.4", "-2", 1001)
    assert not book.valid
    book.snapshot([], [], 1002, "source")
    assert book.valid and not book.yes
    with pytest.raises(BookError):
        book.snapshot(None, [], 1003, "source")
    assert not book.valid


def test_bad_book_does_not_mutate_half_a_snapshot():
    book = OrderBook("TEST")
    book.snapshot([["0.4", "10"]], [["0.5", "5"]], 1000, "source")
    with pytest.raises(BookError):
        book.snapshot([["0.6", "20"]], [["-0.5", "5"]], 2000, "source")
    assert book.yes == {D("0.4"): D("10")}
    assert not book.valid


def test_sequence_is_per_subscription_and_gap_is_not_accepted():
    guard = SequenceGuard()
    assert guard.accept(1, 10)
    assert guard.accept(2, 40)
    assert guard.accept(1, 11)
    assert not guard.accept(1, 13)
    assert not guard.accept(2, 40)
