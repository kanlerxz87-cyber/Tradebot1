#!/usr/bin/env python3
"""Fail the build on any broken internal link or missing anchor.

GitHub Pages has no server-side validation, so this runs in CI and before deploy.
External links are not fetched (that would make CI flaky and slow); they are listed in the
source register with a check date instead.
"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs and attrs["id"]:
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("name"):
            self.ids.add(attrs["name"])
        for key in ("href", "src"):
            value = attrs.get(key)
            if value:
                self.links.append((key, value))


def collect(path: Path) -> LinkParser:
    parser = LinkParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    pages = sorted(DOCS.rglob("*.html"))
    if not pages:
        print("no HTML pages found", file=sys.stderr)
        return 1

    parsed = {page: collect(page) for page in pages}
    problems: list[str] = []
    checked = 0

    for page, parser in parsed.items():
        for attr, raw in parser.links:
            if raw.startswith(("http://", "https://", "mailto:", "data:", "javascript:", "tel:")):
                continue
            if raw.startswith("//"):
                continue
            checked += 1
            split = urlsplit(raw)
            target_part = split.path
            fragment = unquote(split.fragment)

            if target_part in ("", "."):
                target = page
            else:
                target = (page.parent / unquote(target_part)).resolve()
                if target.is_dir():
                    target = target / "index.html"

            try:
                target.relative_to(DOCS)
            except ValueError:
                problems.append(f"{page.relative_to(ROOT)} → {raw} escapes docs/")
                continue

            if not target.exists():
                problems.append(f"{page.relative_to(ROOT)} → {raw} (missing {target.relative_to(ROOT)})")
                continue

            if fragment and target.suffix == ".html":
                target_ids = parsed.get(target).ids if target in parsed else collect(target).ids
                if fragment not in target_ids:
                    problems.append(
                        f"{page.relative_to(ROOT)} → {raw} (missing anchor #{fragment} in {target.relative_to(ROOT)})"
                    )

    # Structural checks that keep the verification promise honest.
    for page in pages:
        text = page.read_text(encoding="utf-8")
        if "<title>" not in text or text.count("<main") != 1:
            problems.append(f"{page.relative_to(ROOT)}: missing <title> or <main>")
        if "docs.kalshi.com" not in text and page.name not in {"index.html"}:
            problems.append(f"{page.relative_to(ROOT)}: no link to an official Kalshi source")

    if args.verbose:
        print(f"checked {checked} internal links across {len(pages)} pages")

    if problems:
        print(f"{len(problems)} link problem(s):", file=sys.stderr)
        for problem in problems:
            print("  -", problem, file=sys.stderr)
        return 1

    print(f"OK — {checked} internal links across {len(pages)} pages, no broken targets or anchors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
