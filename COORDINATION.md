# COORDINATION.md — Shared Task Board

This file is the shared task board for multi-session work on this repo. Read it
before starting any work. Claim a task by adding your session ID and file scope
below, commit and push the claim immediately, then work only inside that scope.

**Status values:** `unclaimed` · `in progress` · `done` · `needs review`
(`needs review` = published on the "Flagged for Review" page; does not block anything)

Session IDs in this log use the Arena branch slug as the session identifier:
`arena/ef466564-tradebot1`.

---

## Task Board

| # | Task | Status | Owner session | File scope |
|---|------|--------|----------------|------------|
| 1 | Research & verify Kalshi Trade API v2 (REST + WS) against official docs | done | arena/ef466564-tradebot1 | `docs/EXECUTIVE_SUMMARY.md`, `docs/API_VERIFICATION.md` |
| 2 | Build data-collection pipeline (Kalshi client, swing alerts, paper-trading sim, portfolio tracking) | done | arena/ef466564-tradebot1 | `scripts/**`, `.github/workflows/collect-kalshi-data.yml`, `data/**` |
| 3 | Build GitHub Pages dashboard (landing + category pages + alerts + portfolio + verification + flagged-for-review) | done | arena/ef466564-tradebot1 | `docs/**` (site, excludes the two markdown reports from task 1 which live alongside it) |
| 4 | Integration: merge, verify no broken links, enable Pages, open + merge PR | done | arena/ef466564-tradebot1 | repo root, `.github/workflows/pages.yml` |

---

## Session Log

### arena/ef466564-tradebot1 — 2026-11-22

**Context:** Repo was empty (`README.md` only, one commit). No other sessions were
active; this session claimed and executed all four tasks above sequentially since
there was no conflicting work to coordinate around. Single working branch:
`arena/ef466564-tradebot1` (per Arena session rules, no other branch was created
or pushed to).

**Critical environment constraint discovered and verified (flag for review):**
The sandbox this agent runs in only has outbound network access to
`github.com`, `codeload.github.com`, `api.github.com`, `registry.npmjs.org`,
`pypi.org`, `files.pythonhosted.org`. Direct `curl`/`requests` calls from this
sandbox to `external-api.demo.kalshi.co` and `demo-api.kalshi.co` both return
connection failures (verified with `curl -m 10 -o /dev/null -w "%{http_code}"`,
result `000` for both hosts, tested 2026-11-22). **This means no live Kalshi
data could be fetched or hallucinated from inside this coding session.** The
architecture below works around this honestly instead of faking numbers:

- A Python collector (`scripts/`) implements the real Kalshi Trade API v2
  client (public, unauthenticated market-data endpoints only — no order
  placement, since no user API key was provided and none should be requested
  per "no manual input").
- `.github/workflows/collect-kalshi-data.yml` runs that collector on a
  schedule **on GitHub's own runners**, which do have full internet access.
  That is the only part of this system that will ever produce real Kalshi
  numbers; this sandbox never did and could not.
- Until that workflow has run at least once after merge, every data file in
  `docs/data/*.json` is intentionally shipped **empty** (`"markets": []`,
  etc.) with a `"status": "awaiting_first_collection_run"` marker. No
  placeholder/sample market prices were invented anywhere in the site or
  data. This is logged here explicitly so a reviewer knows why the live
  dashboard shows "no data yet" until the first scheduled Action runs.

**Sources used (all fetched this session, official unless noted):**
- https://docs.kalshi.com/welcome (official Kalshi API docs)
- https://docs.kalshi.com/getting_started/quick_start_market_data (official)
- https://docs.kalshi.com/getting_started/demo_env (official — confirms demo
  REST/WS base URLs exactly match the ones the user supplied)
- https://docs.kalshi.com/getting_started/api_environments (official, referenced)
- https://docs.kalshi.com/websockets/websocket-connection (official)
- https://docs.kalshi.com/llms-full.txt (official, auto-generated full API index)
- https://kalshi.com/golf/majors , https://kalshi.com/markets/kxpgatour/... (official site, golf series tickers KXPGATOUR/KXMASTERS/KXPGA/KXUSOPEN/KXTHEOPEN)
- https://www.cnbc.com/2026/09/14/prediction-markets-traders-think-gas-prices-will-hit-new-highs-in-2026.html (independent news corroboration of Kalshi gas-price markets settling on AAA data)
- Third-party technical write-ups (parlay.run, dwellir.com, totalis.trade,
  oddsshopper.com, tradoxvps.com) were used only as cross-checks on
  undocumented operational details (rate-limit tiers, example payloads) and
  are cited as secondary, never as the basis for a "verified" claim where the
  official docs were silent. See `docs/API_VERIFICATION.md` for exactly which
  rows rely on secondary sources and are marked "unverified — secondary source only".

**Irregularities flagged for review:** see `docs/FLAGGED_FOR_REVIEW.md` (also
published as a site page). Nothing below blocked the merge, per instructions.

**PR / merge:** see entry appended at the end of this log once opened.
