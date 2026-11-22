# Executive summary — Kalshi demo environment

**Prepared:** 2026-11-22 (UTC) · **Repository:** `kanlerxz87-cyber/Tradebot1`
**Live gateways:** [research desk](https://kanlerxz87-cyber.github.io/Tradebot1/docs/desk/) ·
[market monitor](https://kanlerxz87-cyber.github.io/Tradebot1/docs/)

Four independent implementations of the same brief now sit in one repository, built by parallel
sessions and integrated on 2026-11-22. This summary covers the two that are documented as parts
(**A** the autonomous research desk, **B** the browser-side market monitor preserved verbatim) and
records the other two in the integration section at the end.

| | Part A — research desk | Part B — market monitor |
| - | - | - |
| Location | `docs/desk/` | `docs/` |
| Data path | scheduled server-side collector (production public REST) | browser polls public demo REST |
| Alerts | persisted ≥ $0.10 archive + live ticks | session-only ≥ $0.10 observations |
| Trading | 4 strategies, ledger committed to the repo | 1 screen, browser-local |
| Verification | 26 dated source rows, 14 flags | endpoint-level citations, review page |

| Also published | Location | What it is |
| - | - | - |
| Trade board | `board.html` (+ five `categories/` pages) | Node implementation: events ranked by resting dollars, two auto-scrolling ≥ $0.10 feeds, 60s–24h chart, order-book ladder, five strategies, 17 flags |
| Engine view | `docs/engine/` | Python engine's own site: 39-entry verification register, five topic tables, both alert feeds, six-strategy fee-exact simulator, its own flags page |
| Prototype | `site/` | First standalone prototype, kept for review; simulated fallback data, clearly separated from verified values |

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

* Performance figures are **paper**, not exchange fills. Fees are modelled with the published Kalshi
  schedule (verified 2026-11-22, 42/42 table values), but exchange rebates and per-series multipliers
  are not modelled.
* Alerts are cycle-resolution: the cron runs every 15 minutes; the live server and direct mode raise
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
| Official fee schedule | **verified 2026-11-22** against <https://kalshi.com/docs/kalshi-fee-schedule.pdf> — 42/42 published table values reproduced (F1 resolved) |
| Breakages | 0 open; 14 flagged items, 0 blocking |

### 6. Next three moves

1. Create the demo account, add `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY` as repository secrets: paper
   results become exchange-confirmed demo results (flag F2).
2. Move collection to `orderbook_delta` WebSocket streaming once credentialed, so alerts fire on ticks
   rather than cycles.
3. Read per-series fee multipliers from the schedule instead of applying the general rate to every series
   (fee-free series such as `KXBTCY` are currently overcharged in simulation).

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

## Integration pass — session `arena/daf65d06-tradebot1`, 2026-11-22

**What this pass did.** Merged the three parallel deliverables that were still apart (the research desk
was already on `main`; the Node trade board arrived in PR #8, the Python engine in PR #10) into one
branch, ran every gate in the repository against the combined tree, corrected one factual claim that
turned out to be resolvable, and published the result.

**Conflicts and how they were resolved without losing work.** `.gitignore` and `COORDINATION.md` had
add/add conflicts (both sides appended); both sides' lines were kept. The engine branch had also
*removed* the Node board's CI job and its `board.html` / `assets/` / `categories/` / `data/` staging from
the Pages workflow — an artefact of it branching before the board merged. That removal was **not**
applied: the board stays published and keeps its five CI gates, and the engine's checks were added
alongside them.

**Verification run on the combined tree** (all green):

| Gate | Result |
| - | - |
| `python3 -m pytest -q` | 144 passed (desk + engine) |
| `node --test tests/*.test.mjs` | 36 passed (board) |
| `node scripts/build-site.mjs --check` | board pages match templates + data — fixed to be clock-independent, see below |
| `node scripts/check-links.mjs` / `check-render.mjs` / `check-data.mjs` | 19 pages, 642 references, 123 external, 0 problems; every row keeps its source link |
| `python3 tools/build_site.py --check` | desk output current |
| `python3 tools/check_links.py` | 272 internal links across 13 pages, no broken targets or anchors |
| `python3 tools/check_gateway.py` (new) | 26 gateway targets resolve and are published |
| `python3 -m engine.check_site --root docs/engine` | no broken links, no unsourced table row, no unrendered template |
| `python3 tests/check_site.py` | 37 HTML pages and local link targets verified |
| `python3 python/test_simulator.py` | all simulator tests passed |
| `python3 -m kalshi_trader.cli verify` | published data integrity OK |

**Two corrections made during integration.**

1. **The fee model is no longer "unverified".** Session `arena-e3e5f70f` flagged the trading fee as
   unverified (F1) because the fee-schedule PDF could not be retrieved from its sandbox. It is
   retrievable: <https://kalshi.com/docs/kalshi-fee-schedule.pdf> ("Last updated and effective:
   July 7, 2026") states the taker fee as `roundup(M × 0.07 × C × P × (1 − P))`, the maker fee as
   `roundup(M × 0.0175 × C × P × (1 − P))` with a default multiplier of 0, and explicitly states there
   is no settlement fee and no membership fee. All 21 per-contract and 21 per-100-contract rows of its
   General Trading Fees Table were reproduced value by value (42/42) and are now asserted in
   `tests/test_model_fees.py`; `kalshi_trader/fees.py` carries `VERIFIED = True`, ledger entries are
   labelled `quadratic_verified`, and F1 is marked resolved. Two residual limits are recorded rather
   than hidden: the rebate accumulator is not modelled, and per-series multipliers are not read from the
   schedule (fee-free series such as `KXBTCY` would be overcharged in simulation).

2. **The board's `--check` gate could never pass twice.** `scripts/build-site.mjs --check` compared
   regenerated pages against the committed ones *including* a build timestamp and relative "21m ago"
   ages, so it failed on any rebuild more than a minute after the commit. Those clock-derived fragments
   are now normalised out of the comparison, so the gate keeps comparing the generated shell (navigation,
   headings, static tables and links) instead of failing for a reason unrelated to correctness. The live
   rows are rendered in the browser from JSON and are gated separately by `scripts/check-data.mjs` (data
   contract) and `scripts/check-render.mjs` (every rendered row must carry a source link).

**Sources re-checked directly in this pass** (in addition to the 26 desk rows and 39 engine register
entries): [API environments](https://docs.kalshi.com/getting_started/api_environments) (REST/WS demo and
production hosts, signed-path rule), [fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf),
[fee rounding](https://docs.kalshi.com/getting_started/fee_rounding) (six-decimal fees, rebate
accumulator), [fixed-point fields](https://docs.kalshi.com/getting_started/fixed_point_migration)
(`*_dollars` prices, `*_fp` counts), [demo environment](https://docs.kalshi.com/getting_started/demo_env)
(mock funds, separate credentials, and Kalshi's own warning that demo prices may not reflect real
markets), and the public series page <https://kalshi.com/markets/kxaaagasm> (strikes 3.45 / 3.50 / 3.55
with "Above 3.50" at 47¢, which is the disagreement with the demo book that the engine flag records).

**Still open and non-blocking** — published on the Flagged for Review pages with source links:
the demo account is not connected (no credentials exist in this repository, so no demo fills or demo
balance can be shown), the topic mappings Kalshi does not publish (no Gas or Culture category; golf is a
Sports tag), alert resolution is per collection cycle rather than per tick, dollar-volume rankings are
derived estimates, and browser CORS behaviour towards Kalshi is undocumented.

**Deploy.** `docs/engine/` and the board's root pages are staged by the existing Pages workflow, so no
Pages setting had to change (`build_type` changes are rejected with HTTP 403 for this token; the site is
served by the legacy `main /` build). The pull request, merge commit and the post-deploy URL check are
recorded in `COORDINATION.md`.
