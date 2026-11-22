#!/usr/bin/env python3
"""Print a Markdown summary of the current capture for a GitHub Actions job summary.

Reads docs/live/data/live.json and writes only what the file actually contains: no counts are
inferred, and a missing file is reported as missing rather than as zero.
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "live.json"


def main() -> int:
    if not PATH.exists():
        print("- no capture file")
        return 0
    data = json.loads(PATH.read_text())
    coverage = data.get("coverage", {})
    print(f"- generated_at: `{data.get('generated_at')}`")
    print(f"- seed file: {data.get('seed', False)}")
    print(
        f"- events: {coverage.get('events_carried')} &middot; markets: {coverage.get('markets_carried')} "
        f"&middot; books: {coverage.get('books_fetched')} &middot; resolutions: {coverage.get('resolutions_carried')}"
    )
    print(
        f"- requests: {coverage.get('requests')} &middot; errors: {len(data.get('errors') or [])} "
        f"&middot; partial: {coverage.get('partial')}"
    )
    for topic in data.get("topics", []):
        print(f"  - {topic.get('label')}: {topic.get('event_count')} events, {topic.get('market_count')} markets")
    for error in (data.get("errors") or [])[:10]:
        print(f"- error: `{error.get('label')}` {error.get('status')} {error.get('error')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
