"""Strict 5-topic classifier, >=$0.10 swing alert engine, fee rounder, and strategy simulator.

Zero external dependencies (pure Python 3 stdlib).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any

ALLOWED_TOPICS = ("Gas Prices", "Elections", "Culture", "Crypto", "Golf")
SWING_THRESHOLD = 0.10
HIGH_ROI_SCORE_THRESHOLD = 62

# Strict word-bounded patterns + verified Kalshi series prefixes to avoid substring false positives
# (e.g., "OpenAI" != Golf, "resolve" != Solana, "soil" != Oil, "sportsbook" != Culture).
_GAS_RE = re.compile(
    r"\b(gas\s+prices?|gasoline|regular\s+gas|gallon\s+of\s+gas|aaa\s+gas|pump\s+prices?|crude\s+oil|wti\s+crude|brent\s+crude)\b",
    re.IGNORECASE,
)
_ELECTIONS_STRICT_RE = re.compile(
    r"\b(elections?|electoral|presidential|nominee|nomination|primary|ballot|gubernatorial|mayoral|house\s+seats|senate\s+seat)\b",
    re.IGNORECASE,
)
_CRYPTO_RE = re.compile(
    r"\b(bitcoin|btc(?:-usd)?|ethereum|ether|eth(?:-usd)?|solana|dogecoin|litecoin|crypto(?:currency)?|blockchain|airdrop|fdv|eip[-\s]?\d+)\b",
    re.IGNORECASE,
)
_GOLF_RE = re.compile(
    r"\b(golf|golfer|pga\s+tour|pga\s+championship|liv\s+golf|dp\s+world\s+tour|the\s+masters|masters\s+tournament|ryder\s+cup|solheim\s+cup|rsm\s+classic|open\s+championship|us\s+open\s+golf|make\s+the\s+cut|birdies)\b",
    re.IGNORECASE,
)
_CULTURE_RE = re.compile(
    r"\b(grammys?|oscars?|academy\s+awards?|emmys?|cma\s+awards?|golden\s+globes?|box\s+office|james\s+bond|billboard|spotify|netflix|metacritic|rotten\s+tomatoes|album\s+of\s+the\s+year|best\s+picture|best\s+pop|grand\s+theft\s+auto|rockstar\s+games|film\s+theme)\b",
    re.IGNORECASE,
)

_SERIES_TOPIC_PREFIXES = (
    (("KXAAAGAS", "AAAGAS"), "Gas Prices"),
    (("KXPRES", "KXSENATE", "KXGOV", "KXHOUSE", "RHOUSESEATS", "KXCA1SPECIAL", "KXTXRAILROAD"), "Elections"),
    (("KXBTCD", "KXBTC", "KXETH", "KXLTC", "KXDEMOFUTHOURLY", "BTCETHRETURN", "KXFDV", "KXAIRDROP", "KXEIP"), "Crypto"),
    (("KXPGATOUR", "KXPGA", "KXGOLF", "KXLIV", "KXDPWORLDTOUR"), "Golf"),
    (("KXGRAM", "KXOSCAR", "KXEMMY", "KXCMA", "KXPERFORM", "KXSPOTIFY", "KXNETFLIX", "KXMETACRITIC", "KXGTA"), "Culture"),
)


def classify_topic(market_or_event: dict[str, Any], parent_event: dict[str, Any] | None = None) -> str | None:
    """Classify a Kalshi event/market into strictly one of the 5 allowed topics, or None."""
    ev = parent_event or market_or_event
    series_ticker = str(ev.get("series_ticker") or market_or_event.get("series_ticker") or "").upper()
    event_ticker = str(market_or_event.get("event_ticker") or ev.get("event_ticker") or "").upper()
    for prefixes, topic in _SERIES_TOPIC_PREFIXES:
        if any(series_ticker.startswith(p) or event_ticker.startswith(p) for p in prefixes):
            return topic

    category = str(ev.get("category") or market_or_event.get("category") or "").strip().lower()
    tags = " ".join(ev.get("tags") or market_or_event.get("tags") or []).lower()
    text = " ".join(
        str(x or "")
        for x in (
            ev.get("title"),
            market_or_event.get("title"),
            market_or_event.get("yes_sub_title"),
            market_or_event.get("rules_primary"),
        )
    )

    if _GAS_RE.search(text):
        return "Gas Prices"
    if "golf" in tags or _GOLF_RE.search(text) or market_or_event.get("primary_participant_key") == "golf_competitor":
        return "Golf"
    if category == "crypto" or _CRYPTO_RE.search(text):
        return "Crypto"
    if category == "elections":
        return "Elections"
    if _ELECTIONS_STRICT_RE.search(text) and category not in ("sports", "crypto", "economics", "financials"):
        return "Elections"
    if category == "entertainment" or _CULTURE_RE.search(text):
        return "Culture"
    return None


def compute_kalshi_fee(
    price_dollars: float,
    contracts: float,
    fee_multiplier: float = 0.07,
    target_precision: str = "0.01",
    rounding_accumulator: Decimal = Decimal("0"),
    series_fee_multiplier: float = 1.0,
    is_maker: bool = False,
) -> tuple[Decimal, Decimal]:
    """Compute quadratic Kalshi trade fee + precision rounding per official Fee Rounding docs.

    Source: https://docs.kalshi.com/getting_started/fee_rounding.md
    Supports per-series `series_fee_multiplier` (`1`, `0.5`, `0` from `GET /series/{ticker}`)
    and maker (`0.0175`) vs. taker (`0.07`) base rates.
    Returns `(net_fee_dollars, updated_accumulator)`.
    """
    dec_p = max(Decimal("0"), min(Decimal("1"), Decimal(str(price_dollars))))
    dec_c = max(Decimal("0"), Decimal(str(contracts)))
    base_rate = Decimal("0.0175") if is_maker else Decimal(str(fee_multiplier))
    dec_mult = max(Decimal("0"), Decimal(str(series_fee_multiplier)))
    raw_model_fee = base_rate * dec_mult * dec_c * dec_p * (Decimal("1") - dec_p)
    trade_fee = (raw_model_fee * Decimal("1000000")).to_integral_value(rounding=ROUND_CEILING) / Decimal("1000000")

    prec = Decimal(target_precision)
    signed_revenue = -(dec_p * dec_c)
    unaligned = signed_revenue - trade_fee
    aligned_change = (unaligned / prec).to_integral_value(rounding=ROUND_FLOOR) * prec
    rounding_fee = unaligned - aligned_change

    acc = rounding_accumulator + rounding_fee
    gross_fee = trade_fee + rounding_fee
    rebate_units = int((acc / prec).to_integral_value(rounding=ROUND_FLOOR))
    rebate = min(Decimal(rebate_units) * prec, gross_fee)
    acc -= rebate
    net_fee = max(Decimal("0.000000"), gross_fee - rebate)
    return net_fee, acc


def score_roi_opportunity(market: dict[str, Any], swing_delta: float | None = None) -> dict[str, Any]:
    """Transparent 0-100 analytical model filter for selective alert routing.

    Explicitly NOT a calibrated probability forecast or return guarantee.
    Evaluates:
      1. Spread efficiency (0-30 pts) + hard executable spread gate (<= $0.15)
      2. Volume & Open Interest liquidity (0-30 pts)
      3. Payoff symmetry / non-degenerate pricing (0-20 pts)
      4. Swing magnitude & fee ratio (0-20 pts)
    """
    bid = _to_float(market.get("yes_bid_dollars"))
    ask = _to_float(market.get("yes_ask_dollars"))
    last = _to_float(market.get("last_price_dollars"))
    vol = _to_float(market.get("volume_fp")) or 0.0
    vol24 = _to_float(market.get("volume_24h_fp")) or 0.0
    oi = _to_float(market.get("open_interest_fp")) or 0.0

    spread_pts = 0.0
    spread = None
    if bid is not None and ask is not None and ask >= bid and ask > 0:
        spread = round(ask - bid, 4)
        spread_pts = max(0.0, 30.0 - spread * 250.0)

    liq_pts = min(18.0, math.log10(vol + vol24 + 1.0) * 4.5) + min(12.0, math.log10(oi + 1.0) * 3.5)

    ref_p = last if (last is not None and last > 0) else ((bid + ask) / 2.0 if (bid is not None and ask is not None) else 0.5)
    symmetry_pts = max(0.0, 20.0 - abs(ref_p - 0.50) * 36.0)

    swing_abs = abs(swing_delta) if swing_delta is not None else 0.0
    swing_pts = min(20.0, swing_abs * 80.0)

    total = int(round(min(100.0, spread_pts + liq_pts + symmetry_pts + swing_pts)))
    actionable_spread = spread is None or spread <= 0.15
    actionable_band = 0.04 <= ref_p <= 0.96
    return {
        "score": total,
        "qualifies_high_roi": bool(total >= HIGH_ROI_SCORE_THRESHOLD and actionable_spread and actionable_band),
        "spread": spread,
        "components": {
            "spread_efficiency": round(spread_pts, 1),
            "liquidity_depth": round(liq_pts, 1),
            "payoff_symmetry": round(symmetry_pts, 1),
            "swing_impulse": round(swing_pts, 1),
        },
    }


@dataclass
class SwingAlert:
    ticker: str
    event_ticker: str
    topic: str
    title: str
    prev_price: float
    new_price: float
    delta: float
    roi_score: int
    high_roi: bool
    timestamp_iso: str
    source_url: str


@dataclass
class CustomStrategyRule:
    name: str
    trade_type: str  # e.g. "breakout", "fade", "value", "liquidity"
    topic_filter: str = "All"
    min_abs_swing: float = 0.10
    price_min: float = 0.04
    price_max: float = 0.96
    max_spread: float = 1.00
    direction: str = "follow"  # "follow" | "fade" | "always_yes" | "always_no"
    contracts: int = 10
    enabled: bool = True


@dataclass
class SimulatedTrade:
    trade_id: str
    ticker: str
    event_ticker: str
    title: str
    topic: str
    strategy: str
    trade_type: str
    side: str  # "yes" | "no"
    contracts: int
    entry_price: float
    gross_cost: float
    fee_paid: float
    opened_at: str
    execution_venue: str = "paper_sim"  # "paper_sim" | "kalshi_demo_api"
    status: str = "open"  # "open" | "finalized"
    result: str = ""  # "yes" | "no" | "scalar"
    settlement_value: float | None = None
    payout: float | None = None
    realized_pnl: float | None = None


@dataclass
class StrategyPortfolioEngine:
    starting_bankroll: float = 2500.0
    contracts_per_signal: int = 10
    cash: float = field(init=False)
    fee_accumulator: Decimal = field(default_factory=lambda: Decimal("0"))
    trades: list[SimulatedTrade] = field(default_factory=list)
    alerts: list[SwingAlert] = field(default_factory=list)
    last_prices: dict[str, float] = field(default_factory=dict)
    enabled_strategies: dict[str, bool] = field(
        default_factory=lambda: {
            "momentum": True,
            "mean_reversion": True,
            "spread_capture": True,
            "favorite_follow": True,
            "longshot_value": True,
        }
    )
    custom_rules: list[CustomStrategyRule] = field(default_factory=list)
    _seq: int = 0

    def __post_init__(self) -> None:
        self.cash = float(self.starting_bankroll)

    def observe_market(self, market: dict[str, Any], topic: str, timestamp_iso: str, source_url: str) -> SwingAlert | None:
        ticker = str(market["ticker"])
        cur = _to_float(market.get("last_price_dollars"))
        status = str(market.get("status") or "active")

        if status == "finalized" and market.get("result") in ("yes", "no", "scalar"):
            settle_val = _to_float(market.get("settlement_value_dollars"))
            self.settle_market(ticker, str(market["result"]), settle_val)

        if cur is None:
            return None
        prev = self.last_prices.get(ticker)
        self.last_prices[ticker] = cur
        if prev is None or status != "active":
            return None

        diff = round(cur - prev, 4)
        if abs(diff) + 1e-9 < SWING_THRESHOLD:
            return None

        scored = score_roi_opportunity(market, diff)
        alert = SwingAlert(
            ticker=ticker,
            event_ticker=str(market.get("event_ticker") or ""),
            topic=topic,
            title=str(market.get("title") or ticker),
            prev_price=prev,
            new_price=cur,
            delta=diff,
            roi_score=scored["score"],
            high_roi=scored["qualifies_high_roi"],
            timestamp_iso=timestamp_iso,
            source_url=source_url,
        )
        self.alerts.insert(0, alert)
        self._auto_trade_on_alert(alert, market)
        return alert

    def execute_trade(
        self,
        market: dict[str, Any],
        topic: str,
        side: str,
        contracts: int,
        strategy: str,
        trade_type: str,
        timestamp_iso: str,
        price_override: float | None = None,
        venue: str = "paper_sim",
    ) -> SimulatedTrade | None:
        side_norm = side.lower()
        if side_norm not in ("yes", "no") or contracts <= 0:
            return None
        last = _to_float(market.get("last_price_dollars"))
        yes_ask = _to_float(market.get("yes_ask_dollars"))
        no_ask = _to_float(market.get("no_ask_dollars"))

        if price_override is not None:
            entry = float(price_override)
        elif side_norm == "yes":
            entry = yes_ask if (yes_ask is not None and 0 < yes_ask < 1.0) else (last or 0.5)
        else:
            entry = no_ask if (no_ask is not None and 0 < no_ask < 1.0) else (1.0 - (last or 0.5))

        if entry <= 0.0 or entry >= 1.0:
            return None

        series_mult = _to_float(market.get("fee_multiplier"))
        if series_mult is None:
            series_mult = 1.0
        fee_dec, new_acc = compute_kalshi_fee(
            entry,
            contracts,
            rounding_accumulator=self.fee_accumulator,
            series_fee_multiplier=series_mult,
        )
        fee = float(fee_dec)
        gross = round(entry * contracts, 4)
        total_outlay = gross + fee
        if self.cash < total_outlay:
            return None

        self.cash = round(self.cash - total_outlay, 6)
        self.fee_accumulator = new_acc
        self._seq += 1
        trade = SimulatedTrade(
            trade_id=f"SIM-{self._seq:04d}",
            ticker=str(market["ticker"]),
            event_ticker=str(market.get("event_ticker") or ""),
            title=str(market.get("title") or market["ticker"]),
            topic=topic,
            strategy=strategy,
            trade_type=trade_type,
            side=side_norm,
            contracts=int(contracts),
            entry_price=round(entry, 4),
            gross_cost=gross,
            fee_paid=round(fee, 6),
            opened_at=timestamp_iso,
            execution_venue=venue,
        )
        self.trades.append(trade)
        return trade

    def _auto_trade_on_alert(self, alert: SwingAlert, market: dict[str, Any]) -> list[SimulatedTrade]:
        executed: list[SimulatedTrade] = []
        p = alert.new_price
        bid = _to_float(market.get("yes_bid_dollars"))
        ask = _to_float(market.get("yes_ask_dollars"))
        spread = (ask - bid) if (bid is not None and ask is not None and ask >= bid) else 1.0

        if self.enabled_strategies.get("momentum"):
            side = "yes" if alert.delta > 0 else "no"
            t = self.execute_trade(
                market, alert.topic, side, self.contracts_per_signal, "momentum", "breakout", alert.timestamp_iso,
                price_override=p if side == "yes" else round(1.0 - p, 4),
            )
            if t:
                executed.append(t)

        if self.enabled_strategies.get("mean_reversion"):
            side = "no" if alert.delta > 0 else "yes"
            t = self.execute_trade(
                market, alert.topic, side, self.contracts_per_signal, "mean_reversion", "fade", alert.timestamp_iso,
                price_override=p if side == "yes" else round(1.0 - p, 4),
            )
            if t:
                executed.append(t)

        if self.enabled_strategies.get("spread_capture") and spread <= 0.08 and alert.high_roi:
            side = "yes" if alert.delta > 0 else "no"
            t = self.execute_trade(
                market, alert.topic, side, self.contracts_per_signal, "spread_capture", "liquidity", alert.timestamp_iso,
                price_override=p if side == "yes" else round(1.0 - p, 4),
            )
            if t:
                executed.append(t)

        if self.enabled_strategies.get("favorite_follow") and 0.60 <= p <= 0.92 and alert.delta > 0:
            t = self.execute_trade(
                market, alert.topic, "yes", self.contracts_per_signal, "favorite_follow", "favorite", alert.timestamp_iso,
                price_override=p,
            )
            if t:
                executed.append(t)

        if self.enabled_strategies.get("longshot_value") and 0.05 <= p <= 0.38 and alert.delta < 0:
            t = self.execute_trade(
                market, alert.topic, "yes", self.contracts_per_signal, "longshot_value", "longshot", alert.timestamp_iso,
                price_override=p,
            )
            if t:
                executed.append(t)

        for rule in self.custom_rules:
            if not rule.enabled:
                continue
            if rule.topic_filter != "All" and rule.topic_filter != alert.topic:
                continue
            if abs(alert.delta) + 1e-9 < rule.min_abs_swing:
                continue
            if not (rule.price_min <= p <= rule.price_max) or spread > rule.max_spread:
                continue
            if rule.direction == "follow":
                side = "yes" if alert.delta > 0 else "no"
            elif rule.direction == "fade":
                side = "no" if alert.delta > 0 else "yes"
            elif rule.direction == "always_no":
                side = "no"
            else:
                side = "yes"
            t = self.execute_trade(
                market, alert.topic, side, rule.contracts, rule.name, rule.trade_type, alert.timestamp_iso,
                price_override=p if side == "yes" else round(1.0 - p, 4),
            )
            if t:
                executed.append(t)

        return executed

    def settle_market(self, ticker: str, result: str, settlement_value_dollars: float | None = None) -> list[SimulatedTrade]:
        """Settle all open trades on `ticker` when Kalshi status reaches `finalized`."""
        res = result.lower()
        if res not in ("yes", "no", "scalar"):
            return []
        settled: list[SimulatedTrade] = []
        for t in self.trades:
            if t.ticker != ticker or t.status != "open":
                continue
            if res == "yes":
                unit_payout = 1.0 if t.side == "yes" else 0.0
            elif res == "no":
                unit_payout = 1.0 if t.side == "no" else 0.0
            else:
                yes_val = max(0.0, min(1.0, float(settlement_value_dollars or 0.0)))
                unit_payout = yes_val if t.side == "yes" else (1.0 - yes_val)
            payout = round(unit_payout * t.contracts, 4)
            pnl = round(payout - t.gross_cost - t.fee_paid, 4)
            t.status = "finalized"
            t.result = res
            t.settlement_value = unit_payout
            t.payout = payout
            t.realized_pnl = pnl
            self.cash = round(self.cash + payout, 6)
            settled.append(t)
        return settled

    def analytics_by_category(self) -> dict[str, dict[str, Any]]:
        """Group performance by `Topic x Strategy x TradeType`."""
        summary: dict[str, dict[str, Any]] = {}
        for t in self.trades:
            key = f"{t.topic} | {t.strategy} | {t.trade_type}"
            bucket = summary.setdefault(
                key,
                {
                    "topic": t.topic,
                    "strategy": t.strategy,
                    "trade_type": t.trade_type,
                    "total_trades": 0,
                    "settled_trades": 0,
                    "wins": 0,
                    "fees_paid": 0.0,
                    "realized_pnl": 0.0,
                },
            )
            bucket["total_trades"] += 1
            bucket["fees_paid"] = round(bucket["fees_paid"] + t.fee_paid, 4)
            if t.status == "finalized" and t.realized_pnl is not None:
                bucket["settled_trades"] += 1
                if t.realized_pnl > 0:
                    bucket["wins"] += 1
                bucket["realized_pnl"] = round(bucket["realized_pnl"] + t.realized_pnl, 4)
        return summary


def _to_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        n = float(val)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None
