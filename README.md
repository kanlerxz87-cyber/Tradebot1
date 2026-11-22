# Tradebot1 — Kalshi Demo Research Desk

[**Open the dashboard**](https://kanlerxz87-cyber.github.io/Tradebot1/docs/) · [Portfolio & strategies](https://kanlerxz87-cyber.github.io/Tradebot1/docs/portfolio/) · [Executive summary](https://kanlerxz87-cyber.github.io/Tradebot1/docs/executive-summary.html) · [Flagged for Review](https://kanlerxz87-cyber.github.io/Tradebot1/docs/review/)

A source-linked research workspace for **gas prices, elections, culture, crypto and golf**. Public market observations, hypothetical paper accounts, and authenticated demo-account activity are kept separate. **No real-money trading, invented market prices, or promised ROI.**

## What is implemented

- **Nine primary pages:** overview, five topics, portfolio, executive summary and Flagged for Review. Responsive navigation, event-grouped tables, search, sorting and formula-safe CSV export. Each factual table row links to an official source.
- **Honest source modes:** published, timestamped official snapshots; public browser REST where reachable; or a same-origin trusted service with REST and authenticated WebSocket adapters. Snapshots never generate alerts or pretend to be live.
- **Two scrolling alert feeds:** all observed moves of **at least $0.10 in either direction**, and a separately labeled research screen. A rolling 60-second observed window accumulates smaller moves and re-anchors after each alert. Polling can miss intervening trades.
- **Price and liquidity inspection:** real timestamped observations or official candle closes; 1-minute, 1-hour and 24-hour windows; chart hover; YES/NO depth with quantities at each price. Published depth is prominently marked **not current liquidity**.
- **Two independent paper strategies:** momentum and mean reversion, each with an explicitly hypothetical $1,000 starting balance. Fresh executable quotes/depth, event exposure limits, persistent ledgers, standard finalized binary settlement, and gross performance grouped by topic × strategy × side. Fees and net ROI remain unknown.
- **Demo-only backend:** full-path RSA/Ed25519 signing, public REST allowlists, WebSocket sequence recovery, SQLite history, SSE, source-linked portfolio reads and guarded V2 IOC order/cancel routes. Execution is disabled by default; private endpoints require a separate operator bearer token.

### What is not verified

**No configured demo credentials; no authenticated exchange stream, demo-account balance, fill or order has been verified in this session.** The local service runs, but this sandbox cannot reach Kalshi from its application process. GitHub Actions has collected public API snapshots; that is not an authenticated account connection. The public website never requests a private key or exposes private portfolio data.

The observed REST sample does not report dollar notional consistently. The dashboard **does not calculate price × volume** as turnover. Sorting by “Reported $ notional” uses only exchange-reported cumulative traded notional; blanks remain blank. Default 24-hour contract-count sorting is explicitly **not a dollar ranking**. Coverage is bounded, not exchange-wide, and an empty Culture page is not filled with substitute contracts. See [all review items](docs/VERIFICATION.md).

## Quick start — trusted same-origin service

Run from the repository root:

```sh
python -m venv .venv
.venv/bin/pip install -r services/kalshi/requirements.lock
.venv/bin/python -m uvicorn services.kalshi.kalshi_demo.server:app --host 0.0.0.0 --port 8000
```

The service serves `docs/` at `/` and `/api/…` on the same origin. Browser code uses relative API URLs, including in a remote preview. The process reads its **environment**, not an automatically loaded `.env` file. See [`.env.example`](.env.example), the [API contract](services/kalshi/README.md), and [operations/runbook](OPERATIONS.md). Do not put a private key, account token or database in the static site or Git.

For static-only preview, no JavaScript framework or npm dependency is needed:

```sh
python -m http.server 8000 --bind 0.0.0.0
# Open /docs/ on that server; account endpoints are intentionally absent.
```

## Verify and regenerate

```sh
python scripts/build_site.py
node --test tests/*.test.mjs
python tests/check_site.py
python python/test_simulator.py
.venv/bin/python -m pytest services/kalshi/tests -q
.venv/bin/python -m ruff check services/kalshi/kalshi_demo services/kalshi/tests

# Optional real Chromium end-to-end checks; fixtures are test-only.
npm ci --prefix services/kalshi/browser-check --ignore-scripts
npm test --prefix services/kalshi/browser-check
```

The browser suite tests desktop/mobile layouts, navigation, search, sorting, CSV, chart controls, both feeds, paper cash/settlement, and same-origin SSE/history/book adapters. Tests use recorded public observations or explicit synthetic fixtures with network calls blocked/mocked. Passing them **does not verify live execution**. Screenshots, browser binaries and databases are ignored under `services/kalshi/data/` or `node_modules/`.

## Data collection and publication

- `scripts/build_snapshot.py` reads **public demo endpoints only**, with bounded retries and sampling. It scans up to six high-contract-volume series per topic plus a newest-market sample, publishes at most eight events/topic and eight contracts/event, and includes a small set of sourced candle/depth snapshots. It retains original timestamps if refresh fails.
- GitHub Actions checks the backend, frontend, generated files and real Chromium scenarios before Pages deployment. Main-branch/scheduled runs fetch and validate a public snapshot, then stage only `index.html`, `.nojekyll`, `docs/` and `site/`.
- The workflow requests Actions-based Pages publishing. Existing repository permissions may leave the legacy `main /` publisher configured; the committed source-linked snapshot and root redirect are retained as fallback. A successful workflow alone is not a content check. Final PR/deployment evidence is recorded on the [coordination board](COORDINATION.md).
- GitHub Pages is a **static research publication**, not the host for the signing service or continuous trading automation. No secret, runtime database or backend process is included in its artifact.

## Repository review and preserved earlier work

- `docs/`, `scripts/`, `tests/`: supported public UI, generator, snapshot collection and deterministic frontend checks.
- `services/kalshi/`: supported demo-only service, pinned dependencies, tests, browser checks and verification manifest.
- `EXECUTIVE_SUMMARY.md`, `OPERATIONS.md`, `docs/VERIFICATION.md`: requirements/status, operations and source-by-source verification.
- `site/` and `python/`: preserved earlier-session prototype and simulator. **The prototype's synthetic fallback is not official data. The legacy `python/kalshi_client.py` uses relative-path signing and obsolete order writes; do not use it for current execution.** The supported replacement is `services/kalshi/`. Original work remains in Git; discrepancies are published rather than erased.
- `COORDINATION.md`: task owners, non-overlapping claims, additive conflict resolutions and release evidence.

## Official references

[Demo environment](https://docs.kalshi.com/getting_started/demo_env) · [Events](https://docs.kalshi.com/api-reference/events/get-events) · [Market lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle) · [Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) · [Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) · [Authentication](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests) · [V2 orders](https://docs.kalshi.com/api-reference/orders/create-order-v2) · [Historical data](https://docs.kalshi.com/getting_started/historical_data) · [GitHub Pages hosting](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)

Independent research. Not affiliated with Kalshi. Demo prices and hypothetical returns are not production trading evidence.
