"""Simulated ("paper") trading engine.

Accounting rules — deliberately conservative and simple:

* Every position is a **long cash-secured** position in YES or NO contracts, bought at the
  current ask. Nothing is shorted and no leverage is used, so the maximum loss per position
  is its premium plus fees.
* Buying NO at price ``p`` is modelled as paying ``1 − yes_bid`` (the implied NO ask), which
  is exactly how Kalshi's bid-only book works
  (https://docs.kalshi.com/getting_started/orderbook_responses).
* Fees follow :mod:`kalshi_trader.fees` (verified against Kalshi's fee schedule) and are
  charged on entry *and*
  exit; settlement itself is fee-free.
* Settlement pays ``$1.00`` per winning contract and ``$0.00`` per losing contract
  (https://docs.kalshi.com/getting_started/market_settlement).
* Fills are capped by the visible top-of-book size when Kalshi reports one, so the simulation
  cannot pretend to buy more contracts than were displayed.
* Contract counts are integers — Kalshi supports fractional contracts, but rounding down is
  the conservative choice.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import fees as fee_mod
from . import model as model_mod
from . import strategies as strat_mod
from .config import Settings

STATE_VERSION = 1


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ask_price(market: dict[str, Any], side: str) -> float | None:
    if side == "yes":
        price = market.get("yes_ask")
        if price is None and market.get("no_bid") is not None:
            price = round(1.0 - float(market["no_bid"]), 4)
    else:
        price = market.get("no_ask")
        if price is None and market.get("yes_bid") is not None:
            price = round(1.0 - float(market["yes_bid"]), 4)
    try:
        return round(float(price), 4) if price is not None else None
    except (TypeError, ValueError):
        return None


def _mark_price(market: dict[str, Any], side: str, fallback: float) -> float:
    if side == "yes":
        value = market.get("yes_bid")
    else:
        value = market.get("no_bid")
    if value is None:
        value = market.get("price", fallback)
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return fallback


class PaperLedger:
    """Autonomous simulated book persisted as JSON (committed by CI each cycle)."""

    def __init__(self, settings: Settings, state: dict[str, Any] | None = None) -> None:
        self.settings = settings
        self.state = state or self._fresh_state()

    # ------------------------------------------------------------------ state
    def _fresh_state(self) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "bankroll_start": round(self.settings.bankroll, 2),
            "cash": round(self.settings.bankroll, 2),
            "fee_model": fee_mod.model_label(self.settings.fee_model),
            "positions": {},
            "trades": [],
            "equity": [],
            "rejected": [],
            "counters": {"trade_seq": 0},
        }

    @classmethod
    def load(cls, settings: Settings, path: Path | None = None) -> "PaperLedger":
        path = path or settings.paper_ledger
        if path.exists():
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                if state.get("version") == STATE_VERSION:
                    return cls(settings, state)
            except (json.JSONDecodeError, OSError):
                pass
        return cls(settings)

    def save(self, path: Path | None = None) -> Path:
        path = path or self.settings.paper_ledger
        path.parent.mkdir(parents=True, exist_ok=True)
        self.state["updated_at"] = _now_iso()
        # Keep the ledger label in sync with the current fee model so a verified model is not
        # reported as unverified in an old ledger.
        self.state["fee_model"] = fee_mod.model_label(self.settings.fee_model)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1, sort_keys=False), encoding="utf-8")
        tmp.replace(path)
        return path

    # ------------------------------------------------------------- accounting
    @property
    def cash(self) -> float:
        return float(self.state["cash"])

    @property
    def positions(self) -> dict[str, dict[str, Any]]:
        return self.state["positions"]

    def _outlays(self) -> float:
        """Premium plus entry fees still tied up in open positions."""
        return sum(float(pos["cost"]) + float(pos.get("entry_fee") or 0.0) for pos in self.positions.values())

    def _equity_at_cost(self) -> float:
        """Equity with open positions valued at cost (no mark): realised + unrealised = total."""
        return round(self.cash + self._outlays(), 2)

    def _equity(self, marks: dict[str, float] | None = None) -> float:
        value = self.cash
        for pos in self.positions.values():
            mark = (marks or {}).get(pos["ticker"], pos.get("last_mark", pos["entry_price"]))
            value += pos["contracts"] * float(mark)
        return round(value, 2)

    def _record_rejection(self, ticker: str, strategy: str, reason: str, ts: int) -> None:
        bucket = self.state.setdefault("rejected", [])
        bucket.append({"ts": ts, "ticker": ticker, "strategy": strategy, "reason": reason})
        del bucket[:-200]

    # ------------------------------------------------------------------- open
    def open_position(
        self,
        market: dict[str, Any],
        strategy_id: str,
        side: str,
        reason: str,
        now: int,
        *,
        model_score: float | None = None,
    ) -> dict[str, Any] | None:
        key = f"{market.get('ticker')}:{strategy_id}"
        if key in self.positions:
            return None
        if len(self.positions) >= self.settings.max_open_positions:
            self._record_rejection(market.get("ticker", ""), strategy_id, "max open positions reached", now)
            return None

        price = _ask_price(market, side)
        if price is None or price <= 0 or price >= 1:
            self._record_rejection(market.get("ticker", ""), strategy_id, "no tradable ask", now)
            return None

        equity = self._equity()
        risk = max(0.0, equity) * self.settings.risk_per_trade
        if risk < price:
            self._record_rejection(market.get("ticker", ""), strategy_id, "risk budget below one contract", now)
            return None

        contracts = int(risk // price)
        visible = market.get("top_book_contracts") or 0
        if visible and visible > 0:
            contracts = min(contracts, int(visible))
        if contracts < 1:
            self._record_rejection(market.get("ticker", ""), strategy_id, "size rounded to zero", now)
            return None

        cost = round(contracts * price, 2)
        multiplier = fee_mod.series_multiplier(market.get("series_ticker"), "taker")
        fee = fee_mod.taker_fee(
            contracts, price, self.settings.fee_model, multiplier=multiplier
        )
        if cost + fee > self.cash:
            affordable = int(self.cash // (price + 0.01)) if price else 0
            contracts = max(0, min(contracts, affordable))
            if contracts < 1:
                self._record_rejection(market.get("ticker", ""), strategy_id, "insufficient cash", now)
                return None
            cost = round(contracts * price, 2)
            fee = fee_mod.taker_fee(
                contracts, price, self.settings.fee_model, multiplier=multiplier
            )

        strategy = strat_mod.STRATEGIES[strategy_id]
        position = {
            "id": f"pos-{uuid.uuid4().hex[:10]}",
            "key": key,
            "ticker": market.get("ticker"),
            "topic": market.get("topic"),
            "title": market.get("title"),
            "series_ticker": market.get("series_ticker"),
            "strategy": strategy_id,
            "strategy_name": strategy.name,
            "side": side,
            "contracts": contracts,
            "entry_price": price,
            "entry_ts": now,
            "entry_iso": _now_iso(),
            "cost": cost,
            "entry_fee": fee,
            "target_move": strategy.target_move,
            "stop_move": strategy.stop_move,
            "timeout_hours": strategy.timeout_hours,
            "hold_to_resolution": strategy.hold_to_resolution,
            "reason": reason,
            "model_score": model_score,
            "last_mark": price,
            "api_url": market.get("api_url"),
            "series_page_url": market.get("series_page_url"),
        }
        self.state["cash"] = round(self.cash - cost - fee, 2)
        self.positions[key] = position
        self.state["counters"]["trade_seq"] += 1
        return position

    # ------------------------------------------------------------------ close
    def close_position(
        self,
        key: str,
        market: dict[str, Any] | None,
        now: int,
        reason: str,
        *,
        settle: bool = False,
    ) -> dict[str, Any] | None:
        position = self.positions.get(key)
        if position is None:
            return None
        side = position["side"]
        contracts = position["contracts"]

        if settle:
            result = (market or {}).get("result")
            if result not in {"yes", "no"}:
                return None
            exit_price = 1.0 if result == side else 0.0
            fee = 0.0
        else:
            if market is None:
                return None
            exit_price = _mark_price(market, side, position["entry_price"])
            # The published series multiplier applies to the exit fill too.
            fee = fee_mod.taker_fee(
                contracts,
                exit_price,
                self.settings.fee_model,
                multiplier=fee_mod.series_multiplier(position.get("series_ticker"), "taker"),
            )
            if exit_price <= 0:
                fee = 0.0  # nothing to sell into at $0

        proceeds = round(contracts * exit_price, 2)
        cost = float(position["cost"])
        entry_fee = float(position["entry_fee"])
        pnl = round(proceeds - cost - entry_fee - fee, 2)
        hold_h = round((now - int(position["entry_ts"])) / 3600.0, 2)
        trade = {
            "id": position["id"],
            "ticker": position["ticker"],
            "topic": position["topic"],
            "title": position["title"],
            "series_ticker": position.get("series_ticker"),
            "strategy": position["strategy"],
            "strategy_name": position.get("strategy_name"),
            "side": side,
            "contracts": contracts,
            "entry_price": position["entry_price"],
            "exit_price": round(exit_price, 4),
            "entry_ts": position["entry_ts"],
            "exit_ts": now,
            "entry_iso": position.get("entry_iso"),
            "exit_iso": _now_iso(),
            "cost": round(cost, 2),
            "proceeds": proceeds,
            "fees": round(entry_fee + fee, 2),
            "pnl": pnl,
            "roi_pct": round((pnl / cost) * 100.0, 2) if cost else 0.0,
            "hold_hours": hold_h,
            "exit_reason": reason,
            "settled_result": (market or {}).get("result") if settle else None,
            "model_score": position.get("model_score"),
            "api_url": position.get("api_url"),
            "series_page_url": position.get("series_page_url"),
            "fee_model": self.state.get("fee_model"),
        }
        self.state["cash"] = round(self.cash + proceeds - fee, 2)
        del self.positions[key]
        trades = self.state.setdefault("trades", [])
        trades.append(trade)
        if len(trades) > self.settings.max_trades:
            del trades[: len(trades) - self.settings.max_trades]
        return trade

    # ------------------------------------------------------------------ cycle
    def mark_and_exit(self, markets: dict[str, dict[str, Any]], now: int) -> list[dict[str, Any]]:
        """Mark open positions to market and close anything that hit a rule."""
        closed: list[dict[str, Any]] = []
        for key in list(self.positions):
            position = self.positions[key]
            market = markets.get(position["ticker"])
            if market is None:
                continue
            position["last_mark"] = _mark_price(market, position["side"], position["entry_price"])
            position["last_mark_ts"] = now

            # Settlement always wins over price rules.
            if market.get("result") in {"yes", "no"}:
                trade = self.close_position(key, market, now, f"settled {market['result'].upper()}", settle=True)
                if trade:
                    closed.append(trade)
                continue

            reason = strat_mod.exit_reason(position, market, now)
            if reason:
                trade = self.close_position(key, market, now, reason)
                if trade:
                    closed.append(trade)
        return closed

    def record_equity(self, now: int) -> float:
        equity = self._equity()
        curve = self.state.setdefault("equity", [])
        if curve and curve[-1][0] == now:
            curve[-1] = [now, equity]
        else:
            curve.append([now, equity])
        # Keep ~30 days at 15-minute cadence, then thin out.
        if len(curve) > 3000:
            thinned = curve[-3000:]
            self.state["equity"] = thinned[::2] if len(thinned) > 2500 else thinned
        return equity

    # --------------------------------------------------------------- snapshot
    def snapshot(self, now: int | None = None) -> dict[str, Any]:
        now = now or int(time.time())
        equity = self._equity()
        start = float(self.state["bankroll_start"])
        realized = round(sum(t["pnl"] for t in self.state.get("trades", [])), 2)
        # Unrealised is marked to market: equity (cash + marked positions) less cash less what the
        # positions cost, where the cost includes the entry fee that was already paid out of cash.
        # That makes realised + unrealised reconcile to equity - bankroll, which the tests assert.
        unrealized = round(equity - self.cash - self._outlays(), 2) if self.positions else 0.0
        return {
            "updated_ts": now,
            "updated_iso": _now_iso(),
            "bankroll_start": start,
            "cash": round(self.cash, 2),
            "equity": equity,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": round(equity - start, 2),
            "roi_pct": round(((equity - start) / start) * 100.0, 2) if start else 0.0,
            "open_positions": sorted(
                self.positions.values(), key=lambda p: p["entry_ts"], reverse=True
            ),
            "trades": list(reversed(self.state.get("trades", [])))[:200],
            "equity_curve": self.state.get("equity", [])[-600:],
            "fee_model": fee_mod.model_label(self.state.get("fee_model") or "quadratic"),
            "fee_verified": fee_mod.VERIFIED,
            "rejected": list(reversed(self.state.get("rejected", [])))[:40],
        }


def run_cycle(
    ledger: PaperLedger,
    markets: Iterable[dict[str, Any]],
    scored: dict[str, dict[str, Any]],
    alerts: list[dict[str, Any]],
    now: int,
) -> dict[str, Any]:
    """One autonomous decision cycle.

    Order of operations: settle/exit existing positions, then open new ones from alerts and
    standing rules, then record the equity point.
    """
    market_list = list(markets)
    by_ticker = {m["ticker"]: m for m in market_list if m.get("ticker")}

    closed = ledger.mark_and_exit(by_ticker, now)
    opened: list[dict[str, Any]] = []

    # 1. Alert-driven entries (highest priority).
    alert_by_ticker = {a["ticker"]: a for a in alerts if a.get("ticker")}
    for ticker, alert in alert_by_ticker.items():
        market = by_ticker.get(ticker)
        if market is None:
            continue
        model = scored.get(ticker) or model_mod.score_market(market, [], now)
        for candidate in strat_mod.entry_candidates(
            market, model, now, from_alert=alert
        ):
            position = ledger.open_position(
                market,
                candidate["strategy"],
                candidate["side"],
                candidate["reason"],
                now,
                model_score=model.get("score"),
            )
            if position:
                opened.append(position)
                break  # one new position per market per cycle

    # 2. Standing (non-alert) rules, best-scored first.
    for market in sorted(
        market_list, key=lambda m: (scored.get(m["ticker"], {}).get("score") or 0), reverse=True
    ):
        if len(ledger.positions) >= ledger.settings.max_open_positions:
            break
        model = scored.get(market["ticker"]) or model_mod.score_market(market, [], now)
        candidates = [
            c for c in strat_mod.entry_candidates(market, model, now) if c["strategy"] not in {"momentum", "fade"}
        ]
        for candidate in candidates:
            position = ledger.open_position(
                market,
                candidate["strategy"],
                candidate["side"],
                candidate["reason"],
                now,
                model_score=model.get("score"),
            )
            if position:
                opened.append(position)
                break

    equity = ledger.record_equity(now)
    return {"opened": opened, "closed": closed, "equity": equity}
