# Tradebot1 — Kalshi demo-environment research

[Research desk](https://kanlerxz87-cyber.github.io/Tradebot1/docs/desk/) ·
[Market monitor](https://kanlerxz87-cyber.github.io/Tradebot1/docs/) ·
[Executive summary](https://kanlerxz87-cyber.github.io/Tradebot1/docs/desk/executive-summary.html) ·
[Flagged for Review](https://kanlerxz87-cyber.github.io/Tradebot1/docs/desk/flagged.html) ·
[Prototype](https://kanlerxz87-cyber.github.io/Tradebot1/site/)

The repository began as a one-line README. Parallel sessions built independent implementations of the
same brief; both are kept, because they make different trade-offs and each is useful in its own way.

| Path | What it is | Data source |
| - | - | - |
| **`docs/desk/`** | **Research desk** — scheduled collector, ≥ $0.10 alert archive, two scrolling chats, price + liquidity charts, resolution tracker, four autonomous paper strategies, verified tables | public production REST, collected server-side every 15 min |
| `docs/` | **Market monitor** — browser-side dashboard, no backend | public demo REST polled from the visitor's browser |
| `site/` | First standalone prototype (simulated fallback, local simulator, credentialed python client) | sample/simulated |

Neither frontend touches a real demo account, and no production order path exists anywhere in the
repository.

## Research desk (`docs/desk/`)

The autonomous half of the repository: a Python package and a 15-minute GitHub Actions loop.

* **Topics** — gas prices, elections, culture, crypto, golf, using Kalshi's own category/tag fields
  (gas → `KXAAAGASM` + Economics/Commodities; elections → `Elections`; culture → `Entertainment`
  (+ `Social`), because no Culture category exists; crypto → `Crypto`; golf → `Sports` tag `Golf`).
  Each topic gets its own page; events stay grouped inside a topic.
* **Alerts** — `|Δ mid| ≥ $0.10` (tolerance 1e-9, last-trade fallback), stored with price, size,
  volume, open interest and candidate news links, and rendered as two scrolling chats: every move, and
  the subset that passes a published six-weight ROI screen (score ≥ 0.45).
* **Lifecycle** — every followed event is polled until Kalshi marks it settled, then recorded as YES or
  NO with the market's own `result`, plus the payout the book actually received.
* **Trading** — four strategies (momentum, fade, late favourite, cheap upside) with fixed-fraction
  sizing (2% of equity, 12-open cap, book-depth cap), spread + modelled fees, settlement at $1/$0.
  Analytics by strategy, topic, price band and exit reason.
* **Verification** — every table row carries an official `docs.kalshi.com` link and a check date;
  anything unconfirmed is blank and listed on `docs/desk/flagged.html` (14 items, 0 blocking).
* **Automation** — `.github/workflows/collect.yml` (every 15 min) collects, rebuilds the static tables,
  runs integrity + link gates, commits the snapshot and ledger, then verifies the published URL.
  `.github/workflows/ci.yml` runs 48 unit tests on every push and PR.

Local use:

```sh
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                     # 48 tests
.venv/bin/python -m kalshi_trader.cli collect     # one live cycle → docs/desk/data/*.json
.venv/bin/python -m kalshi_trader.cli serve       # site + API + WebSocket on :8000
.venv/bin/python tools/build_site.py --check      # generated tables current
.venv/bin/python tools/check_links.py             # no broken internal links
```

No API key is needed for market data. `cli demo-status` reports whether demo credentials exist; if
`KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY` are added as repository secrets, the demo adapter activates
without any code change.

Deeper reading: [`EXECUTIVE_SUMMARY.md`](EXECUTIVE_SUMMARY.md) (both implementations),
[`docs/desk/verification.html`](docs/desk/verification.html),
[`docs/desk/flagged.html`](docs/desk/flagged.html),
[`docs/desk/requirements.html`](docs/desk/requirements.html),
[`docs/desk/strategies.html`](docs/desk/strategies.html).

## Trade board (`board.html`, session `9bea7e55`)

A third, independent implementation, this one in Node with no runtime dependencies. It is linked from
the landing page as **"Trade board"**.

| Path | What it is |
| - | - |
| `board.html` | Live events ranked by resting bid dollars, grouped by topic, with the headline figures. |
| `dashboard.html` | Two auto-scrolling alert feeds — every swing ≥ $0.10, and a labelled heuristic-filtered subset — plus the observation log. |
| `market.html?t=TICKER` | Price chart (60s–24h window), order-book ladder showing contracts at each price, settlement rules, a local paper-trade calculator. |
| `markets.html`, `portfolio.html`, `strategies.html`, `demo-account.html` | Market list by topic, simulated results, strategy rules, the real demo account. |
| `executive-summary.html`, `sources.html`, `methodology.html`, `suggestions.html`, `flagged.html`, `api.html` | Status matrix, source registry, exact formulas, next steps, 17 source-linked flags, endpoints. |
| `categories/{gas,elections,culture,crypto,golf}.html` | One page per topic: the request that proves its discovery rule, its markets, resolutions and swings. |

Everything published is generated from `data/*.json` by `scripts/build-site.mjs` from
`templates/*.tpl`. The generator **fails the build** if any data-table row has no source link, and the
pages read only committed files, so the site works with no backend and no key.

```sh
npm install                     # jsdom, used only by the render test
npm test                        # 32 assertions, including Kalshi's own fee table
node scripts/check-data.mjs     # the committed JSON against its contract
node scripts/build-site.mjs && node scripts/build-site.mjs --check
node scripts/check-links.mjs    # 19 pages, 642 references
node scripts/check-render.mjs   # jsdom render of every page, source links intact
node tools/collector.mjs --dry-run    # fetch without writing (needs egress)
```

Collection: `.github/workflows/collect-node.yml` polls the demo REST API every 30 minutes (offset
from the Python collector), `.github/workflows/demo-account.yml` takes a signed hourly read of the
demo account, and the board keeps its own separate data under `data/`. Verification record:
[`verification/2026-11-22-9bea7e55.md`](verification/2026-11-22-9bea7e55.md).

| Page | URL |
| - | - |
| Trade board | <https://kanlerxz87-cyber.github.io/Tradebot1/board.html> |
| Alerts | <https://kanlerxz87-cyber.github.io/Tradebot1/dashboard.html> |
| Flagged for review | <https://kanlerxz87-cyber.github.io/Tradebot1/flagged.html> |

## Market monitor (`docs/`)

- Five separate topic pages. Every market, orderbook, paper ledger and lifecycle table row links to its
  official Kalshi public endpoint. Ranking is a derived **estimated 24h $ proxy**: per event, the sum of
  `last YES price × 24h contract volume` over scanned contracts — not exchange-reported turnover.
- Public REST discovery every 90 seconds, tracked tickers every 45 seconds, minute/hour Kalshi candles
  and seconds-level browser-session observations.
- Two scrolling lists of **observed** ≥ $0.10 last-YES changes: all, and an explicit
  spread/volume/ask-price screen. A published snapshot is a baseline, never an alert.
- Local paper YES buys at the reported ask, marked at the reported bid, finalized per Kalshi
  `status=finalized` + `result`. No fees, slippage or fill verification; state lives in the browser.
- A scheduled Pages workflow generates a bounded public demo snapshot into the deployment artifact;
  empty responses never become invented values.

## Other parallel-session deliverables (preserved)

- [`docs/VERIFICATION.md`](docs/VERIFICATION.md), [`site/`](site/) and [`python/`](python/) were merged by
  session `arena-39ef3867`. The prototype's simulated display values are **not** verified quotes.
- [`python/README.md`](python/README.md) describes a credentialed local demo client. Never put a private
  key in this repository, the public site or localStorage.
- The **trade board** above (`board.html` and its pages) was merged by session `9bea7e55`.
- [`COORDINATION.md`](COORDINATION.md) records owners, verification and cross-session merge handling.
  The landing page at `/` links every implementation and none of them replaced another.

## Verification and local preview

```sh
node --test tests/*.test.mjs
python3 tests/check_site.py
python3 python/test_simulator.py
node --check docs/assets/app.mjs
node --check site/assets/app.js
python3 -m http.server 8000 --bind 0.0.0.0
```

Open `http://localhost:8000/` for the gateway, `/docs/desk/` for the research desk or `/docs/` for the
monitor. No npm dependencies.

## Official sources checked 2026-11-22

- [API environments, demo vs production credentials](https://docs.kalshi.com/getting_started/api_environments)
- [Public events, nested markets, pagination](https://docs.kalshi.com/api-reference/events/get-events.md)
- [Market quote/result/volume fields and caching](https://docs.kalshi.com/api-reference/market/get-markets.md)
- [Lifecycle and finalized status](https://docs.kalshi.com/getting_started/market_lifecycle.md)
- [Orderbook levels](https://docs.kalshi.com/getting_started/orderbook_responses) ·
  [candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)
- [Rate limits](https://docs.kalshi.com/getting_started/rate_limits) ·
  [creating orders](https://docs.kalshi.com/getting_started/quick_start_create_order) ·
  [WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets)
- [Series/event/market terms and the KXAAAGASM scheme](https://docs.kalshi.com/getting_started/terms) ·
  [category → tag map](https://external-api.kalshi.com/trade-api/v2/search/tags_by_categories)

## Limits

No authenticated demo portfolio, no executed orders, no verified fee schedule, no calibrated ROI model
and no verified news→price causality. The Pages setting is legacy `main /` and the Pages API rejects
`build_type` changes from this token (HTTP 403); the root `index.html` is the gateway to both dashboards.
See the [Flagged for Review page](https://kanlerxz87-cyber.github.io/Tradebot1/docs/desk/flagged.html).
