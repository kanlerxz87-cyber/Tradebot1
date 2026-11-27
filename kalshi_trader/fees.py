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
* The per-series multiplier ``M`` is read from the published "Non-Standard Fees" table for
  the rows that are unambiguous in the PDF (see ``SERIES_MULTIPLIERS``). A series that is not
  in that table is charged the general multiplier of 1, which can overstate a fee on a
  fee-free series outside the encoded rows; the remaining rows are flagged on the Flagged
  for Review page (F1). Corrected 2026-11-27: an earlier revision of this docstring named
  ``KXCPI`` and ``KXFED`` as examples of ``M = 0`` series. The published table lists both of
  them at maker 1 / taker 1; only ``KXBTCY`` (of the three named) is 0 / 0. Source:
  https://kalshi.com/docs/kalshi-fee-schedule.pdf ("Non-Standard Fees").
"""

from __future__ import annotations

import math
from typing import Any

VERIFIED = True
TAKER_RATE = 0.07
MAKER_RATE = 0.0175  # 25% of the taker rate, per the PDF's "Maker Fees" section

#: Published per-series multipliers, "Non-Standard Fees" table of the fee schedule
#: (https://kalshi.com/docs/kalshi-fee-schedule.pdf, effective 2026-07-07).
#: Only rows whose three columns are unambiguous in the published PDF are encoded; the
#: table's later rows interleave columns during text extraction ("KXNASDAQ100Y Nasdaq
#: yearly range 11"), so they are deliberately omitted rather than guessed. An omitted
#: series falls back to the general multiplier of 1.
SERIES_MULTIPLIERS: dict[str, tuple[float, float]] = {
    "KXAAAGASM": (1.0, 1.0),        # US gas price
    "KXATPMATCH": (1.0, 1.0),       # ATP Tennis Match
    "KXBALLONDOR": (1.0, 1.0),      # Ballon d'Or
    "KXBTCMAX150": (1.0, 1.0),      # When will bitcoin hit 150k?
    "KXBTCY": (0.0, 0.0),           # BTC price range EOY
    "KXCITRINI": (0.0, 0.0),        # Will the Citrini scenario materialize?
    "KXCPI": (1.0, 1.0),            # CPI
    "KXCPIYOY": (1.0, 1.0),         # Inflation
    "KXDOED": (0.0, 0.0),           # DOE eliminated
    "KXEGGS": (1.0, 1.0),           # Egg prices
    "KXELECTIRAN": (0.0, 0.0),      # Will Iran hold a presidential election?
    "KXEMMYCACTO": (1.0, 1.0),      # Emmys, Lead Comedy Actor
    "KXEMMYCACTR": (1.0, 1.0),      # Emmys, Lead Comedy Actress
    "KXEMMYCSERIES": (1.0, 1.0),    # Emmys, Comedy Series
    "KXEMMYDACTO": (1.0, 1.0),      # Emmys, Lead Drama Actor
    "KXEMMYDACTR": (1.0, 1.0),      # Emmys, Lead Drama Actress
    "KXEMMYDSERIES": (1.0, 1.0),    # Emmys, Drama Series
    "KXETHY": (0.0, 0.0),           # ETH price EOY
    "KXFED": (1.0, 1.0),            # Fed funds rate
    "KXFEDDECISION": (1.0, 1.0),    # Fed meeting
    "KXGAMBLINGREPEAL": (0.0, 0.0), # Gambling Repeal
    "KXGDP": (1.0, 1.0),            # US GDP growth
    "KXGREENLAND": (0.0, 0.0),      # Greenland purchase
    "KXHEISMAN": (1.0, 1.0),        # Heisman Trophy Winner
    "KXINXY": (1.0, 1.0),           # S&P 500 yearly range
    "KXIPO": (1.0, 1.0),            # IPOs
    "KXIRANDEMOCRACY": (0.0, 0.0),  # Will Iran become a democracy in 2026?
    "KXLALIGA": (1.0, 1.0),         # LA LIGA
    "KXLAYOFFSYINFO": (0.0, 0.0),   # Tech layoffs
    "KXLLM1": (1.0, 1.0),           # Year-end top LLM
    "KXMARMAD": (1.0, 1.0),         # College Basketball Champion
}

MULTIPLIER_SOURCE = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"


def series_multiplier(series_ticker: Any, side: str = "taker") -> float:
    """Published multiplier for a series; 1.0 when the series is not in the encoded rows.

    ``side`` is ``"taker"`` for a fill against resting orders and ``"maker"`` for a
    resting order that later executes.
    """
    row = SERIES_MULTIPLIERS.get(str(series_ticker or "").upper())
    if row is None:
        return 1.0
    maker, taker = row
    return maker if side == "maker" else taker


def series_from_ticker(ticker: Any) -> str:
    """Series ticker of a market ticker: ``KXBTCY-27JAN0100-T20000.00`` -> ``KXBTCY``."""
    text = str(ticker or "").upper()
    dash = text.find("-")
    return text if dash == -1 else text[:dash]
MODEL_NAMES = {"quadratic": "quadratic", "none": "none"}

FEE_SOURCE = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
FEE_SOURCE_NOTE = (
    "Fee = roundup(0.07 x contracts x price x (1 - price)) for taker fills and "
    "roundup(0.0175 x ...) for maker fills, per Kalshi's fee schedule (effective 2026-07-07). "
    "The paper book rounds up to the cent, which never understates the fee."
)


def taker_fee(
    contracts: float, price: float, model: str = "quadratic", multiplier: float = 1.0
) -> float:
    """Fee in dollars for a taker fill, multiplied by the series multiplier."""
    if model == "none" or contracts <= 0 or price <= 0 or price >= 1 or multiplier <= 0:
        return 0.0
    raw = multiplier * TAKER_RATE * contracts * price * (1.0 - price)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def maker_fee(
    contracts: float, price: float, model: str = "quadratic", multiplier: float = 1.0
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
