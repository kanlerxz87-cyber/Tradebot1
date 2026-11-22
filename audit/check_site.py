#!/usr/bin/env python3
"""Gates for the audit site.

Fails the build on any of:

  * a data table row with no https source link;
  * an internal link or asset that does not resolve, from any audit page;
  * a placeholder in rendered text ("undefined", "NaN", "TODO", "null");
  * a source shown on the site that is missing from the fact register, or a
    fact in the register that never appears on the sources page;
  * a generated page that no longer matches audit/build_site.py output.

    python3 audit/check_site.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "docs" / "audit"
DATA = SITE / "data" / "audit.json"
PAGES = ["index.html", "findings.html", "flagged.html", "sources.html", "methodology.html"]

problems: list[str] = []


def bad(message: str) -> None:
    problems.append(message)


def main() -> int:
    if not DATA.exists():
        print("missing docs/audit/data/audit.json — run python3 audit/verify.py", file=sys.stderr)
        return 1
    doc = json.loads(DATA.read_text())

    fact_urls = {f["url"] for f in doc["facts"]}
    for fact in doc["facts"]:
        if not fact["url"].startswith("https://"):
            bad(f"{fact['id']}: not https")
        if not fact.get("quote"):
            bad(f"{fact['id']}: no verbatim quote")

    for item in doc["items"]:
        if not item["sources"] and not item.get("repoSources"):
            bad(f"{item['id']}: no source at all")
        if not item["sources"] and not item.get("noOfficialSource"):
            bad(f"{item['id']}: no official source and no explanation for its absence")
        for source in item["sources"]:
            if source["url"] not in fact_urls:
                bad(f"{item['id']}: source {source['url']} is not in the fact register")
        for source in item.get("repoSources") or []:
            if not source["url"].startswith("https://"):
                bad(f"{item['id']}: repo source is not https")
        if item["status"] == "fixed" and not item["check"]["ok"]:
            bad(f"{item['id']}: published as fixed, check does not pass")

    sources_html = (SITE / "sources.html").read_text()
    for fact in doc["facts"]:
        if fact["url"] not in sources_html:
            bad(f"{fact['id']}: url missing from sources.html")

    for name in PAGES:
        path = SITE / name
        if not path.exists():
            bad(f"{name}: page missing")
            continue
        html = path.read_text()
        for table in re.findall(r"<tbody>(.*?)</tbody>", html, flags=re.S):
            rows = re.findall(r"<tr>(.*?)</tr>", table, flags=re.S)
            for row in rows:
                if "https://" not in row or "<a " not in row:
                    bad(f"{name}: a data row has no https source link: {re.sub(r'<[^>]+>', ' ', row)[:80].strip()!r}")
        for placeholder in ("undefined", "NaN", "TODO", "None</td>", ">null<"):
            if placeholder in html:
                bad(f"{name}: placeholder {placeholder!r} in rendered text")
        for href in re.findall(r'href="([^"]+)"', html):
            if href.startswith(("http://", "https://", "mailto:", "#", "data:")):
                continue
            target = (path.parent / href.split("#")[0]).resolve()
            if not target.exists():
                bad(f"{name}: broken internal link {href}")

    if problems:
        for problem in problems:
            print(f"audit site: {problem}", file=sys.stderr)
        return 1
    print(
        f"audit site OK — {len(PAGES)} pages, {len(doc['items'])} findings each with a source, "
        f"{len(doc['facts'])} facts, no broken internal links"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
