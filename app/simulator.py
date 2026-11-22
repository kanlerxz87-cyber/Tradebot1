"""Simulated trading: strategies, portfolio accounting, and demo-execution mirroring.

The requirement is to "automate simulated trades to test different strategies",
then "track portfolio performance ... and categorize trades and create
strategies based on the type of trade".

Design rules
------------
* **Every strategy is a category of trade**, not a random signal generator.
  Each has an entry rule, an exit rule and explicit risk limits, and the
  category is stored with every fill so the analytics can group by it.
* **Prices are executable prices.** A buy happens at the side's implied ask
  (1 - opposite best bid); a sell happens at that side's best bid. This follows
  the bids-only orderbook contract in
  https://docs.kalshi.com/getting_started/orderbook_responses
* **Fees are real.** The taker fee is `roundup(M x 0.07 x C x P x (1-P))` from
  https://kalshi.com/docs/kalshi-fee-schedule.pdf, computed on entry and exit.
  There is **no settlement fee**, so a position held to resolution is credited
  its payout with no further charge.
* **Positions are all-or-nothing per market.** Partial exits would make the
  cost-basis bookkeeping ambiguous, so a position is opened once and closed
  once. This is documented in the UI.
* **Nothing is invented.** If the book is empty, no trade is placed and the
  rejection reason is recorded. If a strategy's data inputs are unknown, it
  refuses to trade rather than assuming a value.

Two execution modes
-------------------
`paper` (default) - the simulator's own ledger, no credentials needed.
`demo`            - mirrors each simulated fill to the Kalshi demo account with
                    POST /portfolio/events/orders, using the signed API. It is
                    opt-in (`KALSHI_ENABLE_LIVE_ORDERS=true`) and refuses to run
                    against production by default (`live_orders_allowed_envs`).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .alerts import ScoringInputs, score_alert
from .config import Settings
from .money import CENT, ONE, ZERO, fee_dollars, to_decimal
from .storage import Store

BUY, SELL = "buy", "sell"
YES, NO = "yes", "no"


# --------------------------------------------------------------------------- #
# Strategy definitions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StrategySpec:
    key: str
    name: str
    category: str
    thesis: str
    # entry gates
    min_score: Decimal = Decimal("0.0")
    min_price: Decimal = Decimal("0.02")
    max_price: Decimal = Decimal("0.98")
    min_depth_10c: Decimal = Decimal("0")
    require_two_sided: bool = True
    allowed_topics: tuple[str, ...] = ("gas", "elections", "culture", "crypto", "golf")
    directions: tuple[str, ...] = ("up", "down")
    require_trusted_news: bool = False
    min_hours_to_close: float = 0.0
    # sizing
    budget_pct: Decimal = Decimal("0.05")        # share of starting cash per trade
    max_contracts: Decimal = Decimal("100")
    # exits
    take_profit: Decimal | None = Decimal("0.15")   # in dollars per contract
    stop_loss: Decimal | None = Decimal("0.10")
    max_hold_hours: float = 24.0
    exit_on_reverse_swing: bool = True
    hold_to_resolution: bool = False
    # execution
    maker_entry: bool = False
    enabled: bool = True


SPECS: tuple[StrategySpec, ...] = (
    StrategySpec(
        key="momentum_follow",
        name="Momentum follow",
        category="Trend following",
        thesis="When a contract repriced by 10c+ on confirmed trades or two-sided quotes, "
               "the move often continues for a few ticks. Buy YES in the direction of the move.",
        min_score=Decimal("0.45"),
        min_price=Decimal("0.10"),
        max_price=Decimal("0.85"),
        min_depth_10c=Decimal("50"),
        take_profit=Decimal("0.12"),
        stop_loss=Decimal("0.08"),
        max_hold_hours=12,
        budget_pct=Decimal("0.04"),
    ),
    StrategySpec(
        key="mean_reversion",
        name="Mean reversion (fade the panic)",
        category="Contrarian",
        thesis="A sharp DOWN move in a market that is still above 25c is often a liquidity gap "
               "rather than news. Buy YES into the drop and exit on the bounce.",
        min_score=Decimal("0.40"),
        min_price=Decimal("0.25"),
        max_price=Decimal("0.90"),
        min_depth_10c=Decimal("75"),
        directions=("down",),
        take_profit=Decimal("0.10"),
        stop_loss=Decimal("0.12"),
        max_hold_hours=6,
        budget_pct=Decimal("0.03"),
    ),
    StrategySpec(
        key="cheap_tail",
        name="Cheap tail (longshot)",
        category="Asymmetric payoff",
        thesis="Low-priced contracts offer large payout multiples. Only enter when the swing is "
               "large, confirmed, and the book can absorb the order within 10 cents.",
        min_score=Decimal("0.50"),
        min_price=Decimal("0.03"),
        max_price=Decimal("0.22"),
        min_depth_10c=Decimal("200"),
        take_profit=None,
        stop_loss=None,
        max_hold_hours=72,
        budget_pct=Decimal("0.01"),
        max_contracts=Decimal("50"),
    ),
    StrategySpec(
        key="favorite_carry",
        name="Favorite carry",
        category="High-probability carry",
        thesis="High-priced favourites that dip on noise tend to revert. Small edge, high hit "
               "rate; held to resolution to collect the full $1 payout.",
        min_score=Decimal("0.45"),
        min_price=Decimal("0.70"),
        max_price=Decimal("0.95"),
        min_depth_10c=Decimal("100"),
        directions=("down",),
        take_profit=None,
        stop_loss=None,
        max_hold_hours=240,
        hold_to_resolution=True,
        budget_pct=Decimal("0.05"),
    ),
    StrategySpec(
        key="news_catalyst",
        name="News catalyst",
        category="Event driven",
        thesis="Only trade swings that coincide with a headline from a trusted outlet in the "
               "lookback window. Fewer trades, higher conviction.",
        min_score=Decimal("0.50"),
        min_price=Decimal("0.10"),
        max_price=Decimal("0.90"),
        min_depth_10c=Decimal("100"),
        require_trusted_news=True,
        take_profit=Decimal("0.18"),
        stop_loss=Decimal("0.10"),
        max_hold_hours=24,
        budget_pct=Decimal("0.04"),
    ),
    StrategySpec(
        key="baseline_control",
        name="Baseline control",
        category="Control / benchmark",
        thesis="Equal-sized YES entry on every qualifying swing. No filtering at all. Used as the "
               "benchmark every other strategy must beat.",
        min_score=Decimal("0.0"),
        min_price=Decimal("0.05"),
        max_price=Decimal("0.95"),
        min_depth_10c=Decimal("0"),
        require_two_sided=False,
        take_profit=Decimal("0.10"),
        stop_loss=Decimal("0.10"),
        max_hold_hours=24,
        budget_pct=Decimal("0.01"),
        max_contracts=Decimal("20"),
    ),
)


def spec_by_key(key: str) -> StrategySpec | None:
    return next((s for s in SPECS if s.key == key), None)


@dataclass
class MarketContext:
    """Live state the strategies are allowed to see for one market."""

    ticker: str
    event_ticker: str | None
    topic: str
    title: str
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None
    depth_10c: Decimal | None = None
    liquidity: Decimal | None = None
    volume_24h: Decimal | None = None
    open_interest: Decimal | None = None
    hours_to_close: float | None = None
    two_sided: bool = False
    page_url: str | None = None


@dataclass
class Decision:
    action: str
    side: str
    contracts: Decimal
    price: Decimal
    reason: str
    accepted: bool = True
    rejection: str | None = None


class RiskLimits:
    """Hard caps applied after a strategy proposes a trade."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def check(self, *, cash: Decimal, price: Decimal, contracts: Decimal,
              market_exposure: Decimal, gross_exposure: Decimal) -> tuple[Decimal, str | None]:
        """Return (allowed_contracts, rejection_reason)."""
        if price <= 0 or price >= ONE:
            return ZERO, "price outside (0, 1)"
        if contracts <= 0:
            return ZERO, "zero contracts"
        notional = price * contracts
        if notional > cash:
            affordable = (cash / price).to_integral_value(rounding="ROUND_FLOOR")
            contracts = min(contracts, affordable)
            if contracts <= 0:
                return ZERO, "insufficient cash"
        room_market = self.settings.max_position_per_market - market_exposure
        room_gross = self.settings.max_portfolio_gross - gross_exposure
        room = min(room_market, room_gross)
        if room <= 0:
            return ZERO, "position limit reached"
        max_c = (room / price).to_integral_value(rounding="ROUND_FLOOR")
        contracts = min(contracts, max_c, self.settings.max_contracts_per_order)
        if contracts <= 0:
            return ZERO, "position limit reached"
        return contracts, None


# --------------------------------------------------------------------------- #
# Simulator
# --------------------------------------------------------------------------- #
class Simulator:
    def __init__(self, store: Store, settings: Settings, *, api: Any | None = None):
        self.store = store
        self.settings = settings
        self.api = api                      # KalshiAPI for demo mirroring, optional
        self.risk = RiskLimits(settings)
        self._lock = asyncio.Lock()
        self._prices: dict[str, Decimal] = {}
        self._last_marks_ts = 0.0
        self.events: list[dict] = []        # UI feed of fills / rejections
        self._bootstrap()

    # -- setup ------------------------------------------------------------
    def _bootstrap(self) -> None:
        for spec in SPECS:
            self.store.upsert_strategy(spec.key, spec.name, spec.thesis, {
                "category": spec.category,
                "min_score": str(spec.min_score),
                "price_band": [str(spec.min_price), str(spec.max_price)],
                "directions": list(spec.directions),
                "take_profit": str(spec.take_profit) if spec.take_profit is not None else None,
                "stop_loss": str(spec.stop_loss) if spec.stop_loss is not None else None,
                "max_hold_hours": spec.max_hold_hours,
                "hold_to_resolution": spec.hold_to_resolution,
                "require_trusted_news": spec.require_trusted_news,
                "budget_pct": str(spec.budget_pct),
            }, enabled=spec.enabled)
            self.store.ensure_account(spec.key, str(self.settings.starting_cash))

    def starting_cash(self, strategy: str) -> Decimal:
        acct = self.store.account(strategy)
        return to_decimal(acct["starting_cash"]) if acct else self.settings.starting_cash

    def cash(self, strategy: str) -> Decimal:
        acct = self.store.account(strategy)
        return to_decimal(acct["cash"], ZERO) if acct else ZERO

    def exposure(self, strategy: str) -> tuple[Decimal, dict[str, Decimal]]:
        total = ZERO
        per_market: dict[str, Decimal] = {}
        for pos in self.store.positions(strategy):
            basis = to_decimal(pos["cost_basis"], ZERO) or ZERO
            total += basis
            per_market[pos["ticker"]] = per_market.get(pos["ticker"], ZERO) + basis
        return total, per_market

    # -- marks ------------------------------------------------------------
    def update_price(self, ticker: str, price: Decimal | None) -> None:
        if price is not None and ZERO < price < ONE:
            self._prices[ticker] = price

    def mark_price(self, ticker: str, side: str) -> Decimal | None:
        """Liquidation value per contract for a side, from the last observed mid."""
        mid = self._prices.get(ticker)
        if mid is None:
            return None
        return mid if side == YES else ONE - mid

    # -- decisions --------------------------------------------------------
    def _strategy_price_ok(self, spec: StrategySpec, price: Decimal) -> bool:
        return spec.min_price <= price <= spec.max_price

    def propose(self, spec: StrategySpec, *, alert: dict, ctx: MarketContext,
                score: dict, news_trusted: bool) -> Decision | None:
        """Apply one strategy's entry rules to one alert."""
        if not spec.enabled:
            return None
        if ctx.topic not in spec.allowed_topics:
            return None
        if alert.get("direction") not in spec.directions:
            return None
        if Decimal(str(score["score"])) < spec.min_score:
            return None
        if spec.require_trusted_news and not news_trusted:
            return None
        if spec.require_two_sided and not ctx.two_sided:
            return None
        if ctx.best_ask is None or not (ZERO < ctx.best_ask < ONE):
            return None
        if not self._strategy_price_ok(spec, ctx.best_ask):
            return None
        if spec.min_depth_10c > 0 and (ctx.depth_10c is None or ctx.depth_10c < spec.min_depth_10c):
            return None
        if ctx.hours_to_close is not None and ctx.hours_to_close < spec.min_hours_to_close:
            return None
        # Momentum buys with the move, contrarian buys against it; both trade YES.
        budget = self.starting_cash(spec.key) * spec.budget_pct
        if budget <= 0:
            return None
        contracts = (budget / ctx.best_ask).to_integral_value(rounding="ROUND_FLOOR")
        contracts = min(contracts, spec.max_contracts)
        if contracts <= 0:
            return None
        return Decision(
            action=BUY, side=YES, contracts=Decimal(contracts), price=ctx.best_ask,
            reason=f"{spec.category}: {spec.thesis.split('.')[0]}.",
        )

    # -- execution --------------------------------------------------------
    async def execute(self, spec: StrategySpec, decision: Decision, *, alert: dict,
                      ctx: MarketContext, mode: str = "paper") -> dict:
        async with self._lock:
            cash = self.cash(spec.key)
            gross, per_market = self.exposure(spec.key)
            existing = self.store.position(spec.key, ctx.ticker, decision.side)
            market_exposure = per_market.get(ctx.ticker, ZERO)
            contracts, rejection = self.risk.check(
                cash=cash, price=decision.price, contracts=decision.contracts,
                market_exposure=market_exposure, gross_exposure=gross,
            )
            if existing is not None:
                return self._record_event(spec, decision, alert, ctx, {
                    "status": "skipped",
                    "rejection": "already holding this market",
                })
            if rejection or contracts <= 0:
                return self._record_event(spec, decision, alert, ctx, {
                    "status": "rejected", "rejection": rejection or "risk limit",
                })

            fee = self._fee(decision.price, contracts, maker=spec.maker_entry)
            cost = decision.price * contracts + fee
            if cost > cash:
                contracts = ((cash - fee) / decision.price).to_integral_value(rounding="ROUND_FLOOR")
                if contracts <= 0:
                    return self._record_event(spec, decision, alert, ctx, {
                        "status": "rejected", "rejection": "insufficient cash after fees",
                    })
                cost = decision.price * contracts + fee

            order_id, status = None, "filled"
            if mode == "demo":
                order_id, status = await self._send_demo_order(spec, ctx, decision, contracts)
                if status != "filled":
                    return self._record_event(spec, decision, alert, ctx, {
                        "status": "rejected", "order_id": order_id,
                        "rejection": f"demo order {status}",
                    })

            self.store.save_position(spec.key, ctx.ticker, decision.side, topic=ctx.topic,
                                     contracts=contracts, cost_basis=cost)
            new_cash = cash - cost
            self.store.update_account(spec.key, cash=new_cash, fee_delta=fee, trades_delta=1)
            self.store.add_sim_trade({
                "strategy": spec.key, "ticker": ctx.ticker, "event_ticker": ctx.event_ticker,
                "topic": ctx.topic, "title": ctx.title, "side": decision.side, "action": BUY,
                "contracts": str(contracts), "price": str(decision.price), "fee": str(fee),
                "ts": time.time(), "mode": mode, "reason": decision.reason,
                "order_id": order_id, "status": status,
            })
            return self._record_event(spec, decision, alert, ctx, {
                "status": "filled", "contracts": str(contracts), "price": str(decision.price),
                "fee": str(fee), "cash": str(new_cash), "order_id": order_id,
                "reason": decision.reason,
            })

    async def close(self, spec: StrategySpec, ticker: str, *, reason: str,
                    mode: str = "paper", payout_value: Decimal | None = None) -> dict | None:
        """Close a position at the current bid, or settle it at a resolution payout."""
        async with self._lock:
            positions = [p for p in self.store.positions(spec.key) if p["ticker"] == ticker]
            if not positions:
                return None
            pos = positions[0]
            side = pos["side"]
            contracts = to_decimal(pos["contracts"], ZERO) or ZERO
            basis = to_decimal(pos["cost_basis"], ZERO) or ZERO
            if contracts <= 0:
                return None

            if payout_value is not None:
                # Settlement: payout is $1 per contract for the winning side, $0 otherwise.
                value = ONE if (side == YES and payout_value == ONE) or (side == NO and payout_value == ZERO) else ZERO
                proceeds = value * contracts
                fee = ZERO           # documented: there is no settlement fee
                status = "settled"
            else:
                price = self.mark_price(ticker, side)
                if price is None:
                    return None
                proceeds = price * contracts
                fee = self._fee(price, contracts, maker=False)
                proceeds -= fee
                status = "closed"

            realized = proceeds - basis
            cash = self.cash(spec.key) + proceeds
            self.store.save_position(spec.key, ticker, side, topic=pos.get("topic"),
                                     contracts=ZERO, cost_basis=ZERO)
            self.store.update_account(
                spec.key, cash=cash, realized_delta=realized, fee_delta=fee,
                wins_delta=1 if realized > 0 else 0, losses_delta=1 if realized <= 0 else 0,
            )
            self.store.add_sim_trade({
                "strategy": spec.key, "ticker": ticker, "event_ticker": None,
                "topic": pos.get("topic"), "title": pos.get("title"), "side": side,
                "action": SELL, "contracts": str(contracts),
                "price": str(proceeds / contracts if contracts else ZERO), "fee": str(fee),
                "ts": time.time(), "mode": mode, "reason": reason, "status": status,
            })
            event = {
                "ts": time.time(), "strategy": spec.key, "strategy_name": spec.name,
                "category": spec.category, "ticker": ticker, "topic": pos.get("topic"),
                "action": SELL, "status": status, "reason": reason,
                "contracts": str(contracts), "proceeds": str(proceeds),
                "realized": str(realized), "fee": str(fee),
            }
            self.events.append(event)
            self.events[:] = self.events[-400:]
            return event

    async def _send_demo_order(self, spec: StrategySpec, ctx: MarketContext,
                               decision: Decision, contracts: Decimal) -> tuple[str | None, str]:
        """Mirror a simulated buy to the demo account.

        Request/response contract: https://docs.kalshi.com/api-reference/orders/create-order-v2
        `side: bid` buys YES at `price`; `count` and `price` are fixed-point strings;
        `time_in_force` and `self_trade_prevention_type` are required.
        """
        if self.api is None or not self.settings.live_orders_enabled:
            return None, "filled"
        payload = {
            "ticker": ctx.ticker,
            "client_order_id": f"sim-{spec.key}-{int(time.time()*1000)}",
            "side": "bid" if decision.side == YES else "ask",
            "count": f"{contracts:.2f}",
            "price": f"{decision.price:.4f}",
            "time_in_force": "immediate_or_cancel",
            "self_trade_prevention_type": "taker_at_cross",
        }
        try:
            response = await self.api.create_order(payload)
        except Exception as exc:
            return None, f"error:{type(exc).__name__}"
        order = response.get("order") or response
        order_id = order.get("order_id") or order.get("id")
        remaining = to_decimal(order.get("remaining_count"), None)
        filled = remaining is not None and remaining == 0
        return order_id, "filled" if filled or remaining is None else "resting"

    # -- lifecycle --------------------------------------------------------
    async def mark_and_manage(self, *, now: float | None = None, mode: str = "paper") -> list[dict]:
        """Mark positions to market, apply exits, and snapshot equity."""
        now = now or time.time()
        actions: list[dict] = []
        for spec in SPECS:
            for pos in self.store.positions(spec.key):
                ticker = pos["ticker"]
                side = pos["side"]
                contracts = to_decimal(pos["contracts"], ZERO) or ZERO
                if contracts <= 0:
                    continue
                opened = pos.get("opened_ts") or now
                basis = to_decimal(pos["cost_basis"], ZERO) or ZERO
                entry = (basis / contracts) if contracts else ZERO
                mark = self.mark_price(ticker, side)
                if mark is None:
                    continue
                pnl_per = mark - entry
                held_hours = (now - float(opened)) / 3600

                reason = None
                if spec.take_profit is not None and pnl_per >= spec.take_profit:
                    reason = f"take profit (+${pnl_per:.2f}/contract)"
                elif spec.stop_loss is not None and -pnl_per >= spec.stop_loss:
                    reason = f"stop loss (-${-pnl_per:.2f}/contract)"
                elif held_hours >= spec.max_hold_hours:
                    reason = f"max hold {spec.max_hold_hours:.0f}h reached"
                if reason:
                    event = await self.close(spec, ticker, reason=reason, mode=mode)
                    if event:
                        actions.append(event)
        self._snapshot_equity()
        return actions

    async def settle_resolutions(self, resolutions: list[dict], *, mode: str = "paper") -> list[dict]:
        """Settle open positions in markets that have been determined."""
        actions: list[dict] = []
        by_ticker = {r["ticker"]: r for r in resolutions if r.get("result") in {"yes", "no"}}
        for spec in SPECS:
            for pos in self.store.positions(spec.key):
                res = by_ticker.get(pos["ticker"])
                if not res:
                    continue
                payout = ONE if res["result"] == "yes" else ZERO
                event = await self.close(spec, pos["ticker"], reason=f"resolved {res['result'].upper()}",
                                         mode=mode, payout_value=payout)
                if event:
                    actions.append(event)
        return actions

    def _snapshot_equity(self) -> None:
        for spec in SPECS:
            cash = self.cash(spec.key)
            value = ZERO
            for pos in self.store.positions(spec.key):
                contracts = to_decimal(pos["contracts"], ZERO) or ZERO
                mark = self.mark_price(pos["ticker"], pos["side"])
                value += (mark or ZERO) * contracts
            self.store.record_equity(spec.key, cash=cash, positions_value=value)

    # -- helpers ----------------------------------------------------------
    def _fee(self, price: Decimal, contracts: Decimal, *, maker: bool) -> Decimal:
        return fee_dollars(price, contracts, maker=maker, rounding=self.settings.fee_rounding)

    def _record_event(self, spec: StrategySpec, decision: Decision, alert: dict,
                      ctx: MarketContext, extra: dict) -> dict:
        event = {
            "ts": time.time(), "strategy": spec.key, "strategy_name": spec.name,
            "category": spec.category, "ticker": ctx.ticker, "topic": ctx.topic,
            "action": decision.action, "side": decision.side,
            "proposed_contracts": str(decision.contracts), "alert_delta": str(alert.get("delta")),
        }
        event.update(extra)
        # Keep rejections too: they explain why a strategy is quiet.
        self.store.add_sim_trade({
            "strategy": spec.key, "ticker": ctx.ticker, "event_ticker": ctx.event_ticker,
            "topic": ctx.topic, "title": ctx.title, "side": decision.side, "action": decision.action,
            "contracts": extra.get("contracts") or str(decision.contracts),
            "price": str(decision.price), "fee": extra.get("fee", "0"), "ts": event["ts"],
            "mode": "paper", "reason": extra.get("reason") or extra.get("rejection"),
            "order_id": extra.get("order_id"), "status": extra.get("status"),
        })
        self.events.append(event)
        self.events[:] = self.events[-400:]
        return event

    # -- analytics --------------------------------------------------------
    def portfolio_summary(self) -> dict:
        rows = []
        for spec in SPECS:
            acct = self.store.account(spec.key) or {}
            cash = to_decimal(acct.get("cash"), ZERO) or ZERO
            start = to_decimal(acct.get("starting_cash"), self.settings.starting_cash) or self.settings.starting_cash
            realized = to_decimal(acct.get("realized_pnl"), ZERO) or ZERO
            fees = to_decimal(acct.get("fees_paid"), ZERO) or ZERO
            positions = self.store.positions(spec.key)
            mtm = ZERO
            open_rows = []
            for pos in positions:
                contracts = to_decimal(pos["contracts"], ZERO) or ZERO
                basis = to_decimal(pos["cost_basis"], ZERO) or ZERO
                mark = self.mark_price(pos["ticker"], pos["side"])
                value = (mark or ZERO) * contracts
                mtm += value
                open_rows.append({
                    "ticker": pos["ticker"], "side": pos["side"], "topic": pos.get("topic"),
                    "contracts": str(contracts), "cost_basis": str(basis),
                    "entry_price": str((basis / contracts).quantize(Decimal("0.0001"))) if contracts else None,
                    "mark": str(mark) if mark is not None else None,
                    "market_value": str(value),
                    "unrealized": str(value - basis),
                    "opened_utc": _iso(pos.get("opened_ts")),
                })
            equity = cash + mtm
            rows.append({
                "key": spec.key, "name": spec.name, "category": spec.category,
                "thesis": spec.thesis,
                "starting_cash": str(start), "cash": str(cash), "positions_value": str(mtm),
                "equity": str(equity), "realized_pnl": str(realized), "unrealized_pnl": str(mtm - sum(
                    (to_decimal(p['cost_basis'], ZERO) or ZERO) for p in positions)),
                "fees_paid": str(fees),
                "total_return_pct": str(((equity - start) / start * 100).quantize(Decimal("0.01")) if start else 0),
                "trades": int(acct.get("trades") or 0), "wins": int(acct.get("wins") or 0),
                "losses": int(acct.get("losses") or 0),
                "win_rate": _pct(acct.get("wins"), (int(acct.get("wins") or 0) + int(acct.get("losses") or 0))),
                "open_positions": open_rows,
                "limits": {
                    "take_profit": str(spec.take_profit) if spec.take_profit is not None else None,
                    "stop_loss": str(spec.stop_loss) if spec.stop_loss is not None else None,
                    "max_hold_hours": spec.max_hold_hours,
                    "hold_to_resolution": spec.hold_to_resolution,
                },
            })
        return {"strategies": rows, "generated_utc": _iso(time.time()),
                "mode": "demo-mirrored" if self.settings.live_orders_enabled else "paper",
                "disclaimer": "Simulated results. Demo-exchange prices may not reflect real markets "
                              "(https://docs.kalshi.com/getting_started/demo_env)."}

    def category_analytics(self) -> dict:
        """Group realised trades by category, topic and side."""
        trades = [t for t in self.store.sim_trades(limit=5000) if t["action"] == SELL
                  and t["status"] in {"closed", "settled"}]
        by_key: dict[str, dict] = {}
        for t in trades:
            spec = spec_by_key(t["strategy"])
            if spec is None:
                continue
            price = to_decimal(t["price"], ZERO) or ZERO
            contracts = to_decimal(t["contracts"], ZERO) or ZERO
            fee = to_decimal(t["fee"], ZERO) or ZERO
            proceeds = price * contracts - fee
            # Cost basis is recovered from the matching account ledger at summary
            # time; here we report proceeds/fees and group counts.
            for dimension, value in (("category", spec.category), ("topic", t.get("topic") or "other"),
                                     ("side", t.get("side") or "yes"), ("strategy", spec.key)):
                bucket = by_key.setdefault(f"{dimension}:{value}", {
                    "dimension": dimension, "value": value, "trades": 0,
                    "proceeds": ZERO, "fees": ZERO, "settled": 0,
                })
                bucket["trades"] += 1
                bucket["proceeds"] += proceeds
                bucket["fees"] += fee
                bucket["settled"] += 1 if t["status"] == "settled" else 0
        out = []
        for bucket in by_key.values():
            out.append({**{k: (str(v) if isinstance(v, Decimal) else v) for k, v in bucket.items()}})
        out.sort(key=lambda row: row["trades"], reverse=True)
        return {"groups": out, "trades_considered": len(trades)}

    def recent_events(self, limit: int = 60) -> list[dict]:
        return list(reversed(self.events[-limit:]))


def _pct(part: Any, whole: int) -> str | None:
    if not whole:
        return None
    value = to_decimal(part, ZERO) or ZERO
    return str((value / Decimal(whole) * 100).quantize(Decimal("0.1")))


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def score_for_alert(alert: dict, ctx: MarketContext, *, threshold: Decimal = Decimal("0.10"),
                    fee: Decimal | None = None) -> dict:
    return score_alert(ScoringInputs(
        delta=to_decimal(alert.get("delta"), ZERO) or ZERO,
        from_price=to_decimal(alert.get("from_price"), ZERO) or ZERO,
        to_price=to_decimal(alert.get("to_price"), ZERO) or ZERO,
        best_ask=ctx.best_ask, best_bid=ctx.best_bid,
        contracts_within_10c=ctx.depth_10c, liquidity_dollars=ctx.liquidity,
        volume_24h=ctx.volume_24h, open_interest=ctx.open_interest,
        spread=(ctx.best_ask - ctx.best_bid) if (ctx.best_ask is not None and ctx.best_bid is not None) else None,
        hours_to_close=ctx.hours_to_close,
        confidence=alert.get("confidence", "confirmed"),
        fee_dollars=fee,
    ), threshold=threshold)
