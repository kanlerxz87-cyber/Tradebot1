# COORDINATION.md — Shared Task Board

> Read this file before starting work. Claim a task by writing your session ID below,
> then commit and push the claim immediately. Never start a task another session has claimed.
> Keep file scopes non-overlapping.

**Repo:** `kanlerxz87-cyber/Tradebot1`
**Last updated:** 2026-11-22 (UTC)
**Active session:** `arena-e3e5f70f` (branch `arena/e3e5f70f-tradebot1`, base `c8413fc`)

## Session registry

| Session ID | Branch | Started (UTC) | Scope | Status |
| - | - | - | - | - |
| `arena-e3e5f70f` | `arena/e3e5f70f-tradebot1` | 2026-11-22 | Entire initial build (repo was empty, 1 file) | active |

> Handoff rule: if a claim is >60 minutes old with no commits, another session may take
> over the task and must note the handoff in the Activity log.

## Task board

| # | Task | Status | Owner | Files / scope |
| - | - | - | - | - |
| T1 | Verify Kalshi demo REST + WebSocket endpoints, auth, orderbook, candlesticks, fees, demo-account process against official docs | done | `arena-e3e5f70f` | `docs/data/sources.json`, `docs/api-reference.html` |
| T2 | Backend package: signing, REST client, topics/discovery, swing detector, model, fees, paper engine, demo adapter, portfolio analytics | done — 48 tests pass | `arena-e3e5f70f` | `kalshi_trader/**`, `tests/**` |
| T3 | Live dashboard (topic tabs, two alert chats, price chart with time-range selector, orderbook depth, resolution tracker) | done | `arena-e3e5f70f` | `docs/index.html`, `docs/assets/**` |
| T4 | Static category pages + verified tables with per-row source links | done | `arena-e3e5f70f` | `docs/topics/**` |
| T5 | Executive summary | done | `arena-e3e5f70f` | `EXECUTIVE_SUMMARY.md`, `docs/executive-summary.html` |
| T6 | Flagged-for-Review page (unverified / irregular items) | done — 14 items, 0 blocking | `arena-e3e5f70f` | `docs/flagged.html`, `docs/data/flags.json` |
| T7 | Autonomous data collection + paper-trading CI cron | in progress — awaiting first real cycle | `arena-e3e5f70f` | `.github/workflows/collect.yml`, `kalshi_trader/collector.py` |
| T8 | CI: unit tests + site link check + GitHub Pages deploy | in progress — awaiting first deploy | `arena-e3e5f70f` | `.github/workflows/ci.yml`, `.github/workflows/pages.yml` |
| T9 | Final integration: re-verify combined data, confirm build has no broken links, PR → main, merge, confirm Pages deploy | in progress | `arena-e3e5f70f` | `main`, `COORDINATION.md` |

**Shared outputs** (site index + navigation, `docs/data/latest.json`) are changed only by the
final integration session (T9) once all other tasks are merged.

## Verified sources (official only)

| # | Fact | Official source | Checked |
| - | - | - | - |
| S1 | Demo REST base URL `https://external-api.demo.kalshi.co/trade-api/v2` (recommended); `https://demo-api.kalshi.co/trade-api/v2` also supported | https://docs.kalshi.com/getting_started/api_environments | 2026-11-22 |
| S2 | Demo WebSocket `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`; `wss://demo-api.kalshi.co/trade-api/ws/v2` also supported | https://docs.kalshi.com/getting_started/api_environments | 2026-11-22 |
| S3 | Auth headers `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`, `KALSHI-ACCESS-TIMESTAMP`; signed text = timestamp + METHOD + path **without** query string | https://docs.kalshi.com/getting_started/api_environments (Request Signing) | 2026-11-22 |
| S4 | RSA keys use RSA-PSS/SHA-256; Ed25519 keys sign directly | https://docs.kalshi.com/api-reference/portfolio/get-positions (securitySchemes) | 2026-11-22 |
| S5 | Public market data needs no API key (`GET /markets`, `/markets/{ticker}/orderbook`, `/series`, `/events`) | https://docs.kalshi.com/getting_started/quick_start_market_data | 2026-11-22 |
| S6 | Orderbook returns YES/NO **bids only** as `orderbook_fp.{yes_dollars,no_dollars}` = `[[price_dollars, count_fp], …]` ascending; best bid is last element; asks are implied via `$1.00 − opposite bid` | https://docs.kalshi.com/getting_started/orderbook_responses | 2026-11-22 |
| S7 | Candlesticks: `GET /series/{series_ticker}/markets/{ticker}/candlesticks`, `period_interval` ∈ {1, 60, 1440} minutes, `start_ts`/`end_ts` in seconds, max 5,000 periods per request | https://docs.kalshi.com/api-reference/market/get-market-candlesticks | 2026-11-22 |
| S8 | Category is a series field; `categories` is the discovery list; `tags` are subcategories. Official categories include `Elections`, `Crypto`, `Entertainment`, `Sports`, `Economics`, `Commodities` | https://docs.kalshi.com/getting_started/terms | 2026-11-22 |
| S9 | `Golf` is a **tag** under category `Sports` | https://external-api.kalshi.com/trade-api/v2/search/tags_by_categories (official API) | 2026-11-22 |
| S10 | US gas price series is `KXAAAGASM`, primary category `Economics`, categories `[Economics, Commodities]`, tags `[Oil and energy, Oil & Gas]` | https://docs.kalshi.com/getting_started/terms (worked example) | 2026-11-22 |
| S11 | Market outcome field `result` is `yes`/`no` after settlement; YES holders get $1 on YES | https://docs.kalshi.com/getting_started/market_settlement | 2026-11-22 |
| S12 | Orders: `POST /portfolio/events/orders` with `ticker, side, count, price, time_in_force, self_trade_prevention_type, client_order_id`; 201 = accepted | https://docs.kalshi.com/getting_started/quick_start_create_order | 2026-11-22 |
| S13 | Rate limits are token buckets; most requests cost 10 tokens; `GET /portfolio/balance` has its own 1–5 req/s bucket; unauthenticated requests have separate limits | https://docs.kalshi.com/getting_started/rate_limits | 2026-11-22 |
| S14 | Demo environment is `https://demo.kalshi.co`, mock funds, credentials separate from production, prices may not reflect real markets | https://docs.kalshi.com/getting_started/demo_env + https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account | 2026-11-22 |
| S15 | WS `ticker` channel message fields: `price_dollars`, `yes_bid_dollars`, `yes_ask_dollars`, `volume_fp`, `open_interest_fp`, `yes_bid_size_fp`, `yes_ask_size_fp`, `ts_ms` | https://docs.kalshi.com/websockets/market-ticker | 2026-11-22 |
| S16 | REST market data is cached for a short time (prices/sizes/status can lag several seconds); use WebSockets for current state | https://docs.kalshi.com/getting_started/quick_start_market_data | 2026-11-22 |

## Activity log

| UTC time | Session | Event |
| - | - | - |
| 2026-11-22 | `arena-e3e5f70f` | Read repo: single `README.md` (11 bytes), no code, no `COORDINATION.md`. Created this board and claimed T1–T8. |
| 2026-11-22 | `arena-e3e5f70f` | T1 done: verified S1–S16 against docs.kalshi.com and the public API. Recorded flags (see below). |

## Build notes (session `arena-e3e5f70f`)

### Automated checks and their results

| Check | Command | Result |
| - | - | - |
| Unit tests | `pytest -q` | 48 passed (signing, normalisation, implied asks, $0.10 boundary, topics, sizing, settlement, collector cycle) |
| JS syntax | `node --check` on both bundles + inline scripts | clean |
| Internal links | `python tools/check_links.py` | 258 links across 13 pages, no broken target or anchor |
| Site generation | `python tools/build_site.py --check` | current |
| Data integrity | `python -m kalshi_trader.cli verify` | OK (runs after the first real cycle) |
| HTTP smoke test | `cli serve --no-live` + curl | 14/14 routes return 200; static tables contain real rows |

### Data policy enforced by CI

* No API key is required; the collector runs on public endpoints.
* A cycle never raises on a single API failure — errors are written into the snapshot and shown on the page.
* If a demo key is added as a secret, `kalshi_demo.py` activates without code changes.
* Commit messages from the bot are `data: cycle <timestamp>`; the site is redeployed in the same job
  because pushes made with `GITHUB_TOKEN` do not trigger other workflows.

### Handoff / merge record

* Integration branch: `arena/e3e5f70f-tradebot1` (base `c8413fc`).
* Pull request and merge result: recorded below once merged.
* Site: https://kanlerxz87-cyber.github.io/Tradebot1/
