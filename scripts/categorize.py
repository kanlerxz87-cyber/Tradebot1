"""
Maps a Kalshi market/event into one of the five user-requested topics, using
Kalshi's own `category` field first and a narrow keyword fallback second.
Anything that cannot be confidently placed is returned as None so the caller
can route it to docs/data/uncategorized.json instead of guessing.
"""
from . import config


def _text_blob(market):
    parts = [
        market.get("title") or "",
        market.get("subtitle") or "",
        market.get("yes_sub_title") or "",
        market.get("event_ticker") or "",
        market.get("ticker") or "",
    ]
    return " ".join(parts).lower()


def categorize_market(market, event_category=None):
    """
    `market`: a market dict as returned by GET /markets.
    `event_category`: the `category` string from GET /events for this
      market's event_ticker, if the caller already fetched it (preferred,
      since category lives on the event/series, not always on the market
      object itself).
    Returns the topic key (e.g. "golf") or None if unmatched.
    """
    category = (event_category or market.get("category") or "").strip().lower()
    blob = _text_blob(market)
    ticker = (market.get("ticker") or "").upper()
    event_ticker = (market.get("event_ticker") or "").upper()

    candidates = []
    for topic_key, cfg in config.TOPICS.items():
        category_hit = any(c in category for c in cfg["category_match"]) if category else False
        keyword_hit = any(k in blob for k in cfg["keyword_fallback"])
        series_hit = any(
            ticker.startswith(s) or event_ticker.startswith(s) for s in cfg["series_hint"]
        )

        if topic_key in config.SPORTS_CATEGORY_REQUIRES_KEYWORD:
            # "Sports" alone is too broad (covers football, basketball, etc.)
            # so golf additionally requires a keyword/series hit.
            if category_hit and (keyword_hit or series_hit):
                candidates.append(topic_key)
            elif series_hit:
                candidates.append(topic_key)
        else:
            if category_hit or keyword_hit or series_hit:
                candidates.append(topic_key)

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        # Prefer a series_hint/keyword match over a bare category match when
        # more than one topic's category string loosely matched.
        for topic_key in candidates:
            cfg = config.TOPICS[topic_key]
            if any(ticker.startswith(s) or event_ticker.startswith(s) for s in cfg["series_hint"]):
                return topic_key
        return candidates[0]
    return None
