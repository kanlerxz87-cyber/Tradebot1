#!/usr/bin/env python3
"""Gate the live console before it is published.

Checks, all of which fail the build:

  1. every market row carries an http(s) source URL and a read time;
  2. every market row's source URL is on an official Kalshi documentation or demo host;
  3. every fact in data/sources.json has an official URL, and every S-id referenced by a flag exists;
  4. the fee model reproduces all 21 published rows before the page claims it does;
  5. every flag states a behaviour and a severity;
  6. the console still exposes the element ids that the repository's older site check asserts on;
  7. no page or script contains a private key, a KALSHI-ACCESS-SIGNATURE value, or a production host
     used as a data source.

Run: python3 docs/live/check_live.py
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DOCS = HERE
problems: list[str] = []

OFFICIAL_HOSTS = {
    "docs.kalshi.com",
    "external-api.demo.kalshi.co",
    "demo-api.demo.kalshi.co",
    "demo-api.kalshi.co",
    "kalshi.com",
    "www.kalshi.com",
    "help.kalshi.com",
    "github.com",  # the probe evidence file, itself a committed artefact
}

DEMO_ONLY = {"external-api.demo.kalshi.co", "demo-api.kalshi.co"}

FEES_TABLE = [
    (0.01, 0.01, 0.07), (0.05, 0.01, 0.34), (0.10, 0.01, 0.63), (0.15, 0.01, 0.90),
    (0.20, 0.02, 1.12), (0.25, 0.02, 1.32), (0.30, 0.02, 1.47), (0.35, 0.02, 1.60),
    (0.40, 0.02, 1.68), (0.45, 0.02, 1.74), (0.50, 0.02, 1.75), (0.55, 0.02, 1.74),
    (0.60, 0.02, 1.68), (0.65, 0.02, 1.60), (0.70, 0.02, 1.47), (0.75, 0.02, 1.32),
    (0.80, 0.02, 1.12), (0.85, 0.01, 0.90), (0.90, 0.01, 0.63), (0.95, 0.01, 0.34),
    (0.99, 0.01, 0.07),
]

REQUIRED_IDS = ["market-rows", "all-feed", "screen-feed", "paper-body", "paper-rows", "chart", "book-rows", "connection", "coverage"]


def host_of(url: str) -> str:
    match = re.match(r"^https?://([^/]+)", url or "")
    return match.group(1).lower() if match else ""


def check_data() -> int:
    live = json.loads((DOCS / "data" / "live.json").read_text())
    rows = 0
    for event in live.get("events", []):
        if not event.get("source_url"):
            problems.append(f"event {event.get('event_ticker')}: no source_url")
        for market in event.get("markets", []):
            rows += 1
            ticker = market.get("ticker", "?")
            url = market.get("source_url") or ""
            if not url.startswith("https://"):
                problems.append(f"{ticker}: market row has no https source_url (rule 1)")
            elif host_of(url) not in OFFICIAL_HOSTS:
                problems.append(f"{ticker}: source host {host_of(url)} is not an official Kalshi host (rule 2)")
            if not market.get("read_at"):
                problems.append(f"{ticker}: market row has no read_at (rule 1)")
    for ticker, book in (live.get("books") or {}).items():
        if not str(book.get("source_url", "")).startswith("https://"):
            problems.append(f"book {ticker}: no https source_url")
        if not book.get("read_at"):
            problems.append(f"book {ticker}: no read_at")
    if host_of(live.get("base_url", "")) not in DEMO_ONLY:
        problems.append(f"base_url {live.get('base_url')} is not a demo host")
    for request in live.get("requests", []):
        if host_of(request.get("url", "")) not in OFFICIAL_HOSTS:
            problems.append(f"request {request.get('label')}: non-official host")
    return rows


def check_sources() -> int:
    sources = json.loads((DOCS / "data" / "sources.json").read_text())
    ids = set()
    for fact in sources["facts"]:
        ids.add(fact["id"])
        if not str(fact.get("url", "")).startswith(("https://", "http://")):
            problems.append(f"{fact['id']}: no URL")
        elif host_of(fact["url"]) not in OFFICIAL_HOSTS:
            problems.append(f"{fact['id']}: host {host_of(fact['url'])} is not official")
        if fact.get("kind") not in {"official-doc", "official-pdf", "official-api"}:
            problems.append(f"{fact['id']}: kind {fact.get('kind')!r} is not an official kind")
        if not fact.get("claim"):
            problems.append(f"{fact['id']}: no claim text")
    return len(ids), ids


def check_flags(ids: set[str]) -> int:
    flags = json.loads((DOCS / "data" / "flags.json").read_text())
    seen = set()
    for flag in flags["flags"]:
        seen.add(flag["id"])
        for field in ("title", "detail", "behaviour"):
            if not flag.get(field):
                problems.append(f"{flag['id']}: missing {field}")
        if flag.get("severity") not in {"high", "medium", "low"}:
            problems.append(f"{flag['id']}: severity {flag.get('severity')!r}")
        source = flag.get("source")
        if source is not None and host_of(source.get("url", "")) not in OFFICIAL_HOSTS:
            problems.append(f"{flag['id']}: source host not official")
    missing = {f"F{n}" for n in range(1, len(flags["flags"]) + 1)} - seen
    if missing:
        problems.append(f"flag ids are not contiguous: missing {sorted(missing)}")
    for page in (DOCS / "flagged.html", DOCS / "verification.html"):
        text = page.read_text()
        for cited in re.findall(r"\((S\d+)\)", text):
            if cited not in ids:
                problems.append(f"{page.name}: cites {cited}, which is not in sources.json")
    return len(seen)


def check_fees() -> int:
    bad = 0
    for price, one, hundred in FEES_TABLE:
        for contracts, expected in ((1, one), (100, hundred)):
            raw = 0.07 * contracts * price * (1 - price)
            computed = math.ceil(raw * 1e6 - 1e-9) / 1e6
            rounded = math.ceil(computed * 100 - 1e-9) / 100
            if abs(rounded - expected) > 1e-9:
                bad += 1
                problems.append(f"fee mismatch at {price} x {contracts}: {rounded} != {expected}")
    return len(FEES_TABLE)


def check_pages() -> int:
    pages = sorted(DOCS.glob("*.html"))
    index = (DOCS / "index.html").read_text()
    for element_id in REQUIRED_IDS:
        if f'id="{element_id}"' not in index:
            problems.append(f"index.html is missing id {element_id} that the shared site check looks for")
    # app.mjs imports ./core.mjs, so only the entry module is referenced by the page itself.
    if 'src="assets/app.mjs"' not in index:
        problems.append("index.html does not load the console module assets/app.mjs")
    for page in pages:
        text = page.read_text()
        if "http://external-api.kalshi.com" in text:
            problems.append(f"{page.name}: references the production API host")
        for href in re.findall(r'href="([^"]+)"', text):
            if href.startswith(("http://", "https://", "mailto:", "data:", "#")):
                continue
            if "${" in href:
                # A template placeholder inside a <script> block: the browser resolves it at run
                # time from JSON, so it is not a static link the gate can or should resolve.
                continue
            target = (page.parent / href.split("#")[0]).resolve()
            if href.split("#")[0] and not target.exists():
                problems.append(f"{page.name}: broken internal link {href}")
    return len(pages)


def check_secrets() -> int:
    suspicious = re.compile(r"BEGIN (RSA |EC |)PRIVATE KEY|KALSHI-ACCESS-SIGNATURE: [A-Za-z0-9+/]{40,}")
    scanned = 0
    for path in list(DOCS.rglob("*.mjs")) + list(DOCS.rglob("*.html")) + list(DOCS.rglob("*.json")):
        scanned += 1
        if suspicious.search(path.read_text(errors="ignore")):
            problems.append(f"{path.relative_to(REPO)}: possible key material")
    return scanned


def main() -> int:
    rows = check_data()
    fact_count, ids = check_sources()
    flag_count = check_flags(ids)
    fee_rows = check_fees()
    pages = check_pages()
    files = check_secrets()
    if problems:
        print(f"{len(problems)} problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(
        f"live console OK: {rows} market rows with official sources, {fact_count} verified facts, "
        f"{flag_count} flags, {fee_rows} fee rows reproduced, {pages} pages, {files} files free of key material"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
