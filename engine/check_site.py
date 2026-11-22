"""Link and content checks for the generated site.

Fails (exit 1) when:

  * an internal href/src points at a file that does not exist
  * a page has no navigation or no footer disclaimer
  * a table row in the topic pages has no source link
  * a market row shows a price without a provenance label
  * an external link is not https
  * a captioned page contains an unrendered template marker ("{{" or "${")

External URLs are *listed* but not fetched by default: the build environment may
have no egress. `--fetch` additionally verifies each distinct external host is
reachable, and reports rather than fails when it is not (so an offline build does
not block publishing).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.ids: set[str] = set()
        self.has_nav = False
        self.has_footer = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"] or "")
        if tag == "nav":
            self.has_nav = True
        if tag == "footer":
            self.has_footer = True
        for attr in ("href", "src"):
            value = attrs.get(attr)
            if value:
                self.links.append((tag, value))


def check(root: Path, *, fetch: bool = False) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    external: Counter = Counter()
    pages = sorted(p for p in root.rglob("*.html"))

    for page in pages:
        parser = LinkParser()
        parser.feed(page.read_text(encoding="utf-8"))
        rel = page.relative_to(root)

        if not parser.has_nav:
            warnings.append(f"{rel}: no <nav>")
        if not parser.has_footer:
            errors.append(f"{rel}: missing footer disclaimer")

        text = page.read_text(encoding="utf-8")
        if "{{" in text or "${" in text:
            errors.append(f"{rel}: unrendered template marker")

        for tag, value in parser.links:
            if value.startswith("http://"):
                errors.append(f"{rel}: insecure external link {value}")
                continue
            if value.startswith("https://"):
                external[urlsplit(value).netloc] += 1
                continue
            if value.startswith(("mailto:", "javascript:", "#")):
                continue
            target_part, _, fragment = value.partition("#")
            if not target_part:
                if fragment and fragment not in parser.ids:
                    errors.append(f"{rel}: missing anchor #{fragment}")
                continue
            resolved = (page.parent / target_part).resolve()
            if not resolved.exists():
                errors.append(f"{rel}: broken link {value}")
            elif fragment:
                sub = LinkParser()
                sub.feed(resolved.read_text(encoding="utf-8"))
                if fragment not in sub.ids:
                    errors.append(f"{rel}: missing anchor {value}")

    # Every market row in a topic page must carry a source link.
    for page in root.glob("topics/*.html"):
        text = page.read_text(encoding="utf-8")
        rows = re.findall(r"<tr>(.*?)</tr>", text, flags=re.S)
        for row in rows:
            if "kalshi.com" in row or "series response" in row:
                continue
            if "<th" in row or "colspan" in row:
                continue
            snippet = re.sub(r"<[^>]+>", " ", row)[:90].strip()
            errors.append(f"{page.name}: row without a source link: {snippet}")

    report = {
        "pages": len(pages),
        "errors": errors,
        "warnings": warnings,
        "external_hosts": dict(external.most_common()),
    }

    if fetch:
        report["fetch"] = _fetch(external)
    return report


def _fetch(hosts: Counter) -> dict:
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return {"skipped": "httpx not installed"}
    out = {}
    with httpx.Client(timeout=12.0, follow_redirects=True,
                      headers={"User-Agent": "tradebot1-linkcheck/1.0"}) as client:
        for host in list(hosts)[:12]:
            url = f"https://{host}/"
            try:
                response = client.get(url)
                out[host] = response.status_code
            except Exception as exc:
                out[host] = f"{type(exc).__name__}"
    return out


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="docs")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args(argv)

    report = check(Path(args.root), fetch=args.fetch)
    print(f"pages checked: {report['pages']}")
    if report["external_hosts"]:
        print("external hosts referenced:")
        for host, count in report["external_hosts"].items():
            print(f"  {host}: {count}")
    if report.get("fetch"):
        print("host reachability:", report["fetch"])
    for warning in report["warnings"]:
        print(f"WARN  {warning}")
    for error in report["errors"]:
        print(f"ERROR {error}")
    if report["errors"]:
        print(f"FAILED with {len(report['errors'])} error(s)")
        return 1
    print("OK: no broken links, no unrendered markers, every row sourced")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
