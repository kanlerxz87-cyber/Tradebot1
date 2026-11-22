# Cross-implementation audit

Generated 2026-11-22T07:55:54Z by `qa/audit.py` (run it again to reproduce). **0 errors, 4 warnings, 8 notes.**

This audit reads the committed datasets and every published page. It cannot confirm a price against Kalshi — that is done separately and recorded below. It checks internal consistency, official-host provenance and link integrity.

## What was checked

- docs/desk/data/latest.json: markets, books, topics, alerts
- docs/desk latest.json: 300 rows, price bounds
- docs/desk/data/alerts.json: 1 alerts
- docs/desk/data/history.json: 62 tracked series, sample length 2
- data/snapshot.json: 8 markets
- board data/snapshot.json: 8 rows, price bounds
- data/account.json: connected=False
- docs/data/snapshot.json: 28 events, partial=True
- monitor docs/data/snapshot.json: 207 rows, price bounds
- 74 HTML pages, 1360 internal references
- tracked files: 332, bytecode/cache artefacts: 0
- tools/build_site.py --check (run separately by CI; reports current)
- secret scan: 7266 paths

## Findings

| ID | Severity | Finding | Count | Source | Action |
| - | - | - | - | - | - |
| `BOOK-1` | warn | Published ladder is a partial view of the book — The reported total depth is larger than the sum of the levels printed in the same payload, and one row's top-of-book total disagrees with its first level. The ladder is monotonic and every level is within $0.00-$1.00, so this is a display-truncation issue rather than a corrupt quote — but a page must not print the ladder total and the depth total as if they were the same number. | 8 | https://docs.kalshi.com/getting_started/orderbook_responses | Recompute from the raw payload or blank the derived field. |
| `DERIVED-1` | warn | Estimated 24h notional was computed from a different price than the row prints — 24h volume x the row's own price differs from the printed estimate on 15 row(s); the largest gap is 32.2%, on a 15-minute crypto market where the quote moved far between the two reads. The implied price is an earlier mid, so the notional was fixed before the row's quote was refreshed. On slow markets the error is a cent or two; on fast ones it is material. | 15 | docs/desk/data/latest.json | Recompute the estimate after the final quote is applied, or label it as measured at an earlier time. The direction of the number is unaffected; the exact dollar figure is. |
| `FLAKY-1` | warn | An audit gate pins line numbers in a concurrently edited file — 1 evidence reference(s) cite COORDINATION.md by line number, and `audit/build_site.py --check` fails whenever that number shifts. Every session that appends to the board therefore breaks another session's build until the page is regenerated. | 1 | docs/audit/findings.html | Cite the section heading or a stable quote instead of a line number, or exclude the reference from the staleness comparison. |
| `PROVENANCE-1` | warn | Research-desk capture comes from the production root — rest_base is https://external-api.kalshi.com/trade-api/v2, while the brief asks for the demo environment and the Node board's capture uses the demo root. Production and demo catalogues and quotes differ (https://docs.kalshi.com/getting_started/demo_env), so a page mixing the two must say which is which. | 0 | docs/desk/data/latest.json | Label the environment on every page that renders this capture, as the live desk does in /api/meta. |
| `EXTERNAL-1` | info | External link outside the official-source list — dashboard.html links to www.cfbenchmarks.com. Not a Kalshi source; kept for context. | 1 | dashboard.html | — |
| `EXTERNAL-2` | info | External link outside the official-source list — dashboard.html links to www.livgolf.com. Not a Kalshi source; kept for context. | 1 | dashboard.html | — |
| `EXTERNAL-3` | info | External link outside the official-source list — docs/engine/verification.html links to api.github.com. Not a Kalshi source; kept for context. | 1 | docs/engine/verification.html | — |
| `FRESH-1` | info | docs/desk/data/latest.json captured 2026-11-22T07:21:40Z — 0.57 h before this audit. Freshness is not accuracy: a recent capture can still be a bounded sample. | 0 | docs/desk/data/latest.json | — |
| `FRESH-2` | info | data/snapshot.json captured 2026-11-22T07:00:00Z — 0.93 h before this audit. Freshness is not accuracy: a recent capture can still be a bounded sample. | 0 | data/snapshot.json | — |
| `GENCHECK-1` | info | The Node generator's --check can never pass as written — `scripts/build-site.mjs --check` re-renders every page and compares the result with the committed file, but the render embeds a fresh `data-generated` timestamp and relative text such as '21m ago'. Every page therefore reports stale within a minute of generation. The data itself matched when this audit compared it. | 0 | scripts/build-site.mjs | Compare the page with the timestamp and relative-time fields normalised, or drop the strict comparison from the gate. CI does not currently run this check. |
| `MISSING-1` | info | docs/desk/data/positions.json not present — Dataset is absent on this branch; its checks were skipped. | 0 | docs/desk/data/positions.json | — |
| `STATUS-1` | info | Status values match the documented lifecycle — Observed: active. The lifecycle page lists these statuses and maps the open/settled request filters onto active/finalized. | 1 | https://docs.kalshi.com/getting_started/market_lifecycle | — |

## Reproduce

```sh
python3 qa/audit.py            # writes qa/report.json, qa/report.md, qa.html
python3 qa/audit.py --check    # fails only on errors and broken links
```
