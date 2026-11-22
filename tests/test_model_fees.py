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


def test_fee_model_is_verified_against_the_published_schedule():
    assert fees.VERIFIED is True
    assert fees.model_label("quadratic") == "quadratic_verified"
    assert fees.FEE_SCHEDULE_URL == "https://kalshi.com/docs/kalshi-fee-schedule.pdf"


# Every row of the "General Trading Fees Table" in
# https://kalshi.com/docs/kalshi-fee-schedule.pdf (effective 2026-07-07), read on 2026-11-22:
# (price of one contract, fee for 1 contract, fee for 100 contracts).
PUBLISHED_FEES = [
    (0.01, 0.01, 0.07),
    (0.05, 0.01, 0.34),
    (0.10, 0.01, 0.63),
    (0.15, 0.01, 0.90),
    (0.20, 0.02, 1.12),
    (0.25, 0.02, 1.32),
    (0.30, 0.02, 1.47),
    (0.35, 0.02, 1.60),
    (0.40, 0.02, 1.68),
    (0.45, 0.02, 1.74),
    (0.50, 0.02, 1.75),
    (0.55, 0.02, 1.74),
    (0.60, 0.02, 1.68),
    (0.65, 0.02, 1.60),
    (0.70, 0.02, 1.47),
    (0.75, 0.02, 1.32),
    (0.80, 0.02, 1.12),
    (0.85, 0.01, 0.90),
    (0.90, 0.01, 0.63),
    (0.95, 0.01, 0.34),
    (0.99, 0.01, 0.07),
]


def test_fee_model_reproduces_every_published_table_value():
    for price, one, hundred in PUBLISHED_FEES:
        assert round(fees.taker_fee(1, price), 2) == one, (price, 1)
        assert round(fees.taker_fee(100, price), 2) == hundred, (price, 100)


def test_maker_fee_is_a_quarter_of_the_taker_fee_before_rounding():
    # The schedule prints 0.0175 for makers and 0.07 for takers.
    assert fees.MAKER_RATE * 4 == fees.TAKER_RATE == 0.07


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
