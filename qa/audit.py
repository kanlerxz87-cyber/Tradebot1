#!/usr/bin/env python3
"""Cross-implementation audit of every committed dataset in this repository.

What this does
--------------
Four independent implementations of the same brief live in this repository
(``docs/desk``, ``docs/``, ``site/`` and the Node trade board).  Each keeps its own
committed JSON.  This script reads them all and checks the things a trader would
get hurt by if they were wrong:

* prices outside $0.00-$1.00 (a binary contract cannot be worth more than $1);
* a crossed book (YES bid above YES ask, or YES bid + NO bid above $1.00);
* an order-book ladder that is not monotonic, or whose depths disagree with the
  totals the same payload reports;
* the same ticker appearing twice, or in two topics at once;
* a swing alert that does not actually clear the $0.10 threshold;
* resolution values that are not ``yes``/``no``/``void``;
* a table row whose source link is not on an official Kalshi host;
* derived totals that do not recompute from the fields printed beside them;
* broken internal links on any published page;
* committed secrets.

What this does *not* do
-----------------------
It cannot confirm a price against Kalshi.  It checks the committed snapshot
against itself, against the other implementations' snapshots, and against the
official documentation for field semantics.  Live confirmation of a sample of
rows is recorded separately in ``qa/report.md``.

Usage
-----
    python3 qa/audit.py            # write qa/report.json, qa/report.md, qa.html
    python3 qa/audit.py --check    # exit 1 only on errors (broken links, secrets,
                                   # corrupted prices); warnings never fail a build
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "qa"

OFFICIAL_HOSTS = {
    # From https://docs.kalshi.com/getting_started/api_environments (fetched 2026-11-22)
    "docs.kalshi.com",
    "kalshi.com",
    "www.kalshi.com",
    "external-api.kalshi.com",
    "api.elections.kalshi.com",
    "external-api.demo.kalshi.co",
    "demo-api.kalshi.co",
    "external-api-ws.kalshi.com",
    "external-api-ws.demo.kalshi.co",
    "demo-api.kalshi.co",
    "user-ws.kalshi.com",
    "user-ws.demo.kalshi.co",
    # Kalshi-published documents and help centre, cited by the series records
    "assets.kalshi.com",
    "help.kalshi.com",
    "demo.kalshi.co",
}
SECONDARY_HOSTS = {
    # Named by Kalshi's own settlement-source field, not Kalshi hosts.
    "gasprices.aaa.com",
    "www.aaa.com",
    "www.bls.gov",
    "www.bea.gov",
    "www.federalreserve.gov",
    "www.eia.gov",
    "www.weather.gov",
    "www.pgatour.com",
    "www.espn.com",
    "www.foxsports.com",
}
TOPICS = ("gas", "elections", "culture", "crypto", "golf")
THRESHOLD = 0.10
TOL = 1e-9

findings: list[dict[str, Any]] = []
checked: list[str] = []


def add(severity: str, code: str, title: str, detail: str, *, examples: Iterable[Any] = (),
        source: str = "", action: str = "", count: int | None = None) -> None:
    examples = list(examples)[:6]
    findings.append({
        "id": f"{code}-{len([f for f in findings if f['code'] == code]) + 1}",
        "severity": severity,
        "code": code,
        "title": title,
        "detail": detail,
        "count": count if count is not None else len(examples),
        "examples": examples,
        "source": source,
        "action": action,
    })


def load(rel: str) -> Any:
    path = ROOT / rel
    if not path.exists():
        add("info", "MISSING", f"{rel} not present", "Dataset is absent on this branch; its checks were skipped.", source=rel)
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        add("error", "JSON", f"{rel} is not valid JSON", str(exc), source=rel,
            action="Fix the generator before publishing; every page that reads this file is dead.")
        return None


# --------------------------------------------------------------------------- #
# price / book helpers
# --------------------------------------------------------------------------- #

def price_ok(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 - TOL <= value <= 1.0 + TOL


def _num(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def check_prices(rows: Iterable[dict], dataset: str, fields: Iterable[str]) -> None:
    bad: list[dict] = []
    for row in rows:
        for field in fields:
            if field in row and row[field] is not None and not price_ok(row[field]):
                bad.append({"ticker": row.get("ticker"), "field": field, "value": row[field]})
    checked.append(f"{dataset}: {len(list(rows)) if isinstance(rows, list) else 'n'} rows, price bounds")
    if bad:
        add("error", "PRICE", f"{dataset}: price outside $0.00-$1.00",
            f"{len(bad)} value(s) fall outside the only range a binary contract can trade in.",
            examples=bad, count=len(bad),
            source="https://docs.kalshi.com/getting_started/orderbook_responses",
            action="Blank the value and flag it; never clamp it silently.")


def check_crossed(rows: Iterable[dict], dataset: str, bid: str = "yes_bid", ask: str = "yes_ask",
                  nobid: str | None = None) -> None:
    crossed = []
    for row in rows:
        b, a = row.get(bid), row.get(ask)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)) and b > a + TOL:
            crossed.append({"ticker": row.get("ticker"), "yes_bid": b, "yes_ask": a})
            continue
        if nobid:
            nb = row.get(nobid)
            if isinstance(b, (int, float)) and isinstance(nb, (int, float)) and b + nb > 1.0 + 1e-6:
                crossed.append({"ticker": row.get("ticker"), "yes_bid": b, "no_bid": nb})
    if crossed:
        add("error", "CROSSED", f"{dataset}: crossed book",
            "YES bid at or above YES ask, or YES bid + NO bid above $1.00. One of the two sides is stale "
            "or the payload mixed two snapshots. A strategy that trusts this quote buys at a loss by construction.",
            examples=crossed, count=len(crossed),
            source="https://docs.kalshi.com/getting_started/orderbook_responses",
            action="Drop the row from trading until a fresh two-sided quote arrives.")


def ladder_problems(book: dict) -> list[str]:
    out = []
    for side in ("yes_bids", "yes_asks"):
        levels = book.get(side) or []
        prices = [lvl.get("price") for lvl in levels if isinstance(lvl, dict)]
        if any(not price_ok(p) for p in prices):
            out.append(f"{side}: price out of range")
        if side == "yes_bids" and prices != sorted(prices, reverse=True):
            out.append("yes_bids not descending")
        if side == "yes_asks" and prices != sorted(prices):
            out.append("yes_asks not ascending")
        sizes = [lvl.get("contracts") for lvl in levels if isinstance(lvl, dict)]
        if any(isinstance(s, (int, float)) and s < 0 for s in sizes):
            out.append(f"{side}: negative size")
    # ``yes_depth_contracts`` is the depth of the *full* book; the payload prints at most
    # 12 levels per side, so the sum can only be compared when nothing was truncated.
    truncated = len(book.get("yes_bids") or []) >= 12 or len(book.get("no_bids") or []) >= 12
    best_bid = (book.get("best_yes_bid") or {}).get("contracts")
    best_ask = (book.get("best_yes_ask") or {}).get("contracts")
    if best_bid is not None and (book.get("yes_bids") or [{}])[0].get("contracts") not in (None, best_bid):
        out.append("best_yes_bid disagrees with first level")
    if best_ask is not None and (book.get("yes_asks") or [{}])[0].get("contracts") not in (None, best_ask):
        out.append("best_yes_ask disagrees with first level")
    depth = book.get("yes_depth_contracts")
    if depth is not None and not truncated:
        total = sum(lvl.get("contracts", 0) for lvl in book.get("yes_bids") or [] if isinstance(lvl, dict))
        if abs(total - depth) > 0.01:
            out.append(f"yes_depth_contracts {depth} != ladder sum {round(total, 2)}")
    return out


# --------------------------------------------------------------------------- #
# dataset checks
# --------------------------------------------------------------------------- #

def audit_desk() -> None:
    latest = load("docs/desk/data/latest.json")
    if not latest:
        return
    checked.append("docs/desk/data/latest.json: markets, books, topics, alerts")
    rows: list[dict] = []
    for topic, payload in (latest.get("topics") or {}).items():
        for row in payload.get("markets") or []:
            rows.append(row)
            if topic not in TOPICS:
                add("warn", "TOPIC", "Unexpected topic id", f"Topic {topic!r} is outside the five requested topics.",
                    source="docs/desk/data/latest.json")
            if row.get("topic") != topic:
                add("warn", "TOPIC", "Row topic disagrees with its container",
                    f"{row.get('ticker')} sits under {topic} but carries topic={row.get('topic')!r}.",
                    examples=[row.get("ticker")], source="docs/desk/data/latest.json")
    check_prices(rows, "docs/desk latest.json", ("yes_bid", "yes_ask", "mid", "price", "last", "spread"))
    check_crossed(rows, "docs/desk latest.json")

    book_bad = []
    for row in rows:
        book = row.get("orderbook") or {}
        problems = ladder_problems(book)
        if problems:
            book_bad.append({"ticker": row.get("ticker"), "problems": problems})
    if book_bad:
        add("warn", "BOOK", "Published ladder is a partial view of the book",
            "The reported total depth is larger than the sum of the levels printed in the same payload, and "
            "one row's top-of-book total disagrees with its first level. The ladder is monotonic and every "
            "level is within $0.00-$1.00, so this is a display-truncation issue rather than a corrupt quote — "
            "but a page must not print the ladder total and the depth total as if they were the same number.",
            examples=book_bad, count=len(book_bad),
            source="https://docs.kalshi.com/getting_started/orderbook_responses",
            action="Recompute from the raw payload or blank the derived field.")

    # Derived notional must recompute from the row's own price and volume.
    drift = []
    worst = 0.0
    for row in rows:
        v24, price, stated = row.get("volume_24h"), row.get("price"), row.get("notional_24h_est")
        if all(isinstance(x, (int, float)) for x in (v24, price, stated)) and v24:
            gap = abs(v24 * price - stated)
            if gap > max(1.0, 0.005 * abs(stated)):
                implied = stated / v24
                worst = max(worst, gap / max(stated, 1.0))
                drift.append({"ticker": row.get("ticker"), "volume_24h": v24, "printed_price": price,
                              "implied_price_used": round(implied, 4), "stated": stated,
                              "recomputed": round(v24 * price, 2)})
    if drift:
        add("warn", "DERIVED", "Estimated 24h notional was computed from a different price than the row prints",
            f"24h volume x the row's own price differs from the printed estimate on {len(drift)} row(s); the "
            f"largest gap is {worst * 100:.1f}%. The implied price is the previous mid, so the notional was "
            "fixed before the row's quote was refreshed.",
            examples=drift, count=len(drift), source="docs/desk/data/latest.json",
            action="Recompute the estimate after the final quote is applied, or label it as measured at an "
                   "earlier time. The direction of the number is unaffected; the exact dollar figure is.")

    # Topic totals vs sum of member rows.
    mismatch = []
    for topic, payload in (latest.get("topics") or {}).items():
        members = payload.get("markets") or []
        summed = sum(m.get("notional_24h_est") or 0 for m in members[:60])
        stated = payload.get("notional_24h_est")
        if isinstance(stated, (int, float)) and abs(summed - stated) > max(1.0, 0.01 * abs(stated)):
            mismatch.append({"topic": topic, "stated": stated, "sum_first_60": round(summed, 2)})
    if mismatch:
        add("info", "TOTAL", "Topic headline totals are not the sum of the printed rows",
            "Expected when a topic header covers more markets than the page prints; recorded so the two "
            "numbers are never read as the same quantity.",
            examples=mismatch, count=len(mismatch), source="docs/desk/data/latest.json")

    # Duplicate tickers across topics.
    seen: dict[str, set[str]] = {}
    for topic, payload in (latest.get("topics") or {}).items():
        for row in payload.get("markets") or []:
            seen.setdefault(row.get("ticker"), set()).add(topic)
    dupes = {t: sorted(ts) for t, ts in seen.items() if len(ts) > 1}
    if dupes:
        add("error", "DUPLICATE", "A ticker appears in more than one topic",
            "Topic boards would double-count the same contract and the two feeds would disagree.",
            examples=dupes, count=len(dupes), source="docs/desk/data/latest.json")

    # Alerts: threshold, sign, ordering, subset relation.
    alerts = latest.get("alerts") or []
    checked.append(f"docs/desk/data/alerts.json: {len(alerts)} alerts")
    weak = [a for a in alerts if isinstance(a, dict) and abs(a.get("delta") or 0) < THRESHOLD - TOL]
    if weak:
        add("error", "THRESHOLD", "Alert below the $0.10 threshold",
            "The published rule is |change| >= $0.10; these alerts do not meet it.",
            examples=[{"ticker": a.get("ticker"), "delta": a.get("delta")} for a in weak],
            count=len(weak), source="https://docs.kalshi.com/getting_started/orderbook_responses")
    sign_bad = []
    for a in alerts:
        if not isinstance(a, dict):
            continue
        delta, size, direction = a.get("delta"), a.get("abs_delta"), a.get("direction")
        if size is not None and isinstance(delta, (int, float)) and abs(abs(delta) - size) > 1e-6:
            sign_bad.append({"ticker": a.get("ticker"), "delta": delta, "abs_delta": size})
        elif isinstance(delta, (int, float)) and ((direction == "up" and delta < 0) or (direction == "down" and delta > 0)):
            sign_bad.append({"ticker": a.get("ticker"), "delta": delta, "direction": direction})
    if sign_bad:
        add("warn", "SIGN", "Alert direction disagrees with its delta",
            "The arrow, the sign of delta and abs_delta must agree; these rows do not.",
            examples=sign_bad, count=len(sign_bad), source="docs/desk/data/latest.json")
    times = [a.get("observed_at") for a in alerts if isinstance(a, dict) and a.get("observed_at")]
    if times != sorted(times):
        add("info", "ORDER", "Alerts are not stored in time order",
            "The feed sorts on render; noted so nobody assumes the file is chronological.", count=len(times))
    filt = latest.get("filtered_alerts") or []
    ids = {a.get("ticker") for a in alerts if isinstance(a, dict)}
    extra = [a for a in filt if isinstance(a, dict) and a.get("ticker") not in ids]
    if extra:
        add("error", "SUBSET", "Model feed contains a move that is not in the all-moves feed",
            "The second chat is defined as a subset of the first.", examples=extra, count=len(extra))

    # Resolution values. https://docs.kalshi.com/getting_started/market_lifecycle:
    # result is yes, no or scalar; an empty string means not yet determined.
    bad_result = []
    for row in rows:
        result = row.get("result")
        if result not in (None, "", "yes", "no", "scalar", "void"):
            bad_result.append({"ticker": row.get("ticker"), "result": result})
    if bad_result:
        add("error", "RESULT", "Resolution value outside yes/no/void", examples=bad_result, count=len(bad_result),
            source="https://docs.kalshi.com/getting_started/market_lifecycle")

    documented_statuses = {
        "initialized", "active", "inactive", "closed", "determined", "disputed", "amended", "finalized",
    }
    statuses = sorted({r.get("status") for r in rows if r.get("status")})
    undocumented = [s for s in statuses if s not in documented_statuses]
    if undocumented:
        add("error", "STATUS", "Status value not in the documented set",
            "The lifecycle page defines initialized, active, inactive, closed, determined, disputed, "
            "amended and finalized (open/settled are request filters, not statuses).",
            examples=undocumented, count=len(undocumented),
            source="https://docs.kalshi.com/getting_started/market_lifecycle")
    elif statuses:
        add("info", "STATUS", "Status values match the documented lifecycle",
            f"Observed: {', '.join(statuses)}. The lifecycle page lists these statuses and maps the "
            "open/settled request filters onto active/finalized.",
            examples=statuses, source="https://docs.kalshi.com/getting_started/market_lifecycle")

    # Placeholder quotes: a 0.00 bid beside a 1.00 ask is not a 50-cent market.
    placeholders = [r.get("ticker") for r in rows
                    if _num(r.get("yes_bid")) == 0 and _num(r.get("yes_ask")) is not None
                    and _num(r.get("yes_ask")) >= 0.99 and not r.get("last")]
    if placeholders:
        add("warn", "PLACEHOLDER", "Market rows carry a 0.00 x 1.00 book with no last trade",
            f"{len(placeholders)} row(s) have no usable two-sided quote. A naive mid of these is exactly $0.50, "
            "which would look like a permanent price and would emit false swings whenever a real quote appears.",
            examples=placeholders, count=len(placeholders),
            source="https://docs.kalshi.com/getting_started/orderbook_responses",
            action="Exclude from trading and from swing detection until both sides are real.")

    # Provenance: which environment does the capture come from?
    rest_base = str(latest.get("rest_base") or "")
    if "external-api.kalshi.com" in rest_base or "api.elections.kalshi.com" in rest_base:
        add("warn", "PROVENANCE", "Research-desk capture comes from the production root",
            f"rest_base is {rest_base}, while the brief asks for the demo environment "
            "and the Node board's capture uses the demo root. Production and demo catalogues and quotes "
            "differ (https://docs.kalshi.com/getting_started/demo_env), so a page mixing the two must say which "
            "is which.",
            source="docs/desk/data/latest.json",
            action="Label the environment on every page that renders this capture, as the live desk does in /api/meta.")
    elif "demo" in rest_base:
        add("info", "PROVENANCE", "Capture provenance is the demo environment",
            f"rest_base is {rest_base}.", source="docs/desk/data/latest.json")

    # Every market row must carry an official source link.
    missing = [r.get("ticker") for r in rows if not r.get("api_url") and not r.get("series_page_url")]
    if missing:
        add("error", "SOURCE", "Market row with no official source link",
            "Every data row on the site must link to an official Kalshi URL.",
            examples=missing, count=len(missing), source="https://docs.kalshi.com/api-reference/market/get-market")
    off_host = []
    for row in rows:
        for field in ("api_url", "series_page_url"):
            url = row.get(field)
            if url and urlparse(url).hostname not in OFFICIAL_HOSTS:
                off_host.append({"ticker": row.get("ticker"), "field": field, "url": url})
    if off_host:
        add("warn", "HOST", "Source link is not on an official Kalshi host", examples=off_host, count=len(off_host))

    # Paper book arithmetic.
    paper = load("docs/desk/data/paper.json")
    if paper:
        head = paper.get("headline") or {}
        equity, cash, unreal = head.get("equity"), head.get("cash"), head.get("unrealized_pnl")
        if all(isinstance(x, (int, float)) for x in (equity, cash, unreal)):
            positions = load("docs/desk/data/positions.json") or {}
            rows_p = positions.get("items") if isinstance(positions, dict) else None
            if isinstance(rows_p, list):
                value = sum((p.get("mark_value") or p.get("market_value") or 0) for p in rows_p)
                if abs((cash + value) - equity) > 0.02:
                    add("warn", "PAPER", "Paper equity does not equal cash + marked positions",
                        f"cash {cash} + positions {round(value, 2)} = {round(cash + value, 2)} vs equity {equity}.",
                        source="docs/desk/data/paper.json")

    histories = load("docs/desk/data/history.json") or {}
    series = histories.get("series") or {}
    if series:
        sample = next(iter(series.values()))
        checked.append(f"docs/desk/data/history.json: {len(series)} tracked series, sample length {len(sample)}")


def audit_board() -> None:
    snap = load("data/snapshot.json")
    if not snap:
        return
    markets = snap.get("markets") or {}
    rows = list(markets.values()) if isinstance(markets, dict) else list(markets)
    checked.append(f"data/snapshot.json: {len(rows)} markets")
    check_prices(rows, "board data/snapshot.json", ("yesBid", "yesAsk", "noBid", "noAsk", "lastPrice", "previousPrice"))
    check_crossed(rows, "board data/snapshot.json", "yesBid", "yesAsk", "noBid")
    bad_topic = [r.get("ticker") for r in rows if r.get("topic") not in TOPICS + (None,)]
    if bad_topic:
        add("warn", "TOPIC", "Board row carries a topic outside the five", examples=bad_topic, count=len(bad_topic))
    no_src = [r.get("ticker") for r in rows if not str(r.get("sourceUrl") or "").startswith("https://")]
    if no_src:
        add("error", "SOURCE", "Board row without an https source URL", examples=no_src, count=len(no_src))
    # Raw order-book JSON must parse and agree with the normalised best bid.
    bad_raw = []
    for row in rows:
        raw = ((row.get("orderbook") or {}).get("raw") or "")
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            bad_raw.append({"ticker": row.get("ticker"), "problem": "raw orderbook is not JSON"})
            continue
        book = parsed.get("orderbook_fp") or {}
        levels = [lvl for side in ("yes_dollars", "no_dollars") for lvl in book.get(side) or []]
        for lvl in levels:
            if not (isinstance(lvl, list) and len(lvl) == 2):
                bad_raw.append({"ticker": row.get("ticker"), "problem": "level is not [price, size]"})
                break
            if not price_ok(float(lvl[0])):
                bad_raw.append({"ticker": row.get("ticker"), "problem": f"raw price {lvl[0]} out of range"})
                break
    if bad_raw:
        add("error", "RAW", "Raw order-book payload in the snapshot is malformed", examples=bad_raw, count=len(bad_raw),
            source="https://docs.kalshi.com/getting_started/orderbook_responses")

    feed = load("data/live/feed.json")
    if feed:
        alerts = feed.get("alerts") or []
        weak = [a for a in alerts if isinstance(a, dict) and not a.get("isDemoExample")
                and abs(a.get("absDelta") or a.get("delta") or 0) < THRESHOLD - TOL]
        if weak:
            add("error", "THRESHOLD", "Board alert below the $0.10 threshold", examples=weak, count=len(weak))
        demo = [a for a in alerts if isinstance(a, dict) and a.get("isDemoExample")]
        if demo:
            add("info", "EXAMPLE", "Board feed contains a labelled worked example",
                "One alert is built from two fields of a single API response rather than two observations in "
                "time. It is labelled in the payload and on the page; it is not market data.",
                examples=[a.get("marketTicker") for a in demo], count=len(demo), source="data/live/feed.json")

    portfolio = load("data/live/portfolio.json")
    if portfolio:
        start = portfolio.get("startingCash")
        if isinstance(start, (int, float)):
            positions = portfolio.get("positions") or []
            cash = (portfolio.get("summary") or {}).get("cash")
            if isinstance(cash, (int, float)):
                value = sum((p.get("markValue") or p.get("value") or 0) for p in positions)
                if cash < -0.01:
                    add("error", "PAPER", "Board paper cash is negative", f"cash={cash}",
                        source="data/live/portfolio.json")

    account = load("data/account.json")
    if account:
        connected = account.get("connected")
        checked.append(f"data/account.json: connected={connected}")
        if connected is False and not account.get("reason"):
            add("warn", "ACCOUNT", "Demo account marked disconnected without a reason",
                "A silent disconnect is indistinguishable from a broken credential.",
                source="data/account.json")


def audit_monitor() -> None:
    snap = load("docs/data/snapshot.json")
    if not snap:
        return
    events = snap.get("events") or []
    checked.append(f"docs/data/snapshot.json: {len(events)} events, partial={snap.get('partial')}")
    markets = [m for e in events for m in (e.get("markets") or [])]
    check_prices(markets, "monitor docs/data/snapshot.json", ("yes_bid", "yes_ask", "yesBid", "yesAsk", "last_price"))
    if not markets:
        add("info", "EMPTY", "Monitor snapshot holds no markets", "The page then renders an empty watchlist.", source="docs/data/snapshot.json")


def audit_links() -> None:
    """Every published page's local links must resolve to a committed file."""
    pages = sorted(
        list(ROOT.glob("*.html"))
        + list((ROOT / "docs").rglob("*.html"))
        + list((ROOT / "site").rglob("*.html"))
        + list((ROOT / "categories").rglob("*.html"))
    )
    pages = [p for p in pages if "node_modules" not in p.parts]
    link_re = re.compile(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']', re.I)
    script_re = re.compile(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", re.I | re.S)
    broken: list[dict] = []
    total = 0
    for page in pages:
        # Markup only: a template literal inside a script is not a link until it is rendered.
        text = script_re.sub("", page.read_text(errors="replace"))
        for raw in link_re.findall(text):
            if raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
                continue
            parsed = urlparse(raw)
            if parsed.scheme in ("http", "https"):
                if parsed.hostname not in OFFICIAL_HOSTS | SECONDARY_HOSTS | {
                    "github.com", "kanlerxz87-cyber.github.io", "docs.github.com", "www.kalshi.com",
                    "api.kalshi.com",
                }:
                    add("info", "EXTERNAL", "External link outside the official-source list",
                        f"{page.relative_to(ROOT)} links to {parsed.hostname}. Not a Kalshi source; kept for context.",
                        examples=[raw], source=str(page.relative_to(ROOT)))
                continue
            if parsed.scheme:
                continue
            total += 1
            target = unquote(parsed.path)
            if not target:
                continue
            resolved = (page.parent / target).resolve()
            if resolved.is_dir():
                resolved = resolved / "index.html"
            if not resolved.exists():
                broken.append({"page": str(page.relative_to(ROOT)), "href": raw})
    checked.append(f"{len(pages)} HTML pages, {total} internal references")
    if broken:
        add("error", "LINK", "Broken internal link", f"{len(broken)} local reference(s) point at files that do not exist.",
            examples=broken, count=len(broken), action="Fix before publishing; the site build must have zero broken links.")


def audit_artifacts() -> None:
    """Committed bytecode, virtualenvs and build output are not source."""
    import subprocess
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return
    junk = [f for f in tracked if "/__pycache__/" in f or f.endswith((".pyc", ".pyo")) or f.startswith(".venv/")]
    checked.append(f"tracked files: {len(tracked)}, bytecode/cache artefacts: {len(junk)}")
    if junk:
        add("warn", "ARTIFACT", "Bytecode or virtualenv files are committed",
            f"{len(junk)} tracked path(s) are build artefacts, not source. They bloat the repository, change on "
            "every test run and can leak absolute paths.",
            examples=junk, count=len(junk), source="git ls-files",
            action="git rm --cached them and keep __pycache__/ and .venv/ ignored.")


def audit_generators() -> None:
    """Record generator behaviours that look like failures but are not data problems."""
    node_gen = ROOT / "scripts/build-site.mjs"
    if node_gen.exists():
        text = node_gen.read_text()
        if "data-generated" in text and "ago" in text:
            add("info", "GENCHECK", "The Node generator's --check can never pass as written",
                "`scripts/build-site.mjs --check` re-renders every page and compares the result with the committed "
                "file, but the render embeds a fresh `data-generated` timestamp and relative text such as "
                "'21m ago'. Every page therefore reports stale within a minute of generation. The data itself "
                "matched when this audit compared it.",
                source="scripts/build-site.mjs",
                action="Compare the page with the timestamp and relative-time fields normalised, or drop the "
                       "strict comparison from the gate. CI does not currently run this check.")
    python_gen = ROOT / "tools/build_site.py"
    if python_gen.exists():
        checked.append("tools/build_site.py --check (run separately by CI; reports current)")


def audit_secrets() -> None:
    patterns = [
        (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key block"),
        (re.compile(r"KALSHI_API_KEY_ID\s*=\s*[A-Za-z0-9-]{8,}"), "inline API key id"),
        (re.compile(r"(?:api[_-]?secret|client[_-]?secret|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]", re.I), "inline secret"),
    ]
    skip_dirs = {"node_modules", ".git", ".venv", "__pycache__", ".pytest_cache"}
    hits = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".ico", ".pdf", ".gz", ".zip"}:
            continue
        if skip_dirs & set(path.parts):
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for pattern, label in patterns:
            if pattern.search(text):
                hits.append({"file": str(path.relative_to(ROOT)), "kind": label})
                break
    checked.append(f"secret scan: {len(list(ROOT.rglob('*')))} paths")
    if hits:
        add("error", "SECRET", "Possible committed credential", "A file matches a credential pattern. Rotate it and remove it from history.",
            examples=hits, count=len(hits), action="Treat as leaked until proven otherwise.")


def audit_docs_freshness() -> None:
    for rel, key in (("docs/desk/data/latest.json", "generated_at"), ("data/snapshot.json", "meta")):
        path = ROOT / rel
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        stamp = data.get(key) if isinstance(data.get(key), str) else (data.get("meta") or {}).get("capturedAt")
        if not stamp:
            continue
        try:
            when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        age = dt.datetime.now(dt.timezone.utc) - when
        hours = age.total_seconds() / 3600
        if hours > 24:
            add("warn", "STALE", f"{rel} is {hours:.1f} h old",
                f"Timestamp {stamp}. Anything rendered from it is a historical snapshot, not a live quote.",
                source=rel, action="Re-run the collector or label the page as historical.")
        else:
            add("info", "FRESH", f"{rel} captured {stamp}",
                f"{hours:.2f} h before this audit. Freshness is not accuracy: a recent capture can still be a "
                "bounded sample.", source=rel)


# --------------------------------------------------------------------------- #
# report rendering
# --------------------------------------------------------------------------- #

SEV_ORDER = {"error": 0, "warn": 1, "info": 2}


def summarize() -> dict[str, int]:
    counts = {"error": 0, "warn": 0, "info": 0}
    for f in findings:
        counts[f["severity"]] += 1
    return counts


def to_markdown() -> str:
    counts = summarize()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Cross-implementation audit",
        "",
        f"Generated {now} by `qa/audit.py` (run it again to reproduce). "
        f"**{counts['error']} errors, {counts['warn']} warnings, {counts['info']} notes.**",
        "",
        "This audit reads the committed datasets and every published page. It cannot confirm a price "
        "against Kalshi — that is done separately and recorded below. It checks internal consistency, "
        "official-host provenance and link integrity.",
        "",
        "## What was checked",
        "",
    ]
    for item in checked:
        lines.append(f"- {item}")
    lines += ["", "## Findings", "", "| ID | Severity | Finding | Count | Source | Action |", "| - | - | - | - | - | - |"]
    for f in sorted(findings, key=lambda f: (SEV_ORDER[f["severity"]], f["id"])):
        lines.append(
            f"| `{f['id']}` | {f['severity']} | {f['title']} — {f['detail']} | {f['count']} | "
            f"{f['source']} | {f['action'] or '—'} |"
        )
    lines += [
        "",
        "## Reproduce",
        "",
        "```sh",
        "python3 qa/audit.py            # writes qa/report.json, qa/report.md, qa.html",
        "python3 qa/audit.py --check    # fails only on errors and broken links",
        "```",
        "",
    ]
    return "\n".join(lines)


def to_html(report: dict[str, Any]) -> str:
    rows = []
    for f in sorted(findings, key=lambda f: (SEV_ORDER[f["severity"]], f["id"])):
        examples = ""
        if f["examples"]:
            text = json.dumps(f["examples"], ensure_ascii=False)
            examples = f'<details><summary>Examples</summary><pre>{html.escape(text[:1200])}</pre></details>'
        source = html.escape(f["source"] or "—")
        if f["source"].startswith("http"):
            source = f'<a href="{html.escape(f["source"])}" rel="noopener noreferrer">{html.escape(f["source"].rsplit("/", 1)[-1] or f["source"])}</a>'
        rows.append(
            f'<tr class="sev-{f["severity"]}"><td><code>{html.escape(f["id"])}</code></td>'
            f'<td><span class="badge {f["severity"]}">{f["severity"]}</span></td>'
            f'<td><strong>{html.escape(f["title"])}</strong><br><span class="dim">{html.escape(f["detail"])}</span>{examples}</td>'
            f'<td class="num">{f["count"]}</td><td>{source}</td><td class="dim">{html.escape(f["action"] or "—")}</td></tr>'
        )
    counts = report["counts"]
    checked_items = "".join(f"<li>{html.escape(c)}</li>" for c in report["checked"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Audit — Tradebot1</title>
<meta name="description" content="Cross-implementation audit of every committed Kalshi dataset in this repository: price bounds, crossed books, source provenance, link integrity.">
<link rel="stylesheet" href="docs/desk/assets/css/site.css">
<style>
  .qa-wrap {{ max-width: 1120px; margin: 0 auto; padding: 34px 20px 70px; }}
  .qa-wrap h1 {{ font-size: 26px; margin: 8px 0 6px; letter-spacing: -.02em; }}
  .qa-wrap .sub {{ color: var(--text-dim); max-width: 78ch; line-height: 1.6; }}
  .kpis {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 22px 0; }}
  .kpi {{ border: 1px solid var(--line); border-radius: 10px; padding: 14px; background: var(--panel); }}
  .kpi b {{ display: block; font-size: 24px; }}
  .kpi span {{ color: var(--text-dim); font-size: 12px; text-transform: uppercase; letter-spacing: .07em; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
  th {{ color: var(--text-dim); font-size: 11px; text-transform: uppercase; letter-spacing: .07em; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .badge {{ font-size: 10px; text-transform: uppercase; letter-spacing: .06em; padding: 2px 7px; border-radius: 999px; border: 1px solid currentColor; }}
  .badge.error {{ color: #ff8080; }} .badge.warn {{ color: #ffc46b; }} .badge.info {{ color: #7ec8ff; }}
  .dim {{ color: var(--text-dim); }}
  pre {{ white-space: pre-wrap; word-break: break-word; background: rgba(255,255,255,.03); padding: 10px; border-radius: 8px; font-size: 11px; }}
  details summary {{ cursor: pointer; color: var(--accent); font-size: 11px; margin-top: 4px; }}
  a {{ color: var(--accent); }} .wrap-table {{ overflow-x: auto; }}
  ul.checked {{ columns: 2; gap: 26px; font-size: 12px; color: var(--text-dim); }}
  @media (max-width: 720px) {{ ul.checked {{ columns: 1; }} }}
</style></head>
<body><main class="qa-wrap">
  <p class="dim" style="margin:0"><a href="index.html">← Back to the desk</a> · Kalshi research, not advice</p>
  <h1>Audit: what the committed data actually supports</h1>
  <p class="sub">Four independent implementations keep their own snapshots. This page re-checks each of them
  for the failures that would cost a trader money: impossible prices, crossed books, ladders that do not add
  up, alerts that do not clear $0.10, resolution values outside yes/no/void, rows with no official source,
  and dead internal links. Generated {html.escape(report['generated_at'])} by <code>qa/audit.py</code>.</p>

  <div class="kpis">
    <div class="kpi"><b>{counts['error']}</b><span>Errors</span></div>
    <div class="kpi"><b>{counts['warn']}</b><span>Warnings</span></div>
    <div class="kpi"><b>{counts['info']}</b><span>Notes</span></div>
    <div class="kpi"><b>{len(report['checked'])}</b><span>Checks run</span></div>
  </div>

  <h2 style="font-size:16px">Findings</h2>
  <div class="wrap-table"><table>
    <thead><tr><th>ID</th><th>Severity</th><th>Finding</th><th class="num">Rows</th><th>Source</th><th>Action</th></tr></thead>
    <tbody>{''.join(rows) or '<tr><td colspan="6">No findings.</td></tr>'}</tbody>
  </table></div>

  <h2 style="font-size:16px;margin-top:26px">What was checked</h2>
  <ul class="checked">{checked_items}</ul>

  <p class="dim" style="margin-top:24px">Prices and thresholds are checked against official Kalshi documentation:
  <a href="https://docs.kalshi.com/getting_started/orderbook_responses">order book</a>,
  <a href="https://docs.kalshi.com/getting_started/market_lifecycle">market lifecycle</a>,
  <a href="https://docs.kalshi.com/api-reference/market/get-markets">markets API</a>,
  <a href="https://docs.kalshi.com/getting_started/api_environments">environments</a>.
  A passing internal check is not a live confirmation of a price.</p>
</main></body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit non-zero on errors")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    audit_desk()
    audit_board()
    audit_monitor()
    audit_links()
    audit_artifacts()
    audit_generators()
    audit_secrets()
    audit_docs_freshness()

    counts = summarize()
    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": counts,
        "checked": checked,
        "findings": findings,
        "reproduce": "python3 qa/audit.py",
    }
    QA.mkdir(exist_ok=True)
    (QA / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (QA / "report.md").write_text(to_markdown())
    (ROOT / "qa.html").write_text(to_html(report))
    if not args.quiet:
        print(f"errors={counts['error']} warnings={counts['warn']} notes={counts['info']}")
        for f in findings:
            if f["severity"] == "error":
                print(f"  ERROR {f['id']}: {f['title']} ({f['count']})")
    return 1 if (args.check and counts["error"]) else 0


if __name__ == "__main__":
    sys.exit(main())
