# Executive summary — Kalshi demo environment

**Prepared:** 2026-11-22 (UTC) · **Repository:** `kanlerxz87-cyber/Tradebot1`
**Live gateways:** [research desk](https://kanlerxz87-cyber.github.io/Tradebot1/docs/desk/) ·
[market monitor](https://kanlerxz87-cyber.github.io/Tradebot1/docs/)

Five implementations now exist, each additive. **Part A** is the autonomous research desk (collector plus
scheduled trading loop). **Part B** is the browser-side market monitor, preserved verbatim. **Part C**
(bottom of this file) is the newest: a dependency-free live desk with a real server, plus a
cross-implementation audit of every dataset in the repository. Where numbers disagree, the desk's come from
a server-side collector, the monitor's from the visitor's browser, and the live desk's from whichever of
those captures it is anchored to — which it names in `/api/meta`.

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


---

# Part C — Live desk and cross-implementation audit (`live/`, `qa/`)

**Prepared:** 2026-11-22 (UTC) · **Session:** `arena-35fb0d1f` · **Pages:** [live.html](live.html) · [qa.html](qa.html)

## 1. What this part adds

Two things the earlier parts did not have: a **running server** that can be pointed at Kalshi from any
machine, and an **independent audit** of the data the rest of the repository publishes.

| Path | What it is |
| - | - |
| `live/server.py`, `live/desk.py` | Standard-library HTTP server, engine, REST API, Server-Sent Events push. No dependencies, no build step, no key. |
| `live/static/` | The dashboard: topic tabs, two alert chats, canvas price chart (30s–4h), liquidity ladder, simulated book, resolution watch. |
| `live/tests/` | 29 assertions: threshold inclusivity and symmetry, price bounds, book arithmetic, quote hygiene, no order path, HTTP surface. |
| `qa/audit.py`, `qa/report.*` | Audits `docs/desk`, `docs/`, `site/`, the Node board and every published page. Regenerates `qa.html`. |
| `live.html` | Published record: routes, modes, requirement matrix, snapshot tables with per-row source links, verification log. |

## 2. Verified against official sources (fetched 2026-11-22)

| Fact | Source |
| - | - |
| Demo REST `https://external-api.demo.kalshi.co/trade-api/v2` (also `demo-api.kalshi.co`); demo WS `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | [API environments](https://docs.kalshi.com/getting_started/api_environments) |
| Order book returns **bids only**, arrays ascending, best bid last, `yes_ask = $1 − best NO bid`, no auth required | [Order book responses](https://docs.kalshi.com/getting_started/orderbook_responses) |
| Statuses are `initialized`, `active`, `inactive`, `closed`, `determined`, `disputed`, `amended`, `finalized`; `open`/`settled` are request filters; `result` is `yes`, `no` or `scalar` | [Market lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle) |
| Live demo `GET /markets` field names: `yes_bid_dollars`, `yes_ask_dollars`, `last_price_dollars`, `volume_24h_fp`, `open_interest_fp`, `status`, `result`, `close_time`, `rules_primary` | [demo markets response](https://external-api.demo.kalshi.co/trade-api/v2/markets?status=open&limit=1&series_ticker=KXAAAGASM) |
| Demo `GET /exchange/status` reports four exchange indexes, all active | [demo exchange status](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) |

**Two corrections to earlier notes in this repository.** (1) An earlier register read the docs as requiring
`open`/`settled` and flagged `active`/`finalized` as contradictions; the lifecycle page lists `active` and
`finalized` as the statuses, so the API was right. (2) `result` can be `scalar`, which a yes/no-only resolver
must not coerce.

**Not verified, and labelled as such in the product:** the fee schedule page did not load from this sandbox,
so `FEE_VERIFIED` stays `False`; the Kalshi WebSocket was never connected (the desk uses SSE); no credential
exists, so no demo-account balance or order was ever read or sent.

## 3. Audit findings (published at `qa.html`)

Every committed dataset, 68 published pages and 1 218 internal references were re-checked. **0 errors, 3 warnings, 9 notes.**

| Severity | Finding | Detail |
| - | - | - |
| warn | 24h notional used an older price than the row prints | 15 of 300 rows; largest gap 2.2%; implied price is the previous mid, so the number is directionally right and exactly wrong |
| warn | Published order-book ladder is a partial view | 8 rows: reported depth exceeds the sum of printed levels, so ladder totals and depth totals must not be presented as the same quantity |
| warn | Capture provenance is the production root | `docs/desk/data/latest.json` was collected from `external-api.kalshi.com`, while the brief specifies demo; the live desk surfaces the capture's environment in `/api/meta` |
| note | No resolved market in the capture | Resolution tables are empty rather than seeded; the live desk shows close-time countdowns and fills results only from Kalshi's own fields |
| note | The Node generator's `--check` can never pass | It re-renders and compares, but the render embeds a fresh timestamp and relative text ("21m ago"), so every page reports stale within a minute. Verified against a clean checkout of `main`: identical output, so it is a check design issue, not stale data |
| note | No demo account connected | `data/account.json` is `connected: false` with a documented reason; simulated results are not demo-account results |

The page also checks prices against $0.00–$1.00, crossed books, duplicate tickers across topics, alert
thresholds, resolution values against the documented set, official-host source links, and scans for
committed credentials. It cannot confirm a price against Kalshi — that is stated on the page.

## 4. How to use it

```sh
python3 live/server.py --port 8000            # auto: live if reachable, else labelled simulation
python3 live/server.py --mode live            # poll the demo API
python3 -m unittest discover -s live/tests
python3 qa/audit.py --check                   # zero errors required
python3 live/build_page.py --check            # live.html is current
```

The single honest caveat: on a machine without egress to Kalshi — including the sandbox that built this —
the desk runs the **simulated** mode, which is labelled on every surface. Live mode is implemented, unit
tested against scripted responses, and needs only network access, not a key.
