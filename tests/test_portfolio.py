from kalshi_trader.portfolio import demo_account_summary, max_drawdown, summarize


def test_max_drawdown():
    curve = [[1, 1000], [2, 1100], [3, 900], [4, 1200], [5, 1000]]
    dollars, pct = max_drawdown(curve)
    assert dollars == 200
    assert pct == round(200 / 1100 * 100, 2)


def test_summarize_groups_and_metrics():
    snapshot = {
        "bankroll_start": 1000,
        "cash": 900,
        "equity": 1050,
        "realized_pnl": 50,
        "unrealized_pnl": 0,
        "total_pnl": 50,
        "roi_pct": 5.0,
        "open_positions": [],
        "fee_model": "quadratic_verified",
        "fee_verified": False,
        "equity_curve": [[1, 1000], [2, 1050]],
        "trades": [
            {"pnl": 30, "fees": 1, "contracts": 10, "strategy": "momentum", "topic": "crypto", "side": "yes", "entry_price": 0.5, "hold_hours": 2, "exit_reason": "target +$0.10 (mark $0.60)"},
            {"pnl": -10, "fees": 1, "contracts": 20, "strategy": "fade", "topic": "golf", "side": "no", "entry_price": 0.9, "hold_hours": 30, "exit_reason": "stop"},
            {"pnl": 5, "fees": 0.5, "contracts": 5, "strategy": "momentum", "topic": "crypto", "side": "yes", "entry_price": 0.2, "hold_hours": 0.5, "exit_reason": "settled YES"},
        ],
    }
    out = summarize(snapshot)
    assert out["summary"]["trades"] == 3
    assert out["summary"]["wins"] == 2
    assert out["summary"]["win_rate_pct"] == 66.7
    assert out["summary"]["fees_paid"] == 2.5
    assert out["summary"]["profit_factor"] == round(35 / 10, 2)
    strategies = {row["label"]: row for row in out["by_strategy"]}
    assert strategies["momentum"]["trades"] == 2
    assert strategies["momentum"]["pnl"] == 35
    bands = {row["label"] for row in out["by_price_band"]}
    assert "$0.50–$0.75" in bands
    assert "$0.10–$0.25" in bands


def test_demo_account_summary_without_data_is_explicit():
    out = demo_account_summary(None, None)
    assert out["connected"] is False
    assert "not estimated" in out["note"]


def test_demo_account_summary_maps_fields():
    balance = {"balance": 12345, "balance_dollars": "123.4500", "portfolio_value": 500, "updated_ts": 1}
    positions = [
        {
            "ticker": "T-1",
            "position_fp": "10.00",
            "market_exposure_dollars": "5.0000",
            "realized_pnl_dollars": "1.0000",
            "fees_paid_dollars": "0.1000",
            "total_traded_dollars": "50.0000",
        }
    ]
    out = demo_account_summary(balance, positions)
    assert out["connected"] is True
    assert out["cash_dollars"] == 123.45
    assert out["portfolio_value_dollars"] == 5.0
    assert out["positions"][0]["position_contracts"] == "10.00"
