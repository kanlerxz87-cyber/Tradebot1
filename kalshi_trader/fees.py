"""Trading-fee model for the simulated book.

**Verification status: VERIFIED** against Kalshi's own published fee schedule,
``https://kalshi.com/docs/kalshi-fee-schedule.pdf`` (linked from the ``fee_type`` field of
``GET /series``: https://docs.kalshi.com/api-reference/market/get-series-list), read on
2026-11-22. The PDF is dated "Last updated and effective: July 7, 2026" and states:

    fees = roundup(M x 0.07 x C x P x (1 - P))          # taker / general trading fee
    fees = roundup(M x 0.0175 x C x P x (1 - P))        # maker fee

with ``P`` the price of a contract in dollars, ``C`` the number of contracts, ``M`` the
per-series multiplier (default 1 taker, 0 maker) and "round up = rounds up such that the
fee + positionCost is rounded to a centicent". The same PDF gives a worked table — one
contract at $0.50 costs $0.02, one hundred contracts at $0.50 cost $1.75 — which the tests
reproduce exactly.

Two limits are kept deliberately:

* The PDF's worked table rounds each fee **up to the cent** (100 contracts at $0.35 is
  $1.5925 exactly and the table prints $1.60). This module applies that same rule, so all
  21 rows of the published table are reproduced exactly and asserted in
  ``tests/test_model_fees.py``. It is labelled ``fee_model="quadratic"``.
* The per-series multiplier ``M`` in the formula is applied as 1 unless a series is known to
  be fee-free. The PDF's non-standard table lists several series with ``M = 0`` (for example
  ``KXBTCY``, ``KXCPI``, ``KXFED`` and the NBA/NFL game series), and those are not
  enumerated exhaustively here, so a fee-free series may still be charged the default fee.
  That is flagged on the Flagged for Review page (F1).
"""

from __future__ import annotations

import math

VERIFIED = True
TAKER_RATE = 0.07
MAKER_RATE = 0.0175  # 25% of the taker rate, per the PDF's "Maker Fees" section
MODEL_NAMES = {"quadratic": "quadratic", "none": "none"}

FEE_SOURCE = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
FEE_SOURCE_NOTE = (
    "Fee = roundup(0.07 x contracts x price x (1 - price)) for taker fills and "
    "roundup(0.0175 x ...) for maker fills, per Kalshi's fee schedule (effective 2026-07-07). "
    "The paper book rounds up to the cent, which never understates the fee."
)


def taker_fee(
    contracts: float,
    price: float,
    model: str = "quadratic",
    *,
    multiplier: float = 1.0,
) -> float:
    """Fee in dollars for a taker fill."""
    if model == "none" or contracts <= 0 or price <= 0 or price >= 1 or multiplier <= 0:
        return 0.0
    raw = multiplier * TAKER_RATE * contracts * price * (1.0 - price)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def maker_fee(
    contracts: float,
    price: float,
    model: str = "quadratic",
    *,
    multiplier: float = 1.0,
) -> float:
    if model == "none" or contracts <= 0 or price <= 0 or price >= 1 or multiplier <= 0:
        return 0.0
    raw = multiplier * MAKER_RATE * contracts * price * (1.0 - price)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def model_label(model: str) -> str:
    return MODEL_NAMES.get(model, "quadratic")


def metadata() -> dict[str, object]:
    return {
        "verified": VERIFIED,
        "taker_rate": TAKER_RATE,
        "maker_rate": MAKER_RATE,
        "formula": "ceil_to_cent(rate x contracts x price x (1 - price))",
        "note": FEE_SOURCE_NOTE,
        "source": FEE_SOURCE,
        "effective": "2026-07-07",
    }
