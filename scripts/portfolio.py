"""
Simulated ("paper") portfolio tracker. Starts from a fixed paper balance
(config.STARTING_PAPER_BALANCE_USD) — this is NOT the user's real Kalshi
demo-account balance, because no account credentials exist in this automated
pipeline (see docs/FLAGGED_FOR_REVIEW.md item 3). Every figure here is
labeled "simulated" in the UI.
"""
from . import config
from .io_utils import utcnow_iso


def new_portfolio():
    return {
        "generated_at": utcnow_iso(),
        "is_simulated": True,
        "starting_balance_usd": config.STARTING_PAPER_BALANCE_USD,
        "cash_usd": config.STARTING_PAPER_BALANCE_USD,
        "open_cost_basis_usd": 0.0,
        "realized_pnl_usd": 0.0,
        "unrealized_pnl_usd": 0.0,
        "equity_usd": config.STARTING_PAPER_BALANCE_USD,
        "open_positions_count": 0,
        "closed_trades_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "by_strategy": {},
        "by_topic": {},
    }


def _bucket(d, key):
    if key not in d:
        d[key] = {
            "open_count": 0, "closed_count": 0, "win_count": 0, "loss_count": 0,
            "realized_pnl_usd": 0.0, "unrealized_pnl_usd": 0.0, "cost_basis_usd": 0.0,
        }
    return d[key]


def recompute_portfolio(trades, price_by_ticker):
    """Recomputes the whole portfolio state from the full trade log each run
    (simple and auditable, rather than carrying forward incremental state that
    could drift)."""
    p = new_portfolio()
    cash = config.STARTING_PAPER_BALANCE_USD
    realized = 0.0
    unrealized = 0.0
    open_cost_basis = 0.0

    for t in trades:
        strat_bucket = _bucket(p["by_strategy"], t["strategy"])
        topic_bucket = _bucket(p["by_topic"], t["topic"])

        if t["status"] == "open":
            cash -= t["cost_basis"]
            open_cost_basis += t["cost_basis"]
            p["open_positions_count"] += 1
            strat_bucket["open_count"] += 1
            topic_bucket["open_count"] += 1

            current_price = price_by_ticker.get(t["ticker"])
            if current_price is not None:
                mark_value = current_price if t["side"] == "yes" else round(1 - current_price, 4)
                mtm = round((mark_value - t["entry_price"]) * t["contracts"], 4)
                unrealized += mtm
                strat_bucket["unrealized_pnl_usd"] = round(strat_bucket["unrealized_pnl_usd"] + mtm, 4)
                topic_bucket["unrealized_pnl_usd"] = round(topic_bucket["unrealized_pnl_usd"] + mtm, 4)
            strat_bucket["cost_basis_usd"] = round(strat_bucket["cost_basis_usd"] + t["cost_basis"], 4)
            topic_bucket["cost_basis_usd"] = round(topic_bucket["cost_basis_usd"] + t["cost_basis"], 4)

        elif t["status"] in ("closed_won", "closed_lost"):
            cash -= t["cost_basis"]
            payout = (t["exit_price"] or 0.0) * t["contracts"]
            cash += payout
            realized += t["pnl"] or 0.0
            p["closed_trades_count"] += 1
            strat_bucket["closed_count"] += 1
            topic_bucket["closed_count"] += 1
            strat_bucket["realized_pnl_usd"] = round(strat_bucket["realized_pnl_usd"] + (t["pnl"] or 0.0), 4)
            topic_bucket["realized_pnl_usd"] = round(topic_bucket["realized_pnl_usd"] + (t["pnl"] or 0.0), 4)
            if t["status"] == "closed_won":
                p["win_count"] += 1
                strat_bucket["win_count"] += 1
                topic_bucket["win_count"] += 1
            else:
                p["loss_count"] += 1
                strat_bucket["loss_count"] += 1
                topic_bucket["loss_count"] += 1

    p["cash_usd"] = round(cash, 2)
    p["open_cost_basis_usd"] = round(open_cost_basis, 2)
    p["realized_pnl_usd"] = round(realized, 2)
    p["unrealized_pnl_usd"] = round(unrealized, 2)
    p["equity_usd"] = round(cash + open_cost_basis + unrealized, 2)
    return p
