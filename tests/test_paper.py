import pytest

from kalshi_trader.config import Settings
from kalshi_trader.paper import PaperLedger, run_cycle


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        bankroll=1000.0,
        risk_per_trade=0.02,
        max_open_positions=4,
        fee_model="quadratic",
        paper_ledger=tmp_path / "ledger.json",
        data_dir=tmp_path,
        state_dir=tmp_path,
    )


def _market(**overrides):
    base = {
        "ticker": "T-1",
        "topic": "crypto",
        "title": "Test market",
        "price": 0.50,
        "yes_bid": 0.49,
        "yes_ask": 0.51,
        "no_bid": 0.49,
        "no_ask": 0.51,
        "spread": 0.02,
        "volume_24h": 5000.0,
        "open_interest": 1000.0,
        "top_book_contracts": 5000.0,
        "close_time": "2099-01-01T00:00:00Z",
        "result": None,
    }
    base.update(overrides)
    return base


def test_open_position_accounting(settings):
    ledger = PaperLedger(settings)
    position = ledger.open_position(_market(), "momentum", "yes", "test", now=1_700_000_000)
    assert position is not None
    # 2% of $1000 = $20 risk; 20 / 0.51 = 39.2 → 39 whole contracts
    assert position["contracts"] == 39
    assert position["cost"] == round(position["contracts"] * 0.51, 2)
    assert ledger.cash == round(1000 - position["cost"] - position["entry_fee"], 2)
    assert position["entry_fee"] > 0


def test_no_side_uses_implied_no_ask(settings):
    ledger = PaperLedger(settings)
    market = _market(no_ask=None, yes_bid=0.40)
    position = ledger.open_position(market, "fade", "no", "test", now=1_700_000_000)
    assert position["side"] == "no"
    assert position["entry_price"] == 0.6


def test_close_realises_pnl(settings):
    ledger = PaperLedger(settings)
    position = ledger.open_position(_market(), "momentum", "yes", "test", now=1_700_000_000)
    trade = ledger.close_position(position["key"], _market(yes_bid=0.65, price=0.66), 1_700_003_600, "target")
    assert trade["exit_price"] == 0.65
    expected = round(position["contracts"] * 0.65 - position["cost"] - position["entry_fee"] - trade["fees"] + position["entry_fee"], 2)
    # pnl = proceeds - cost - entry_fee - exit_fee
    assert trade["pnl"] == round(position["contracts"] * 0.65 - position["cost"] - position["entry_fee"] - (trade["fees"] - position["entry_fee"]), 2)
    assert trade["pnl"] == round(expected, 2)
    assert ledger.positions == {}


def test_settlement_pays_one_dollar_per_winning_contract(settings):
    ledger = PaperLedger(settings)
    position = ledger.open_position(_market(), "late_favorite", "yes", "test", now=1_700_000_000)
    trade = ledger.close_position(
        position["key"], _market(result="yes"), 1_700_086_400, "settled YES", settle=True
    )
    assert trade["exit_price"] == 1.0
    assert trade["pnl"] == round(position["contracts"] * 1.0 - position["cost"] - position["entry_fee"], 2)
    assert trade["settled_result"] == "yes"


def test_losing_settlement(settings):
    ledger = PaperLedger(settings)
    position = ledger.open_position(_market(), "late_favorite", "yes", "test", now=1_700_000_000)
    trade = ledger.close_position(position["key"], _market(result="no"), 1_700_086_400, "settled NO", settle=True)
    assert trade["exit_price"] == 0.0
    assert trade["pnl"] < 0


def test_position_limit_enforced(settings):
    ledger = PaperLedger(settings)
    for i in range(4):
        assert ledger.open_position(_market(ticker=f"T-{i}"), "momentum", "yes", "test", now=1_700_000_000)
    assert len(ledger.positions) == 4
    assert ledger.open_position(_market(ticker="T-9"), "momentum", "yes", "test", now=1_700_000_000) is None
    assert ledger.state["rejected"][-1]["reason"] == "max open positions reached"


def test_duplicate_position_per_strategy_blocked(settings):
    ledger = PaperLedger(settings)
    assert ledger.open_position(_market(), "momentum", "yes", "a", now=1_700_000_000)
    assert ledger.open_position(_market(), "momentum", "yes", "b", now=1_700_000_001) is None
    assert ledger.open_position(_market(), "fade", "no", "c", now=1_700_000_002) is not None


def test_size_capped_by_visible_liquidity(settings):
    ledger = PaperLedger(settings)
    position = ledger.open_position(_market(top_book_contracts=3), "momentum", "yes", "test", now=1_700_000_000)
    assert position["contracts"] == 3


def test_persistence_roundtrip(settings):
    ledger = PaperLedger(settings)
    ledger.open_position(_market(), "momentum", "yes", "test", now=1_700_000_000)
    ledger.record_equity(1_700_000_000)
    path = ledger.save()
    reloaded = PaperLedger.load(settings, path)
    assert len(reloaded.positions) == 1
    assert reloaded.state["equity"][0][1] > 0


def test_run_cycle_opens_and_marks(settings):
    ledger = PaperLedger(settings)
    market = _market()
    scored = {"T-1": {"score": 0.9, "direction": "yes", "eligible": True}}
    alert = {"ticker": "T-1", "direction": "up", "abs_delta": 0.12}
    result = run_cycle(ledger, [market], scored, [alert], 1_700_000_000)
    assert len(result["opened"]) == 1
    assert result["equity"] > 0


def test_demo_order_body_uses_book_side_and_fixed_point_strings(monkeypatch):
    """Body contract from https://docs.kalshi.com/api-reference/orders/create-order-v2.md
    and the side mapping in https://docs.kalshi.com/getting_started/order_direction.md."""
    from unittest.mock import PropertyMock

    from kalshi_trader.kalshi_demo import DemoAccount

    sent: list[dict] = []

    class FakeClient:
        def create_order(self, **kwargs):
            sent.append(kwargs)
            return {"order_id": "o-1", "fill_count": "0.00", "remaining_count": "10.00"}

    monkeypatch.setattr(DemoAccount, "configured", PropertyMock(return_value=True))
    account = DemoAccount.__new__(DemoAccount)
    account.settings = None
    account._client = FakeClient()
    account.last_error = None

    yes = account.place_order("T-1", "yes", 10, 0.42)
    no = account.place_order("T-1", "no", 5, 0.31)

    assert sent[0]["side"] == "bid" and sent[1]["side"] == "ask"
    assert sent[0]["count"] == "10.00" and sent[1]["count"] == "5.00"
    assert sent[0]["price"] == "0.4200" and sent[1]["price"] == "0.3100"
    # The price sent for a NO order is the no-leg price, which is the outcome price.
    assert yes["remaining_count"] == "10.00" and yes["resting"] is True
    assert no["ok"] is True


def test_pnl_identity_holds_with_entry_fees(tmp_path):
    """realised + unrealised must equal total P&L, and the entry fee is charged exactly once."""
    from kalshi_trader.config import Settings
    from kalshi_trader.paper import PaperLedger

    settings = Settings(data_dir=tmp_path, bankroll=1000.0, risk_per_trade=0.02)
    ledger = PaperLedger(settings)
    market = {
        "ticker": "T-1",
        "topic": "gas",
        "title": "T",
        "yes_bid": 0.40,
        "yes_ask": 0.42,
        "volume_24h": 5000.0,
        "top_book_contracts": 0,
        "close_time": "2099-01-01T00:00:00Z",
    }
    position = ledger.open_position(market, "late_favorite", "yes", "test", 1_700_000_000)
    assert position is not None

    # On entry the position is carried at cost, so the only P&L so far is the fee actually paid.
    first = ledger.snapshot(1_700_000_001)
    assert first["unrealized_pnl"] == round(-position["entry_fee"], 2)
    assert first["total_pnl"] == round(first["realized_pnl"] + first["unrealized_pnl"], 2)
    assert first["cash"] == round(1000.0 - position["cost"] - position["entry_fee"], 2)

    # Once marked at the bid, unrealised is the spread loss plus that same fee — not twice.
    ledger.mark_and_exit({"T-1": dict(market)}, 1_700_000_002)
    marked = ledger.snapshot(1_700_000_003)
    spread_loss = position["contracts"] * (0.40 - 0.42)
    assert marked["unrealized_pnl"] == round(spread_loss - position["entry_fee"], 2)
    assert marked["total_pnl"] == round(marked["realized_pnl"] + marked["unrealized_pnl"], 2)
    assert marked["equity"] == round(marked["cash"] + position["contracts"] * 0.40, 2)
