"""Candidate catalyst links for a swing alert.

The brief asks the dashboard to show, next to a sharp move, the events and *website links that
may have caused* it. Nothing in this repository can prove causality, so this module produces
two strictly separated lists and never mixes them:

``official``
    Links Kalshi itself publishes for the contract, taken from fields the API returns:
    the series page, the market API object, the contract terms URL, and the series'
    ``settlement_sources`` (the exchange's own statement of what settles the market). These
    are facts about the contract, not explanations of the move.

``search``
    Pre-built *search queries*, not asserted causes: a news search restricted to the move's
    date, a news search for the contract's subject, and a site-scoped search of the
    settlement source's domain when Kalshi names one (for example the AAA gas-price page for
    ``KXAAAGASM``). Every label says "search", the UI renders them in a separate block, and
    each link carries ``verified: False`` because the repository cannot confirm what, if
    anything, the page says about this price.

Why search links rather than scraped headlines: this collector runs in GitHub Actions with no
news API key, and inventing a headline or picking a story by keyword would be exactly the
hallucination the brief forbids. A search URL is honest — it shows the reader a time-boxed
window and lets them judge.

Keywords are derived only from the contract text Kalshi returns (``title``, ``yes_sub_title``,
``rules_primary``). Numbers, ticker symbols and boilerplate are stripped so the query does not
end up as a literal search for "Will average gas prices be above 3.63".
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

#: Words that carry no search signal in a Kalshi contract title.
STOPWORDS = {
    "will", "the", "a", "an", "be", "is", "are", "was", "were", "any", "all", "at", "above",
    "below", "over", "under", "than", "more", "less", "between", "and", "or", "of", "in", "on",
    "for", "to", "by", "before", "after", "this", "that", "there", "it", "its", "if", "when",
    "market", "markets", "contract", "contracts", "yes", "no", "close",
    "closes", "settle", "settles", "average", "exactly", "reach", "hit", "least", "most",
    "greater", "lower", "higher", "first", "end", "end of", "value", "index", "level",
    "win", "wins", "winner", "won", "hold", "holds", "take", "takes", "get", "gets", "make",
    "makes", "remain", "remains", "stay", "stays", "become", "becomes", "have", "has", "do",
    "does", "did", "can", "could", "would", "should", "may", "might", "much", "many", "next",
    "last", "year", "years", "day", "days", "week", "weeks", "month", "months", "time",
    # calendar / expiry words: every contract title carries one, so they would match all news
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "january", "february", "march", "april", "june", "july", "august", "september",
    "october", "november", "december", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday", "today", "tomorrow", "tonight",
}
# NOTE: subject nouns such as "gas", "bitcoin" or "golf" are deliberately NOT stopwords —
# they are the only search signal a short contract title carries.

#: Topic-level context added to the search when the contract text alone is too thin.
TOPIC_CONTEXT = {
    "gas": "gas prices",
    "elections": "election",
    "culture": "entertainment",
    "crypto": "crypto",
    "golf": "golf",
}

NEWS_HOST = "https://news.google.com/search"
#: A token is a run of letters (with an internal apostrophe or hyphen) — nothing else.
_TOKEN_RE = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")
_NUMBER_RE = re.compile(r"[$]?\d[\d,]*(?:\.\d+)?%?")
_MARKUP_RE = re.compile(r"\*\*|\*|__|`|\$")


def _clean(text: str) -> str:
    """Strip markdown emphasis and dollar signs Kalshi puts inside contract titles."""
    return _MARKUP_RE.sub(" ", text or "").strip()


def keywords(market: dict[str, Any], *, limit: int = 7) -> list[str]:
    """Subject words for the contract, longest-signal first. Never invents a word."""
    parts = [
        _clean(str(market.get("title") or "")),
        _clean(str(market.get("yes_sub_title") or market.get("subtitle") or "")),
    ]
    text = _NUMBER_RE.sub(" ", " ".join(parts))
    words: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        word = raw.strip("'-").lower()
        # ALL-CAPS acronyms in the contract text are tickers or source names, not subjects.
        if raw.isupper() and len(raw) <= 6:
            continue
        if len(word) < 3 or word in STOPWORDS or word in words:
            continue
        words.append(word)
    if not words:
        topic = str(market.get("topic") or "")
        if TOPIC_CONTEXT.get(topic):
            words = TOPIC_CONTEXT[topic].split()
    return words[:limit]


def _date_window(iso: str | None) -> str | None:
    """Google News' date-range filter has the shape ``cdr:1,cd_min:M/D/YYYY,cd_max:M/D/YYYY``."""
    if not iso or len(iso) < 10:
        return None
    try:
        year, month, day = iso[0:4], int(iso[5:7]), int(iso[8:10])
    except (TypeError, ValueError):
        return None
    return f"cdr:1,cd_min:{month}/{day}/{year},cd_max:{month}/{day}/{year}"


def _news_search(query: str, iso: str | None) -> str:
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    window = _date_window(iso)
    if window:
        params["tbs"] = window
    return f"{NEWS_HOST}?{urllib.parse.urlencode(params)}"


def official_links(market: dict[str, Any], series_meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Links published by Kalshi for this contract. Verified: they are API fields."""
    meta = series_meta or {}
    out: list[dict[str, Any]] = []

    if market.get("series_page_url"):
        out.append(
            {
                "kind": "official",
                "label": "Kalshi series page",
                "url": market["series_page_url"],
                "verified": True,
                "note": "Public product page for the series this market belongs to.",
            }
        )
    if market.get("api_url"):
        out.append(
            {
                "kind": "official",
                "label": "Market object (API)",
                "url": market["api_url"],
                "verified": True,
                "note": "Live exchange fields: price, result, volume, open interest.",
            }
        )
    if meta.get("contract_terms_url"):
        out.append(
            {
                "kind": "official",
                "label": "Contract terms",
                "url": meta["contract_terms_url"],
                "verified": True,
                "note": "Kalshi's filed terms for the series.",
            }
        )
    for source in (meta.get("settlement_sources") or [])[:3]:
        if isinstance(source, dict) and source.get("url"):
            out.append(
                {
                    "kind": "official",
                    "label": f"Settlement source: {source.get('name') or 'Kalshi-listed source'}",
                    "url": source["url"],
                    "verified": True,
                    "note": "The exchange names this source as what determines the market.",
                }
            )
    seen: set[str] = set()
    unique = []
    for item in out:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
    return unique


def search_links(
    market: dict[str, Any],
    *,
    iso: str | None = None,
    series_meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Time-boxed search queries a reader can open to judge the move for themselves."""
    words = keywords(market)
    if not words:
        return []
    subject = " ".join(words[:5])
    out: list[dict[str, Any]] = []

    if iso:
        out.append(
            {
                "kind": "search",
                "label": f"News on {iso[:10]}",
                "url": _news_search(subject, iso),
                "verified": False,
                "note": "News search restricted to the date of the move. Candidate only.",
            }
        )
    out.append(
        {
            "kind": "search",
            "label": "Recent news",
            "url": _news_search(subject, None),
            "verified": False,
            "note": "Unrestricted news search for the contract subject. Candidate only.",
        }
    )

    meta = series_meta or {}
    for source in (meta.get("settlement_sources") or [])[:1]:
        url = (source or {}).get("url") if isinstance(source, dict) else None
        if url and "://" in url:
            host = urllib.parse.urlparse(url).netloc.lstrip("www.")
            if host:
                out.append(
                    {
                        "kind": "search",
                        "label": f"Search {host} for {subject}",
                        "url": f"https://duckduckgo.com/?q={urllib.parse.quote(f'site:{host} {subject}')}",
                        "verified": False,
                        "note": "Kalshi lists this domain as the settlement source.",
                    }
                )
                break
    return out


def for_market(
    market: dict[str, Any],
    series_meta: dict[str, Any] | None = None,
    *,
    iso: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Both lists, ready to attach to an alert or a resolution row."""
    return {
        "official": official_links(market, series_meta),
        "search": search_links(market, iso=iso, series_meta=series_meta),
    }
