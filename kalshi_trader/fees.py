"""Trading-fee model for the simulated book.

**Verification status: UNVERIFIED — see the Flagged for Review page.**

Kalshi's fee schedule PDF (``https://kalshi.com/docs/kalshi-fee-schedule.pdf``, linked from
the ``fee_type`` field of ``GET /series``) could not be retrieved during this session, so the
formula below is *not* confirmed against an official Kalshi document. Multiple independent
third-party write-ups report the general trading fee as

    fee = ceil_to_cent(0.07 x contracts x price x (1 - price))

which is the shape Kalshi's own docs imply by describing ``fee_type`` as "quadratic"
(https://docs.kalshi.com/api-reference/market/get-series-list). Maker fills are reported to
pay a quarter of that.

Because an unverified fee would silently distort every P&L number, the dashboard:
  * applies this model by default, but
  * labels every ledger entry with ``fee_model="quadratic_unverified"``,
  * exposes ``KALSHI_FEE_MODEL=none`` to switch it off, and
  * shows the caveat next to every performance figure.

If Kalshi publishes the current schedule, replace ``TAKER_RATE`` / ``MAKER_RATE`` and flip
``VERIFIED`` to ``True``.
"""

from __future__ import annotations

import math

VERIFIED = False
TAKER_RATE = 0.07
MAKER_RATE = 0.0175  # third-party reports: 25% of the taker rate
MODEL_NAMES = {"quadratic": "quadratic_unverified", "none": "none"}

FEE_SOURCE_NOTE = (
    "Fee model 0.07 x contracts x price x (1 - price), rounded up to the cent. "
    "Reported by third parties; Kalshi's fee schedule PDF could not be retrieved, so this "
    "is flagged unverified."
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
    return MODEL_NAMES.get(model, "quadratic_unverified")


def metadata() -> dict[str, object]:
    return {
        "verified": VERIFIED,
        "taker_rate": TAKER_RATE,
        "maker_rate": MAKER_RATE,
        "formula": "ceil_to_cent(rate x contracts x price x (1 - price))",
        "note": FEE_SOURCE_NOTE,
    }
