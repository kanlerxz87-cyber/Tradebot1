"""Performance analytics for the simulated book (and the demo account when connected).

Every metric is computed from the recorded trade ledger, so the site can show the arithmetic
behind it. No metric is estimated or extrapolated.
"""

from __future__ import annotations

from typing import Any, Iterable

PRICE_BANDS = ((0.0, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 0.90), (0.90, 1.0))
HOLD_BUCKETS = ((0.0, 1.0), (1.0, 6.0), (6.0, 24.0), (24.0, 72.0), (72.0, 1e9))


def _band(price: float) -> str:
    for low, high in PRICE_BANDS:
        if low <= price < high:
            return f"${low:.2f}–${high:.2f}"
    return f"${price:.2f}"


def _hold_bucket(hours: float) -> str:
    for low, high in HOLD_BUCKETS:
        if low <= hours < high:
            return f"{low:g}–{high:g}h" if high < 1e8 else f">{low:g}h"
    return "n/a"


def max_drawdown(curve: Iterable[Iterable[float]]) -> tuple[float, float]:
    """Return (max drawdown in dollars, max drawdown in percent)."""
    peak = None
    worst_abs = 0.0
    worst_pct = 0.0
    for point in curve or []:
        try:
            equity = float(point[1])
        except (TypeError, IndexError, ValueError):
            continue
        peak = equity if peak is None else max(peak, equity)
        if peak and peak > 0:
            dd = peak - equity
            if dd > worst_abs:
                worst_abs = dd
                worst_pct = (dd / peak) * 100.0
    return round(worst_abs, 2), round(worst_pct, 2)


def _group(trades: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for trade in trades:
        key = key_fn(trade) or "unknown"
        bucket = buckets.setdefault(
            key,
            {"label": key, "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "fees": 0.0, "contracts": 0.0, "roi_sum": 0.0},
        )
        bucket["trades"] += 1
        bucket["pnl"] += float(trade.get("pnl") or 0.0)
        bucket["fees"] += float(trade.get("fees") or 0.0)
        bucket["contracts"] += float(trade.get("contracts") or 0.0)
        bucket["roi_sum"] += float(trade.get("roi_pct") or 0.0)
        if float(trade.get("pnl") or 0.0) > 0:
            bucket["wins"] += 1
        elif float(trade.get("pnl") or 0.0) < 0:
            bucket["losses"] += 1
    rows: list[dict[str, Any]] = []
    for bucket in buckets.values():
        bucket["pnl"] = round(bucket["pnl"], 2)
        bucket["fees"] = round(bucket["fees"], 2)
        bucket["win_rate_pct"] = round(bucket["wins"] / bucket["trades"] * 100.0, 1) if bucket["trades"] else 0.0
        bucket["avg_roi_pct"] = round(bucket["roi_sum"] / bucket["trades"], 2) if bucket["trades"] else 0.0
        bucket.pop("roi_sum", None)
        rows.append(bucket)
    rows.sort(key=lambda r: r["pnl"], reverse=True)
    return rows


def summarize(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compute the performance block rendered on the portfolio page."""
    trades: list[dict[str, Any]] = list(snapshot.get("trades") or [])
    wins = [t for t in trades if float(t.get("pnl") or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0) < 0]
    gross_win = sum(float(t["pnl"]) for t in wins)
    gross_loss = abs(sum(float(t["pnl"]) for t in losses))
    fees_paid = sum(float(t.get("fees") or 0) for t in trades)
    dd_abs, dd_pct = max_drawdown(snapshot.get("equity_curve") or [])

    summary = {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "flat": len(trades) - len(wins) - len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100.0, 1) if trades else 0.0,
        "gross_win": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "expectancy": round(sum(float(t["pnl"]) for t in trades) / len(trades), 2) if trades else 0.0,
        "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "fees_paid": round(fees_paid, 2),
        "avg_hold_hours": round(sum(float(t.get("hold_hours") or 0) for t in trades) / len(trades), 2) if trades else 0.0,
        "max_drawdown": dd_abs,
        "max_drawdown_pct": dd_pct,
        "best_trade": max(trades, key=lambda t: float(t.get("pnl") or 0)) if trades else None,
        "worst_trade": min(trades, key=lambda t: float(t.get("pnl") or 0)) if trades else None,
    }

    return {
        "headline": {
            "bankroll_start": snapshot.get("bankroll_start"),
            "cash": snapshot.get("cash"),
            "equity": snapshot.get("equity"),
            "realized_pnl": snapshot.get("realized_pnl"),
            "unrealized_pnl": snapshot.get("unrealized_pnl"),
            "total_pnl": snapshot.get("total_pnl"),
            "roi_pct": snapshot.get("roi_pct"),
            "open_positions": len(snapshot.get("open_positions") or []),
            "fee_model": snapshot.get("fee_model"),
            "fee_verified": snapshot.get("fee_verified"),
        },
        "summary": summary,
        "by_strategy": _group(trades, lambda t: t.get("strategy")),
        "by_topic": _group(trades, lambda t: t.get("topic")),
        "by_side": _group(trades, lambda t: (t.get("side") or "").upper()),
        "by_price_band": _group(trades, lambda t: _band(float(t.get("entry_price") or 0))),
        "by_hold_time": _group(trades, lambda t: _hold_bucket(float(t.get("hold_hours") or 0))),
        "by_exit_reason": _group(trades, lambda t: (t.get("exit_reason") or "").split("(")[0].strip() or "unknown"),
    }


def demo_account_summary(balance: dict[str, Any] | None, positions: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Normalise a demo-account read (fields verified in the API reference)."""
    if not balance:
        return {
            "connected": False,
            "note": "No demo credentials configured — demo account figures are unavailable and are not estimated.",
        }
    try:
        cash = float(balance.get("balance_dollars") or (int(balance.get("balance") or 0) / 100.0))
    except (TypeError, ValueError):
        cash = 0.0
    try:
        portfolio_value = float(balance.get("portfolio_value") or 0) / 100.0
    except (TypeError, ValueError):
        portfolio_value = 0.0
    rows = []
    for position in positions or []:
        rows.append(
            {
                "ticker": position.get("ticker"),
                "position_contracts": position.get("position_fp"),
                "exposure": position.get("market_exposure_dollars"),
                "realized_pnl": position.get("realized_pnl_dollars"),
                "fees_paid": position.get("fees_paid_dollars"),
                "total_traded": position.get("total_traded_dollars"),
            }
        )
    return {
        "connected": True,
        "cash_dollars": round(cash, 2),
        "portfolio_value_dollars": round(portfolio_value, 2),
        "positions": rows,
        "updated_ts": balance.get("updated_ts"),
    }
