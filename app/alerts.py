"""Swing detection and the selective ("high ROI") ranking model.

Requirement being implemented: alert whenever a contract price moves **at least
$0.10 in either direction**.

Decisions, and why
------------------
1. **Which price is watched.** Kalshi's orderbook has bids only; asks are
   implied (https://docs.kalshi.com/getting_started/orderbook_responses).
   The dashboard reports the *mid* of (best yes bid, implied yes ask) when the
   book is two-sided and the spread is sane, because a single-sided or crossed
   book produces phantom swings. Concretely, demo data shows
   `no_bid_dollars="0.0000"` next to `yes_ask_dollars="1.0000"`; watching the ask
   there would fire a false $0.10 alert on every empty book. When the book is
   one-sided we fall back to `last_price`, then to the best bid.
2. **Two comparisons.** A move is detected against the previous sample *and*
   against the sample `swing_window_seconds` ago, so a fast 3-tick bleed and a
   slow 60-second drift are both caught.
3. **Confidence.** A swing backed by a trade print or by a two-sided quote is
   `confirmed`; a swing that exists only in a one-sided quote is `quote-only`
   and is shown as such rather than silently trusted.
4. **De-duplication.** Each market has a cooldown so the chat stays readable,
   but a direction flip always alerts.

The selective feed's score is an explicitly labelled heuristic ranking of
*opportunity quality*, not a probability of profit. Every component is shown in
the UI so a trader can audit or ignore it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from .money import ONE, ZERO, to_decimal

SWING_CONFIDENCE = ("confirmed", "quote-only", "unconfirmed")


@dataclass
class PriceSample:
    ts: float
    mid: Decimal
    yes_bid: Decimal | None = None
    yes_ask: Decimal | None = None
    last_price: Decimal | None = None
    liquidity: Decimal | None = None
    two_sided: bool = False
    traded: bool = False


@dataclass
class SwingAlert:
    ticker: str
    ts: float
    direction: str                 # "up" | "down"
    from_price: Decimal
    to_price: Decimal
    window_s: int
    confidence: str
    reasons: list[str] = field(default_factory=list)

    @property
    def delta(self) -> Decimal:
        return self.to_price - self.from_price

    @property
    def abs_delta(self) -> Decimal:
        return abs(self.delta)

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "ts": self.ts,
            "direction": self.direction,
            "from_price": str(self.from_price),
            "to_price": str(self.to_price),
            "delta": str(self.delta),
            "abs_delta": str(self.abs_delta),
            "window_s": self.window_s,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
        }


def observed_price(*, yes_bid: object, yes_ask: object, last_price: object,
                   max_sane_spread: Decimal = Decimal("0.20")) -> tuple[Decimal | None, bool, bool]:
    """Return (price, two_sided, used_last_price) from a ticker/orderbook sample.

    See module docstring for why a one-sided book is not trusted for swing maths.
    """
    bid = to_decimal(yes_bid)
    ask = to_decimal(yes_ask)
    last = to_decimal(last_price)

    two_sided = bid is not None and ask is not None and bid > 0 and ask < ONE and ask >= bid
    if two_sided and (ask - bid) <= max_sane_spread:
        return (bid + ask) / 2, True, False
    if last is not None and last > 0 and last < ONE:
        return last, False, True
    if bid is not None and bid > 0:
        return bid, False, False
    if ask is not None and ask < ONE:
        return ask, False, False
    return None, False, False


class SwingDetector:
    """Rolling per-market price history with $0.10 swing detection."""

    def __init__(self, *, threshold: Decimal = Decimal("0.10"), window_seconds: int = 60,
                 cooldown_seconds: int = 30, max_samples: int = 240,
                 max_sane_spread: Decimal = Decimal("0.20")):
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self.max_samples = max_samples
        self.max_sane_spread = max_sane_spread
        self._history: dict[str, list[PriceSample]] = {}
        self._last_alert: dict[str, tuple[float, str]] = {}

    # ------------------------------------------------------------------ #
    def observe(self, ticker: str, *, ts: float | None = None, yes_bid: object = None,
                yes_ask: object = None, last_price: object = None, liquidity: object = None,
                traded: bool = False) -> SwingAlert | None:
        """Record a sample and return an alert if the threshold was crossed."""
        now = time.time() if ts is None else ts
        price, two_sided, used_last = observed_price(
            yes_bid=yes_bid, yes_ask=yes_ask, last_price=last_price, max_sane_spread=self.max_sane_spread
        )
        if price is None:
            return None
        sample = PriceSample(
            ts=now, mid=price, yes_bid=to_decimal(yes_bid), yes_ask=to_decimal(yes_ask),
            last_price=to_decimal(last_price), liquidity=to_decimal(liquidity),
            two_sided=two_sided, traded=traded or used_last,
        )
        history = self._history.setdefault(ticker, [])
        history.append(sample)
        if len(history) > self.max_samples:
            del history[: len(history) - self.max_samples]

        alert = self._detect(ticker, history, sample)
        if alert is None:
            return None

        previous = self._last_alert.get(ticker)
        if previous is not None:
            last_ts, last_dir = previous
            if now - last_ts < self.cooldown_seconds and last_dir == alert.direction:
                return None   # suppress same-direction churn inside the cooldown
        self._last_alert[ticker] = (now, alert.direction)
        return alert

    def _detect(self, ticker: str, history: list[PriceSample], current: PriceSample) -> SwingAlert | None:
        candidates: list[tuple[PriceSample, str]] = []
        if len(history) >= 2:
            candidates.append((history[-2], "previous tick"))
        ref = self._sample_at_or_before(history, current.ts - self.window_seconds)
        if ref is not None:
            candidates.append((ref, f"{self.window_seconds}s window"))
        if not candidates:
            return None

        # Compare against every candidate and keep the largest move: a slow
        # bleed trips the window rule even when each single step is tiny.
        ref_sample, ref_label = max(
            candidates, key=lambda c: abs(c[0].mid - current.mid)
        )
        if ref_sample is current:
            return None
        delta = current.mid - ref_sample.mid
        if abs(delta) < self.threshold:
            return None

        direction = "up" if delta > 0 else "down"
        reasons = [f"{direction} {abs(delta):.4f} vs {ref_label} ({ref_sample.mid:.4f} -> {current.mid:.4f})"]

        if current.traded or (current.last_price is not None and current.last_price != ref_sample.last_price):
            confidence = "confirmed"
            reasons.append("last traded price changed with the quote")
        elif current.two_sided and ref_sample.two_sided:
            confidence = "confirmed"
            reasons.append("two-sided quotes moved together")
        else:
            confidence = "quote-only"
            reasons.append("one-sided or empty book: treated as an unconfirmed quote move")

        if current.liquidity is not None and current.liquidity < 200:
            reasons.append(f"thin book (${current.liquidity:.0f} resting)")

        return SwingAlert(
            ticker=ticker, ts=current.ts, direction=direction, from_price=ref_sample.mid,
            to_price=current.mid, window_s=int(max(1, current.ts - ref_sample.ts)),
            confidence=confidence, reasons=reasons,
        )

    @staticmethod
    def _sample_at_or_before(history: list[PriceSample], cutoff: float) -> PriceSample | None:
        best = None
        for sample in history:
            if sample.ts <= cutoff:
                best = sample
            else:
                break
        return best

    def history(self, ticker: str) -> list[PriceSample]:
        return list(self._history.get(ticker, []))

    def reset(self, ticker: str | None = None) -> None:
        if ticker is None:
            self._history.clear()
            self._last_alert.clear()
        else:
            self._history.pop(ticker, None)
            self._last_alert.pop(ticker, None)


# --------------------------------------------------------------------------- #
# Selective ranking
# --------------------------------------------------------------------------- #
@dataclass
class ScoringInputs:
    """Everything the score is allowed to look at. All optional values may be None (unknown)."""

    delta: Decimal
    from_price: Decimal
    to_price: Decimal
    best_ask: Decimal | None = None           # cost to buy YES now
    best_bid: Decimal | None = None
    contracts_within_10c: Decimal | None = None
    liquidity_dollars: Decimal | None = None
    volume_24h: Decimal | None = None
    open_interest: Decimal | None = None
    spread: Decimal | None = None
    hours_to_close: float | None = None
    confidence: str = "confirmed"
    fee_dollars: Decimal | None = None        # round-trip fee estimate at current price


SCORE_WEIGHTS = {
    "magnitude": Decimal("0.30"),
    "liquidity": Decimal("0.25"),
    "cost": Decimal("0.20"),
    "horizon": Decimal("0.15"),
    "confirmation": Decimal("0.10"),
}


def _clamp(value: Decimal) -> Decimal:
    return max(ZERO, min(ONE, value))


def score_alert(inputs: ScoringInputs, *, threshold: Decimal = Decimal("0.10")) -> dict:
    """Return {"score", "components", "label", "caveats"}.

    Components are each in [0, 1] and are reported so the UI can explain the
    ranking. The final score is a weighted mean.
    """
    caveats: list[str] = []

    # 1. Magnitude: how far past the $0.10 trigger, saturating at 4x threshold.
    mag = _clamp(inputs.delta.__abs__() / (threshold * 4))
    if mag >= 1:
        caveats.append("swing is 4x the alert threshold")

    # 2. Liquidity: contracts you could actually buy within 10 cents.
    if inputs.contracts_within_10c is None:
        liq = Decimal("0.3")
        caveats.append("depth unknown (orderbook unavailable)")
    else:
        liq = _clamp(inputs.contracts_within_10c / Decimal("500"))
    if inputs.liquidity_dollars is not None and inputs.liquidity_dollars < 500:
        caveats.append("under $500 of resting bids")

    # 3. Cost: spread and fee drag on a round trip.
    cost = Decimal("0.5")
    parts = []
    if inputs.spread is not None:
        parts.append(_clamp(ONE - inputs.spread / Decimal("0.10")))
    if inputs.fee_dollars is not None and inputs.best_ask and inputs.best_ask > 0:
        drag = inputs.fee_dollars / inputs.best_ask      # fee per contract / price per contract
        parts.append(_clamp(ONE - drag / Decimal("0.10")))
        if drag > Decimal("0.05"):
            caveats.append("fees exceed 5% of contract price")
    if parts:
        cost = sum(parts) / Decimal(len(parts))

    # 4. Horizon: a market closing in minutes cannot pay for the round trip.
    if inputs.hours_to_close is None:
        horizon = Decimal("0.5")
    else:
        horizon = _clamp(Decimal(str(inputs.hours_to_close)) / Decimal("24"))

    # 5. Confirmation.
    confirmation = {"confirmed": ONE, "quote-only": Decimal("0.35"),
                    "unconfirmed": ZERO}.get(inputs.confidence, ZERO)

    if inputs.volume_24h is not None and inputs.volume_24h < 10:
        caveats.append("under 10 contracts traded in 24h")

    components = {
        "magnitude": mag.quantize(Decimal("0.001")),
        "liquidity": liq.quantize(Decimal("0.001")),
        "cost": cost.quantize(Decimal("0.001")),
        "horizon": horizon.quantize(Decimal("0.001")),
        "confirmation": confirmation.quantize(Decimal("0.001")),
    }
    score = sum(components[k] * w for k, w in SCORE_WEIGHTS.items())
    score = score.quantize(Decimal("0.001"))

    # Payout multiple: how many dollars a $1 contract returns if it resolves YES.
    payout = Decimal("0")
    if inputs.best_ask is not None and 0 < inputs.best_ask < ONE:
        payout = ((ONE - inputs.best_ask) / inputs.best_ask).quantize(Decimal("0.01"))

    label = "high" if score >= Decimal("0.65") else "medium" if score >= Decimal("0.45") else "low"
    return {
        "score": score,
        "label": label,
        "components": components,
        "weights": {k: str(v) for k, v in SCORE_WEIGHTS.items()},
        "payout_multiple": payout,
        "caveats": caveats,
        "disclaimer": "Heuristic ranking of trade quality, not a probability of profit.",
    }


def explain(score: dict) -> list[str]:
    """Human-readable breakdown for the chat card."""
    out = [f"score {score['score']} ({score['label']})"]
    for key, value in score["components"].items():
        out.append(f"{key} {value} x {score['weights'][key]}")
    if score.get("payout_multiple"):
        out.append(f"pays {score['payout_multiple']}:1 if YES")
    return out


def dedupe(alerts: Iterable[SwingAlert]) -> list[SwingAlert]:
    seen: dict[str, SwingAlert] = {}
    for alert in alerts:
        prev = seen.get(alert.ticker)
        if prev is None or alert.abs_delta > prev.abs_delta:
            seen[alert.ticker] = alert
    return list(seen.values())
