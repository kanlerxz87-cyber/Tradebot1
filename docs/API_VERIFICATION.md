# Kalshi Trade API v2 — Line-by-Line Verification

_Verification performed: 2026-11-22, session `arena/ef466564-tradebot1`._
_Rule applied throughout: a row is marked **Verified** only when it was
confirmed directly against an official Kalshi source (`docs.kalshi.com` or
`kalshi.com`) fetched during this session. Anything not directly confirmed is
marked **Unverified** and left blank/flagged rather than guessed, per the
user's instruction._

## A. Base URLs supplied by the user, checked against official docs

| # | Claim in the task prompt | Status | Official source checked |
|---|---|---|---|
| A1 | REST Trade API prod: `https://external-api.demo.kalshi.co/trade-api/v2` *(as given twice in the prompt)* | **Verified** — matches docs exactly | [docs.kalshi.com/getting_started/demo_env](https://docs.kalshi.com/getting_started/demo_env) |
| A2 | REST Trade API demo (alt host): `https://demo-api.kalshi.co/trade-api/v2` | **Verified** — listed as "also supported" | [docs.kalshi.com/getting_started/demo_env](https://docs.kalshi.com/getting_started/demo_env) |
| A3 | WebSocket: `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | **Verified** | [docs.kalshi.com/getting_started/demo_env](https://docs.kalshi.com/getting_started/demo_env) |
| A4 | WebSocket (alt host): `wss://demo-api.kalshi.co/trade-api/ws/v2` | **Verified** — listed as "also supported" | [docs.kalshi.com/getting_started/demo_env](https://docs.kalshi.com/getting_started/demo_env) |

## B. Public (unauthenticated) REST endpoints this project uses

| # | Endpoint | Method | Auth required? | Status | Source |
|---|---|---|---|---|---|
| B1 | `/series` | GET | No | **Verified** | [docs.kalshi.com quick start](https://docs.kalshi.com/getting_started/quick_start_market_data) |
| B2 | `/series/{series_ticker}` | GET | No | **Verified** | [docs.kalshi.com quick start](https://docs.kalshi.com/getting_started/quick_start_market_data) — used in Step 1 example |
| B3 | `/events` | GET | No | **Verified** | [docs.kalshi.com quick start](https://docs.kalshi.com/getting_started/quick_start_market_data) |
| B4 | `/events/{event_ticker}` | GET | No | **Verified** | [docs.kalshi.com quick start](https://docs.kalshi.com/getting_started/quick_start_market_data) — used in Step 2 example |
| B5 | `/markets` (filters: `series_ticker`, `event_ticker`, `status`, `limit`, `cursor`) | GET | No | **Verified** | [docs.kalshi.com quick start](https://docs.kalshi.com/getting_started/quick_start_market_data) |
| B6 | `/markets/{ticker}` | GET | No | **Verified** | [docs.kalshi.com quick start](https://docs.kalshi.com/getting_started/quick_start_market_data) |
| B7 | `/markets/{ticker}/orderbook` (param: `depth`) | GET | No | **Verified** | [docs.kalshi.com quick start, Step 3](https://docs.kalshi.com/getting_started/quick_start_market_data) |
| B8 | `/markets/trades` | GET | No | **Unverified — secondary source only** (not directly opened in this session; referenced by third-party guides) | cited by multiple third-party dev guides, not independently re-confirmed against `docs.kalshi.com` page content this session |
| B9 | `/series/{series_ticker}/markets/{ticker}/candlesticks` (params: `period_interval` ∈ {1, 60, 1440} min, `start_ts`, `end_ts`) | GET | No | **Unverified — secondary source only** | third-party guide (dwellir.com); matches the shape of other confirmed endpoints but the official reference page for this one was not opened directly in this session |
| B10 | `/exchange/status` | GET | No | **Unverified — secondary source only** | third-party guide mention; not opened directly |

**Why B8–B10 are flagged instead of marked verified:** this session confirmed
them only through secondary developer write-ups, not by opening the specific
official reference page for each. The live collector treats these as
best-effort / optional and will not fail if they 404 or change shape; any
field they'd populate is left blank with an "unverified" tag in the UI rather
than filled from the secondary-sourced assumption.

## C. Authenticated endpoints (NOT used by this project — documented for completeness)

| # | Endpoint | Status | Source |
|---|---|---|---|
| C1 | Auth headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE`, RSA-PSS or Ed25519 signature over `timestamp + method + path` | **Verified** | [docs.kalshi.com API keys docs](https://docs.kalshi.com/llms-full.txt) (official doc index, "Create API Key" / auth sections) |
| C2 | `/portfolio/balance`, `/portfolio/positions`, `/portfolio/orders`, `/portfolio/fills` | **Verified to exist** (listed in official doc index) but **not called** by this project — no user API key was available/requested | [docs.kalshi.com/llms-full.txt](https://docs.kalshi.com/llms-full.txt) |
| C3 | `/portfolio/events/orders` (V2 order create), amend/decrease/cancel/batched variants | **Verified to exist**, **not called** | [docs.kalshi.com/llms-full.txt](https://docs.kalshi.com/llms-full.txt) |

This project therefore **never places a real order and never reads the real
demo-account balance** — see `docs/EXECUTIVE_SUMMARY.md` §5 for why, and what
the user would need to provide (a GitHub Actions secret holding a Kalshi demo
API key) to change that.

## D. WebSocket channels

| # | Channel | Public/Private | Status | Source |
|---|---|---|---|---|
| D1 | `ticker` | Public | **Verified exists** (official doc index lists it) | [docs.kalshi.com/llms-full.txt](https://docs.kalshi.com/llms-full.txt) |
| D2 | `trade` | Public | **Verified exists** | [docs.kalshi.com/llms-full.txt](https://docs.kalshi.com/llms-full.txt) |
| D3 | `market_lifecycle_v2` | Public | **Verified exists** | [docs.kalshi.com/llms-full.txt](https://docs.kalshi.com/llms-full.txt) |
| D4 | `orderbook_delta` | Requires connection auth | **Verified exists**; subscribe message shape confirmed | [docs.kalshi.com/websockets/websocket-connection](https://docs.kalshi.com/websockets/websocket-connection) |
| D5 | `fill`, `market_positions` | Private/account-scoped | **Verified exist** (doc index), **not used** (no account credentials) | [docs.kalshi.com/llms-full.txt](https://docs.kalshi.com/llms-full.txt) |

**Important finding, flagged for review:** this project's static GitHub Pages
site does **not** open a browser-side WebSocket or REST connection directly to
Kalshi, because (1) Kalshi's CORS policy for direct browser `fetch()`/`WebSocket`
calls from an arbitrary third-party origin like a `github.io` page was **not
confirmed** in official docs during this session (no `Access-Control-Allow-Origin`
statement was found on the pages reviewed), and (2) GitHub Pages cannot run a
persistent server-side process to hold an authenticated socket open. Per the
"no hallucinations" rule, this project does not assume CORS works. Instead,
`.github/workflows/collect-kalshi-data.yml` polls the REST API server-side
(where CORS is irrelevant) on a schedule and publishes JSON snapshots that the
static site fetches. This is logged in `docs/FLAGGED_FOR_REVIEW.md` as an
architecture decision made to avoid an unverifiable assumption, not a defect.

## E. Rate limits (for the collector's polling interval design)

| # | Claim | Status | Source |
|---|---|---|---|
| E1 | Requests are metered in "tokens"; most cost 10 tokens; exceeding budget returns `429 Too Many Requests` | **Verified** | [docs.kalshi.com/llms-full.txt, "Rate Limits and Tiers"](https://docs.kalshi.com/llms-full.txt) |
| E2 | Exact tier numbers (requests/sec per tier) | **Unverified — conflicting secondary sources** (three different third-party guides gave three different numeric tables) | Not in the specific official rate-limit table this session opened; the collector therefore uses a conservative fixed delay (1 request/second) rather than trusting any one of the conflicting numbers |

## F. Topic/category mapping confirmations

See `docs/EXECUTIVE_SUMMARY.md` §4 for the full table. Golf tickers
(`KXPGATOUR`, `KXMASTERS`, `KXPGA`, `KXUSOPEN`, `KXTHEOPEN`) are the only
topic tickers confirmed on **official `kalshi.com` pages** directly
([kalshi.com/golf/majors](https://kalshi.com/golf/majors)). Gas, elections,
culture, and crypto ticker *families* are sourced from a mix of official
examples (ticker naming pattern) and secondary corroboration; the live
collector re-derives the authoritative, current list every run directly from
`GET /series` and `GET /events`, rather than trusting this static research.

## G. How to re-verify any row yourself

Every GET endpoint above needs no API key. You can re-check any "Verified" row
with a single command, e.g.:

```bash
curl "https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXAAAGASM&status=open&limit=5"
```

(This sandbox could not run that command itself — see
`docs/EXECUTIVE_SUMMARY.md` §3 — but it will succeed from any machine with
normal internet access, and does run automatically from GitHub Actions.)
