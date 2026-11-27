# Executive Summary — Kalshi Demo Live Alerting, Strategy & Portfolio System

**Date:** 2026-11-27 (UTC)  
**Repository:** `kanlerxz87-cyber/Tradebot1`  
**Live Root Overview & 19-Page Hub:** [`/`](https://kanlerxz87-cyber.github.io/Tradebot1/)  
**Dedicated Kalshi Demo API Desk (`/demo-desk/`):** [`/demo-desk/`](https://kanlerxz87-cyber.github.io/Tradebot1/demo-desk/) · [`/demo-desk/flagged/`](https://kanlerxz87-cyber.github.io/Tradebot1/demo-desk/flagged/)  
**Preserved Sibling Desks:** [`/docs/`](https://kanlerxz87-cyber.github.io/Tradebot1/docs/) · [`/site/`](https://kanlerxz87-cyber.github.io/Tradebot1/site/) · [`/terminal/`](https://kanlerxz87-cyber.github.io/Tradebot1/terminal/) · [`/live.html`](https://kanlerxz87-cyber.github.io/Tradebot1/live.html)

---

## 1. Mission & Strict 5-Topic Scope

This project collects, organizes, verifies, and analyzes live **Kalshi Demo Environment** prediction markets across strictly **five topics only**:
1. **Gas Prices** (`Economics` / `Commodities`, tag `Oil and energy` — e.g., `KXAAAGASMINTX-26DEC31`, `KXAAAGASMIN-26DEC31`)
2. **Elections** (`Elections` — e.g., `KXPRESPERSON-28`, `KXSENATEIAD-28`, `KXXISUCCESSOR-45JAN01`)
3. **Culture** (`Entertainment` — e.g., `KXPERFORMBONDSONG-35`, `KXGRAMBPS-68`)
4. **Crypto** (`Crypto` on shard `2` + `KXDEMOFUTHOURLY` BTC hourly benchmark on shard `0` — e.g., `KXBTCY-27JAN0100`, `KXDEMOFUTHOURLY-26NOV27H20-UP`, `KXBTCD-26NOV2817`)
5. **Golf** (`Sports`, tag `Golf` — e.g., `KXPGATOUR-MAST27`, `KXLIVCOMPETE-27APR`, plus `KXPGATOUR-THRC26` tracked from open to `finalized`)

Topics are separated into dedicated category subpages (`/demo-desk/gas/`, `/demo-desk/elections/`, `/demo-desk/culture/`, `/demo-desk/crypto/`, `/demo-desk/golf/`, plus root `/topics/{gas-prices,elections,culture,crypto,golf}.html`) and separated topic panels on the main dashboard, while markets belonging to the same `event_ticker` are grouped together and ranked by verified contract volume.

---

## 2. Official Endpoints & Protocol Findings (Verified 2026-11-27)

| Layer | Verified Value | Official Source |
|---|---|---|
| Demo REST Base (Primary) | `https://external-api.demo.kalshi.co/trade-api/v2` | [API Environments](https://docs.kalshi.com/getting_started/api_environments) · [Live Status](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) |
| Demo REST Base (Supported Alternate) | `https://demo-api.kalshi.co/trade-api/v2` | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) · [Live Status](https://demo-api.kalshi.co/trade-api/v2/exchange/status) |
| Demo WebSocket (Primary) | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets) |
| Demo WebSocket (Supported Alternate) | `wss://demo-api.kalshi.co/trade-api/ws/v2` | [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets) |
| Exchange Sharding Status | `exchange_active: true`, `trading_active: true` across 4 shards (`0`: Default, `1`: Demo shard 1, `2`: Demo shard 2 [Crypto], `3`: unnamed) | [Live Exchange Status](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) |
| Request Signing (REST & WS) | Headers `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP` (ms, ±30s), `KALSHI-ACCESS-SIGNATURE` = Base64 signature over `timestamp + METHOD + full_path_without_query` (e.g., `/trade-api/v2/portfolio/balance` or `/trade-api/ws/v2`) using Ed25519 or RSA-PSS/SHA-256 | [Quick Start: Create Order](https://docs.kalshi.com/getting_started/quick_start_create_order) |
| V2 Order Execution | `POST /trade-api/v2/portfolio/events/orders` (`side: "bid"\|"ask"`, fixed-point dollar `price`, string `count`, `client_order_id`). Legacy `POST /portfolio/orders` is removed (`410 Gone`). | [Quick Start: Create Order](https://docs.kalshi.com/getting_started/quick_start_create_order) |
| Orderbook Liquidity Mechanics | `GET /markets/{ticker}/orderbook` returns `orderbook_fp.yes_dollars` and `no_dollars` sorted **ascending** (best bid is **last** element `[-1]`). Implied executable `YES Ask = $1.00 - NO Bid`; `NO Ask = $1.00 - YES Bid`. | [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses) |
| Lifecycle & Resolution | Filter `?status=open` matches REST `status: "active"`; filter `?status=settled` matches REST `status: "finalized"` with `result` in `{"yes", "no", "scalar"}` and `settlement_value_dollars`. | [Market Lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle) |
| Fee & Series Multiplier Model | Raw fee `0.07 * fee_multiplier * C * P * (1 - P)` rounded up to `$0.000001` (`ceil_6dp`), aligned to `$0.0001` (Direct) or `$0.01` (Non-Direct) via per-order rounding accumulator; `series.fee_multiplier` read live from `GET /series/{series_ticker}`. | [Fee Rounding](https://docs.kalshi.com/getting_started/fee_rounding) · [Fee Schedule PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf) |

---

## 3. Core System Capabilities (`/demo-desk/`, Root Node Hub & `kalshi_engine/`)

1. **Dual Real-Time Scrolling Alert Chats (`|Δp| ≥ $0.10`)**:
   - **All-Events Swing Chat**: Streams every observed contract price swing `≥ $0.10` in either direction across all 5 topics, pre-loaded with verified `2026-11-27` 5-second trade prints from `KXDEMOFUTHOURLY-26NOV27H20-UP` (`+$0.10`, `-$0.30`) and `KXBTCY-27JAN0100-B47500` (`+$0.44`), and updated live in the browser via `GET /markets/{ticker}` + `GET /markets/trades`.
   - **Selective High-ROI Model Chat**: Filters `≥ $0.10` swings through a transparent quantitative screen (`net_roi >= 12%` after 6dp taker fees, `spread <= $0.08`, resting `depth >= 25` contracts, actionable `[$0.06, $0.94]` band) — rejecting illiquid orderbook-vacuum spikes such as `KXBTCY-27JAN0100-B47500`'s `$0.97`-spread jump.
2. **Interactive Time-Series Chart, Liquidity Ladder & Depth-Weighted VWAP Preview**:
   - X-axis selectable across **Seconds** (5-second trade prints), **Minutes** (Kalshi 1m candlesticks), and **Hours** (24h window); Y-axis plots contract price (`$0.00–$1.00`) with diamond markers on `|Δp| ≥ $0.10` jumps and direct `settlement_sources` links.
   - Displays full non-truncated reciprocal `orderbook_fp` depth bars and computes real-time **depth-weighted VWAP fill price + slippage + 6dp fee impact** on the order ticket before execution.
3. **End-to-End Resolution Lifecycle Tracking (`YES` / `NO` / `SCALAR`)**:
   - Verified contracts tracked from `active` on `2026-11-22` through `finalized` settlement by `2026-11-27`, including `KXPGATOUR-THRC26-MPEN` (The RSM Classic: Marco Penge → `YES` `$1.0000` at `2026-11-23T19:58:03Z`), `KXPGATOUR-THRC26-CBEZ`/`-MMCN`/`-MTHO` → `NO` (`$0.0000`), `KXDEMOFUTHOURLY-26NOV22H08-UP` → `YES` (`$1.0000`), `KXDEMOFUTHOURLY-26NOV27H19-UP` → `NO` (`$0.0000`), and `KXXISUCCESSOR-45JAN01-DXUE` → `SCALAR` (`$0.5000`).
4. **Automated Strategy Simulation, Authenticated Demo Account Sync & Custom Strategy Lab**:
   - Runs 5 built-in strategies + user-defined custom strategies categorized by trade type, alongside automated hourly GitHub Actions Demo Account execution (`demo-account.yml` → `data/account.json`) and same-origin local/cloud V2 order relay (`python3 -m kalshi_engine.relay_server --host 0.0.0.0 --port 8787` exposing `/api/demo/status` and `/api/demo/order` with zero `127.0.0.1` browser dependencies).

---

## 4. Summary of Key Repository & Upstream Irregularities Flagged (`2026-11-27`)

Full line-by-line audit with official links: [`audit/REPO_LINE_BY_LINE_AUDIT.md`](REPO_LINE_BY_LINE_AUDIT.md), [`/flagged.html`](https://kanlerxz87-cyber.github.io/Tradebot1/flagged.html), and [`/demo-desk/flagged/`](https://kanlerxz87-cyber.github.io/Tradebot1/demo-desk/flagged/).
- **Workflow HTML Staleness (`R13` — Fixed in `3f5311c5`)**: `.github/workflows/collect-node.yml` and `demo-account.yml` updated `data/live/*` and `data/account.json` every 30–60m without running `node scripts/build-site.mjs`, causing all 19 generated HTML pages and `AUD-08` to go stale after every scheduled commit. Both workflows now regenerate and stage all 19 HTML pages.
- **Series Fee Multiplier Drift (`R16` & `U8` — Fixed & Flagged `F-19` in `3f5311c5`)**: Kalshi's July 7, 2026 Fee Schedule PDF lists `KXBTCY` with `Maker=0, Taker=0`, whereas live Demo `GET /series/KXBTCY` returns `fee_multiplier: 1, fee_type: "quadratic"`. Wired `series.fee_multiplier` end-to-end across `tools/collector.mjs`, `tools/strategies.mjs`, and `demo-desk/assets/live-core.mjs`, and published discrepancy `F-19` on `/flagged.html`.
- **Stale Portfolio Seed Note & Browser Relay URL (`R15`, `R16` — Fixed in `3f5311c5`)**: Removed the stale `"No simulated position has been opened yet"` note from `data/live/portfolio.json` (which held 8 open positions) and replaced `http://127.0.0.1:8787` in `demo-desk/assets/live-app.mjs` with same-origin relative `/api/demo/*`.
