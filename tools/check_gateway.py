#!/usr/bin/env python3
"""Gate for the root gateway page.

The gateway (`index.html`) is hand-written rather than generated, so it is not covered by
`tools/build_site.py --check` (desk), `scripts/build-site.mjs --check` (board) or
`engine/check_site.py` (engine). It is the first page a visitor sees on GitHub Pages, so a
dead card there is a broken site. This check fails when:

  * a relative link or asset does not exist in the repository,
  * a card points outside the published paths, or
  * the page is missing the required disclaimers (demo/paper only, official sources).

    python3 tools/check_gateway.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATEWAY = ROOT / "index.html"

# Paths published by the Pages workflows. A relative link outside these is dead on the
# live site even when the file exists in the repository.
PUBLISHED_PREFIXES = ("docs/", "site/", "demo-desk/", "terminal/", "assets/", "categories/", "data/", "board.html", "dashboard.html")
# Every root-level .html file is staged by the Pages workflow (`cp ./*.html public/`), so the
# published set is derived from the repository instead of being listed by hand.
PUBLISHED_ROOT_PAGES = {
    path.name for path in Path(__file__).resolve().parent.parent.glob("*.html")
} | {
    "index.html",
    "board.html",
    "dashboard.html",
    "markets.html",
    "market.html",
    "portfolio.html",
    "strategies.html",
    "demo-account.html",
    "executive-summary.html",
    "sources.html",
    "methodology.html",
    "suggestions.html",
    "flagged.html",
    "api.html",
    "404.html",
}

LINK = re.compile(r'(?:href|src)="([^"]+)"')


def resolves(target: str) -> bool:
    path = target.split("#", 1)[0].split("?", 1)[0]
    if not path or path in (".", "./"):
        return True  # pure anchor / self-reference
    if path.endswith("/"):
        return (ROOT / path / "index.html").is_file()
    return (ROOT / path).exists()


def is_published(target: str) -> bool:
    path = target.split("#", 1)[0].split("?", 1)[0]
    if path in (".", "./", ""):
        return True
    if path in PUBLISHED_ROOT_PAGES:
        return True
    return any(path.startswith(prefix) for prefix in PUBLISHED_PREFIXES)


def main() -> int:
    if not GATEWAY.is_file():
        print("FAIL: index.html missing", file=sys.stderr)
        return 1
    html = GATEWAY.read_text(encoding="utf-8")

    problems: list[str] = []
    checked = 0
    for raw in LINK.findall(html):
        if raw.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if raw.startswith("'") or raw.startswith('"'):
            continue  # a JS expression inside an inline script, not a rendered link
        checked += 1
        if not resolves(raw):
            problems.append(f"dead local link: {raw}")
        elif not is_published(raw):
            problems.append(f"exists but is not published by the Pages workflow: {raw}")

    for required, why in (
        ("docs/desk/", "the research desk"),
        ("board.html", "the trade board"),
        ("docs/engine/", "the engine verification site"),
        ("docs/", "the market monitor"),
        ("docs/desk/flagged.html", "the desk's flagged-for-review page"),
        ("https://docs.kalshi.com/getting_started/api_environments", "the official API docs"),
    ):
        if required not in html:
            problems.append(f"gateway does not link to {why} ({required})")

    lowered = html.lower()
    if "paper" not in lowered or "no production order path" not in lowered:
        problems.append("gateway is missing the demo/paper-only disclaimer")
    if "flagged for review" not in lowered:
        problems.append("gateway is missing a link to the Flagged for review page")

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"OK: gateway links resolve and are published ({checked} local targets checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
