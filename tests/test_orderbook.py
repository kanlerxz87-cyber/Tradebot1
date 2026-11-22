"""Orderbook semantics, verified against Kalshi's documented response contract.

Sources:
* https://docs.kalshi.com/getting_started/orderbook_responses
  - payload is wrapped in `orderbook_fp` with `yes_dollars` / `no_dollars`
  - each level is a two element string array [price_dollars, count_fp]
  - arrays are sorted ascending; the best bid is the LAST element
  - bids only; YES ask = 1 - best NO bid
  - empty book (and unknown ticker) returns empty arrays, not 404
"""

from decimal import Decimal

from app.money import Orderbook, implied_no_ask, implied_yes_ask, spread

# The exact payload published in the Kalshi orderbook documentation.
DOC_EXAMPLE = {
    "orderbook_fp": {
        "yes_dollars": [
            ["0.0100", "200.00"], ["0.1500", "100.00"], ["0.2000", "50.00"],
            ["0.2500", "20.00"], ["0.3000", "11.00"], ["0.3100", "10.00"],
            ["0.3200", "10.00"], ["0.3300", "11.00"], ["0.3400", "9.00"],
            ["0.3500", "11.00"], ["0.4100", "10.00"], ["0.4200", "13.00"],
        ],
        "no_dollars": [
            ["0.0100", "100.00"], ["0.1600", "3.00"], ["0.2500", "50.00"],
            ["0.2800", "19.00"], ["0.3600", "5.00"], ["0.3700", "50.00"],
            ["0.3800", "300.00"], ["0.4400", "29.00"], ["0.4500", "20.00"],
            ["0.5600", "17.00"],
        ],
    }
}


def test_best_bids_are_the_last_elements():
    book = Orderbook.from_payload(DOC_EXAMPLE)
    assert book.best_yes_bid == Decimal("0.4200")
    assert book.best_no_bid == Decimal("0.5600")


def test_implied_asks_match_documented_arithmetic():
    book = Orderbook.from_payload(DOC_EXAMPLE)
    # Documented: best YES ask = 1.00 - 0.5600 = 0.44
    assert book.best_yes_ask == Decimal("0.44")
    # Documented: best NO ask = 1.00 - best YES bid
    assert book.best_no_ask == Decimal("0.58")
    assert spread(book.best_yes_bid, book.best_yes_ask) == Decimal("0.02")


def test_empty_book_is_not_an_error():
    book = Orderbook.from_payload({"orderbook_fp": {"yes_dollars": [], "no_dollars": []}})
    assert book.is_empty()
    assert book.best_yes_bid is None
    assert book.best_yes_ask is None
    assert book.liquidity_dollars() == Decimal("0")


def test_missing_payload_yields_unknown_not_zero():
    book = Orderbook.from_payload({})
    assert book.is_empty()
    assert book.best_yes_bid is None


def test_depth_math_for_contracts_within_ten_cents():
    book = Orderbook(DOC_EXAMPLE["orderbook_fp"]["yes_dollars"]
                     and [(Decimal(p), Decimal(c)) for p, c in DOC_EXAMPLE["orderbook_fp"]["yes_dollars"]],
                     [(Decimal(p), Decimal(c)) for p, c in DOC_EXAMPLE["orderbook_fp"]["no_dollars"]])
    # Buying YES consumes NO bids: 1 - 0.56 = 0.44 is best, so asks <= 0.54 count.
    # NO bids available: 0.56, 0.45, 0.44 (imply asks 0.44, 0.55, 0.56) -> only 0.44 qualifies.
    assert book.contracts_within("yes", Decimal("0.10")) == Decimal("17.00")
    # Ladder is cumulative and ascending by ask price. Total NO-bid contracts:
    # 100+3+50+19+5+50+300+29+20+17 = 593.
    ladder = book.cumulative("yes")
    assert Decimal(ladder[0]["price"]) == Decimal("0.44")
    assert Decimal(ladder[-1]["cumulative"]) == Decimal("593.00")


def test_liquidity_sums_both_sides_in_cash_terms():
    book = Orderbook.from_payload(DOC_EXAMPLE)
    expected = sum(Decimal(p) * Decimal(c) for p, c in
                   DOC_EXAMPLE["orderbook_fp"]["yes_dollars"] + DOC_EXAMPLE["orderbook_fp"]["no_dollars"])
    assert book.liquidity_dollars() == expected


def test_invalid_levels_are_dropped():
    book = Orderbook.from_payload({"orderbook_fp": {"yes_dollars": [["0.0000", "10"], ["1.0000", "5"], ["0.5", "3"]],
                                                    "no_dollars": [["bad", "1"]]}})
    assert book.yes_bids == [(Decimal("0.5"), Decimal("3"))]
    assert book.no_bids == []


def test_implied_price_helpers_guard_zero():
    assert implied_yes_ask(Decimal("1.00")) is None
    assert implied_no_ask(Decimal("0.00")) == Decimal("1.00")
