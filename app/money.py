"""Money, contract-size, orderbook and fee maths.

Every rule implemented here is traceable to an official Kalshi page:

* Prices and counts are **fixed-point strings**, not floats.
  `yes_bid_dollars="0.5600"`, `volume_fp="10.00"`, `count_fp="10.00"`.
  Source: https://docs.kalshi.com/getting_started/fixed_point_migration
* The orderbook returns **bids only**; asks are implied.
  A YES bid at X is a NO ask at (1 - X).
  Source: https://docs.kalshi.com/getting_started/orderbook_responses
* Orderbook arrays are sorted ascending by price, so the best bid is the
  **last** element. Source: same page.
* Trading fee (taker) = roundup(M x 0.07 x C x P x (1-P)).
  Maker fee      = roundup(M x 0.0175 x C x P x (1-P)).
  There is no settlement fee and no membership fee.
  Source: https://kalshi.com/docs/kalshi-fee-schedule.pdf ("Last updated and
  effective: July 7, 2026").

Nothing here rounds silently: `fee_cents` returns a Decimal in dollars rounded
up to the cent, which is what the published fee table shows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from typing import Iterable, Sequence

CENT = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")
MICRO = Decimal("0.000001")

TAKER_FEE_MULTIPLIER = Decimal("0.07")
MAKER_FEE_MULTIPLIER = Decimal("0.0175")


# --------------------------------------------------------------------------- #
# Parsing / formatting
# --------------------------------------------------------------------------- #
def to_decimal(value: object, default: Decimal | None = None) -> Decimal | None:
    """Parse a Kalshi fixed-point string into a Decimal.

    Accepts None, "", ints, floats and strings. Returns `default` when the value
    is missing or unparseable -- callers must treat that as *unknown*, never as
    zero. This is deliberate: an unknown price must never look like $0.00.
    """
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return default
    try:
        return Decimal(str(value).strip())
    except Exception:
        return default


def dollars(value: object, default: Decimal | None = None) -> Decimal | None:
    return to_decimal(value, default)


def contracts(value: object, default: Decimal | None = None) -> Decimal | None:
    return to_decimal(value, default)


def fmt_dollars(value: Decimal | None, places: int = 2) -> str:
    if value is None:
        return "--"
    q = Decimal(1).scaleb(-places)
    return f"${value.quantize(q):,}"


def fmt_cents(value: Decimal | None) -> str:
    """0.42 -> 42c (the way Kalshi traders speak)."""
    if value is None:
        return "--"
    return f"{(value * 100).quantize(Decimal('1'))}c"


def fmt_contracts(value: Decimal | None) -> str:
    if value is None:
        return "--"
    return f"{value.quantize(Decimal('0.01')):,}"


# --------------------------------------------------------------------------- #
# Fees
# --------------------------------------------------------------------------- #
def fee_dollars(
    price: Decimal,
    count: Decimal,
    *,
    maker: bool = False,
    multiplier: Decimal | None = None,
    rounding: str = "cent",
) -> Decimal:
    """Fee for one execution, in dollars.

    `rounding="cent"` reproduces the published "Fee for 1 contract" /
    "Fee for 100 contracts" table, which rounds the fee *plus position cost* up
    to the next cent. `rounding="micro"` rounds the naked fee up to 6 decimals,
    matching the fill-level `trade_fee` described in
    https://docs.kalshi.com/getting_started/fee_rounding.

    Never returns a negative number. A non-positive count or a price outside
    (0, 1) yields 0: Kalshi never charges a fee for an order that did not
    execute, and such inputs cannot execute.
    """
    if price is None or count is None:
        return ZERO
    if count <= 0 or price <= 0 or price >= ONE:
        return ZERO
    m = multiplier if multiplier is not None else (MAKER_FEE_MULTIPLIER if maker else TAKER_FEE_MULTIPLIER)
    raw = m * count * price * (ONE - price)
    if rounding == "micro":
        return max(ZERO, raw.quantize(MICRO, rounding=ROUND_CEILING))
    # round up (fee + position_cost) to the cent, then subtract position cost
    position_cost = count * price
    total = (raw + position_cost).quantize(CENT, rounding=ROUND_CEILING)
    return max(ZERO, total - position_cost)


def fee_cents_per_contract(price: Decimal, maker: bool = False) -> Decimal:
    """Published per-contract fee, in cents, for one contract.

    Kalshi's fee table posts e.g. $0.50 -> $0.02 for a single contract, which is
    why this is computed on one contract rather than on a rate.
    """
    return fee_dollars(price, ONE, maker=maker) * 100


# --------------------------------------------------------------------------- #
# Binary-market price relationships
# --------------------------------------------------------------------------- #
def implied_yes_ask(best_no_bid: Decimal | None) -> Decimal | None:
    """YES ask = 1.0000 - best NO bid (bids only, asks implied)."""
    if best_no_bid is None:
        return None
    ask = ONE - best_no_bid
    return ask if ask > 0 else None


def implied_no_ask(best_yes_bid: Decimal | None) -> Decimal | None:
    if best_yes_bid is None:
        return None
    ask = ONE - best_yes_bid
    return ask if ask > 0 else None


def spread(best_bid: Decimal | None, best_ask: Decimal | None) -> Decimal | None:
    if best_bid is None or best_ask is None:
        return None
    return best_ask - best_bid


def executable_buy_price(side: str, levels: Sequence[tuple[Decimal, Decimal]] | None) -> Decimal | None:
    """Best price at which you can BUY a given side from a bids-only book.

    Buying YES consumes the cheapest NO bid: you pay 1 - best_no_bid.
    Buying NO consumes the cheapest YES bid: you pay 1 - best_yes_bid.
    """
    if not levels:
        return None
    best = max(price for price, _ in levels)
    return implied_yes_ask(best) if side == "yes" else implied_no_ask(best)


# --------------------------------------------------------------------------- #
# Orderbook
# --------------------------------------------------------------------------- #
@dataclass
class Orderbook:
    """A parsed `orderbook_fp` payload.

    `yes_bids` and `no_bids` are [(price_dollars, count_contracts)] sorted
    ascending, exactly as returned. `depth` honours the `depth` query param.
    """

    yes_bids: list[tuple[Decimal, Decimal]] = field(default_factory=list)
    no_bids: list[tuple[Decimal, Decimal]] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict | None) -> "Orderbook":
        payload = payload or {}
        # Accept both the current `orderbook_fp` shape and the older `orderbook`
        # shape so fixtures and older captures still parse.
        fp = payload.get("orderbook_fp") or {}
        legacy = payload.get("orderbook") or {}
        yes = fp.get("yes_dollars") if fp else legacy.get("yes")
        no = fp.get("no_dollars") if fp else legacy.get("no")
        return cls(_levels(yes, legacy_scale=not fp), _levels(no, legacy_scale=not fp))

    # -- best prices ------------------------------------------------------
    @property
    def best_yes_bid(self) -> Decimal | None:
        return self.yes_bids[-1][0] if self.yes_bids else None

    @property
    def best_no_bid(self) -> Decimal | None:
        return self.no_bids[-1][0] if self.no_bids else None

    @property
    def best_yes_ask(self) -> Decimal | None:
        return implied_yes_ask(self.best_no_bid)

    @property
    def best_no_ask(self) -> Decimal | None:
        return implied_no_ask(self.best_yes_bid)

    def best_ask_for(self, side: str) -> Decimal | None:
        return self.best_yes_ask if side == "yes" else self.best_no_ask

    def best_bid_for(self, side: str) -> Decimal | None:
        return self.best_yes_bid if side == "yes" else self.best_no_bid

    # -- liquidity --------------------------------------------------------
    def liquidity_dollars(self) -> Decimal:
        """Cash value of every resting bid on both sides."""
        total = ZERO
        for price, count in self.yes_bids + self.no_bids:
            total += price * count
        return total

    def contracts_within(self, side: str, cents: Decimal = Decimal("0.10")) -> Decimal:
        """How many contracts are available to buy `side` within N cents of best."""
        best = self.best_ask_for(side)
        if best is None:
            return ZERO
        limit = best + cents
        book = self.no_bids if side == "yes" else self.yes_bids
        total = ZERO
        for price, count in book:
            ask = ONE - price
            if ask <= limit:
                total += count
        return total

    def cumulative(self, side: str) -> list[dict]:
        """Ladder for charts: cumulative contracts available at each ask price."""
        book = sorted(
            ((ONE - price, count) for price, count in (self.no_bids if side == "yes" else self.yes_bids)),
            key=lambda row: row[0],
        )
        out, running = [], ZERO
        for ask, count in book:
            running += count
            out.append({"price": str(ask), "contracts": str(count), "cumulative": str(running)})
        return out

    def spread_for(self, side: str = "yes") -> Decimal | None:
        return spread(self.best_bid_for(side), self.best_ask_for(side))

    def is_empty(self) -> bool:
        return not self.yes_bids and not self.no_bids

    def as_dict(self) -> dict:
        return {
            "yes_bids": [[str(p), str(c)] for p, c in self.yes_bids],
            "no_bids": [[str(p), str(c)] for p, c in self.no_bids],
            "best_yes_bid": _s(self.best_yes_bid),
            "best_yes_ask": _s(self.best_yes_ask),
            "best_no_bid": _s(self.best_no_bid),
            "best_no_ask": _s(self.best_no_ask),
            "liquidity_dollars": _s(self.liquidity_dollars()),
        }


def _levels(raw: object, legacy_scale: bool = False) -> list[tuple[Decimal, Decimal]]:
    out: list[tuple[Decimal, Decimal]] = []
    if not isinstance(raw, (list, tuple)):
        return out
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = to_decimal(row[0])
        count = to_decimal(row[1])
        if price is None or count is None:
            continue
        if legacy_scale:  # older payloads used integer cents
            price = price / 100
        if price <= 0 or price >= ONE or count <= 0:
            continue
        out.append((price, count))
    out.sort(key=lambda row: row[0])
    return out


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


# --------------------------------------------------------------------------- #
# Binary search helper used by the alert detector
# --------------------------------------------------------------------------- #
def hours_between(a_ts: float, b_ts: float) -> float:
    return abs(b_ts - a_ts) / 3600.0


def logit(p: Decimal) -> float:
    p = min(max(float(p), 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def summarize_levels(levels: Iterable[tuple[Decimal, Decimal]]) -> dict:
    levels = list(levels)
    if not levels:
        return {"levels": 0, "contracts": "0", "dollars": "0"}
    total_c = sum(c for _, c in levels)
    total_d = sum(p * c for p, c in levels)
    return {"levels": len(levels), "contracts": str(total_c), "dollars": str(total_d)}
