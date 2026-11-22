"""Strategy registry for the autonomous simulated book.

Each strategy is a small, auditable rule set — no machine learning, no hidden parameters.
Every parameter appears in the dict returned by :func:`describe`, which the site renders so
the reader can see exactly what is being tested.

Only two of the four strategies react to swing alerts; the other two trade the standing
book. That keeps the alert chats and the simulated book decoupled enough to compare.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import model as model_mod


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    thesis: str
    alert_driven: bool
    target_move: float | None
    stop_move: float | None
    timeout_hours: float | None
    hold_to_resolution: bool
    params: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "thesis": self.thesis,
            "alert_driven": self.alert_driven,
            "target_move": self.target_move,
            "stop_move": self.stop_move,
            "timeout_hours": self.timeout_hours,
            "hold_to_resolution": self.hold_to_resolution,
            "params": self.params,
        }


STRATEGIES: dict[str, Strategy] = {
    "momentum": Strategy(
        id="momentum",
        name="Momentum continuation",
        thesis=(
            "A $0.10+ move on a liquid, tight book tends to continue briefly. Buy the side "
            "that just moved, exit on +$0.10, stop on −$0.10, or after 24h."
        ),
        alert_driven=True,
        target_move=0.10,
        stop_move=0.10,
        timeout_hours=24,
        hold_to_resolution=False,
        params={"min_model_score": model_mod.PICK_MIN_SCORE, "max_spread": 0.06, "min_volume_24h": 250},
    ),
    "fade": Strategy(
        id="fade",
        name="Swing fade",
        thesis=(
            "Large single-cycle moves in thin books often partially retrace. Take the "
            "opposite side of the alert, target +$0.08, stop −$0.12, or after 6h."
        ),
        alert_driven=True,
        target_move=0.08,
        stop_move=0.12,
        timeout_hours=6,
        hold_to_resolution=False,
        params={"min_model_score": 0.30, "max_spread": 0.08, "min_volume_24h": 100},
    ),
    "late_favorite": Strategy(
        id="late_favorite",
        name="Late favourite, hold to settlement",
        thesis=(
            "Contracts already priced 0.85–0.96 with real volume are usually near-certain; "
            "the residual premium is small but the hit rate has historically been high. "
            "Hold to resolution."
        ),
        alert_driven=False,
        target_move=None,
        stop_move=0.15,
        timeout_hours=None,
        hold_to_resolution=True,
        params={"min_price": 0.85, "max_price": 0.96, "min_volume_24h": 500, "max_hours_to_close": 168},
    ),
    "cheap_upside": Strategy(
        id="cheap_upside",
        name="Cheap upside",
        thesis=(
            "Long-dated, heavily traded contracts priced 0.03–0.10 are cheap lottery tickets; "
            "sizing is held to the same fixed fraction so a run of losses cannot wipe the "
            "book. Hold to resolution."
        ),
        alert_driven=False,
        target_move=None,
        stop_move=None,
        timeout_hours=None,
        hold_to_resolution=True,
        params={"min_price": 0.03, "max_price": 0.10, "min_volume_24h": 1000, "max_hours_to_close": 720},
    ),
}

#: Bang-bang control: a never-trading book, used as the benchmark baseline.
STYLE_BENCHMARK = {
    "id": "cash",
    "name": "Cash benchmark",
    "thesis": "Holds cash. Any strategy that cannot beat this is not adding value.",
}


def hours_to_close(market: dict[str, Any], now: int) -> float | None:
    ts = model_mod._parse_ts(market)  # noqa: SLF001 - deliberate reuse of the shared parser
    if ts is None:
        return None
    return (ts - now) / 3600.0


def entry_candidates(
    market: dict[str, Any],
    scored: dict[str, Any],
    now: int,
    *,
    from_alert: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return every (strategy, side, rationale) a market qualifies for right now."""
    out: list[dict[str, Any]] = []
    price = float(market.get("price") or 0.0)
    spread = float(market.get("spread") or 0.0)
    volume = float(market.get("volume_24h") or 0.0)
    hours = hours_to_close(market, now)
    model_score = float(scored.get("score") or 0.0)

    # --- alert-driven -----------------------------------------------------
    if from_alert is not None and scored.get("direction"):
        side = scored["direction"]
        alert_side = "yes" if from_alert.get("direction") == "up" else "no"

        p = STRATEGIES["momentum"].params
        if (
            side == alert_side
            and model_score >= p["min_model_score"]
            and spread <= p["max_spread"]
            and volume >= p["min_volume_24h"]
        ):
            out.append(
                {
                    "strategy": "momentum",
                    "side": side,
                    "reason": (
                        f"alert {from_alert.get('direction')} ${from_alert.get('abs_delta'):.2f}; "
                        f"model score {model_score:.2f} >= {p['min_model_score']}; spread ${spread:.2f}"
                    ),
                }
            )

        p = STRATEGIES["fade"].params
        if (
            side != alert_side
            and model_score >= p["min_model_score"]
            and spread <= p["max_spread"]
            and volume >= p["min_volume_24h"]
        ):
            out.append(
                {
                    "strategy": "fade",
                    "side": side,
                    "reason": (
                        f"fading {from_alert.get('direction')} ${from_alert.get('abs_delta'):.2f}; "
                        f"model score {model_score:.2f}; spread ${spread:.2f}"
                    ),
                }
            )

    # --- standing rules ---------------------------------------------------
    lf = STRATEGIES["late_favorite"].params
    if (
        lf["min_price"] <= price <= lf["max_price"]
        and volume >= lf["min_volume_24h"]
        and hours is not None
        and 0 < hours <= lf["max_hours_to_close"]
    ):
        out.append(
            {
                "strategy": "late_favorite",
                "side": "yes",
                "reason": (
                    f"price ${price:.2f} in [{lf['min_price']}, {lf['max_price']}], "
                    f"24h volume {volume:,.0f}, closes in {hours:.1f}h"
                ),
            }
        )

    cu = STRATEGIES["cheap_upside"].params
    if (
        cu["min_price"] <= price <= cu["max_price"]
        and volume >= cu["min_volume_24h"]
        and hours is not None
        and 0 < hours <= cu["max_hours_to_close"]
    ):
        out.append(
            {
                "strategy": "cheap_upside",
                "side": "yes",
                "reason": (
                    f"price ${price:.2f} in [{cu['min_price']}, {cu['max_price']}], "
                    f"24h volume {volume:,.0f}, closes in {hours:.1f}h"
                ),
            }
        )
    return out


def exit_reason(position: dict[str, Any], market: dict[str, Any], now: int) -> str | None:
    """Decide whether an open position should be closed at the current mark."""
    strategy = STRATEGIES.get(position.get("strategy", ""))
    if strategy is None:
        return None
    side = position["side"]
    entry = float(position["entry_price"])
    if side == "yes":
        mark = market.get("yes_bid")
        mark = float(mark) if mark is not None else float(market.get("price") or entry)
    else:
        mark = market.get("no_bid")
        if mark is None:
            yes_ask = market.get("yes_ask")
            mark = (1.0 - float(yes_ask)) if yes_ask is not None else float(market.get("price") or entry)
        mark = float(mark)

    move = mark - entry
    if strategy.target_move and move >= strategy.target_move - 1e-9:
        return f"target +${strategy.target_move:.2f} (mark ${mark:.2f})"
    if strategy.stop_move and move <= -strategy.stop_move + 1e-9:
        return f"stop −${strategy.stop_move:.2f} (mark ${mark:.2f})"
    if strategy.timeout_hours is not None:
        held_h = (now - int(position["entry_ts"])) / 3600.0
        if held_h >= strategy.timeout_hours:
            return f"timeout after {strategy.timeout_hours:.0f}h (mark ${mark:.2f})"
    return None
