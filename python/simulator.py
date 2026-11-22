"""Paper-trading simulator (mirrors site/assets/app.js logic).

Strategies: momentum (follow >=$0.10 jump), meanrev (fade it),
favorite (buy Yes > $0.60), longshot (buy Yes < $0.40).
Settles at $1.00/contract on the winning side. Pure stdlib.
"""
from dataclasses import dataclass, field

ALERT_THRESHOLD = 0.10


@dataclass
class Position:
    ticker: str
    topic: str
    side: str
    contracts: int
    fill: float
    strategy: str
    status: str = "open"
    result: str = ""
    pnl: float = 0.0

    @property
    def cost(self):
        return self.fill * self.contracts


@dataclass
class PaperPortfolio:
    bankroll: float = 1000.0
    contracts_per_trade: int = 10
    cash: float = field(init=False)
    positions: list = field(default_factory=list)

    def __post_init__(self):
        self.cash = self.bankroll

    def on_alert(self, ticker, topic, delta, price, strategies):
        if abs(delta) < ALERT_THRESHOLD:
            return None
        preferred = "momentum" if delta > 0 else "meanrev"
        other = "meanrev" if preferred == "momentum" else "momentum"
        strat = preferred if strategies.get(preferred, False) else (other if strategies.get(other, False) else None)
        if strat is None:
            return None
        side = ("yes" if delta > 0 else "no") if strat == "momentum" else ("no" if delta > 0 else "yes")
        fill = price if side == "yes" else 1 - price
        cost = fill * self.contracts_per_trade
        if self.cash < cost:
            return None
        self.cash -= cost
        pos = Position(ticker, topic, side, self.contracts_per_trade, fill, strat)
        self.positions.append(pos)
        return pos

    def settle(self, ticker, result):
        for p in self.positions:
            if p.ticker == ticker and p.status == "open":
                p.status = "closed"
                p.result = result
                payout = p.contracts * 1.0 if p.side == result else 0.0
                p.pnl = payout - p.cost
                self.cash += payout

    def realized_pnl(self):
        return sum(p.pnl for p in self.positions if p.status == "closed")

    def category_pnl(self):
        cats = {}
        for p in self.positions:
            if p.status != "closed":
                continue
            k = f"{p.topic} x {p.strategy}"
            cats.setdefault(k, {"n": 0, "pnl": 0.0})
            cats[k]["n"] += 1
            cats[k]["pnl"] += p.pnl
        return cats
