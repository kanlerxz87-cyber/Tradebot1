"""Transparent, unvalidated hypotheses; hypothetical cash is NOT a demo account."""

from decimal import Decimal, ROUND_DOWN
from uuid import uuid4

from .domain import D, ONE, OrderBook, decimal
from .store import Store

STRATEGIES = ("mean_reversion", "momentum")


def screen(alert: dict, history: list[dict], market: dict, book: OrderBook | None,
           now_ms: int) -> dict | None:
    if market.get("status") != "active" or book is None or not book.valid:
        return None
    if book.observed_ms is None or not 0 <= now_ms - book.observed_ms <= 10_000:
        return None
    if not 0 <= now_ms - market.get("price_observed_ms", 0) <= 10_000:
        return None
    # Strictly earlier observations only: no lookahead in fair-value hypotheses.
    prior = [decimal(point["price_dollars"]) for point in history
             if alert["timestamp_ms"] - 900_000 <= point["timestamp_ms"] < alert["timestamp_ms"]]
    prior = [price for price in prior if price is not None]
    if len(prior) < 20 or not book.yes or not book.no:
        return None
    best_bid, best_ask = max(book.yes), book.asks("yes")[0][0]
    spread = best_ask - best_bid
    if spread < 0 or spread > D("0.04"):
        return None
    current = decimal(alert["to_price"])
    hypotheses = {
        "mean_reversion": sum(prior[-60:], D(0)) / len(prior[-60:]),
        "momentum": max(D("0.01"), min(D("0.99"), current + (current - prior[-20]) / 2)),
    }
    candidates = []
    for strategy, yes_fair in hypotheses.items():
        for outcome, fair in (("yes", yes_fair), ("no", ONE - yes_fair)):
            asks = book.asks(outcome)
            if not asks:
                continue
            price, size = asks[0]
            if price <= 0 or price >= 1 or size < 10:
                continue
            edge, roi = fair - price, (fair - price) / price
            if edge >= D("0.03") and roi >= D("0.05"):
                candidates.append({
                    "strategy": strategy, "outcome": outcome,
                    "estimated_fair_value": str(fair.quantize(D("0.0001"))),
                    "entry_ask": str(price), "available_at_ask": str(size),
                    "gross_edge_dollars": str(edge.quantize(D("0.0001"))),
                    "hypothetical_gross_roi": str(roi.quantize(D("0.0001"))),
                    "net_roi": None, "fees": None, "prior_observations": len(prior),
                    "label": "Unvalidated research hypothesis — pre-fee, not expected or guaranteed profit",
                    "source_url": market["source_url"], "book_source_url": book.source,
                })
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: D(candidate["gross_edge_dollars"]))


class PaperEngine:
    """Independent long-only hypothetical accounts, with source-linked fill ledgers."""
    def __init__(self, store: Store):
        self.store = store
        self.state = store.get("paper", "state", None) or {
            "mode": "hypothetical_paper_not_demo_account",
            "assumptions": {
                "starting_cash_per_strategy": "1000.00",
                "starting_cash_status": "explicit simulation assumption, not a Kalshi balance",
                "fees": None, "net_performance": None,
                "fill_model": "consume current opposite-bid depth; no queue/fill guarantee",
                "liquidity_model": "strategies are independent counterfactual accounts",
            },
            "accounts": {name: {"cash": "1000.00", "realized_gross_pnl": "0", "positions": [],
                                "trades": [], "settlements": []} for name in STRATEGIES},
        }
        # Within a book observation, don't reuse depth for another fill in the same account.
        self.consumed: dict[tuple, Decimal] = {}

    def save(self):
        self.store.put("paper", "state", self.state)

    def buy(self, strategy: str, market: dict, outcome: str, requested_count: Decimal,
            limit_price: Decimal, book: OrderBook, now_ms: int, trigger_id: str) -> dict | None:
        if strategy not in STRATEGIES or outcome not in {"yes", "no"}:
            raise ValueError("Unknown strategy or outcome")
        if requested_count <= 0 or limit_price <= 0 or limit_price >= 1:
            return None
        if (market.get("status") != "active" or not market.get("event_ticker")
                or decimal(market.get("notional_value_dollars")) != ONE):
            return None
        if market.get("settlement_bounds_type") not in {None, "", "default"}:
            return None
        if not book.valid or book.observed_ms is None or not 0 <= now_ms - book.observed_ms <= 10_000:
            return None
        account = self.state["accounts"][strategy]
        if any(trade["trigger_id"] == trigger_id for trade in account["trades"]):
            return None
        if any(position["ticker"] == market["ticker"] and position["status"] == "open"
               for position in account["positions"]):
            return None
        # At most $20 per event/strategy. No leverage, no synthetic fills beyond visible depth.
        cash = D(account["cash"])
        event_exposure = sum((D(position["cost"]) for position in account["positions"]
                              if position["event_ticker"] == market["event_ticker"]
                              and position["status"] == "open"), D(0))
        budget = min(cash, max(D(0), D("20") - event_exposure))
        remaining, fills = requested_count, []
        for price, available in book.asks(outcome):
            if price > limit_price or price <= 0 or remaining <= 0:
                break
            key = (strategy, market["ticker"], outcome, book.observed_ms, price)
            available = max(D(0), available - self.consumed.get(key, D(0)))
            take = min(available, remaining, budget / price).quantize(D("0.01"), rounding=ROUND_DOWN)
            if take <= 0:
                continue
            cost = take * price
            fills.append({"price": str(price), "count": str(take), "cost": str(cost),
                          "source_url": book.source})
            self.consumed[key] = self.consumed.get(key, D(0)) + take
            remaining -= take
            budget -= cost
        if not fills:
            return None
        quantity = sum((D(fill["count"]) for fill in fills), D(0))
        cost = sum((D(fill["cost"]) for fill in fills), D(0))
        trade = {
            "id": str(uuid4()), "ticker": market["ticker"], "event_ticker": market.get("event_ticker"),
            "topic": market["topic"], "strategy": strategy, "outcome": outcome,
            "count": str(quantity), "requested_count": str(requested_count),
            "cost": str(cost), "average_price": str(cost / quantity),
            "fees": None, "fills": fills, "timestamp_ms": now_ms,
            "source_url": market["source_url"], "trigger_id": trigger_id,
            "execution": "hypothetical_depth_fill_not_exchange_execution",
        }
        account["cash"] = str(cash - cost)
        account["trades"].append(trade)
        account["positions"].append({**trade, "status": "open", "result": None,
                                     "payout": None, "realized_gross_pnl": None})
        self.save()
        # Bound scratch memory; positions/trades remain persisted.
        self.consumed = {key: value for key, value in self.consumed.items() if key[3] >= now_ms - 60_000}
        return trade

    def on_alert(self, alert: dict, market: dict, book: OrderBook | None, now_ms: int):
        model = alert.get("model")
        if not model or not book:
            return
        self.buy(model["strategy"], market, model["outcome"], D("10"),
                 D(model["entry_ask"]), book, now_ms, alert["id"])

    def settle(self, market: dict):
        # Only finalized binary $1 contracts. determined/disputed/scalar are not settlement.
        if market.get("status") != "finalized" or market.get("result") not in {"yes", "no"}:
            return
        if decimal(market.get("notional_value_dollars")) != ONE:
            return
        if market.get("settlement_bounds_type") not in {None, "", "default"}:
            return
        result = market["result"]
        reported = decimal(market.get("settlement_value_dollars"))
        expected_yes = ONE if result == "yes" else D(0)
        if reported is not None and reported != expected_yes:
            return
        changed = False
        for account in self.state["accounts"].values():
            for position in account["positions"]:
                if position["ticker"] != market["ticker"] or position["status"] != "open":
                    continue
                payout = D(position["count"]) if position["outcome"] == result else D(0)
                profit = payout - D(position["cost"])
                position.update(status="settled", result=result, payout=str(payout),
                                realized_gross_pnl=str(profit), settlement_ts=market.get("settlement_ts"),
                                settlement_source_url=market["source_url"])
                account["cash"] = str(D(account["cash"]) + payout)
                account["realized_gross_pnl"] = str(D(account["realized_gross_pnl"]) + profit)
                account["settlements"].append({
                    "position_id": position["id"], "ticker": market["ticker"], "topic": position["topic"],
                    "result": result, "payout": str(payout), "realized_gross_pnl": str(profit),
                    "timestamp": market.get("settlement_ts"), "source_url": market["source_url"],
                })
                changed = True
        if changed:
            self.save()

    def summary(self, markets: dict[str, dict], now_ms: int) -> dict:
        accounts = {}
        for name, account in self.state["accounts"].items():
            marks, positions = [], []
            for position in account["positions"]:
                row = {**position, "unrealized_gross_pnl": None,
                       "gross_pnl": position["realized_gross_pnl"]}
                positions.append(row)
                if position["status"] != "open":
                    continue
                market = markets.get(position["ticker"], {})
                # A fresh last trade does not make an old bid fresh. Quote and trade
                # clocks are separate; mark to bid only in the valid quote window.
                bid = decimal(market.get(f"{position['outcome']}_bid_dollars"), D(0), ONE)
                quote_age = now_ms - (market.get("quote_observed_ms") or 0)
                if bid is None or not 0 <= quote_age <= 45_000:
                    marks.append(None)
                else:
                    mark = bid * D(position["count"])
                    marks.append(mark)
                    row["unrealized_gross_pnl"] = str(mark - D(position["cost"]))
                    row["gross_pnl"] = row["unrealized_gross_pnl"]
            marked = sum(marks, D(0)) if all(mark is not None for mark in marks) else None
            settled = [p for p in account["positions"] if p["status"] == "settled"]
            wins = sum(D(p["realized_gross_pnl"]) > 0 for p in settled)
            by_topic = {}
            for position in settled:
                topic = position["topic"]
                by_topic[topic] = str(D(by_topic.get(topic, "0")) + D(position["realized_gross_pnl"]))
            accounts[name] = {
                **account, "positions": positions,
                "marked_position_value": str(marked) if marked is not None else None,
                "gross_equity": str(D(account["cash"]) + marked) if marked is not None else None,
                "win_rate": str(D(wins) / len(settled)) if settled else None,
                "settled_trades": len(settled), "gross_pnl_by_topic": by_topic,
                "net_roi": None, "fee_status": "unverified; gross-only accounting",
            }
        return {**self.state, "accounts": accounts}
