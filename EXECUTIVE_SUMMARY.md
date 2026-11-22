# Executive summary — Kalshi demo environment

**Prepared:** 2026-11-22 (UTC) · **Repository:** `kanlerxz87-cyber/Tradebot1`
**Live gateways:** [research desk](https://kanlerxz87-cyber.github.io/Tradebot1/docs/desk/) ·
[market monitor](https://kanlerxz87-cyber.github.io/Tradebot1/docs/)

Two parallel sessions built independent implementations of the same brief and both are published, so this
summary covers both. **Part A** is the autonomous research desk: a Python collector package plus a
scheduled trading loop. **Part B** is the browser-side market monitor, preserved verbatim. Where the two
disagree, the desk's numbers come from a server-side collector and the monitor's from the visitor's own
browser session; the desk's verification register is the more complete of the two.

| | Part A — research desk | Part B — market monitor |
| - | - | - |
| Location | `docs/desk/` | `docs/` |
| Data path | scheduled server-side collector (production public REST) | browser polls public demo REST |
| Alerts | persisted ≥ $0.10 archive + live ticks | session-only ≥ $0.10 observations |
| Trading | 4 strategies, ledger committed to the repo | 1 screen, browser-local |
| Verification | 25 dated source rows, 14 flags | endpoint-level citations, review page |

---

## Part A — Research desk (`docs/desk/`)

**Prepared:** 2026-11-22 (UTC) · **Web version:** <https://kanlerxz87-cyber.github.io/Tradebot1/docs/desk/executive-summary.html>
**Scope:** a live dashboard, an alerting desk and an autonomous simulated trading book for five Kalshi
topics (gas prices, elections, culture, crypto, golf), built from an empty repository.

---

### 1. What was built

A single system with three loops:

1. **Collection** — a scheduled job scans every open Kalshi event, keeps only the five requested topics
   using Kalshi's own category/tag taxonomy, and records prices, sizes, volume, open interest and the
   visible order book.
2. **Alerting** — every move of at least **$0.10** in either direction is recorded and shown in a
   scrolling chat; a second chat shows only the alerts that pass a documented, deliberately simple ROI
   score. Price, liquidity and resolution are visible next to each alert.
3. **Trading** — four rule-based strategies trade those signals in a simulated ledger with fixed-fraction
   sizing, paying the spread and modelled fees, and settle at the exchange-reported outcome. Performance
   is reported by strategy, topic, price band and exit reason.

The site is static (GitHub Pages) and is refreshed by the job that collects the data. A bundled local
server adds seconds-level collection, a same-origin proxy and WebSocket push.

### 2. Verified API facts the build rests on

| Fact | Source |
| - | - |
| Demo REST: `https://external-api.demo.kalshi.co/trade-api/v2` (recommended), `https://demo-api.kalshi.co/trade-api/v2` (also supported) | [docs.kalshi.com/getting_started/api_environments](https://docs.kalshi.com/getting_started/api_environments) |
| Demo WebSocket: `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` (recommended), `wss://demo-api.kalshi.co/trade-api/ws/v2` (also supported) | same page |
| Signed text = `timestamp + METHOD + path` (no query string); RSA‑PSS/SHA‑256 or Ed25519 | same page; [portfolio/get-positions](https://docs.kalshi.com/api-reference/portfolio/get-positions) |
| Public market data needs no API key | [quick_start_market_data](https://docs.kalshi.com/getting_started/quick_start_market_data) |
| Orderbook returns **bids only**; asks implied as $1.00 − opposite bid | [orderbook_responses](https://docs.kalshi.com/getting_started/orderbook_responses) |
| Categories live on the series; `Golf` is a Sports tag; no `Culture` category exists | [terms](https://docs.kalshi.com/getting_started/terms), [tags_by_categories](https://external-api.kalshi.com/trade-api/v2/search/tags_by_categories) |
| US gas-price series is `KXAAAGASM` (Economics/Commodities, tags Oil and energy / Oil & Gas) | [terms](https://docs.kalshi.com/getting_started/terms) |
| Settlement pays $1 per winning contract; `result` is `yes`/`no` | [market_settlement](https://docs.kalshi.com/getting_started/market_settlement) |
| Orders: `POST /portfolio/events/orders`; 201 = accepted | [quick_start_create_order](https://docs.kalshi.com/getting_started/quick_start_create_order) |
| REST reads are cached and can lag several seconds | [quick_start_market_data](https://docs.kalshi.com/getting_started/quick_start_market_data) |

All 25 sourced claims, with check dates, are in [`docs/data/sources.json`](docs/data/sources.json) and on
the [verification page](https://kanlerxz87-cyber.github.io/Tradebot1/verification.html).

### 3. Key decisions

| Decision | Rationale | Flag |
| - | - | - |
| Market data from production (read-only), execution in paper | Production data is keyless, real and liquid; demo prices may not reflect real markets | F6 |
| Static site + scheduled collector rather than a fake “live” label | GitHub Pages cannot poll an exchange; the snapshot age is always displayed | F10 |
| Culture mapped to the official Entertainment category (+ Social) | No official Culture category exists | F3 |
| Golf by Sports/Golf tag; gas by KXAAAGASM + gas-price matching | Both are official fields; a keyword fallback is used only when the fields miss | F4 |
| Fee model applied but marked unverified | The official fee-schedule PDF could not be retrieved; P&L must not silently depend on it | F1 |
| Demo account left blank rather than estimated | A demo account and key can only be created by the account holder | F2 |
| ROI score is a published heuristic | Six weights, versioned, disclaimed; its value will be measured, not asserted | F12 |

### 4. What the numbers mean (and do not)

* Performance figures are **paper**, not exchange fills. Fees are modelled (unverified).
* Alerts are cycle-resolution: the cron runs every 30 minutes; the live server and direct mode raise
  that to seconds.
* Dollar-volume rankings use `volume_24h × price`, a derived figure labelled `_est` everywhere.
* The high-ROI chat is a noise filter, not a forecast. Its accuracy is whatever the ledger records.

### 5. Status at hand-off

| Item | Status |
| - | - |
| Dashboard, five topic pages, portfolio, strategies, API reference, verification, flagged, requirements | shipped |
| Alerting at ≥ $0.10 with two chats | shipped |
| Resolution tracking to YES/NO | shipped |
| Paper trading + analytics (4 strategies) | shipped and running on a schedule |
| Kalshi demo account integration | implemented, dormant — needs credentials (F2) |
| Official fee schedule | unverified (F1) |
| Breakages | 0 open; 14 flagged items, 0 blocking |

### 6. Next three moves

1. Create the demo account, add `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY` as repository secrets: paper
   results become exchange-confirmed demo results.
2. Retrieve the current fee schedule and flip `VERIFIED = True` in `kalshi_trader/fees.py` (clears F1).
3. Move collection to `orderbook_delta` WebSocket streaming once credentialed, so alerts fire on ticks
   rather than cycles.

---

<details>
<summary><strong>Part B — Market monitor executive summary (session c9075e75, preserved verbatim)</strong></summary>


**Date:** 2026-11-22 · **Repo:** `kanlerxz87-cyber/Tradebot1` ·
**Site:** GitHub Pages from `site/` (see `.github/workflows/pages.yml`)

## What this project is
A live, interactive dashboard for the **Kalshi demo environment** that tracks
the highest-dollar live events in **five topics only — gas prices, elections,
culture, crypto, and golf** — alerts on sudden contract-price swings of
**≥ $0.10**, visualizes price movement and order-book liquidity, tracks
events through to **yes/no resolution**, and runs **automated simulated
(paper) trades** across multiple strategies with full portfolio analysis.

## Official sources (verified line-by-line, 2026-11-22)
| Fact | Source |
|------|--------|
| Demo REST root: `https://external-api.demo.kalshi.co/trade-api/v2` (also `https://demo-api.kalshi.co/trade-api/v2`) | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| Demo WebSocket: `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` (also `wss://demo-api.kalshi.co/trade-api/ws/v2`) | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| Demo site: https://demo.kalshi.co/ — mock funds, credentials not shared with production | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| Public endpoints (e.g. Get Markets) need no auth; authenticated endpoints need API keys | [Making Your First Request](https://docs.kalshi.com/getting_started/making_your_first_request) |
| `GET /markets` returns `ticker`, `event_ticker`, `status`, `yes_bid/ask_dollars`, `last_price_dollars`, `volume_fp`, `open_interest_fp`, `result` (`yes`/`no`), etc. | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) |
| `GET /markets/{ticker}/orderbook?depth=` returns `orderbook_fp.yes_dollars` / `no_dollars` as `[price, size]` levels | [Get Market Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) |
| Auth = `KALSHI-ACCESS-KEY` + `KALSHI-ACCESS-TIMESTAMP` (ms, ±30 s) + `KALSHI-ACCESS-SIGNATURE`; sign `timestamp + METHOD + path` (no query string); Ed25519 or RSA-PSS/SHA-256 | [API Keys](https://docs.kalshi.com/getting_started/api_keys) |
| Production vs demo credentials are not interchangeable | [API Environments](https://docs.kalshi.com/getting_started/api_environments) |

Full table with every row sourced: [`docs/VERIFICATION.md`](docs/VERIFICATION.md).
Anything that could not be confirmed from an official source is left blank
there and listed on the site's **Flagged for Review** page — never inferred.

## How the dashboard works
1. **Live data (browser → Kalshi demo REST).** The dashboard polls
   `GET /markets?status=open` from the visitor's browser (public endpoint,
   no key needed), filters to the five topics, groups markets by event, and
   ranks by dollar activity (`volume_fp`, `open_interest_fp`). Polling is
   used instead of WebSocket because Kalshi WS channels require API-key
   authentication ([API Keys](https://docs.kalshi.com/getting_started/api_keys));
   the WS endpoint is documented on the site for credentialed use.
2. **Alerting (≥ $0.10 swings).** Each poll compares each market's
   `last_price_dollars` to its previous poll value; moves ≥ $0.10 in either
   direction post to two scrolling chats: **All Alerts** and **High-ROI
   (model-filtered)**. The model score is a transparent 0–100 heuristic
   (liquidity, volume, spread, price extremity, momentum) — documented on
   the Methodology page, not a prediction guarantee.
3. **Charts & liquidity.** Canvas price chart (X = time with
   seconds/minutes/hours window selector, Y = contract price $0–$1) plus a
   live order-book table (contracts available at each price) from
   `GET /markets/{ticker}/orderbook`.
4. **Resolutions.** Markets are tracked until `status` becomes settled;
   the `result` field (`yes`/`no`) is logged in the Resolutions table.
5. **Simulated trading.** Four strategies (Momentum, Mean-Reversion,
   Favorite, Longshot) paper-trade automatically on alerts/signals with a
   configurable bankroll. Portfolio page shows equity curve, open/closed
   positions, and performance categorized by topic × strategy × side.
6. **Real demo execution (optional, credentialed).** `python/kalshi_client.py`
   implements signed requests (Ed25519/RSA-PSS) for balance, orders, and
   fills against the demo API. It needs **your** demo API key + private key
   (generate at https://demo.kalshi.co/ → Account Settings → API Keys) —
   this session had no credentials, so no real demo balance is shown.
   Instructions: [`python/README.md`](python/README.md).

## Important caveats (flagged, not hidden)
- This build sandbox cannot reach `*.kalshi.co` (verified: TLS EOF / HTTP
  000), so **no live values were verified from here**. The dashboard fetches
  live data in your browser; if the API is unreachable (or CORS blocks it —
  unverified, see Flagged page), it switches to **clearly-labeled simulated
  data** so every feature still works.
- Topic assignment is a keyword/series heuristic (unverified tickers) —
  review the Topic Mapping table on the Flagged page.
- Price jumps are shown next to **curated official source links** per topic
  (e.g. EIA for gas prices). The site does **not** claim a link caused a
  jump — that requires a news API and human review.
- Simulated/paper results are not real-money results. Demo prices "may not
  be reflective of those in real markets" ([Demo Environment](https://docs.kalshi.com/getting_started/demo_env)).

## Suggestions to make the site more live & interactive (implemented / roadmap)
- **Implemented:** auto-refresh polling with connection status, dual alert
  chats, time-window chart controls, order-book depth, topic tabs, paper
  trading with equity curve, resolution log, simulated fallback mode.
- **Roadmap:** credentialed WebSocket streaming (lower latency than polling),
  browser push/SSE alerts, news-API catalyst attribution, multi-market
  comparison charts, exportable trade CSV, backtest replay from
  `/markets/{ticker}/history`.

## Repository layout
```
site/                 GitHub Pages site (static, no build step)
  index.html          Landing page + executive summary
  dashboard.html      Live dashboard (alerts, charts, orderbook, resolutions)
  portfolio.html      Simulated portfolio + strategy analysis
  methodology.html    Model, strategies, data flow, limitations
  sources.html        Every table row with official source link
  flagged.html        Flagged for Review (unverified items)
  assets/app.js       Dashboard + simulator engine (vanilla JS, canvas charts)
  assets/style.css
python/               Signed Kalshi client + simulator (credentialed use)
docs/VERIFICATION.md  Line-by-line verification table
COORDINATION.md       Shared task board / session log
.github/workflows/pages.yml  GitHub Pages deploy
```

</details>
