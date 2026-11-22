#!/usr/bin/env python3
"""Fail the build on any broken internal link, anywhere in the repository.

Why this exists
---------------
Six independent implementations now live side by side (`site/`, `docs/`, `docs/desk/`,
`docs/engine/`, `docs/audit/`, the root board, `audit/`). Each one has its own link checker, and
each checker only walks its own directory. That leaves the seams unchecked: a link from the root
landing page into the desk, from the desk into the monitor, from the audit page into the engine
site. A page can therefore pass every per-site gate and still ship a 404.

This gate walks every HTML file in the repository and resolves every internal `href`/`src`,
including anchors, so the seams are covered too.

External links are deliberately not fetched: that would make CI slow and flaky, and a reachable
URL is not evidence that the page says what we claim. They are covered by the source registers.

Usage:
    python tools/check_all_links.py            # exit 1 on any broken link
    python tools/check_all_links.py --verbose  # also print the per-page counts
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
# `root` is a module-level variable so tests can point the gate at a fixture tree.


# Directories that are build output, dependencies or version-control metadata. They are not
# published site content, so links inside them are not part of the deployed site.
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "public", "dist", "build", "out", "coverage",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".arena", ".cache",
    # The FastAPI UI in app/static/ is served by a live server with its own /static and /api
    # mounts. It is not published by GitHub Pages, so its server-absolute URLs are not site links.
    "app/static",
}
# The published site is served under /Tradebot1/, so an absolute path may carry that prefix.
SITE_PREFIXES = ("/Tradebot1/",)
# Link types that never point at a file in this repository.
EXTERNAL_SCHEMES = ("http://", "https://", "//", "mailto:", "data:", "javascript:", "tel:", "ftp:")


class PageParser(HTMLParser):
    """Collects internal links, fragment targets and the ids/name anchors on a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        identifier = attrs.get("id")
        if identifier:
            self.ids.add(identifier)
        if tag == "a" and attrs.get("name"):
            self.ids.add(attrs["name"])
        for attribute in ("href", "src"):
            value = attrs.get(attribute)
            if value:
                self.links.append((attribute, value.strip()))


SKIP_PATHS = {(ROOT / name).resolve() for name in SKIP_DIRS}


def is_skipped(path: Path) -> bool:
    return any(parent in SKIP_PATHS for parent in path.parents)


def html_pages() -> list[Path]:
    return [path for path in sorted(ROOT.rglob("*.html")) if not is_skipped(path)]


def parse(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser


def collect_ids(value, found: set[str]) -> None:
    """Gather every `id` value in a decoded JSON document, at any depth."""
    if isinstance(value, dict):
        identifier = value.get("id")
        if isinstance(identifier, str):
            found.add(identifier)
        for item in value.values():
            collect_ids(item, found)
    elif isinstance(value, list):
        for item in value:
            collect_ids(item, found)


def runtime_ids(page: Path) -> set[str]:
    """Anchors a page creates at runtime from a data file it loads.

    Several pages render their rows in the browser from `data/*.json` and use the record id as the
    anchor. Those anchors are real for a visitor but invisible to a static parser, so the checker
    reads the same files the page does. A page that names no data file gets no allowance.
    """
    found: set[str] = set()
    sources: set[Path] = {page}
    parser = parse(page)
    for attribute, raw in parser.links:
        if attribute != "src" or raw.startswith(EXTERNAL_SCHEMES):
            continue
        target, _fragment, error = resolve(page, raw)
        if error or target is None or not target.exists():
            continue
        sources.add(target)
    for source in sources:
        if source.suffix.lower() not in {".html", ".js", ".mjs"}:
            continue
        text = source.read_text(encoding="utf-8", errors="replace")
        for name in set(re.findall(r"data/[A-Za-z0-9_.\-/]+\.json", text)):
            data_file = (ROOT / name) if not name.startswith("/") else (ROOT / name.lstrip("/"))
            if data_file.exists():
                try:
                    collect_ids(json.loads(data_file.read_text(encoding="utf-8")), found)
                except (OSError, ValueError):
                    continue
    return found


def resolve(page: Path, raw: str) -> tuple[Path | None, str, str | None]:
    """Return (resolved target or None if external, fragment, problem)."""
    if raw.startswith(EXTERNAL_SCHEMES) or raw.startswith("#"):
        if raw.startswith("#"):
            return page, unquote(raw[1:]), None
        return None, "", None

    split = urlsplit(raw)
    path_part = unquote(split.path)
    fragment = unquote(split.fragment) if split.fragment else ""

    if path_part.startswith("/"):
        for prefix in SITE_PREFIXES:
            if path_part.startswith(prefix):
                path_part = path_part[len(prefix):]
                break
        else:
            path_part = path_part.lstrip("/")
        target = (ROOT / path_part).resolve()
        if not str(target).startswith(str(ROOT)):
            return None, fragment, f"absolute path escapes the repository: {raw}"
    else:
        target = (page.parent / path_part).resolve() if path_part else page
        if not str(target).startswith(str(ROOT)):
            return None, fragment, f"relative path escapes the repository: {raw}"

    if target.is_dir():
        target = target / "index.html"
    return target, fragment, None


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    global ROOT, SKIP_PATHS
    if root is not None:
        ROOT = Path(root).resolve()
        SKIP_PATHS = {(ROOT / name).resolve() for name in SKIP_DIRS}

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    pages = html_pages()
    if not pages:
        print("no HTML pages found", file=sys.stderr)
        return 1

    parsed: dict[Path, PageParser] = {}
    problems: list[str] = []
    checked = 0
    per_page: list[tuple[Path, int]] = []

    for page in pages:
        parser = parse(page)
        parsed[page] = parser
        count = 0
        for attribute, raw in parser.links:
            if raw.startswith(EXTERNAL_SCHEMES):
                continue
            target, fragment, error = resolve(page, raw)
            if error:
                problems.append(f"{page.relative_to(ROOT)} → {raw} ({error})")
                continue
            if target is None:
                continue
            checked += 1
            count += 1
            if not target.exists():
                problems.append(f"{page.relative_to(ROOT)} → {raw} (missing {target.relative_to(ROOT)})")
                continue
            if fragment and target.suffix.lower() in {".html", ".htm"}:
                ids = parsed[target].ids if target in parsed else parse(target).ids
                if fragment not in ids and fragment not in runtime_ids(target):
                    problems.append(
                        f"{page.relative_to(ROOT)} → {raw} (no element #{fragment} in {target.relative_to(ROOT)})"
                    )
        per_page.append((page, count))

    if args.verbose:
        for page, count in per_page:
            print(f"{count:4d}  {page.relative_to(ROOT)}")

    if problems:
        print(f"{len(problems)} broken internal link(s) across {len(pages)} pages:", file=sys.stderr)
        for problem in problems:
            print("  -", problem, file=sys.stderr)
        return 1

    print(f"OK — {checked} internal links across {len(pages)} HTML pages, no broken target or anchor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
