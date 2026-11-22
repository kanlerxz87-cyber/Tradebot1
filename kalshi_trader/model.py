"""Heuristic ROI model behind the "high-ROI" alert chat.

IMPORTANT — what this is and is not
-----------------------------------
This is a transparent, hand-built scoring function. It is **not** a validated alpha model and
it makes no claim of predictive accuracy. Its only job is to rank swing alerts so the second
chat is quieter than the first. Every score is fully decomposable: each component, its input
and the resulting contribution are stored with the pick and rendered on the site, so a trader
can see exactly why something was promoted.

The score is in ``[0, 1]`` and combines:

===================  ======  ==============================================================
Component            Weight  Meaning
===================  ======  ==============================================================
momentum              0.40   size of the recent move (10-min, else 1-hour window)
liquidity             0.20   log-scaled 24h contract volume
open interest         0.15   log-scaled open interest
price band            0.10   1 at $0.50, falling towards the tails
time to close         0.15   prefers 1h–72h; penalises <15min and >7d
spread penalty       −0.20   wide books are expensive to cross
===================  ======  ==============================================================

``roi_pct_est`` is a *heuristic* return estimate: the score scaled by the observed move and
divided by the entry price, i.e. "if a move of this size repeated, what percentage of the
premium would it be worth". It is explicitly labelled as an estimate everywhere it appears.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

WEIGHTS = {
    "momentum": 0.40,
    "liquidity": 0.20,
    "open_interest": 0.15,
    "band": 0.10,
    "time": 0.15,
    "spread": -0.20,
}

PICK_MIN_SCORE = 0.45
PICK_MIN_ROI_PCT = 6.0
PICK_MAX_SPREAD = 0.06
PICK_MIN_VOLUME_24H = 100.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _parse_ts(market: dict[str, Any]) -> float | None:
    raw = market.get("close_time") or market.get("expected_expiration_time")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _points(history: Iterable[Sequence[Any]] | None) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for point in history or []:
        try:
            ts = int(point[0])
            price = float(point[1])
        except (TypeError, ValueError, IndexError):
            continue
        out.append((ts, price))
    out.sort(key=lambda p: p[0])
    return out


def momentum(points: list[tuple[int, float]], now: int, window_s: int) -> tuple[float, int]:
    """Return (price change over the window, number of points used)."""
    if len(points) < 2:
        return 0.0, 0
    current = points[-1][1]
    cutoff = now - window_s
    reference = None
    for ts, price in points:
        if ts >= cutoff:
            reference = price
            break
    if reference is None:
        reference = points[0][1]
    return round(current - reference, 4), len(points)


def score_market(
    market: dict[str, Any],
    history: Iterable[Sequence[Any]] | None,
    now: int,
) -> dict[str, Any]:
    """Score one market and explain the result."""
    points = _points(history)
    price = float(market.get("price") or 0.0)

    m10, used = momentum(points, now, 600)
    m1h, _ = momentum(points, now, 3600)
    recent = m10 if abs(m10) >= 0.01 else m1h
    if abs(recent) < 0.005 and market.get("previous") is not None:
        recent = round(price - float(market["previous"]), 4)

    volume_24h = float(market.get("volume_24h") or 0.0)
    open_interest = float(market.get("open_interest") or 0.0)
    spread = market.get("spread")
    spread = float(spread) if spread is not None else 0.02

    mom_component = _clamp(abs(recent) / 0.20)
    liq_component = _clamp(math.log10(1.0 + volume_24h) / 4.0)
    oi_component = _clamp(math.log10(1.0 + open_interest) / 5.0)
    band_component = 1.0 - _clamp(abs(price - 0.5) / 0.5)
    spread_component = _clamp(spread / 0.10)

    close_ts = _parse_ts(market)
    hours = (close_ts - now) / 3600.0 if close_ts else None
    if hours is None:
        time_component = 0.5
    elif hours < 0.25:
        time_component = 0.0
    elif hours <= 72:
        time_component = 1.0
    elif hours <= 168:
        time_component = 0.6
    else:
        time_component = 0.3

    contributions = {
        "momentum": WEIGHTS["momentum"] * mom_component,
        "liquidity": WEIGHTS["liquidity"] * liq_component,
        "open_interest": WEIGHTS["open_interest"] * oi_component,
        "band": WEIGHTS["band"] * band_component,
        "time": WEIGHTS["time"] * time_component,
        "spread": WEIGHTS["spread"] * spread_component,
    }
    score = round(_clamp(sum(contributions.values())), 4)

    move = abs(recent)
    roi_pct = round(score * (min(0.30, move + 0.04) / max(price, 0.05)) * 100.0, 2)
    direction = None
    if recent > 0.005:
        direction = "yes"
    elif recent < -0.005:
        direction = "no"

    reasons = [
        (
            f"move {recent:+.2f} over the lookback ({used} price points)"
            if used
            else "no earlier price points yet — first observation of this market"
        ),
        f"24h volume {volume_24h:,.0f} contracts",
        f"open interest {open_interest:,.0f}",
        f"book spread ${spread:.2f}",
        f"time to close {'n/a' if hours is None else f'{hours:.1f}h'}",
    ]

    eligible = (
        direction is not None
        and score >= PICK_MIN_SCORE
        and roi_pct >= PICK_MIN_ROI_PCT
        and spread <= PICK_MAX_SPREAD
        and volume_24h >= PICK_MIN_VOLUME_24H
    )

    return {
        "score": score,
        "roi_pct_est": roi_pct,
        "direction": direction,
        "recent_move": recent,
        "components": {k: round(v, 4) for k, v in contributions.items()},
        "inputs": {
            "price": price,
            "volume_24h": volume_24h,
            "open_interest": open_interest,
            "spread": spread,
            "hours_to_close": round(hours, 2) if hours is not None else None,
        },
        "reasons": reasons,
        "eligible": eligible,
        "model_version": "heuristic-v1",
    }


def pick_from_alert(alert: dict[str, Any], scored: dict[str, Any]) -> dict[str, Any]:
    """Attach a model verdict to an alert for the high-ROI chat."""
    return {
        **alert,
        "model": {
            "score": scored["score"],
            "roi_pct_est": scored["roi_pct_est"],
            "direction": scored["direction"],
            "components": scored["components"],
            "reasons": scored["reasons"],
            "model_version": scored["model_version"],
            "note": "heuristic score, not a validated forecast",
        },
    }


def rank(markets: list[dict[str, Any]], history: dict[str, Any], now: int) -> list[dict[str, Any]]:
    """Score and sort markets, best first."""
    scored: list[dict[str, Any]] = []
    for market in markets:
        result = score_market(market, history.get(market.get("ticker", ""), []), now)
        scored.append({**market, "model": result})
    scored.sort(key=lambda m: (m["model"]["eligible"], m["model"]["score"]), reverse=True)
    return scored
