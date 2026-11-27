"""Topic taxonomy — restricted to the five topics the brief asks for.

Everything here is anchored to the official Kalshi taxonomy documented at
https://docs.kalshi.com/getting_started/terms ("Category", "Subcategory"):

* ``category`` is a **series** field: the series' single primary category.
* ``categories`` is the series' discovery list.
* ``tags`` are subcategories; ``Golf`` is a tag inside the ``Sports`` category
  (verified against ``GET /search/tags_by_categories``).
* The official category list has **no** ``Culture`` entry. The brief's "culture" topic is
  therefore mapped to the official ``Entertainment`` category (plus ``Social`` when a series
  carries it). This mapping is a documented decision, not a Kalshi label, and is flagged on
  the Flagged for Review page.
* The monthly US gas-price series is ``KXAAAGASM`` — primary category ``Economics``,
  categories ``[Economics, Commodities]``, tags ``[Oil and energy, Oil & Gas]``. Kalshi uses
  it as the worked example in its own glossary, which is the strongest available citation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

DOCS_TERMS = "https://docs.kalshi.com/getting_started/terms"
DOCS_TAGS = "https://docs.kalshi.com/api-reference/search/get-tags-for-series-categories"


@dataclass(frozen=True)
class Topic:
    id: str
    label: str
    page: str
    blurb: str
    categories: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    series: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    sources: tuple[str, ...] = field(default_factory=tuple)

    def pattern_regex(self) -> re.Pattern[str] | None:
        if not self.patterns:
            return None
        return re.compile("|".join(self.patterns), re.IGNORECASE)


TOPICS: tuple[Topic, ...] = (
    Topic(
        id="gas",
        label="Gas prices",
        page="topics/gas-prices.html",
        blurb="US average retail gasoline markets (AAA survey strikes).",
        categories=("Economics", "Commodities"),
        tags=("Oil & Gas", "Oil and energy"),
        series=("KXAAAGASM",),
        patterns=(r"gas\s*pric", r"gasoline", r"average\s+gas"),
        sources=(DOCS_TERMS,),
    ),
    Topic(
        id="elections",
        label="Elections",
        page="topics/elections.html",
        blurb="US and international elections, nominations, seats and ballot measures.",
        categories=("Elections",),
        patterns=(),
        sources=(DOCS_TAGS,),
    ),
    Topic(
        id="culture",
        label="Culture",
        page="topics/culture.html",
        blurb="Entertainment and culture: awards, music, film, TV, video games, social moments.",
        categories=("Entertainment", "Social"),
        patterns=(),
        sources=(DOCS_TAGS,),
    ),
    Topic(
        id="crypto",
        label="Crypto",
        page="topics/crypto.html",
        blurb="Bitcoin, Ethereum, Solana and other digital-asset price and event markets.",
        categories=("Crypto",),
        patterns=(),
        sources=(DOCS_TAGS,),
    ),
    Topic(
        id="golf",
        label="Golf",
        page="topics/golf.html",
        blurb="PGA Tour, LIV and Ryder Cup markets — the official Golf subcategory of Sports.",
        categories=("Sports",),
        tags=("Golf",),
        patterns=(r"\bgolf\b", r"\bpga\b", r"\blpga\b", r"ryder\s*cup", r"\bliv\b"),
        sources=(DOCS_TAGS,),
    ),
)

TOPIC_INDEX: dict[str, Topic] = {t.id: t for t in TOPICS}
TOPIC_ORDER: tuple[str, ...] = tuple(t.id for t in TOPICS)


def _norm_set(values: Iterable[Any] | None) -> set[str]:
    if not values:
        return set()
    return {str(v).strip().lower() for v in values if str(v).strip()}


def _matches(values: Iterable[Any] | None, wanted: tuple[str, ...]) -> bool:
    return bool(_norm_set(values) & _norm_set(wanted))


def topic_for_series(series: dict[str, Any]) -> str | None:
    """Classify a series object (from ``GET /series``) into one of the five topics."""
    ticker = str(series.get("ticker") or "")
    categories = list(series.get("categories") or [])
    if series.get("category"):
        categories.append(series["category"])
    tags = list(series.get("tags") or [])
    title = str(series.get("title") or "")

    # 1. Golf is an explicit subcategory tag — highest confidence.
    for topic in TOPICS:
        if topic.tags and topic.id == "golf" and _matches(tags, topic.tags):
            return topic.id

    # 2. Gas prices: known series ticker first, then subcategory tags, then title pattern.
    gas = TOPIC_INDEX["gas"]
    if ticker in gas.series:
        return gas.id
    if _matches(tags, gas.tags) and _looks_like_gas(title):
        return gas.id
    if _looks_like_gas(title):
        return gas.id

    # 3. Category-based topics.
    for topic_id in ("elections", "crypto", "culture"):
        topic = TOPIC_INDEX[topic_id]
        if _matches(categories, topic.categories):
            return topic_id

    # 4. Golf keyword fallback for series that are missing the tag.
    golf = TOPIC_INDEX["golf"]
    regex = golf.pattern_regex()
    if regex and regex.search(title):
        return golf.id
    return None


def _looks_like_gas(text: str) -> bool:
    regex = TOPIC_INDEX["gas"].pattern_regex()
    return bool(regex and regex.search(text or ""))


def topic_for_market(
    market: dict[str, Any],
    series_meta: dict[str, dict[str, Any]],
    series_ticker: str | None = None,
) -> str | None:
    """Classify a market using its series metadata (authoritative) then title keywords."""
    meta = series_meta.get(series_ticker or "") or {}
    if meta:
        topic = topic_for_series(meta)
        if topic:
            return topic
    title = " ".join(str(market.get(k) or "") for k in ("title", "yes_sub_title", "subtitle"))
    gas = TOPIC_INDEX["gas"]
    if _looks_like_gas(title):
        return gas.id
    golf = TOPIC_INDEX["golf"]
    regex = golf.pattern_regex()
    if regex and regex.search(title):
        return golf.id
    return None


def discovery_queries() -> dict[str, list[dict[str, Any]]]:
    """Query parameters used to build the series catalogue for each topic."""
    return {
        "gas": [
            {"category": "Economics", "params": {"category": "Economics", "include_volume": True}},
            {"category": "Commodities", "params": {"category": "Commodities", "include_volume": True}},
        ],
        "elections": [{"category": "Elections", "params": {"category": "Elections", "include_volume": True}}],
        "culture": [
            {"category": "Entertainment", "params": {"category": "Entertainment", "include_volume": True}},
            {"category": "Social", "params": {"category": "Social", "include_volume": True}},
        ],
        "crypto": [{"category": "Crypto", "params": {"category": "Crypto", "include_volume": True}}],
        "golf": [{"category": "Sports", "params": {"tags": "Golf", "include_volume": True}}],
    }


def compact_series(series: dict[str, Any], topic: str | None = None) -> dict[str, Any]:
    """Keep only the fields the dashboard needs (the raw objects are large)."""
    return {
        "ticker": series.get("ticker"),
        "title": series.get("title"),
        "category": series.get("category"),
        "categories": series.get("categories") or [],
        "tags": series.get("tags") or [],
        "frequency": series.get("frequency"),
        "topic": topic,
        "volume": _to_float(series.get("volume_fp")),
        "fee_type": series.get("fee_type"),
        "fee_multiplier": _to_float(series.get("fee_multiplier")),
        "contract_url": series.get("contract_url"),
        "contract_terms_url": series.get("contract_terms_url"),
        "settlement_sources": [
            {"name": s.get("name"), "url": s.get("url")}
            for s in (series.get("settlement_sources") or [])
            if isinstance(s, dict)
        ][:6],
    }


def _to_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None
