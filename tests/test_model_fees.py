import math

from kalshi_trader import fees, model


def _market(**overrides):
    base = {
        "ticker": "T-1",
        "price": 0.50,
        "volume_24h": 5000.0,
        "open_interest": 20000.0,
        "spread": 0.01,
        "close_time": "2099-01-01T00:00:00Z",
        "previous": 0.50,
    }
    base.update(overrides)
    return base


def test_fee_rounds_up_to_cent():
    # 0.07 * 100 * 0.5 * 0.5 = 1.75
    assert fees.taker_fee(100, 0.5) == 1.75
    # 0.07 * 100 * 0.1 * 0.9 = 0.63
    assert fees.taker_fee(100, 0.1) == 0.63
    # a fractional result rounds up, never down
    assert fees.taker_fee(1, 0.5) == 0.02
    assert fees.taker_fee(1, 0.5) >= 0.0175


def test_fee_model_can_be_disabled():
    assert fees.taker_fee(100, 0.5, model="none") == 0.0


def test_fee_model_label_is_plain_after_verification():
    assert fees.VERIFIED is True
    assert fees.model_label("quadratic") == "quadratic"


def test_model_score_bounds_and_direction():
    now = 1_700_000_000
    history = [[now - 600, 0.40], [now - 300, 0.45], [now, 0.55]]
    scored = model.score_market(_market(price=0.55), history, now)
    assert 0 <= scored["score"] <= 1
    assert scored["direction"] == "yes"
    assert scored["recent_move"] == 0.15
    assert scored["roi_pct_est"] > 0
    assert set(scored["components"]) == {"momentum", "liquidity", "open_interest", "band", "time", "spread"}


def test_model_penalises_wide_spread():
    now = 1_700_000_000
    tight = model.score_market(_market(spread=0.01), [], now)
    wide = model.score_market(_market(spread=0.09), [], now)
    assert tight["score"] > wide["score"]


def test_model_requires_direction_for_pick():
    now = 1_700_000_000
    flat = model.score_market(_market(price=0.5, previous=0.5), [], now)
    assert flat["direction"] is None
    assert flat["eligible"] is False


# --- Fee schedule verification (kalshi.com/docs/kalshi-fee-schedule.pdf, effective 2026-07-07)

def test_fee_model_is_marked_verified_against_the_official_schedule():
    from kalshi_trader import fees as fee_mod

    assert fee_mod.VERIFIED is True
    assert fee_mod.FEE_SOURCE == "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
    assert fee_mod.metadata()["source"] == fee_mod.FEE_SOURCE


def test_published_fee_table_rows_reproduce_exactly():
    """Every row of the PDF's "General Trading Fees Table" for 100 contracts."""
    from kalshi_trader.fees import taker_fee

    published = {
        0.01: 0.07, 0.05: 0.34, 0.10: 0.63, 0.15: 0.90, 0.20: 1.12,
        0.25: 1.32, 0.30: 1.47, 0.35: 1.60, 0.40: 1.68, 0.45: 1.74,
        0.50: 1.75, 0.55: 1.74, 0.60: 1.68, 0.65: 1.60, 0.70: 1.47,
        0.75: 1.32, 0.80: 1.12, 0.85: 0.90, 0.90: 0.63, 0.95: 0.34,
        0.99: 0.07,
    }
    for price, expected in published.items():
        assert taker_fee(100, price) == expected, price


def test_single_contract_fee_matches_the_published_table():
    """Every price in the PDF's table costs exactly $0.01 or $0.02 for one contract."""
    from kalshi_trader.fees import taker_fee

    expected = {
        0.01: 0.01, 0.05: 0.01, 0.10: 0.01, 0.15: 0.01, 0.20: 0.02, 0.25: 0.02,
        0.30: 0.02, 0.50: 0.02, 0.85: 0.01, 0.95: 0.01, 0.99: 0.01,
    }
    for price, value in expected.items():
        assert taker_fee(1, price) == value, price


def test_maker_rate_is_a_quarter_of_the_taker_rate():
    from kalshi_trader.fees import MAKER_RATE, TAKER_RATE, maker_fee

    assert MAKER_RATE == TAKER_RATE / 4
    # 100 contracts at $0.50: taker $1.75 -> maker $0.4375 -> $0.44 rounded up to the cent.
    assert maker_fee(100, 0.50) == 0.44


def test_fee_multiplier_zero_produces_zero_fee():
    assert fees.taker_fee(100, 0.50, multiplier=0.0) == 0.0
    assert fees.maker_fee(100, 0.50, multiplier=0.0) == 0.0
    assert fees.taker_fee(100, 0.50, multiplier=1.0) == 1.75


def test_published_series_multipliers_zero_out_fee_free_series():
    # "Non-Standard Fees" table, https://kalshi.com/docs/kalshi-fee-schedule.pdf
    # (effective 2026-07-07): "KXBTCY | BTC price range EOY | 0 | 0".
    assert fees.series_multiplier("KXBTCY") == 0.0
    assert fees.series_multiplier("KXBTCY", "maker") == 0.0
    assert fees.taker_fee(100, 0.5, multiplier=fees.series_multiplier("KXBTCY")) == 0.0
    assert fees.maker_fee(100, 0.5, multiplier=fees.series_multiplier("KXBTCY")) == 0.0


def test_series_named_fee_free_by_an_earlier_revision_are_charged():
    # The published table lists KXCPI and KXFED at maker 1 / taker 1. An earlier
    # docstring claimed they, like KXBTCY, were fee-free; that was wrong.
    for series in ("KXCPI", "KXFED", "KXAAAGASM"):
        assert fees.series_multiplier(series) == 1.0
        assert fees.series_multiplier(series, "maker") == 1.0
        assert fees.taker_fee(100, 0.5, multiplier=fees.series_multiplier(series)) == 1.75


def test_unknown_series_uses_the_general_multiplier():
    assert fees.series_multiplier("KXNOTINTHEPUBLISHEDTABLE") == 1.0
    assert fees.series_multiplier(None) == 1.0


def test_series_is_read_from_the_front_of_the_market_ticker():
    assert fees.series_from_ticker("KXBTCY-27JAN0100-T20000.00") == "KXBTCY"
    assert fees.series_from_ticker("KXAAAGASM-26DEC-T3.50") == "KXAAAGASM"
    assert fees.series_from_ticker("KXBTCY") == "KXBTCY"


def test_multiplier_is_the_only_thing_that_changes_the_formula():
    # A multiplier of 1 must reproduce the published rows exactly.
    for price in (0.01, 0.25, 0.5, 0.75, 0.99):
        assert fees.taker_fee(100, price, multiplier=1.0) == fees.taker_fee(100, price)
