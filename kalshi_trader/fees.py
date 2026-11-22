"""Trading-fee model for the simulated book.

**Verification status: VERIFIED against Kalshi's published fee schedule.**

Source: ``https://kalshi.com/docs/kalshi-fee-schedule.pdf`` ("Last updated and effective:
July 7, 2026"), retrieved 2026-11-22 UTC. The schedule states, verbatim:

    fees = roundup(M x 0.07 x C x P x (1 - P))     (taker / general trading fee)
    fees = roundup(M x 0.0175 x C x P x (1 - P))   (maker fee; default M = 0)

with C = contracts, P = price in dollars and M = the per-series multiplier (default 1 for
takers, 0 for makers). The same document states there is **no settlement fee** and **no
membership fee**, and its "General Trading Fees Table" lists 21 prices at 1 contract and
21 prices at 100 contracts. ``tests/test_model_fees.py`` reproduces all 42 of those values,
so the rounding rule used here (round up to the cent) is the published one rather than a
third-party report.

Per-series multipliers: the schedule lists KXAAAGASM (US gas price) at maker 1 / taker 1,
i.e. the general formula; series with multiplier 0 are fee-free and are *not* special-cased
here — flag F1 on the Flagged for Review page records that limitation.

Rate changes are published at ``https://kalshi.com/fee-schedule`` (cited by the PDF), so
``TAKER_RATE`` / ``MAKER_RATE`` must be re-read from the schedule before relying on any
P&L figure produced by a future cycle.
"""

from __future__ import annotations

import math

VERIFIED = True
FEE_SCHEDULE_URL = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
FEE_CHANGES_URL = "https://kalshi.com/fee-schedule"
FEE_SCHEDULE_EFFECTIVE = "2026-07-07"
TAKER_RATE = 0.07
MAKER_RATE = 0.0175
MODEL_NAMES = {"quadratic": "quadratic_verified", "none": "none"}

FEE_SOURCE_NOTE = (
    "Fee model 0.07 x contracts x price x (1 - price), rounded up to the cent, taken from "
    "Kalshi's published fee schedule (effective 2026-07-07). Checks reproduce all 42 values "
    "of that schedule's General Trading Fees Table. Maker rate 0.0175 with a published "
    "default multiplier of 0; no settlement fee and no membership fee."
)


def taker_fee(contracts: float, price: float, model: str = "quadratic") -> float:
    """Fee in dollars for a taker fill."""
    if model == "none" or contracts <= 0 or price <= 0 or price >= 1:
        return 0.0
    raw = TAKER_RATE * contracts * price * (1.0 - price)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def maker_fee(contracts: float, price: float, model: str = "quadratic") -> float:
    if model == "none" or contracts <= 0 or price <= 0 or price >= 1:
        return 0.0
    raw = MAKER_RATE * contracts * price * (1.0 - price)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def model_label(model: str) -> str:
    return MODEL_NAMES.get(model, "quadratic_verified")


def metadata() -> dict[str, object]:
    return {
        "verified": VERIFIED,
        "taker_rate": TAKER_RATE,
        "maker_rate": MAKER_RATE,
        "formula": "ceil_to_cent(rate x contracts x price x (1 - price))",
        "note": FEE_SOURCE_NOTE,
        "source": FEE_SCHEDULE_URL,
        "changes_source": FEE_CHANGES_URL,
        "effective": FEE_SCHEDULE_EFFECTIVE,
    }
