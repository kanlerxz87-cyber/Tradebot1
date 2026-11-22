"""
Price-swing alert detection: compares each market's current price against the
price recorded on the previous collector run and emits an alert when the
move is >= PRICE_SWING_ALERT_THRESHOLD_DOLLARS in either direction, per the
task's "$0.10 or greater" requirement.

Also implements the transparent "high ROI model" used to populate the second
("selective") scrolling feed. The scoring formula is intentionally simple and
fully disclosed (see docs/EXECUTIVE_SUMMARY.md / suggestions page) rather than
a black box.
"""
from . import config
from .io_utils import utcnow_iso


def market_mid_price(market):
    """Best-effort mid price in dollars from a /markets item. Kalshi returns
    *_dollars string fields per the official quick-start example
    (`yes_bid_dollars`, `yes_ask_dollars`); fall back to legacy cent integer
    fields (`yes_bid`, `yes_ask`, 0-100) divided by 100 if dollars fields are
    absent, and finally to `last_price` cents."""
    def _to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    yes_bid = _to_float(market.get("yes_bid_dollars"))
    yes_ask = _to_float(market.get("yes_ask_dollars"))
    if yes_bid is None and market.get("yes_bid") is not None:
        yes_bid = _to_float(market.get("yes_bid")) / 100.0
    if yes_ask is None and market.get("yes_ask") is not None:
        yes_ask = _to_float(market.get("yes_ask")) / 100.0

    if yes_bid is not None and yes_ask is not None:
        return round((yes_bid + yes_ask) / 2.0, 4)
    if yes_ask is not None:
        return round(yes_ask, 4)
    if yes_bid is not None:
        return round(yes_bid, 4)

    last = _to_float(market.get("last_price_dollars"))
    if last is None and market.get("last_price") is not None:
        last = _to_float(market.get("last_price"))
        if last is not None:
            last = last / 100.0
    return round(last, 4) if last is not None else None


def detect_swings(topic_key, topic_label, current_markets, previous_price_by_ticker):
    """
    current_markets: list of normalized market dicts (see
      collect_kalshi_data.normalize_market) for this topic's run.
    previous_price_by_ticker: {ticker: last_known_price} from the prior run.
    Returns (alerts, new_price_by_ticker).
    """
    alerts = []
    new_price_by_ticker = {}

    for m in current_markets:
        ticker = m["ticker"]
        price = m.get("price")
        new_price_by_ticker[ticker] = price
        if price is None:
            continue

        prev_price = previous_price_by_ticker.get(ticker)
        if prev_price is None:
            continue  # first time we've seen this market; nothing to compare

        delta = round(price - prev_price, 4)
        if abs(delta) >= config.PRICE_SWING_ALERT_THRESHOLD_DOLLARS - 1e-9:
            alerts.append({
                "timestamp": utcnow_iso(),
                "topic": topic_key,
                "topic_label": topic_label,
                "ticker": ticker,
                "title": m.get("title"),
                "event_ticker": m.get("event_ticker"),
                "previous_price": prev_price,
                "new_price": price,
                "delta": delta,
                "direction": "up" if delta > 0 else "down",
                "volume": m.get("volume"),
                "kalshi_url": m.get("kalshi_url"),
                "source_endpoint": m.get("source_endpoint"),
            })

    return alerts, new_price_by_ticker


def high_roi_score(alert, market_by_ticker):
    """
    Transparent scoring heuristic for the "high ROI" selective feed:
      score = |delta| * log10(1 + volume) * directional_edge
    where directional_edge rewards moves away from a 50/50 coin-flip price
    (cheap longshots that just got cheaper, or confident favorites that just
    got more confident), since those are the moves our simple model treats as
    most actionable. This is deliberately simple and documented, not a
    trained model — see docs/EXECUTIVE_SUMMARY.md section 7.
    """
    import math

    m = market_by_ticker.get(alert["ticker"], {})
    volume = m.get("volume") or 0
    try:
        volume = float(volume)
    except (TypeError, ValueError):
        volume = 0.0

    new_price = alert["new_price"]
    distance_from_mid = abs(new_price - 0.5) * 2  # 0 at 50c, 1 at 0c or $1
    score = abs(alert["delta"]) * math.log10(1 + max(volume, 0)) * (0.5 + distance_from_mid)
    return round(score, 4)


HIGH_ROI_MIN_SCORE = 0.05  # disclosed threshold; tune via data once live
