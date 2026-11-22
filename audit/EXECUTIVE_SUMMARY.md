# Executive Summary — Kalshi Demo Live Alerting, Strategy & Portfolio System

**Date:** 2026-11-22 (UTC)  
**Repository:** `kanlerxz87-cyber/Tradebot1`  
**Live Interactive Dashboard & Category Hub:** [`/live/`](https://kanlerxz87-cyber.github.io/Tradebot1/live/)  
**Prior Preserved Implementations:** [`/docs/`](https://kanlerxz87-cyber.github.io/Tradebot1/docs/) (`c9075e75`) · [`/site/`](https://kanlerxz87-cyber.github.io/Tradebot1/site/) (`arena-39ef3867`)

---

## 1. Mission & Scope

This project collects, organizes, verifies, and analyzes live **Kalshi Demo Environment** prediction markets across strictly **five topics only**:
1. **Gas Prices** (`Economics` / `Commodities`, tag `Oil and energy` — e.g., `KXAAAGASMIN`, `KXAAAGASMINTX`)
2. **Elections** (`Elections` — e.g., `KXPRESPERSON-28`, `KXSENATEIAD-28`, `KXNEXTNATOSECGEN-99`)
3. **Culture** (`Entertainment` — e.g., `KXPERFORMBONDSONG-35`, `KXGTA7RELEASEDATE-USA`, `KXGRAMBPS-68`)
4. **Crypto** (`Crypto` on shard `2` + `KXDEMOFUTHOURLY` BTC hourly benchmark on shard `0`)
5. **Golf** (`Sports`, tag `Golf` — e.g., `KXPGATOUR-THRC26`, `KXPGATOUR-AUCPBCS26`)

Topics are separated into dedicated category subpages (`/live/gas/`, `/live/elections/`, `/live/culture/`, `/live/crypto/`, `/live/golf/`) and separated topic panels on the main dashboard, while markets belonging to the same `event_ticker` are grouped together and ranked by verified dollar activity.

---

## 2. Official Endpoints & Protocol Findings (Verified 2026-11-22)

| Layer | Verified Value | Official Source |
|---|---|---|
| Demo REST Base (Primary) | `https://external-api.demo.kalshi.co/trade-api/v2` | [API Environments](https://docs.kalshi.com/getting_started/api_environments.md) · [Live Status](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) |
| Demo REST Base (Supported Alternate) | `https://demo-api.kalshi.co/trade-api/v2` | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env.md) · [Live Status](https://demo-api.kalshi.co/trade-api/v2/exchange/status) |
| Demo WebSocket (Primary) | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets.md) |
| Demo WebSocket (Supported Alternate) | `wss://demo-api.kalshi.co/trade-api/ws/v2` | [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets.md) |
| Exchange Sharding Status | `exchange_active: true`, `trading_active: true` across 4 shards (`0`: Default, `1`: Demo shard 1, `2`: Demo shard 2 [Crypto], `3`: unnamed) | [Live Exchange Status](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) |
| Request Signing (REST & WS) | Headers `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP` (ms, ±30s), `KALSHI-ACCESS-SIGNATURE` = Base64 signature over `timestamp + METHOD + full_path_without_query` (e.g., `/trade-api/v2/portfolio/balance` or `/trade-api/ws/v2`) using Ed25519 (RFC 8032) or RSA-PSS/SHA-256 | [API Keys](https://docs.kalshi.com/getting_started/api_keys.md) |
| V2 Order Execution | `POST /trade-api/v2/portfolio/events/orders` (`side: "bid"\|"ask"`, fixed-point dollar `price`, string `count`, `client_order_id`). Legacy `POST /portfolio/orders` is removed (`410 Gone`). | [Create Order (V2)](https://docs.kalshi.com/api-reference/orders/create-order-v2.md) · [Quick Start: Create Order](https://docs.kalshi.com/getting_started/quick_start_create_order.md) |
| Orderbook Liquidity Mechanics | `GET /markets/{ticker}/orderbook` returns `orderbook_fp.yes_dollars` and `no_dollars` sorted **ascending** (best bid is **last** element `[-1]`). Implied executable `YES Ask = $1.00 - NO Bid`; `NO Ask = $1.00 - YES Bid`. | [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses.md) |
| Lifecycle & Resolution | Filter `?status=open` matches REST `status: "active"`; filter `?status=settled` matches REST `status: "finalized"` with `result` in `{"yes", "no", "scalar"}` and `settlement_value_dollars`. | [Market Lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle.md) |
| Fee & Precision Model | Trade fees computed to `$0.000001` (`ceil_6dp`), aligned to `$0.0001` (Direct) or `$0.01` (Non-Direct) via per-order rounding accumulator and rebates. | [Fee Rounding](https://docs.kalshi.com/getting_started/fee_rounding.md) |

---

## 3. Core System Capabilities (`/live/` + `kalshi_engine/`)

1. **Dual Real-Time Scrolling Alert Chats (`|Δp| ≥ $0.10`)**:
   - **All-Events Swing Chat**: Streams every observed contract price swing `≥ $0.10` in either direction. Pre-loaded with **14 verified real trade-by-trade swings** (`+$0.10`, `-$0.30`) captured live from `KXDEMOFUTHOURLY-26NOV22H08-UP` (`GET /markets/trades`) with exact UUID `trade_id` links, and continuously updated via live browser polling of `/markets` and `/markets/trades`.
   - **Selective High-ROI Model Chat**: Filters `≥ $0.10` swings through a transparent quantitative model evaluating mean-reversion/momentum edge, bid-ask spread tightness, resting orderbook depth, and fee-adjusted payoff ratio (explicitly documented as a heuristic filter, not a guaranteed return).
2. **Interactive Time-Series Chart & Liquidity Depth**:
   - X-axis selectable across **Seconds** (5-second trade tape & session ticks), **Minutes** (Kalshi 1m candlesticks), and **Hours** (Kalshi 60m candlesticks / 24h range); Y-axis plots contract price (`$0.00–$1.00`).
   - Marks `≥ $0.10` jump points directly on the graph alongside verified `settlement_sources` reference links (e.g., Coinbase BTC-USD candles, AAA Fuel Gauge, PGA Tour, Recording Academy) without fabricating causal news claims.
   - Displays both resting `YES/NO Bids` and implied executable `YES/NO Asks` so traders immediately see exact contract quantities available at every price point.
3. **Resolution Lifecycle Tracking (`YES` / `NO` / `SCALAR`)**:
   - Tracks watched contracts via `GET /markets?tickers=...` through `active → closed → determined → finalized`, recording verified outcomes across topics (including `KXDEMOFUTHOURLY-26NOV22H07-UP` → `YES` settled live at `2026-11-22T07:01:32Z`, `KXAAAGASMIN-26DEC31-3.80` → `YES`, `KXPGATOUR-AUCPBCS26-*` → `NO`, `KXGRAMBPS-68-MES` → `YES`, and `KXXISUCCESSOR-45JAN01-DXUE` → `SCALAR $0.50`).
4. **Automated Strategy Simulation, Custom Strategy Builder & Trade Execution**:
   - Runs 5 built-in strategies (`Momentum Breakout`, `Mean-Reversion Fade`, `Tight-Spread Liquidity`, `Favorite Follow`, `Longshot Value`) plus an interactive **Custom Strategy Builder** categorized by topic, trade type, trigger swing, and price band.
   - Provides a live **Order Execution Ticket** supporting instant persistent paper execution (`localStorage`) AND optional local signed relay connection (`kalshi_engine/relay_server.py`) to an authenticated Kalshi Demo account (`POST /trade-api/v2/portfolio/events/orders`). No private keys are ever requested or stored on GitHub Pages.

---

## 4. Summary of Key Repository & Upstream Irregularities Flagged

Full line-by-line audit with official links: [`audit/REPO_LINE_BY_LINE_AUDIT.md`](REPO_LINE_BY_LINE_AUDIT.md) and [`/live/flagged/`](https://kanlerxz87-cyber.github.io/Tradebot1/live/flagged/).
- **`python/kalshi_client.py` (lines 53–56, 90–93)**: Signs `/portfolio/balance` without `/trade-api/v2` (`401 Unauthorized`) and posts to removed `/portfolio/orders` (`410 Gone`). Fixed cleanly in non-overlapping `kalshi_engine/kalshi_v2_client.py`.
- **`site/assets/app.js` (lines 111, 154, 183–196, 253)**: Checks `m.status === "settled"` instead of `"finalized"`, polls only `?status=open`, ignores `favorite`/`longshot` toggles, and truncates `no_dollars` orderbook levels when `no_dollars.length > yes_dollars.length`.
- **`docs/data/snapshot.json` (in git on `main`)**: Empty (`events: []`) in git source, causing legacy `main /` Pages builds to serve an empty snapshot if `pages-build-deployment` runs after Actions. Solved in `/live/data/verified_snapshot.json` by committing verified point-in-time Kalshi Demo API responses directly in git.
- **Upstream Kalshi Demo Metadata Anomalies**: Official Kalshi Demo `/series` responses include real test-data mismatches (e.g., series `HOUSE` linking `ROCKET.pdf` / FAA; `KXCANADALIBERAL` linking SFUSD; `KXIRANCRUDE` linking BLS CPI). All flagged with direct official API URLs.
