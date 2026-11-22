# COORDINATION.md — Tradebot1 Shared Task Board

Shared by all agent sessions working on `kanlerxz87-cyber/Tradebot1`. Read this file before claiming anything.

**Branch policy note (this session):** The session instructions for this working session pin it to branch `arena/30938ff3-tradebot1` (branched from `c8413fcae9e3388b1bd7fd433fac1500630b4140` of `main`). Accordingly, this session does not create `session-<id>/<task>` branches; it works only on `arena/30938ff3-tradebot1`, pushes only to it, and opens one pull request from it to `main`. File scope claimed below is non-overlapping with any other session's scope; if a conflict is found, see Handoff Log.

**Session ID:** `arena-30938ff3` (current branch `arena/30938ff3-tradebot1`)
**Started:** 2026-11-22 (UTC)

## Status legend

- `unclaimed` — free to take
- `in progress` — claimed; do not touch without checking claim age (>60 min without commits → may take over and log handoff)
- `done` — finished; record sources + verification below
- `needs review` — published on the site's "Flagged for Review" page; does not block

## Task Board

| # | Task | Status | Owner | Files / scope |
|---|------|--------|-------|----------------|
| 1 | Repo review (line-by-line vs initial commit) | in progress | arena-30938ff3 | `repo-review.html`, `COORDINATION.md` |
| 2 | Executive summary page | in progress | arena-30938ff3 | `summary.html` |
| 3 | Live dashboard (topics: gas, elections, culture, crypto, golf; chart; order book; 2 alert chats) | in progress | arena-30938ff3 | `dashboard.html`, `assets/js/dashboard.js`, `assets/js/chart.js`, `assets/js/kalshi.js`, `assets/js/simulated-feed.js`, `assets/js/store.js`, `assets/js/alerts.js`, `assets/css/site.css` |
| 4 | Events & resolution tracking (open → settled, YES/NO) | in progress | arena-30938ff3 | `events.html`, `assets/js/events.js` |
| 5 | Simulated trade strategies + analysis lab | in progress | arena-30938ff3 | `strategies.html`, `assets/js/strategies.js` |
| 6 | Portfolio tracking (demo account via user-entered API keys; paper trading) | in progress | arena-30938ff3 | `portfolio.html`, `assets/js/portfolio.js` |
| 7 | GitHub Pages site: landing page + categorized subpages, tables, nav | in progress | arena-30938ff3 | `index.html`, all HTML pages, `README.md`, `.nojekyll` |
| 8 | Verification table (official sources only) | in progress | arena-30938ff3 | `verification.html` |
| 9 | Flagged for Review page | in progress | arena-30938ff3 | `flagged.html` |
| 10 | "Make the site more live & interactive" suggestions | in progress | arena-30938ff3 | `suggestions.html` |
| 11 | Landing-page live stats module | in progress | arena-30938ff3 | `assets/js/index.js`, `assets/js/common.js` |
| 12 | Final integration: build check, link check, merge PR, confirm Pages deploy | in progress | arena-30938ff3 | repo root, branch `arena/30938ff3-tradebot1` → PR → `main` |

## Verification & Sources Log (per task)

### Task 3 / 4 / 6 — Kalshi API facts verified against official docs (docs.kalshi.com), checked 2026-11-22:

- Demo REST base URL `https://external-api.demo.kalshi.co/trade-api/v2` (legacy `demo-api.kalshi.co` also supported) — source: https://docs.kalshi.com/getting_started/api_environments
- Demo WebSocket URL `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` (legacy `wss://demo-api.kalshi.co/trade-api/ws/v2` also supported) — source: https://docs.kalshi.com/getting_started/api_environments
- Request signing: timestamp(ms) + METHOD + full path (no query string); headers `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE` — source: https://docs.kalshi.com/getting_started/api_environments, https://docs.kalshi.com/getting_started/api_keys
- WebSocket handshake requires the same signed headers over `GET /trade-api/ws/v2`; **browsers cannot set custom WebSocket handshake headers natively** → browser WS needs a proxy; dashboard defaults to REST polling — source: https://docs.kalshi.com/getting_started/quick_start_websockets
- WS channels: private (`orderbook_delta`, `fill`, `market_positions`, `user_orders`, …), public (`ticker`, `trade`, `market_lifecycle_v2`) — source: https://docs.kalshi.com/getting_started/quick_start_websockets
- REST market data endpoints (`GET /markets`, `/events`, `/series`, `/markets/{ticker}/orderbook`) are public/no auth; `/portfolio/*` and WS require keys; demo keys are separate from production keys — sources: https://docs.kalshi.com/getting_started/api_keys, https://docs.kalshi.com/getting_started/api_environments (+ secondary corroboration: dwellir.com/guides/kalshi-api-guide, checked 2026-11-22)
- Rate limits are token-based; most requests cost 10 tokens; read/write buckets; unauthenticated public requests have separate limits; 429 → back off — source: https://docs.kalshi.com/getting_started/rate_limits
- `GET /portfolio/balance` has its own bucket: Basic/Advanced = once/sec — source: https://docs.kalshi.com/getting_started/rate_limits
- Order creation: V2 `POST /portfolio/events/orders`; legacy `POST /portfolio/orders`; V2 uses `bid`/`ask` and fixed-point dollar price strings; `client_order_id` recommended — sources: docs.kalshi.com API environments page signs `/trade-api/v2/portfolio/orders`; V2 endpoint corroborated by quantvps.com/blog/kalshi-order-book-api-endpoints-explained (checked 2026-11-22, third-party) and pmxt-dev/pmxt issue #417 (2026-05-22). **Not tested against live demo in this session (no API keys in sandbox) — see Flagged.**
- Taker fee ≈ `0.07 × C × P × (1−P)`, rounded up (fee schedule effective 2026-07-07) — sources: quantvps.com/blog/kalshi-fees-explained, totalis.trade (both secondary, checked 2026-11-22). Official fee-schedule PDF URL not confirmed — see Flagged.
- KalshiEX LLC designated contract market by CFTC on 2020-11-04 — source: totalis.trade (secondary, checked 2026-11-22); primary CFTC source: https://www.cftc.gov/ (not deep-verified this session) — see Flagged.
- Candlesticks endpoint exists: `GET /series/{series_ticker}/markets/{ticker}/candlesticks` (1m/1h/1d bars) — secondary source dwellir.com/guides/kalshi-api-guide.
- `ticker_v2` WS channel retired 2026-02-12; use `ticker` — secondary source parlay.run/kalshi-api (2026-05-16).

**Sandbox limitation (important):** This sandbox has **no network route to `external-api.demo.kalshi.co`** (curl → timeout/000; only github.com, api.github.com, registry.npmjs.org, pypi.org and files.pythonhosted.org are reachable). No Kalshi demo API keys were provided. Therefore: **no live market values, volumes, prices, or resolutions could be collected in this session.** All live values on the site are fetched client-side in the visitor's browser at page-open time, or are clearly labeled SAMPLE/SIMULATED. Every static figure that cannot be confirmed from an official source is left blank and flagged on the Flagged for Review page.

## Flagged for Review (summary — full detail on site page)

1. Live data not verifiable from this sandbox; all live figures are runtime/browser-fetched or simulated and labeled as such.
2. Browser cannot set WebSocket handshake headers → live WS streaming requires a small proxy (or local Electron/Node); REST polling is the default.
3. CORS behavior of the demo REST API from a GitHub Pages origin is unknown; if blocked, the dashboard auto-falls-back to a clearly-labeled simulated feed.
4. V2 order endpoints (`/portfolio/events/orders`) not exercised against the demo account in this session (no keys); order placement is implemented but disabled unless the user supplies demo keys + explicitly enables it.
5. Official Kalshi fee-schedule PDF URL not confirmed; fee figures sourced from dated secondary reports.
6. Repo review irregularities: single-commit repo, README contains only `# Tradebot1`, no LICENSE, no .gitignore, no CI, Pages uses legacy branch build.
7. Causal attribution for ≥$0.10 price swings: the dashboard links related news/search queries and official data sources; links are "possible drivers to check", not proven causation.

## Decisions / Notes

- Static no-build site (vanilla HTML/CSS/JS) so GitHub Pages (legacy branch build from `main` `/`) serves it directly; zero runtime dependencies; charts drawn on `<canvas>`.
- Paper-trading simulator runs entirely client-side; demo-account execution is opt-in and keys never leave the browser except to Kalshi demo hosts over HTTPS.
- Claim made before work started; each task marked done only after verification + commit.

## Handoff Log

- 2026-11-22 arena-30938ff3: Initial claim of all tasks 1–12 on branch `arena/30938ff3-tradebot1` (branch pinned by session note; not using `session-<id>/` branches). Sandbox cannot reach Kalshi demo API; see Verification & Sources Log.
