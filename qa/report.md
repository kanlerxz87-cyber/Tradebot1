# Cross-implementation audit

Generated 2026-11-27T19:57:16Z by `qa/audit.py` (run it again to reproduce). **0 errors, 2 warnings, 4 notes.**

This audit reads the committed datasets and every published page. It cannot confirm a price against Kalshi — that is done separately and recorded below. It checks internal consistency, official-host provenance and link integrity.

## What was checked

- docs/desk/data/latest.json: markets, books, topics, alerts
- docs/desk latest.json: 0 rows, price bounds
- docs/desk/data/alerts.json: 0 alerts
- data/snapshot.json: 8 markets
- board data/snapshot.json: 8 rows, price bounds
- data/account.json: connected=False
- docs/data/snapshot.json: 28 events, partial=True
- monitor docs/data/snapshot.json: 207 rows, price bounds
- 74 HTML pages, 1361 internal references
- tracked files: 414, bytecode/cache artefacts: 0
- tools/build_site.py --check (run separately by CI; reports current)
- secret scan: 6978 paths

## Findings

| ID | Severity | Finding | Count | Source | Action |
| - | - | - | - | - | - |
| `FLAKY-1` | warn | An audit gate pins line numbers in a concurrently edited file — 1 evidence reference(s) cite COORDINATION.md by line number, and `audit/build_site.py --check` fails whenever that number shifts. Every session that appends to the board therefore breaks another session's build until the page is regenerated. | 1 | docs/audit/findings.html | Cite the section heading or a stable quote instead of a line number, or exclude the reference from the staleness comparison. |
| `STALE-1` | warn | data/snapshot.json is 133.0 h old — Timestamp 2026-11-22T07:00:00Z. Anything rendered from it is a historical snapshot, not a live quote. | 0 | data/snapshot.json | Re-run the collector or label the page as historical. |
| `EXTERNAL-1` | info | External link outside the official-source list — dashboard.html links to www.cfbenchmarks.com. Not a Kalshi source; kept for context. | 1 | dashboard.html | — |
| `EXTERNAL-2` | info | External link outside the official-source list — dashboard.html links to www.livgolf.com. Not a Kalshi source; kept for context. | 1 | dashboard.html | — |
| `EXTERNAL-3` | info | External link outside the official-source list — docs/engine/verification.html links to api.github.com. Not a Kalshi source; kept for context. | 1 | docs/engine/verification.html | — |
| `GENCHECK-1` | info | The Node generator's --check can never pass as written — `scripts/build-site.mjs --check` re-renders every page and compares the result with the committed file, but the render embeds a fresh `data-generated` timestamp and relative text such as '21m ago'. Every page therefore reports stale within a minute of generation. The data itself matched when this audit compared it. | 0 | scripts/build-site.mjs | Compare the page with the timestamp and relative-time fields normalised, or drop the strict comparison from the gate. CI does not currently run this check. |

## Reproduce

```sh
python3 qa/audit.py            # writes qa/report.json, qa/report.md, qa.html
python3 qa/audit.py --check    # fails only on errors and broken links
```
