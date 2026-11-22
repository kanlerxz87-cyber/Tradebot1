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
