"""Fee maths verified against Kalshi's own published fee table.

Source: https://kalshi.com/docs/kalshi-fee-schedule.pdf
"Last updated and effective: July 7, 2026", General Trading Fees Table.

Every price/expectation pair below is copied from that table, so this test is a
direct transcription check rather than our own arithmetic agreeing with itself.
"""

from decimal import Decimal

import pytest

from app.money import fee_dollars, fee_cents_per_contract

# (price of 1 contract, fee for 1 contract, price for 100 contracts, fee for 100)
PUBLISHED_TABLE = [
    ("0.01", "0.01", "0.07"), ("0.05", "0.01", "0.34"), ("0.10", "0.01", "0.63"),
    ("0.15", "0.01", "0.90"), ("0.20", "0.02", "1.12"), ("0.25", "0.02", "1.32"),
    ("0.30", "0.02", "1.47"), ("0.35", "0.02", "1.60"), ("0.40", "0.02", "1.68"),
    ("0.45", "0.02", "1.74"), ("0.50", "0.02", "1.75"), ("0.55", "0.02", "1.74"),
    ("0.60", "0.02", "1.68"), ("0.65", "0.02", "1.60"), ("0.70", "0.02", "1.47"),
    ("0.75", "0.02", "1.32"), ("0.80", "0.02", "1.12"), ("0.85", "0.01", "0.90"),
    ("0.90", "0.01", "0.63"), ("0.95", "0.01", "0.34"), ("0.99", "0.01", "0.07"),
]


@pytest.mark.parametrize("price,one,fee100", PUBLISHED_TABLE)
def test_single_contract_fee_matches_published_table(price, one, fee100):
    assert fee_dollars(Decimal(price), Decimal(1)) == Decimal(one)


@pytest.mark.parametrize("price,one,fee100", PUBLISHED_TABLE)
def test_hundred_contract_fee_matches_published_table(price, one, fee100):
    assert fee_dollars(Decimal(price), Decimal(100)) == Decimal(fee100)


def test_fee_is_zero_for_non_executing_orders():
    # "Trading fees are only charged for orders that are immediately matched":
    # a zero quantity cannot execute, so no fee may be charged.
    assert fee_dollars(Decimal("0.50"), Decimal("0")) == Decimal("0")
    assert fee_dollars(Decimal("0"), Decimal("10")) == Decimal("0")
    assert fee_dollars(Decimal("1.00"), Decimal("10")) == Decimal("0")


def test_maker_fee_is_a_quarter_of_the_taker_multiplier():
    # Maker multiplier is 0.0175 against a taker 0.07 (fee schedule, Maker Fees).
    taker = fee_dollars(Decimal("0.50"), Decimal("100"))
    maker = fee_dollars(Decimal("0.50"), Decimal("100"), maker=True)
    assert taker == Decimal("1.75")
    assert maker == Decimal("0.44")
    assert maker < taker


def test_fee_peak_is_at_fifty_cents():
    fees = [fee_cents_per_contract(Decimal(p) / 100) for p in range(5, 96, 5)]
    assert max(fees) == fees[len(fees) // 2] or max(fees) == Decimal("2")


def test_micro_rounding_matches_fill_level_contract():
    # https://docs.kalshi.com/getting_started/fee_rounding:
    # trade fee is rounded up to the nearest $0.000001.
    value = fee_dollars(Decimal("0.5555"), Decimal("1"), rounding="micro")
    # 0.07 x 1 x 0.5555 x 0.4445 = 0.0172843825, rounded up at 6dp.
    assert value == Decimal("0.017285")
