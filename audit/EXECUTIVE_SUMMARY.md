# Executive Summary — Kalshi Demo Live Alerting, Strategy & Portfolio System

**Date:** 2026-11-27 (UTC)  
**Repository:** `kanlerxz87-cyber/Tradebot1`  
**Live Interactive Dashboard & Category Hub:** [`/demo-desk/`](https://kanlerxz87-cyber.github.io/Tradebot1/demo-desk/)  
**Interactive Roadmap & Suggestions:** [`/demo-desk/suggestions/`](https://kanlerxz87-cyber.github.io/Tradebot1/demo-desk/suggestions/)  
**Flagged for Review (Blank Unverified Cells):** [`/demo-desk/flagged/`](https://kanlerxz87-cyber.github.io/Tradebot1/demo-desk/flagged/)

---

## 1. Mission & Scope

This desk collects, organizes, verifies, and analyzes live **Kalshi Demo Environment** prediction markets strictly across **five topics only**:
1. **Gas Prices** (`Economics`, tag `Oil and energy` — `KXAAAGASW-26NOV30`, `KXAAAGASMINTX-26DEC31`, and multi-day finalized `KXAAAGASMIN-26DEC31-3.60`)
2. **Elections** (`Elections` / `Politics` — `KXPRESPERSON-28` 10-candidate field with `356M+` volume and proportional `scalar` settlement `KXXISUCCESSOR-45JAN01-DXUE`)
3. **Culture** (`Entertainment` — `KXPERFORMBONDSONG-35` 5-contender field and finalized `KXGRAMBPS-68` `YES`/`NO` Grammy outcomes)
4. **Crypto** (`Crypto` on shard `2` — `KXBTCY-27JAN0100` `284M+` volume brackets — plus `KXDEMOFUTHOURLY` 5-second BTC hourly benchmark on shard `0`)
5. **Golf** (`Sports`, tag `Golf` — `KXPGATOUR-MAST27` Masters field plus multi-day tracked `KXPGATOUR-THRC26` and `KXPGATOUR-AUCPBCS26` settlements)

Topics are separated into dedicated subpages (`/demo-desk/gas/`, `/demo-desk/elections/`, `/demo-desk/culture/`, `/demo-desk/crypto/`, `/demo-desk/golf/`) and separated topic panels on `/demo-desk/`, while markets sharing the same `event_ticker` are grouped together and ranked by verified contract volume.

---

## 2. Official Endpoints & Protocol Findings (Verified 2026-11-27)

| Layer | Verified Value | Official Source |
|---|---|---|
| Demo REST Base (Primary) | `https://external-api.demo.kalshi.co/trade-api/v2` | [API Environments](https://docs.kalshi.com/getting_started/api_environments) · [Live Status](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) |
| Demo REST Base (Supported Alias) | `https://demo-api.kalshi.co/trade-api/v2` | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) · [Live Status](https://demo-api.kalshi.co/trade-api/v2/exchange/status) |
| Demo Market-Data WebSocket | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` (alias `wss://demo-api.kalshi.co/trade-api/ws/v2`) | [API Environments](https://docs.kalshi.com/getting_started/api_environments) · [WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets) |
| Demo User-Data & External-Feeds WS | `wss://user-ws.demo.kalshi.co/trade-api/ws/v2` (`warp-ws` deprecated) & `wss://external-feeds.demo.kalshi.co/trade-api/ws/v2` | [API Environments](https://docs.kalshi.com/getting_started/api_environments) |
| Exchange Sharding Status | `exchange_active: true`, `trading_active: true` across 4 shards (`0`: Default, `1`: Demo shard 1, `2`: Demo shard 2 [Crypto], `3`: `""`) | [Live Exchange Status](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) |
| Request Signing (REST & WS) | Headers `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP` (ms), `KALSHI-ACCESS-SIGNATURE` = Base64 signature over `timestamp + METHOD + full_path_without_query` (e.g., `/trade-api/v2/portfolio/balance` or `/trade-api/ws/v2`) via Ed25519 or RSA-PSS/SHA-256 | [API Keys](https://docs.kalshi.com/getting_started/api_keys) |
| V2 Order Execution | `POST /trade-api/v2/portfolio/events/orders` (`side: "bid"\|"ask"`, fixed-point dollar `price`, string `count`, `client_order_id`). Legacy `POST /portfolio/orders` returns `410 Gone`. | [Create Order V2](https://docs.kalshi.com/getting_started/quick_start_create_order) |
| Orderbook Liquidity & VWAP | `GET /markets/{ticker}/orderbook` returns `orderbook_fp.yes_dollars` and `no_dollars` sorted **ascending** (best bid at `[-1]`). Implied `YES Ask = $1.00 - NO Bid`; `NO Ask = $1.00 - YES Bid`. Multi-level fills walk asks ascending to compute exact VWAP. | [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses) |
| Lifecycle & Resolution | Filter `?status=open` matches `status: "active"`; filter `?status=settled` matches `status: "finalized"` with `result` in `{"yes", "no", "scalar"}` and `settlement_value_dollars`. | [Market Lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle) |
| 5-Step Fee & Precision Model | `fee = ceil_6dp(rate * fee_multiplier * C * P * (1-P))` (`0.07` taker / `0.0175` maker), `signed_revenue` aligned via `floor_step(..., step)` (`$0.0001` direct / `$0.01` non-direct), `rounding_fee >= 0` accumulated, rebate `min(accumulator, fee)`. Note Demo `/series/KXBTCY` returns `fee_multiplier: 1` vs Production `0`. | [Fee Rounding](https://docs.kalshi.com/getting_started/fee_rounding) · [Demo `/series/KXBTCY`](https://external-api.demo.kalshi.co/trade-api/v2/series/KXBTCY) |

---

## 3. Core System Capabilities (`/demo-desk/` + `kalshi_engine/`)

1. **Dual Real-Time Scrolling Alert Chats (`|Δp| ≥ $0.10`)**:
   - **Chat 1 — All-Events Swing Feed**: Streams every contract move `|Δp| ≥ $0.10` in either direction across the 5 allowed topics, including live 5-second fills on `KXDEMOFUTHOURLY-26NOV27H20-UP` (`+$0.10`, `-$0.30`), `KXAAAGASW-26NOV30-3.5000` (`+$0.37`), and `KXPRESPERSON-28-KHAR` (`+$0.94`).
   - **Chat 2 — Selective High-ROI Model Feed**: Enforces `net_roi ≥ 12%` after exact 6dp taker fees, `spread ≤ $0.08` (blocking `$0.62–$0.98` wide-spread traps), and `depth ≥ 25` contracts, surfacing only executable setups.
2. **Browser-Direct Live Polling + Dual-Host Failover + Same-Origin Preview Relay**:
   - Polls `external-api.demo.kalshi.co/trade-api/v2` directly from the visitor's browser (or every `20s` via the Auto-Poll toggle) with automatic failover to `demo-api.kalshi.co/trade-api/v2` and relative `/api/demo/*` (zero `127.0.0.1` / `localhost` browser references).
   - Fetches `/exchange/status`, `/markets?tickers=...`, `/markets/{ticker}/orderbook?depth=10`, and `/markets/trades`, pushing real-time `|Δp| ≥ $0.10` alerts, executing enabled strategies, and settling positions automatically when `market.status === "finalized"`.
3. **Interactive Time-Series Chart, Reciprocal Orderbook Ladder & Pre-Trade VWAP Preview**:
   - Canvas time-series chart with selectable **Seconds** (`5s` ticks), **Minutes** (`1m` candles), and **Hours** (`24h` window) X-axis views, diamond jump markers (`|Δp| ≥ $0.10`), and clickable official catalyst/settlement URLs.
   - Displays full non-truncated reciprocal `YES`/`NO` bids and implied asks alongside a real-time **Orderbook VWAP & 6dp Fee Preview** on the order ticket.
4. **Multi-Day Resolution Lifecycle Tracking (`YES` / `NO` / `SCALAR`)**:
   - Tracks open contracts observed on `2026-11-22` through official `finalized` outcomes verified on `2026-11-27`: `KXAAAGASMIN-26DEC31-3.60` (`YES`, `$1.0000`), `KXPGATOUR-THRC26-CBEZ/-ZBAU/-LABE` (`NO`, `$0.0000`), `KXDEMOFUTHOURLY-26NOV22H08-UP` (`YES`), `KXDEMOFUTHOURLY-26NOV27H19-UP` (`NO`), `KXGRAMBPS-68-MES/-DAI` (`YES`/`NO`), and `KXXISUCCESSOR-45JAN01-DXUE` (`SCALAR`, `$0.5000`).
5. **Multi-Strategy Automation, Custom Strategy Builder & Trade-Type Analytics**:
   - Automates 5 built-in strategies plus user-created custom rules, computes exact `BigInt` (JS) and `Decimal` (Python) 6dp fees + subpenny accumulators, and reports performance by both **Strategy** and **Trade Type** (`breakout_momentum`, `mean_reversion`, `selective_value`, `tail_convexity`, `custom_rule`).

---

## 4. Key Repository & Upstream Irregularities Identified & Addressed (`R1`–`R18`, `U1`–`U7`)

Full line-by-line details with official links: [`audit/REPO_LINE_BY_LINE_AUDIT.md`](REPO_LINE_BY_LINE_AUDIT.md) and [`/demo-desk/audit/`](https://kanlerxz87-cyber.github.io/Tradebot1/demo-desk/audit/).
- **Snapshot Verification Cleanup (`R13`)**: Line-by-line verification of `demo-desk/data/verified_snapshot.json` against live `/markets/{ticker}` endpoints caught 4 prior resolution entries with unverified non-zero `volume_fp` values (`KXGRAMBPS-68-MES/-DAI`, `KXAAAGASMIN-26DEC31-3.80`, `KXXISUCCESSOR-45JAN01-DXUE`) and 1 mislabeled PGA tournament (`KXPGATOUR-AUCPBCS26` = Austin Championship). All replaced 100% verbatim.
- **Exact Fixed-Point Fee Math (`R14`)**: Replaced IEEE-754 float scaling in `demo-desk/assets/live-core.mjs` (`0.8750000000000001` rounding bug) with exact `BigInt` decimal scaling and full 5-step `signed_revenue` `floor_step` alignment.
- **Proxy-Safe Browser Networking (`R15`)**: Removed hardcoded `http://127.0.0.1:8787` from `demo-desk/assets/live-app.mjs` and bound `kalshi_engine/relay_server.py` to `0.0.0.0` serving both static assets and `/api/demo/*` on the same origin.
- **Scheduled Workflow Drift Fix (`R16`)**: Updated `.github/workflows/collect-node.yml` and `.github/workflows/demo-account.yml` to run `node scripts/build-site.mjs` and `node scripts/check-links.mjs` and stage all 19 generated HTML files so scheduled captures never break `CI` or `pages.yml`.
- **Demo vs Production `fee_multiplier` Divergence (`R18`)**: Verified live that `/series/KXBTCY` returns `fee_multiplier: 1` on Demo vs `0` on Production — fee calculators must read `series.fee_multiplier` from the active environment's `/series/{ticker}` payload rather than hardcoding series overrides.
