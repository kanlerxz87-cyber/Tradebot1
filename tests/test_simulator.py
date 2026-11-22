"""Simulated trading: risk limits, fee accounting, settlement, and analytics."""

import asyncio
from decimal import Decimal

import pytest

from app.config import Settings
from app.simulator import BUY, SELL, YES, MarketContext, Simulator, spec_by_key
from app.storage import Store


@pytest.fixture()
def sim(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    settings = Settings(starting_cash=Decimal("10000"), db_path=str(tmp_path / "state.sqlite3"))
    yield Simulator(store, settings), store
    store.close()


def context(**kwargs):
    base = dict(ticker="TEST-1", event_ticker="TEST", topic="crypto", title="Test market",
                best_bid=Decimal("0.44"), best_ask=Decimal("0.46"), depth_10c=Decimal("500"),
                liquidity=Decimal("9000"), volume_24h=Decimal("500"), hours_to_close=48.0,
                two_sided=True)
    base.update(kwargs)
    return MarketContext(**base)


def alert(direction="up", delta="0.15", confidence="confirmed", score="0.70"):
    return {"direction": direction, "delta": delta, "from_price": "0.30", "to_price": "0.45",
            "confidence": confidence, "score": score, "score_detail": {"score": score}}


def test_every_strategy_has_a_distinct_category_and_account(sim):
    simulator, store = sim
    strategies = store.list_strategies()
    assert len(strategies) >= 6
    categories = {s["params"]["category"] for s in strategies}
    assert len(categories) == len(strategies), "each strategy must be its own trade category"
    for s in strategies:
        acct = store.account(s["key"])
        assert acct is not None
        assert Decimal(acct["starting_cash"]) == Decimal("10000")


def test_propose_respects_direction_price_band_and_depth(sim):
    simulator, _ = sim
    momentum = spec_by_key("momentum_follow")
    assert momentum is not None

    ok = simulator.propose(momentum, alert=alert(), ctx=context(), score={"score": "0.70"},
                           news_trusted=False)
    assert ok is not None and ok.action == BUY and ok.side == YES

    # mean_reversion only fades DOWN moves
    mean_rev = spec_by_key("mean_reversion")
    assert simulator.propose(mean_rev, alert=alert(direction="up"), ctx=context(),
                             score={"score": "0.70"}, news_trusted=False) is None
    # cheap_tail refuses a 46c market
    cheap = spec_by_key("cheap_tail")
    assert simulator.propose(cheap, alert=alert(), ctx=context(), score={"score": "0.70"},
                             news_trusted=False) is None
    # news_catalyst requires a trusted headline
    news = spec_by_key("news_catalyst")
    assert simulator.propose(news, alert=alert(), ctx=context(), score={"score": "0.70"},
                             news_trusted=False) is None
    assert simulator.propose(news, alert=alert(), ctx=context(), score={"score": "0.70"},
                             news_trusted=True) is not None


def test_execute_debits_cash_including_fees_and_records_trade(sim):
    simulator, store = sim
    momentum = spec_by_key("momentum_follow")
    decision = simulator.propose(momentum, alert=alert(), ctx=context(),
                                 score={"score": "0.70"}, news_trusted=False)
    assert decision is not None

    event = asyncio.run(simulator.execute(momentum, decision, alert=alert(), ctx=context()))
    assert event["status"] == "filled"
    contracts = Decimal(event["contracts"])
    fee = Decimal(event["fee"])
    cash = simulator.cash(momentum.key)

    assert Decimal(event["price"]) == Decimal("0.46")
    assert fee > 0
    assert cash == Decimal("10000") - Decimal("0.46") * contracts - fee
    assert store.sim_trades(strategy=momentum.key)[0]["action"] == BUY


def test_no_duplicate_position_in_the_same_market(sim):
    simulator, _ = sim
    momentum = spec_by_key("momentum_follow")
    decision = simulator.propose(momentum, alert=alert(), ctx=context(), score={"score": "0.70"},
                                 news_trusted=False)
    asyncio.run(simulator.execute(momentum, decision, alert=alert(), ctx=context()))
    again = asyncio.run(simulator.execute(momentum, decision, alert=alert(), ctx=context()))
    assert again["status"] == "skipped"


def test_position_limit_caps_size(sim):
    simulator, _ = sim
    momentum = spec_by_key("momentum_follow")
    ctx = context()
    decision = simulator.propose(momentum, alert=alert(), ctx=ctx, score={"score": "0.70"},
                                 news_trusted=False)
    decision.contracts = Decimal("100000")     # force an oversized order
    event = asyncio.run(simulator.execute(momentum, decision, alert=alert(), ctx=ctx))
    assert event["status"] == "filled"
    notional = Decimal(event["contracts"]) * Decimal("0.46")
    assert notional <= simulator.settings.max_position_per_market


def test_settlement_pays_one_dollar_and_charges_no_fee(sim):
    simulator, store = sim
    momentum = spec_by_key("momentum_follow")
    decision = simulator.propose(momentum, alert=alert(), ctx=context(), score={"score": "0.70"},
                                 news_trusted=False)
    opened = asyncio.run(simulator.execute(momentum, decision, alert=alert(), ctx=context()))
    contracts = Decimal(opened["contracts"])
    cash_before = simulator.cash(momentum.key)

    event = asyncio.run(simulator.close(momentum, "TEST-1", reason="resolved YES",
                                        payout_value=Decimal("1")))
    assert event is not None and event["status"] == "settled"
    assert Decimal(event["fee"]) == Decimal("0")
    assert simulator.cash(momentum.key) == cash_before + contracts
    acct = store.account(momentum.key)
    assert int(acct["wins"]) == 1


def test_loss_resolution_pays_nothing(sim):
    simulator, _ = sim
    momentum = spec_by_key("momentum_follow")
    decision = simulator.propose(momentum, alert=alert(), ctx=context(), score={"score": "0.70"},
                                 news_trusted=False)
    asyncio.run(simulator.execute(momentum, decision, alert=alert(), ctx=context()))
    cash_before = simulator.cash(momentum.key)
    event = asyncio.run(simulator.close(momentum, "TEST-1", reason="resolved NO",
                                        payout_value=Decimal("0")))
    assert Decimal(event["proceeds"]) == Decimal("0")
    assert simulator.cash(momentum.key) == cash_before


def test_take_profit_closes_the_position(sim):
    simulator, store = sim
    momentum = spec_by_key("momentum_follow")
    decision = simulator.propose(momentum, alert=alert(), ctx=context(), score={"score": "0.70"},
                                 news_trusted=False)
    asyncio.run(simulator.execute(momentum, decision, alert=alert(), ctx=context()))
    simulator.update_price("TEST-1", Decimal("0.70"))     # +24c vs 46c entry
    actions = asyncio.run(simulator.mark_and_manage())
    assert actions, "take profit should have closed the position"
    assert "take profit" in actions[0]["reason"]
    assert store.positions(momentum.key) == []


def test_missing_mark_prevents_invented_pnl(sim):
    simulator, _ = sim
    momentum = spec_by_key("momentum_follow")
    decision = simulator.propose(momentum, alert=alert(), ctx=context(), score={"score": "0.70"},
                                 news_trusted=False)
    asyncio.run(simulator.execute(momentum, decision, alert=alert(), ctx=context()))
    summary = simulator.portfolio_summary()
    row = next(r for r in summary["strategies"] if r["key"] == momentum.key)
    # No price update was ever applied, so the open position must be marked at
    # zero rather than at a guessed price.
    assert row["open_positions"][0]["mark"] is None
    assert Decimal(row["positions_value"]) == Decimal("0")


def test_category_analytics_groups_realised_trades(sim):
    simulator, _ = sim
    momentum = spec_by_key("momentum_follow")
    decision = simulator.propose(momentum, alert=alert(), ctx=context(), score={"score": "0.70"},
                                 news_trusted=False)
    asyncio.run(simulator.execute(momentum, decision, alert=alert(), ctx=context()))
    asyncio.run(simulator.close(momentum, "TEST-1", reason="resolved YES",
                                payout_value=Decimal("1")))
    analytics = simulator.category_analytics()
    dims = {g["dimension"] for g in analytics["groups"]}
    assert {"category", "topic", "side", "strategy"} <= dims
    assert analytics["trades_considered"] == 1
