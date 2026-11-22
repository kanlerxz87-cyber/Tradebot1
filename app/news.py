"""Find the news that may have caused a swing.

Two kinds of link are produced, and they are never mixed up:

1. **Contract sources** - the settlement sources Kalshi itself publishes on the
   event (`settlement_sources` in `GET /events`). These come straight from the
   API, so they are verified data, not a guess. They answer "who will decide
   this market".
2. **Recent headlines** - a headline search for the event title over the last
   `news_lookback_hours`. These are *candidates*: a headline that appeared near
   the swing is not proof of causation, so the UI labels them
   "possible catalyst".

Headline lookup uses Google News RSS, which needs no API key. Any failure is
reported as unavailable rather than fabricated: `NewsResult.status` is one of
`ok`, `empty`, `error`, `disabled`.
"""

from __future__ import annotations

import asyncio
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import httpx

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

TRUSTED_DOMAINS = {
    "reuters.com", "apnews.com", "nytimes.com", "wsj.com", "bloomberg.com", "cnbc.com",
    "ft.com", "theguardian.com", "bbc.com", "bbc.co.uk", "npr.org", "politico.com",
    "axios.com", "economist.com", "forbes.com", "cnn.com", "foxnews.com", "abcnews.go.com",
    "nbcnews.com", "cbsnews.com", "usatoday.com", "washingtonpost.com", "espn.com",
    "pgatour.com", "golfdigest.com", "si.com", "theathletic.com", "coindesk.com",
    "theblock.co", "cointelegraph.com", "gasprices.aaa.com", "aaa.com", "eia.gov",
    "bls.gov", "federalreserve.gov", "sec.gov",
}


@dataclass
class Headline:
    title: str
    link: str
    source: str
    published_ts: float | None = None
    trusted: bool = False

    def as_dict(self) -> dict:
        return {
            "title": self.title, "link": self.link, "source": self.source,
            "published_ts": self.published_ts, "trusted": self.trusted,
            "published_utc": _iso(self.published_ts),
        }


@dataclass
class NewsResult:
    status: str
    headlines: list[Headline] = field(default_factory=list)
    note: str | None = None

    @property
    def available(self) -> bool:
        return self.status == "ok"

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "note": self.note,
            "headlines": [h.as_dict() for h in self.headlines],
        }


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _domain(url: str) -> str:
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except Exception:
        return ""
    return host.lower().removeprefix("www.")


def query_from_title(title: str, *, extra: str | None = None) -> str:
    """Build a compact search query from a Kalshi market/event title."""
    cleaned = re.sub(r"\bwill\b|\bbe\b|\bthe\b|\bwill\b", " ", title, flags=re.I)
    cleaned = re.sub(r"[^\w\s%$.\-]", " ", cleaned)
    words = [w for w in cleaned.split() if len(w) > 2][:9]
    query = " ".join(words)
    if extra:
        query = f"{query} {extra}".strip()
    return query or title


class NewsFinder:
    def __init__(self, *, lookback_hours: int = 2, timeout: float = 8.0, max_items: int = 4,
                 enabled: bool = True):
        self.lookback_hours = lookback_hours
        self.timeout = timeout
        self.max_items = max_items
        self.enabled = enabled
        self._cache: dict[str, tuple[float, NewsResult]] = {}
        self._cache_ttl = 120

    async def recent(self, query: str, client: httpx.AsyncClient | None = None) -> NewsResult:
        if not self.enabled:
            return NewsResult("disabled", note="Headline lookup disabled by configuration")
        key = query.lower()
        cached = self._cache.get(key)
        if cached and time.time() - cached[0] < self._cache_ttl:
            return cached[1]

        params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout,
                                       headers={"User-Agent": "tradebot1-kalshi-dashboard/1.0"})
        try:
            response = await client.get(GOOGLE_NEWS_RSS, params=params)
            response.raise_for_status()
            result = self._parse(response.text)
        except Exception as exc:  # network is optional here; never fabricate
            result = NewsResult("error", note=f"headline lookup failed: {type(exc).__name__}")
        finally:
            if owns_client:
                await client.aclose()
        self._cache[key] = (time.time(), result)
        return result

    def _parse(self, xml_text: str) -> NewsResult:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            return NewsResult("error", note=f"could not parse feed: {exc}")
        cutoff = time.time() - self.lookback_hours * 3600
        items: list[Headline] = []
        for node in root.iter("item"):
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            pub = node.findtext("pubDate")
            source = (node.findtext("source") or "").strip() or _domain(link)
            ts = _parse_rfc822(pub)
            if not title or not link:
                continue
            # Keep it to the lookback window when a date is available; undated
            # items are kept but marked as such.
            if ts is not None and ts < cutoff:
                continue
            items.append(Headline(title=_clean(title), link=link, source=source,
                                  published_ts=ts, trusted=_domain(link) in TRUSTED_DOMAINS))
        items.sort(key=lambda h: (h.trusted, h.published_ts or 0), reverse=True)
        items = items[: self.max_items]
        if not items:
            return NewsResult("empty", note=f"no headlines in the last {self.lookback_hours}h")
        return NewsResult("ok", headlines=items)

    async def many(self, queries: Iterable[str]) -> dict[str, NewsResult]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            pairs = await asyncio.gather(*(self.recent(q, client) for q in queries), return_exceptions=True)
        out: dict[str, NewsResult] = {}
        for query, result in zip(queries, pairs):
            out[query] = result if isinstance(result, NewsResult) else NewsResult(
                "error", note=f"headline lookup failed: {type(result).__name__}")
        return out


def contract_sources(settlement_sources: Iterable[dict] | None) -> list[dict]:
    """Kalshi's own settlement sources, deduplicated, for 'who settles this'."""
    seen, out = set(), []
    for source in settlement_sources or []:
        name = (source.get("name") or "").strip()
        url = (source.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"name": name or _domain(url), "url": url})
    return out[:8]


def official_reference_links(topic: str, title: str = "") -> list[dict]:
    """Topic-level official sources for cross-checking a market.

    These are stable landing pages of the agencies that publish the underlying
    numbers. They are offered as *reference*, never as a claim about a specific
    contract's settlement without the contract's own rules.
    """
    references = {
        "gas": [
            {"name": "AAA national average gas prices", "url": "https://gasprices.aaa.com/"},
            {"name": "U.S. EIA weekly retail gasoline prices",
             "url": "https://www.eia.gov/petroleum/gasdiesel/"},
        ],
        "elections": [
            {"name": "FEC campaign finance data", "url": "https://www.fec.gov/data/"},
            {"name": "U.S. Election Assistance Commission", "url": "https://www.eac.gov/"},
        ],
        "culture": [
            {"name": "The Numbers (box office)", "url": "https://www.the-numbers.com/"},
            {"name": "Billboard charts", "url": "https://www.billboard.com/charts/"},
        ],
        "crypto": [
            {"name": "CF Benchmarks (Kalshi's crypto settlement source)",
             "url": "https://www.cfbenchmarks.com/"},
            {"name": "CoinGecko market data", "url": "https://www.coingecko.com/"},
        ],
        "golf": [
            {"name": "PGA Tour official site", "url": "https://www.pgatour.com/"},
            {"name": "Official World Golf Ranking", "url": "https://www.owgr.com/"},
        ],
    }
    return references.get(topic, [])


def _clean(title: str) -> str:
    # Google News appends " - Source" to titles; the source is already a field.
    return re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip()


def _parse_rfc822(value: str | None) -> float | None:
    if not value:
        return None
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None
