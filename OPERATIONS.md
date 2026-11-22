# Operations — demo-only research service and Pages publication

## Deployment boundary

The primary `docs/` dashboard is public and static. The Python application is a **separate trusted process**. It must never be copied into a browser bundle with credentials, and its private database must never enter a Pages artifact. [GitHub Pages serves static sites](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages); [Kalshi authenticated requests require server-held signing material](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests).

In this session the service starts and the UI/browser tests work, but the application process cannot reach Kalshi and no demo credentials are configured. Public GitHub Actions collection and page-fetch source checks are separate evidence. **No authenticated order, fill, balance or stream is verified.**

## Local/same-origin service

From the repository root:

```sh
python -m venv .venv
.venv/bin/pip install -r services/kalshi/requirements.lock
.venv/bin/python -m uvicorn services.kalshi.kalshi_demo.server:app --host 0.0.0.0 --port 8000
```

This serves `docs/` at `/` and the API at `/api/…`. Use **one application worker** per SQLite/runtime instance. Multiple workers would run duplicate collectors and independent in-memory stream/kill controls. A production-quality service host would use TLS termination and a supervisor; do not expose an operator token over plain HTTP outside a trusted local network.

Browser code uses relative `/api/…` URLs, never browser-side localhost references. In Arena preview, the server binds `0.0.0.0` and accepts the proxy host. The user's browser and the service are not the same machine. To deploy behind a reverse proxy, proxy both static requests and `/api/…` to this one service; disable buffering for `/api/stream` and permit its 15-second heartbeats. The application does not trust forwarded identity for authorization.

## Configuration and secrets

See [`.env.example`](.env.example). `Settings.from_env()` reads the process environment. Merely creating a `.env` file does **not** load it. No secret value is required for static research or public REST collection.

Provision signing credentials only through a trusted host's secret mechanism, outside the repository and public asset tree. Never enter a private key or operator token in chat, a URL, a workflow log, browser localStorage, or a committed file. No secrets were requested or provisioned by this implementation session.

| Setting | Default / meaning | Official reference or policy boundary |
| --- | --- | --- |
| `KALSHI_REST_URL` | `https://external-api.demo.kalshi.co/trade-api/v2`; only the two documented demo roots accepted | [Demo roots](https://docs.kalshi.com/getting_started/demo_env) |
| `KALSHI_WS_URL` | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`; exact demo allowlist | [Demo stream](https://docs.kalshi.com/getting_started/demo_env) |
| `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH` | Empty. Must be provisioned together; key file `.pem` or `.key`, readable only by the service | [Signing](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests) |
| `KALSHI_OPERATOR_TOKEN` | Empty disables private routes; independently generated bearer secret of at least 32 characters. Local security policy, not a Kalshi credential | [Authenticated account boundary](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests) |
| `KALSHI_ENABLE_DEMO_ORDERS` | `false`. Enabling requires both signing credentials and operator authorization. Does not start an automated exchange-trading loop | [V2 execution semantics](https://docs.kalshi.com/api-reference/orders/create-order-v2) |
| `KALSHI_PAPER_AUTOMATION` | `true`. Server research-only strategies on qualifying observed alerts; independent of the account | [Depth inputs](https://docs.kalshi.com/api-reference/market/get-market-orderbook) |
| `KALSHI_POLL_SECONDS`, `KALSHI_MAX_PAGES` | `30`, `100`; discovery may be incomplete or take longer than the sleep interval. Health reports coverage/errors | [Cursor pagination](https://docs.kalshi.com/api-reference/events/get-events) |
| `KALSHI_MAX_ORDER_DOLLARS`, `KALSHI_MAX_SESSION_DOLLARS` | `10`, `100`; conservative **$1 payout-notional** caps, not fee-inclusive spend. “Session” reservations persist across process restarts | [Contract/order semantics](https://docs.kalshi.com/api-reference/orders/create-order-v2) |
| `KALSHI_DB_PATH` | `services/kalshi/data/observations.sqlite3`; private, ignored, mode 0600. Use a durable volume | [Durable submission identity](https://docs.kalshi.com/getting_started/quick_start_create_order) |
| `KALSHI_STATIC_DIR` | `docs`; only public research assets belong here | [Static hosting boundary](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages) |
| `KALSHI_ALLOWED_ORIGINS` | Exact comma-separated origins; default `https://kanlerxz87-cyber.github.io`. Same-origin preview needs no wildcard. CORS is not authorization | [Authenticated access](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests) |

Demo and production credentials differ. The client rejects production/unknown URLs, redirects and nonallowlisted public paths. It does not inherit arbitrary HTTP proxy credentials from environment (`trust_env=False`). Requests use bounded read retries; writes are never automatically retried. See the [API contract](services/kalshi/README.md) for all routes.

## Health, data modes and freshness

`GET /api/health` exposes connectivity, observation times, configured-credential **presence**, enabled/disabled execution and coverage; never secret material. `GET /api/snapshot` and SSE expose **public observations and explicitly hypothetical ledgers only**, not private account data.

Interpret the fields separately:

- `rest=polling` / `partial` describes the last collection pass, not guaranteed current prices or a full exchange scan.
- `websocket=connected` describes the adapter connection. Ticker is coalesced; public trade notifications supply execution observations. A sequence gap invalidates books and triggers reconnect/snapshot recovery.
- `data_stale` compares the most recent price timestamp with the configured freshness window. Individual markets may still be older. Quote, price, depth and notional timestamps are distinct; a new trade does not refresh an old bid.
- `/api/markets/{ticker}/history` returns observed points, not manufactured preconnection history; maximum 10,000 points with an explicit truncation indicator.
- On static Pages, a published snapshot is labeled **not live**. Historical candle/depth fallback keeps original evidence timestamps; it cannot create alerts or paper fills. Missing values remain null/blank.
- Browser direct REST runs discovery about every 180 seconds and refreshes up to 100 retained unresolved tickers every 20 seconds, round-robin. It is sampled and bounded; missing tickers are retained, not declared resolved. Stronger archive/lifecycle reconciliation belongs to the server.

## Paper and order risk boundaries

**Paper:** two independent $1,000 accounts, no leverage, maximum cumulative open cost $20/event/strategy. Browser entries use one contract at a fresh reported ask with size; server entries consume fresh opposing depth, rounded down to 0.01 contracts. These are counterfactual fills, not execution guarantees. Fees/net ROI stay null. Only compatible standard-$1 finalized binary YES/NO results settle. Stale quote marks stay null. Disputed/scalar/nonstandard outcomes require review.

**Demo orders:** bearer-protected `POST /api/orders`, body as documented in the [service contract](services/kalshi/README.md). It accepts buy-YES or buy-NO limit intents with a caller-persisted UUID4 `client_order_id`; maps NO onto the V2 YES price scale; checks exchange availability, tracked active market, notional, price grid, quantity/limit and caps; uses IOC and explicit self-trade prevention. It deliberately offers no production order, withdrawal, leverage or automatic account-trading loop.

The server **reserves before network I/O** in SQLite. Same ID + same intent returns the durable prior journal entry; same ID + different intent is rejected. A timeout/connection failure after submission is ambiguous. An accepted response can have zero fills. [Upstream client IDs do not provide permanent exactly-once semantics](https://docs.kalshi.com/getting_started/quick_start_create_order).

### When an order response is uncertain

1. Stop new order submission. Invoke protected `POST /api/controls/kill` using a trusted operator client.
2. Preserve the SQLite database and inspect protected `/api/orders/journal` and the live/historical account endpoints.
3. Reconcile upstream orders/fills using the existing client ID and ticker. Do **not** generate a new ID to retry an unresolved intent.
4. Reserved payout-notional remains consumed even for rejects/cancels; no unverified automatic release is implemented. This is deliberately conservative and is not an estimate of fee-inclusive cash loss.
5. The kill switch affects the running process. A request already in flight may have been accepted. Cancels remain available under kill. Before restarting after an incident, keep `KALSHI_ENABLE_DEMO_ORDERS=false`; an in-memory kill is not a durable deployment setting.

Protected requests belong in a trusted operator application. Do not add an operator bearer token to public Pages, a query string, a test fixture or an exported CSV. Private responses use `Cache-Control: no-store` and are excluded from SSE/public snapshots.

## Account reconciliation

The adapter reads balance, live positions first, orders, fills and live settlements, then historical positions/orders/fills, with a 15-second protected cache. Current scope is primary subaccount 0 across exchange shards. Balance/portfolio-value integer units are cents; raw supplied dollar strings are retained. Live/archive reads are not atomic and may overlap. Settlement records do not have the same archive counterpart as positions. See [official historical guidance](https://docs.kalshi.com/getting_started/historical_data).

Do not derive ROI from balance changes without deposits/transfers, fees and archive reconciliation. Unknown topic membership is not forced into one of the five categories. The public portfolio page intentionally displays no authenticated account values; it shows independently labeled paper analytics.

## Persistence, migration and backup

- SQLite uses WAL, a busy timeout and a private file. Documents include retained public markets, events, hypothetical ledgers and protected account cache; the order journal is durable. Treat the **entire database** as private.
- Schema version 2 uses `(ticker, event_id)` observation identity so distinct trades at the same millisecond are retained. Early version-0/1 timestamp schemas migrate transactionally. Legacy receipt rows receive explicitly local migration IDs, not fabricated exchange trade IDs. Existing IDs are preserved; unsupported future schemas refuse to downgrade.
- Back up with SQLite's backup API while running, or stop the process and preserve the database **with its WAL**. Copying only an active `.sqlite3` file can omit committed WAL data. Keep backups encrypted/private and outside `docs/`/`site/`.
- Before rollout, test a backup restore with order execution disabled. Never delete the order journal to regain a risk budget. Automatic age-based history pruning is not implemented; monitor disk usage and archive deliberately after backup.
- Browser localStorage is a separate, untrusted local paper/watchlist store, not a private account store or a shared durable collector. If disabled/full, the UI warns and retains the current in-memory view.

## Publication and release checks

Run the commands in [`README.md`](README.md). `scripts/build_site.py` generates nine consistent pages plus the public verification manifest/register; CI checks for uncommitted generated drift. `tests/check_site.py` checks local links/fragments/imports, official links on static factual rows, and snapshot provenance. Chromium verifies runtime rows and controls with disabled/mocked network. A test pass does not prove that all external websites are reachable.

Main-branch and scheduled publication:

1. Backend tests/Ruff, Node tests, static/link checks, preserved simulator checks and the Chromium suite must pass.
2. Collect an official public snapshot, retaining original times if refresh fails; validate it again.
3. Stage only the public root redirect, `.nojekyll`, `docs/` and preserved `site/`; upload the snapshot separately for audit. Never publish `services/`, a secret or a runtime database.
4. Request Pages `build_type=workflow` to avoid legacy-vs-Actions overwrite races. If repository permission denies this, record it; the root redirect and committed public snapshot keep the legacy `main /` path useful. Do not claim the configuration changed without checking.
5. Merge the explicit integration PR only after checks pass, verify the main deployment, fetch the public page and snapshot, and record the PR/merge/run/content evidence in `COORDINATION.md`.

The active-branch manual snapshot workflow only commits the public JSON on `arena/6addd9fe-tradebot1`, with a pre-push pull/rebase. Main/scheduled workflows do not commit or push another branch. After any branch snapshot refresh, synchronize before a local push.

## Known review items

[The generated register](docs/VERIFICATION.md) and [public review page](docs/review/index.html) are authoritative: account connectivity, network/CORS, Pages static hosting/source permissions, incomplete topic/notional coverage, Culture availability, unvalidated models, fees/net ROI, causal news, primary-subaccount/archive reconciliation and the preserved legacy client/prototype. Unknowns do not block publication, but broken builds, links, account separation or provenance do.
