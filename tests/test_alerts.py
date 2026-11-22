"""Swing detection: the $0.10 rule, false-positive suppression, and scoring."""

from decimal import Decimal

from app.alerts import ScoringInputs, SwingDetector, observed_price, score_alert


def test_observed_price_uses_mid_of_two_sided_book():
    price, two_sided, used_last = observed_price(
        yes_bid="0.40", yes_ask="0.44", last_price="0.42")
    assert price == Decimal("0.42")
    assert two_sided is True
    assert used_last is False


def test_one_sided_book_prefers_last_trade_over_the_empty_side():
    # Demo markets routinely publish no_bid=0.0000 with yes_ask=1.0000. Taking
    # that ask would make every empty book look like a 100c collapse.
    price, two_sided, used_last = observed_price(
        yes_bid="0.14", yes_ask="1.00", last_price="0.30")
    assert price == Decimal("0.30")
    assert two_sided is False
    assert used_last is True


def test_crossed_or_wide_book_falls_back_to_last_price():
    price, two_sided, used_last = observed_price(
        yes_bid="0.80", yes_ask="0.20", last_price="0.55")
    assert price == Decimal("0.55")
    assert two_sided is False


def test_no_price_at_all_returns_none():
    assert observed_price(yes_bid=None, yes_ask=None, last_price=None)[0] is None


def test_alert_fires_at_exactly_ten_cents():
    detector = SwingDetector(threshold=Decimal("0.10"), window_seconds=60, cooldown_seconds=0)
    assert detector.observe("T", ts=1000.0, yes_bid="0.40", yes_ask="0.42") is None
    alert = detector.observe("T", ts=1010.0, yes_bid="0.50", yes_ask="0.52")
    assert alert is not None
    assert alert.direction == "up"
    assert alert.abs_delta == Decimal("0.10")


def test_move_below_threshold_does_not_fire():
    detector = SwingDetector(threshold=Decimal("0.10"), window_seconds=60, cooldown_seconds=0)
    detector.observe("T2", ts=1000.0, yes_bid="0.40", yes_ask="0.42")
    assert detector.observe("T2", ts=1001.0, yes_bid="0.47", yes_ask="0.49") is None


def test_down_move_is_detected():
    detector = SwingDetector(threshold=Decimal("0.10"), window_seconds=60, cooldown_seconds=0)
    detector.observe("T3", ts=1000.0, yes_bid="0.60", yes_ask="0.62")
    alert = detector.observe("T3", ts=1002.0, yes_bid="0.48", yes_ask="0.50")
    assert alert is not None and alert.direction == "down"


def test_cooldown_suppresses_repeats_but_not_direction_flips():
    detector = SwingDetector(threshold=Decimal("0.10"), window_seconds=60, cooldown_seconds=30)
    detector.observe("T4", ts=1000.0, yes_bid="0.30", yes_ask="0.32")
    assert detector.observe("T4", ts=1001.0, yes_bid="0.45", yes_ask="0.47") is not None   # up
    assert detector.observe("T4", ts=1002.0, yes_bid="0.60", yes_ask="0.62") is None       # same dir, cooldown
    assert detector.observe("T4", ts=1003.0, yes_bid="0.40", yes_ask="0.42") is not None   # flip


def test_window_reference_catches_a_slow_bleed():
    detector = SwingDetector(threshold=Decimal("0.10"), window_seconds=60, cooldown_seconds=0)
    # 11 one-cent steps at just under 6s apart: no single step trips the rule,
    # but the first and last samples are 60s apart, so the window must.
    for i in range(11):
        alert = detector.observe("T5", ts=1000.0 + i * 6,
                                 yes_bid=str(Decimal("0.50") + Decimal(i) / 100))
    assert alert is not None
    assert alert.window_s >= 60
    assert alert.direction == "up"


def test_confidence_marks_quote_only_moves():
    # A one-sided book with no trade print: the move exists only in the quote.
    detector = SwingDetector(threshold=Decimal("0.10"), window_seconds=60, cooldown_seconds=0)
    detector.observe("T6", ts=1000.0, yes_bid="0.30", yes_ask="1.00")
    alert = detector.observe("T6", ts=1001.0, yes_bid="0.45", yes_ask="1.00")
    assert alert is not None
    assert alert.confidence == "quote-only"
    assert any("unconfirmed quote" in r for r in alert.reasons)


def test_confidence_marks_trade_backed_moves_confirmed():
    detector = SwingDetector(threshold=Decimal("0.10"), window_seconds=60, cooldown_seconds=0)
    detector.observe("T7", ts=1000.0, yes_bid="0.30", yes_ask="1.00", last_price="0.30")
    alert = detector.observe("T7", ts=1001.0, yes_bid="0.45", yes_ask="1.00", last_price="0.45")
    assert alert is not None
    assert alert.confidence == "confirmed"


def test_scoring_is_bounded_and_explains_itself():
    score = score_alert(ScoringInputs(
        delta=Decimal("-0.10"), from_price=Decimal("0.50"), to_price=Decimal("0.40"),
        best_ask=Decimal("0.41"), best_bid=Decimal("0.39"), contracts_within_10c=Decimal("900"),
        liquidity_dollars=Decimal("20000"), volume_24h=Decimal("5000"),
        open_interest=Decimal("1200"), spread=Decimal("0.02"), hours_to_close=48,
        confidence="confirmed", fee_dollars=Decimal("0.01"),
    ))
    assert Decimal("0") <= score["score"] <= Decimal("1")
    assert set(score["components"]) == {"magnitude", "liquidity", "cost", "horizon", "confirmation"}
    assert score["payout_multiple"] == Decimal("1.44")
    assert "not a probability of profit" in score["disclaimer"]


def test_thin_and_unconfirmed_markets_score_lower():
    good = score_alert(ScoringInputs(
        delta=Decimal("0.20"), from_price=Decimal("0.4"), to_price=Decimal("0.6"),
        best_ask=Decimal("0.6"), contracts_within_10c=Decimal("800"), spread=Decimal("0.01"),
        hours_to_close=24, confidence="confirmed", fee_dollars=Decimal("0.01"),
    ))
    bad = score_alert(ScoringInputs(
        delta=Decimal("0.10"), from_price=Decimal("0.4"), to_price=Decimal("0.5"),
        best_ask=Decimal("0.5"), contracts_within_10c=Decimal("5"), spread=Decimal("0.08"),
        hours_to_close=0.2, confidence="quote-only", fee_dollars=Decimal("0.04"),
    ))
    assert good["score"] > bad["score"]
    assert bad["caveats"], "thin/unconfirmed inputs must produce caveats"
