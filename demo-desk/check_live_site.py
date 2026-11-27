#!/usr/bin/env python3
"""Strict integrity & link checker for live/ pages and verified_snapshot.json."""

from __future__ import annotations

import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

LIVE_DIR = Path(__file__).resolve().parent
REPO_ROOT = LIVE_DIR.parent

OFFICIAL_HOSTS = {
    "docs.kalshi.com",
    "external-api.demo.kalshi.co",
    "demo-api.kalshi.co",
    "demo.kalshi.co",
    "kalshi.com",
    "assets.kalshi.com",
    "gasprices.aaa.com",
    "www.congress.gov",
    "www.whitehouse.gov",
    "apnews.com",
    "www.pgatour.com",
    "www.billboard.com",
    "www.grammy.com",
    "api.exchange.coinbase.com",
    "www.cfbenchmarks.com",
    "github.com",
    "kanlerxz87-cyber.github.io",
}


class PageAuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.in_tbody = False
        self.in_tr = False
        self.current_tr_links: list[str] = []
        self.tbody_rows_links: list[list[str]] = []
        self.in_blank_td = False
        self.blank_td_text = ""
        self.blank_cells: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = dict(attrs)
        if ad.get("id"):
            self.ids.add(ad["id"])
        for k in ("href", "src"):
            val = ad.get(k)
            if val:
                self.links.append(val)
                if self.in_tbody and self.in_tr and k == "href":
                    self.current_tr_links.append(val)
        if tag == "tbody":
            self.in_tbody = True
        elif tag == "tr" and self.in_tbody:
            self.in_tr = True
            self.current_tr_links = []
        elif tag == "td" and ad.get("data-unverified-blank") == "true":
            self.in_blank_td = True
            self.blank_td_text = ""

    def handle_data(self, data: str) -> None:
        if self.in_blank_td:
            self.blank_td_text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.in_blank_td:
            self.in_blank_td = False
            self.blank_cells.append(self.blank_td_text)
        elif tag == "tr" and self.in_tbody and self.in_tr:
            self.in_tr = False
            self.tbody_rows_links.append(self.current_tr_links)
        elif tag == "tbody":
            self.in_tbody = False


def main() -> int:
    errors: list[str] = []
    snap = json.loads((LIVE_DIR / "data" / "verified_snapshot.json").read_text(encoding="utf-8"))
    allowed = {"Elections", "Golf", "Culture", "Crypto", "Gas Prices"}

    if set(snap["topics"]) != allowed:
        errors.append(f"Snapshot topics mismatch: {snap['topics']}")
    for m in snap["markets"]:
        if m["topic"] not in allowed:
            errors.append(f"Disallowed market topic on {m['ticker']}: {m['topic']}")
    for r in snap["resolutions"]:
        if r["topic"] not in allowed:
            errors.append(f"Disallowed resolution topic on {r['ticker']}: {r['topic']}")
    for f in snap["flagged_unverified"]:
        if f["verified_value"] != "":
            errors.append(f"Unverified flag {f['id']} must have blank verified_value, got {f['verified_value']!r}")

    pages = sorted(LIVE_DIR.rglob("*.html"))
    if len(pages) < 12:
        errors.append(f"Expected >=12 HTML pages under demo-desk/, found {len(pages)}")

    for js_file in sorted((LIVE_DIR / "assets").glob("*.mjs")):
        js_txt = js_file.read_text(encoding="utf-8")
        if "127.0.0.1" in js_txt or "localhost" in js_txt:
            errors.append(f"{js_file.relative_to(REPO_ROOT)}: must not contain hardcoded localhost/127.0.0.1")

    parsed_map: dict[Path, PageAuditParser] = {}
    for page in pages:
        p = PageAuditParser()
        p.feed(page.read_text(encoding="utf-8"))
        parsed_map[page] = p

    total_links = 0
    total_rows = 0
    for page, p in parsed_map.items():
        rel = page.relative_to(REPO_ROOT)
        for raw in p.links:
            total_links += 1
            if raw.startswith(("http://", "https://")):
                host = urlsplit(raw).netloc
                if host not in OFFICIAL_HOSTS:
                    errors.append(f"{rel}: untrusted external host {host} in {raw}")
                continue
            if raw.startswith(("mailto:", "data:", "javascript:", "#")):
                continue
            sp = urlsplit(raw)
            target = (page.parent / unquote(sp.path)).resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                errors.append(f"{rel}: broken local link {raw} -> {target}")

        for idx, row_links in enumerate(p.tbody_rows_links, start=1):
            total_rows += 1
            has_official = any(
                (urlsplit(u).netloc in OFFICIAL_HOSTS) if u.startswith("https://") else False
                for u in row_links
            )
            if not has_official:
                errors.append(f"{rel}: table tbody row #{idx} missing official https:// source link (got {row_links})")

        if page.parent.name == "flagged":
            if len(p.blank_cells) != len(snap["flagged_unverified"]):
                errors.append(f"{rel}: expected {len(snap['flagged_unverified'])} blank unverified cells, got {len(p.blank_cells)}")
            for cell in p.blank_cells:
                if cell.strip() != "":
                    errors.append(f"{rel}: unverified cell must be blank, found {cell!r}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(
        f"OK — {len(pages)} live/ HTML pages, {total_links} links verified, "
        f"{total_rows} table rows verified with official sources, "
        f"{len(snap['flagged_unverified'])} blank unverified cells confirmed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
