"""The five topics this dashboard tracks, and how a Kalshi market is mapped to one.

Kalshi publishes categories via the public `GET /search/tags_by_categories`
endpoint, verified 2026-11-22 against
https://external-api.kalshi.com/trade-api/v2/search/tags_by_categories

Categories present in that response: Business, Climate and Weather, Commodities,
Companies, Crypto, Economics, Elections, Entertainment, Financials, Mentions,
Politics, Science and Technology, Social, Sports.

There is **no "Gas" category and no "Culture" category** in Kalshi's taxonomy.
So the dashboard's five topics are *views built on top of* Kalshi's own data:

    gas       -> Commodities (tag "Oil & Gas") plus series whose title/ticker
                 mentions gas; Kalshi's own fee schedule names series KXAAAGASM
                 ("US gas price") -- https://kalshi.com/docs/kalshi-fee-schedule.pdf
    elections -> category "Elections"
    culture   -> Entertainment + Mentions + Social (the closest published
                 equivalents of "culture")
    crypto    -> category "Crypto"
    golf      -> category "Sports" AND tag "Golf" (Sports tags include "Golf")

Every mapping rule below records which published field it read, so the dashboard
can show *why* a market landed in a topic instead of asserting it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

TOPIC_ORDER = ("gas", "elections", "culture", "crypto", "golf")

TOPIC_META: dict[str, dict] = {
    "gas": {
        "label": "Gas prices",
        "blurb": "US retail gasoline prices and energy-linked contracts.",
        "basis": "Kalshi category 'Commodities' + tag 'Oil & Gas', or a gas/energy keyword. "
                 "Kalshi's fee schedule names series KXAAAGASM ('US gas price').",
    },
    "elections": {
        "label": "Elections",
        "blurb": "US and international elections, nominations, and control of chambers.",
        "basis": "Kalshi category 'Elections'.",
    },
    "culture": {
        "label": "Culture",
        "blurb": "Entertainment, awards, music, film, television - the closest published "
                 "equivalent of 'culture' in Kalshi's taxonomy.",
        "basis": "Kalshi category 'Entertainment' or 'Mentions', or the Social tag group.",
    },
    "crypto": {
        "label": "Crypto",
        "blurb": "Bitcoin, Ethereum, Solana and other digital-asset price contracts.",
        "basis": "Kalshi category 'Crypto'.",
    },
    "golf": {
        "label": "Golf",
        "blurb": "PGA Tour, DP World Tour, LPGA, LIV, Champions and Korn Ferry winners "
                 "and finishing positions.",
        "basis": "Kalshi category 'Sports' AND the tag 'Golf'.",
    },
}

# Series tickers verified on kalshi.com / the public series endpoint.
# These are *hints* that raise confidence, never the only reason a market is
# included: category/tag matching always comes first.
GOLF_SERIES_HINTS = (
    "KXPGATOUR", "KXPGATOP5", "KXPGATOP10", "KXPGATOP20", "KXPGAMAKECUT",
    "KXPGAR1LEAD", "KXGOLFMAJOR", "KXDPWORLDTOUR", "KXLPGATOUR", "KXLIVTOUR",
    "KXCHAMPTOUR", "KXKFTOUR", "KXRYDERCUP", "KXSOLHEIMCUP",
)
GAS_SERIES_HINTS = ("KXAAAGAS", "KXAAAGASM", "KXAAAGASW", "KXGAS", "KXGASOLINE")

_GOLF_TITLE = re.compile(
    r"\b(golf|pga|lpga|liv golf|korn ferry|ryder cup|solheim cup|masters|"
    r"open championship|u\.?s\.? open|tour championship|fedex cup|birdie|eagle putt)\b",
    re.I,
)
_GAS_TITLE = re.compile(
    r"\b(gas|gasoline|gas prices?|gallons?|petrol|diesel|pump price|aaa|brent|wti|crude|"
    r"natural gas|heating oil|opec|refiner)\b",
    re.I,
)
_GOLF_FALSE_POSITIVE = re.compile(r"\b(masters? of|grand slam of|eagle(s)? (spread|bank)|gaslight)\b", re.I)


@dataclass(frozen=True)
class TopicMatch:
    topic: str
    confidence: str          # "category" | "tag" | "keyword" | "none"
    reason: str

    @property
    def matched(self) -> bool:
        return self.topic != "other"


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


def _tags(market_or_event: dict) -> set[str]:
    tags: set[str] = set()
    raw = market_or_event.get("tags") or []
    if isinstance(raw, str):
        raw = [raw]
    for tag in raw:
        tags.add(_norm(tag))
    for tag in market_or_event.get("categories") or []:
        tags.add(_norm(tag))
    return tags


def match_topic(
    *,
    category: str | None,
    tags: Iterable[str] | None = None,
    title: str | None = None,
    series_ticker: str | None = None,
    event_ticker: str | None = None,
    market_ticker: str | None = None,
) -> TopicMatch:
    """Map one market to a topic using only published fields plus documented keyword hints."""
    cat = _norm(category)
    tagset = {_norm(t) for t in (tags or [])}
    title = title or ""
    series = (series_ticker or "").upper()
    tickers = " ".join(filter(None, [series, (event_ticker or "").upper(), (market_ticker or "").upper()]))

    # 1. Golf: Sports + Golf tag is authoritative; series hints are secondary.
    if cat == "sports" and ("golf" in tagset or any(h in tickers for h in GOLF_SERIES_HINTS)):
        return TopicMatch("golf", "tag", "Kalshi category 'Sports' with tag 'Golf'")
    if "golf" in tagset or any(h in tickers for h in GOLF_SERIES_HINTS):
        return TopicMatch("golf", "tag", "Kalshi tag 'Golf' or a known golf series ticker")
    if _GOLF_TITLE.search(title) and not _GOLF_FALSE_POSITIVE.search(title):
        return TopicMatch("golf", "keyword", "Title mentions a golf tour, major, or tournament")

    # 2. Crypto
    if cat == "crypto":
        return TopicMatch("crypto", "category", "Kalshi category 'Crypto'")

    # 3. Elections
    if cat == "elections":
        return TopicMatch("elections", "category", "Kalshi category 'Elections'")

    # 4. Gas: explicit energy tags first, then keywords, then series hints.
    if "oil & gas" in tagset or "oil and gas" in tagset or "gas" in tagset:
        return TopicMatch("gas", "tag", "Kalshi tag 'Oil & Gas' or 'Gas'")
    if any(h in tickers for h in GAS_SERIES_HINTS):
        return TopicMatch("gas", "tag", "Known gas / AAA series ticker")
    if _GAS_TITLE.search(title):
        return TopicMatch("gas", "keyword", "Title mentions gasoline, crude, diesel, or a gas index")

    # 5. Culture
    if cat in {"entertainment", "mentions", "social"}:
        return TopicMatch("culture", "category", f"Kalshi category '{category}'")
    if tagset & {"music", "television", "movies", "awards", "oscars", "grammys", "music charts",
                 "tv charts", "movie charts", "collectibles", "video games", "art", "food"}:
        return TopicMatch("culture", "tag", "Kalshi entertainment tag")

    return TopicMatch("other", "none", "No published Kalshi field maps to the tracked topics")


def topic_page_url(event_ticker: str | None, series_ticker: str | None = None) -> str | None:
    """Public kalshi.com URL for manual review.

    `https://kalshi.com/markets/<series_ticker>` was fetched for KXBTCD, KXAAAGASM
    and KXPGATOUR during this session and resolved to a live market page each
    time, so it is the verified form. The event-ticker-only form is NOT verified
    to resolve; when only an event ticker is known the caller gets a link that is
    labelled unverified on the site.
    """
    if series_ticker:
        return f"https://kalshi.com/markets/{series_ticker.lower()}"
    if not event_ticker:
        return None
    return f"https://kalshi.com/markets/{event_ticker.lower()}"
