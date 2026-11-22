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


def test_fee_is_labelled_unverified():
    assert fees.VERIFIED is False
    assert fees.model_label("quadratic") == "quadratic_unverified"


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
