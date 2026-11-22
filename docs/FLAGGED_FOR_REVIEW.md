# Flagged for Review

_Nothing on this page blocked the merge, per the task instructions. Everything
here is either (a) a genuine unverifiable/ambiguous item, or (b) an
architecture decision forced by a sandbox constraint, logged for transparency._

## 1. Sandbox could not reach Kalshi's API — no live data shipped in this PR

**What happened:** The coding sandbox's outbound network allowlist does not
include `external-api.demo.kalshi.co` or `demo-api.kalshi.co`. A direct `curl`
test from the sandbox to both hosts returned connection failures (HTTP status
`000`), confirmed 2026-11-22.
**Impact:** No real Kalshi market data, prices, or portfolio figures were
available while building this project, and none were invented. All
`docs/data/*.json` files ship empty with `"status":
"awaiting_first_collection_run"` until `.github/workflows/collect-kalshi-data.yml`
runs on GitHub's infrastructure (which has full internet access) after merge.
**Action for reviewer:** After merge, check the Actions tab to confirm the
"Collect Kalshi Demo Data" workflow has run successfully and the dashboard
pages are populated. If it fails, check the run log — the workflow uses only
the public, unauthenticated Kalshi endpoints documented in
`docs/API_VERIFICATION.md` §B.

## 2. CORS behavior of Kalshi's API from a browser origin — not confirmed

**What happened:** No official Kalshi documentation page reviewed in this
session states an `Access-Control-Allow-Origin` policy for direct
browser-side requests from a third-party origin (such as a `github.io` Pages
site).
**Decision made to avoid guessing:** the dashboard never calls Kalshi
directly from the browser. All data reaches the browser only via JSON files
committed by the server-side GitHub Actions collector. This is slower
("live-ish", refreshed on a schedule) rather than truly push-based, but it
never silently fails from a CORS block and never requires assuming
unconfirmed server behavior.
**Action for reviewer:** if you have a Kalshi account and want to confirm CORS
behavior yourself, open your browser devtools console on any page and run
`fetch('https://external-api.demo.kalshi.co/trade-api/v2/exchange/status').then(r=>r.json()).then(console.log)`.

## 3. Real trade execution vs. simulated trading

**What happened:** The task asks to "automate simulated trades" and also to
"execute trades on events and track the performance" and "track the
portfolio performance using the kalshi demo account." These two asks are in
tension: executing real orders on the user's own Kalshi demo account requires
that user's personal Kalshi demo API key, which this autonomous session was
told not to solicit ("no manual input on my part").
**Decision made:** Treat every trade in this system as a **paper trade** —
logged against live quoted prices, but never submitted to Kalshi. The
portfolio shown is the paper-trading portfolio, clearly labeled as such
everywhere it appears in the UI.
**Action for reviewer:** To wire this up to a *real* demo-account, add a
Kalshi demo API key (key ID + private key PEM) as GitHub Actions repository
secrets (`KALSHI_DEMO_KEY_ID`, `KALSHI_DEMO_PRIVATE_KEY`) and flip the
`EXECUTE_REAL_DEMO_ORDERS` flag described in `scripts/README.md`. This was
intentionally left off by default.

## 4. Rate-limit tier numbers conflict across sources

**What happened:** Three third-party technical guides gave three different
numeric tables for Kalshi's per-tier requests/second budget. The specific
official rate-limit reference table was not opened page-by-page in this
session to resolve the conflict.
**Decision made:** The collector polls conservatively (throttled to roughly 1
request/second, well under even the most conservative third-party number) and
backs off on any `429` response rather than relying on a specific tier number.
**Action for reviewer:** Confirm your account's actual tier/budget at
`GET /account/endpoint_costs` and `GET /account/limits` (requires your own API
key) if you want to tune the polling frequency up.

## 5. Topic ticker lists are collector-derived, not hand-curated

**What happened:** Only the golf ticker family (`KXPGATOUR`, `KXMASTERS`,
`KXPGA`, `KXUSOPEN`, `KXTHEOPEN`) was confirmed directly against an official
`kalshi.com` page in this session. Gas/elections/culture/crypto ticker
*examples* came from a mix of official naming-pattern examples and secondary
corroboration (see `docs/API_VERIFICATION.md` §F).
**Decision made:** Rather than hardcode a possibly-stale or wrong ticker list,
`scripts/collect_kalshi_data.py` queries `GET /series` and `GET /events` live
and filters by the `category` field Kalshi itself returns, falling back to
keyword matching on title/subtitle only where `category` is ambiguous. Any
market the collector cannot confidently categorize is written to
`docs/data/uncategorized.json` instead of being silently dropped or guessed
into a bucket.
**Action for reviewer:** Check `docs/data/uncategorized.json` periodically —
anything there needs a human judgment call this automated pipeline
deliberately declined to make.
