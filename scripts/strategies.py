"""
Paper-trading strategy engine. Every "trade" here is simulated: it is never
submitted to Kalshi (see docs/FLAGGED_FOR_REVIEW.md item 3). Each strategy is
a small, disclosed rule so the portfolio page can honestly categorize
performance "by the type of trade" as the task requires, instead of a black
box.

Strategies implemented:
  1. momentum_follow   — after a qualifying swing, paper-buy in the direction
                          of the move, betting it continues.
  2. mean_reversion_fade — after an unusually large single-step swing on low
                          volume, paper-buy the opposite side, betting it
                          partially reverts.
  3. high_liquidity_value — on any snapshot (not just alerts), take a small
                          paper position on the heavily-favored side of a
                          high-volume, high-conviction market (price <= 0.12
                          or >= 0.88) as a low-variance "value" play.
"""
from . import config
from .io_utils import utcnow_iso

MEAN_REVERSION_MIN_DELTA = 0.15
HIGH_LIQUIDITY_MIN_VOLUME = 500
HIGH_LIQUIDITY_EXTREME_PRICE_LOW = 0.12
HIGH_LIQUIDITY_EXTREME_PRICE_HIGH = 0.88


def _new_trade(ticker, topic, strategy, side, action, price, contracts, title, kalshi_url):
    return {
        "id": f"{ticker}-{strategy}-{utcnow_iso()}",
        "timestamp": utcnow_iso(),
        "ticker": ticker,
        "title": title,
        "topic": topic,
        "strategy": strategy,
        "side": side,          # "yes" or "no"
        "action": action,      # "buy" (paper trades are always opened as a buy of a side)
        "entry_price": price,
        "contracts": contracts,
        "cost_basis": round(price * contracts, 4),
        "status": "open",      # open -> closed_won / closed_lost / closed_settled
        "exit_price": None,
        "pnl": None,
        "kalshi_url": kalshi_url,
        "source": "simulated_paper_trade",
    }


def generate_momentum_trades(alerts, market_by_ticker):
    trades = []
    for alert in alerts:
        m = market_by_ticker.get(alert["ticker"])
        if not m:
            continue
        side = "yes" if alert["direction"] == "up" else "no"
        price = m.get("price")
        if price is None:
            continue
        trade_price = price if side == "yes" else round(1 - price, 4)
        trades.append(_new_trade(
            alert["ticker"], alert["topic"], "momentum_follow", side, "buy",
            trade_price, config.PAPER_CONTRACTS_PER_TRADE, alert.get("title"), alert.get("kalshi_url"),
        ))
    return trades


def generate_mean_reversion_trades(alerts, market_by_ticker):
    trades = []
    for alert in alerts:
        if abs(alert["delta"]) < MEAN_REVERSION_MIN_DELTA:
            continue
        volume = (market_by_ticker.get(alert["ticker"]) or {}).get("volume") or 0
        try:
            volume = float(volume)
        except (TypeError, ValueError):
            volume = 0.0
        if volume >= HIGH_LIQUIDITY_MIN_VOLUME:
            continue  # this strategy specifically targets thinner books
        m = market_by_ticker.get(alert["ticker"])
        if not m or m.get("price") is None:
            continue
        # Fade the move: take the side opposite of the direction it just moved.
        side = "no" if alert["direction"] == "up" else "yes"
        price = m.get("price")
        trade_price = price if side == "yes" else round(1 - price, 4)
        trades.append(_new_trade(
            alert["ticker"], alert["topic"], "mean_reversion_fade", side, "buy",
            trade_price, config.PAPER_CONTRACTS_PER_TRADE, alert.get("title"), alert.get("kalshi_url"),
        ))
    return trades


def generate_high_liquidity_value_trades(all_markets):
    trades = []
    for m in all_markets:
        price = m.get("price")
        volume = m.get("volume") or 0
        try:
            volume = float(volume)
        except (TypeError, ValueError):
            volume = 0.0
        if price is None or volume < HIGH_LIQUIDITY_MIN_VOLUME:
            continue
        if price <= HIGH_LIQUIDITY_EXTREME_PRICE_LOW:
            side, trade_price = "no", round(1 - price, 4)
        elif price >= HIGH_LIQUIDITY_EXTREME_PRICE_HIGH:
            side, trade_price = "yes", price
        else:
            continue
        trades.append(_new_trade(
            m["ticker"], m["topic"], "high_liquidity_value", side, "buy",
            trade_price, config.PAPER_CONTRACTS_PER_TRADE, m.get("title"), m.get("kalshi_url"),
        ))
    return trades


def settle_trade_if_resolved(trade, resolved_by_ticker):
    """If the underlying market has settled, close the paper trade and compute
    PnL: a winning side pays $1.00/contract, a losing side pays $0."""
    res = resolved_by_ticker.get(trade["ticker"])
    if not res or trade["status"] != "open":
        return trade
    result = res.get("result")  # "yes" or "no"
    if result not in ("yes", "no"):
        return trade
    won = (trade["side"] == result)
    payout_per_contract = 1.0 if won else 0.0
    proceeds = round(payout_per_contract * trade["contracts"], 4)
    trade["status"] = "closed_won" if won else "closed_lost"
    trade["exit_price"] = payout_per_contract
    trade["pnl"] = round(proceeds - trade["cost_basis"], 4)
    trade["settled_timestamp"] = utcnow_iso()
    return trade
