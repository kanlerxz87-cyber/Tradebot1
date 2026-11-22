# Kalshi demo service — API contract

This is a **separately hosted, demo-only** backend for the static dashboard. GitHub Pages cannot run it. It never accepts a production API URL, never sends a key to the browser, and never treats sample data as exchange data. Source verification is in [`verification.json`](verification.json). Operational limits and outstanding deployment requirements are in [`../../OPERATIONS.md`](../../OPERATIONS.md).

## Run from repository root

```sh
python -m venv .venv
.venv/bin/pip install -r services/kalshi/requirements.lock
.venv/bin/python -m uvicorn services.kalshi.kalshi_demo.server:app --host 0.0.0.0 --port 8000
```

Environment configuration is documented in `.env.example`; the process reads its environment, not a committed dotenv file. No Kalshi credentials are provisioned in this checkout. Without them, public REST polling is attempted, WebSocket/account access is explicitly disconnected, and demo order submission is disabled. No synthetic fallback is silently loaded.

## Public read routes

All missing/unconfirmed numeric values are JSON `null`. Prices/quantities are decimal strings, not binary floating-point. Every data row carries `source_url` and observation metadata. Public routes never contain private account data.

| Route | Response / purpose | Official specification |
| --- | --- | --- |
| `GET /api/health` | service mode, connectivity, last success, limitations, credential-presence boolean (never secrets) | [Demo environments](https://docs.kalshi.com/getting_started/demo_env) |
| `GET /api/snapshot` | `{health, events, markets, alerts, selected_alerts, paper}`; persisted observed data only | [Get Events](https://docs.kalshi.com/api-reference/events/get-events) |
| `GET /api/events?topic=crypto` | Event groups in the five requested topics, ordered by reported cumulative dollar notional when complete | [Ticker notional](https://docs.kalshi.com/websockets/market-ticker) |
| `GET /api/alerts?selected=false&limit=100` | Newest-first alerts; inclusive $0.10 threshold, rolling 60-second observed last-price window, deduplicated excursions | [Ticker price](https://docs.kalshi.com/websockets/market-ticker) |
| `GET /api/markets/{ticker}/history?window=minutes` | observed YES-price points; seconds = 60s, minutes = 1h, hours = 24h. No manufactured pre-connection history | [Ticker timestamps](https://docs.kalshi.com/websockets/market-ticker) |
| `GET /api/markets/{ticker}/orderbook` | YES/NO bid levels and complementary asks, quantities, freshness and source; no order-count claims | [Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) |
| `GET /api/stream` | Server-sent events: `snapshot` initially and `update` after observation; 15s heartbeat. Dropped clients resynchronize via snapshot | [WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets) |
| `GET /api/kalshi/{path}` | Allowlisted public GET passthrough (`exchange/status`, `events`, `series`, `markets`, market/orderbook and series candlesticks). Not an open proxy; no authenticated/private paths | [Public market data](https://docs.kalshi.com/getting_started/quick_start_market_data) |
| `GET /api/paper` | Persistent, explicitly hypothetical strategy ledgers and gross performance. Fees/net ROI remain unknown | [Settlement rules](https://docs.kalshi.com/getting_started/market_settlement) |
| `GET /api/verification` | Official sources, fact-by-fact checks and limitations | [Documentation index](https://docs.kalshi.com/llms.txt) |

The public proxy preserves the upstream JSON so the browser can use the same adapter as direct public REST. `Access-Control-Allow-Origin` is restricted to configured origins; same-origin preview uses relative `/api/…` URLs.

## Protected routes

These require `Authorization: Bearer <operator token>`. This is an independently provisioned service token, **not** the Kalshi key. Store it only in a trusted client/session, not in a public static asset or URL. A missing server token disables these routes. Private responses are `Cache-Control: no-store` and do not enter public SSE.

| Route | Behavior | Official specification |
| --- | --- | --- |
| `GET /api/portfolio` | Balance + fully paginated positions, orders, fills and settlements, with per-source errors/coverage. Account values stay blank when disconnected | [Balance](https://docs.kalshi.com/api-reference/portfolio/get-balance), [Positions](https://docs.kalshi.com/api-reference/portfolio/get-positions) |
| `POST /api/orders` | Demo limit buy only. Body: `{ticker, outcome: "yes" or "no", count: "1.00", limit_price: "0.5000", client_order_id: "uuid"}`. Default disabled, fresh source/price-grid/market checks, IOC, per-order and persistent cumulative budget. No automatic retries | [Create Order V2](https://docs.kalshi.com/api-reference/orders/create-order-v2) |
| `DELETE /api/orders/{order_id}?ticker=…` | Cancel an order using ticker-based shard routing. Never implies a fill or cancellation until upstream confirms | [Cancel Order V2](https://docs.kalshi.com/api-reference/orders/cancel-order-v2) |
| `GET /api/orders/journal` | Local submission audit, including ambiguous timeouts; reservations are not silently released or resubmitted | [Client order IDs](https://docs.kalshi.com/getting_started/quick_start_create_order) |
| `POST /api/controls/kill` | Disables new demo orders for the running process. IOC orders have no intended resting remainder; an in-flight request may already have been accepted | [Time in force](https://docs.kalshi.com/api-reference/orders/create-order-v2) |

Only local paper strategies are automated by default. **No automatic submission to a demo account is enabled.** Demo order execution requires both a trusted credential deployment and the explicit server-side enable flag. Never assume a successful submission means a fill. The service deliberately implements buys, not arbitrary leverage, shorts, market orders, withdrawals or production trading.

## Meaning of the analytics

- Ranking uses the exchange-reported **cumulative traded dollar notional**, not actual cash spent, not 24-hour turnover, not `volume × latest price`. Event totals are only present when every tracked child market has that field; otherwise they are null with incomplete coverage.
- Topic matching uses explicit words in official series metadata. It is a transparent local categorization, **not** Kalshi's verified taxonomy. Unmatched/ambiguous topics are omitted and counted for review.
- Alert selection is an **unvalidated research heuristic**, not a prediction of profit. It needs at least 20 earlier observations, fresh executable depth, ≤$0.04 spread, ≥10 contracts, and a hypothetical pre-fee edge ≥$0.03 and gross ROI ≥5%. The two hypothesis strategies (mean reversion and momentum) are separately accounted. Estimated fair values are model outputs, not sourced facts.
- Paper orders consume displayed opposing depth in each hypothetical account, reject stale books, never fill at last price, and keep cash/cost basis/settlement ledgers. Strategies run independently, so they do not claim simultaneously available exchange liquidity across hypothetical accounts.
- Net ROI/fees remain null until an actual fee source is available; no universal fee schedule is invented. News annotations are empty unless a source and timestamp are observed. A timestamp association must never be represented as causation.
- Settlement requires REST `status=finalized` and a compatible standard $1 binary `result=yes/no`. The API filter named `settled` is not a REST status value. A closed market is not resolved. Scalar/void/nonstandard settlement is flagged rather than forced into YES/NO; closed markets continue to be tracked.

## Test

```sh
.venv/bin/python -m pytest services/kalshi/tests -q
.venv/bin/ruff check services/kalshi
```

Tests use clearly synthetic in-memory fixtures and a mocked transport; passing tests verify implementation behavior, not a successful live exchange/account connection. SQLite files, local keys, dependencies and raw private account history are excluded from Git.
