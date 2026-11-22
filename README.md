# Tradebot1 — a Kalshi demo dashboard

A static, source-linked dashboard over the **Kalshi demo exchange**, covering five topics only:
**gas prices, elections, culture, crypto and golf**. It watches for price swings of **$0.10 or
more** in either direction, follows markets to a final **yes** or **no**, and runs five simulated
strategies against demo data.

**Live site:** <https://kanlerxz87-cyber.github.io/Tradebot1/>

Nothing here is investment advice, and no order is ever sent to Kalshi.

---

## What it does

| Page | What it is for |
| --- | --- |
| [`index.html`](index.html) | The board: live events ranked by resting dollars, a topic summary, and the headline figures. |
| [`dashboard.html`](dashboard.html) | **Live alerts.** Two scrolling feeds — every swing ≥ $0.10, and the model-filtered subset — plus the raw observation log. |
| [`markets.html`](markets.html) | Every tracked market grouped by topic, then by event, with the exchange's status and result. |
| [`market.html`](market.html) | One market: a price chart (x = time, 60s–24h; y = price), the order-book ladder with contracts at each price, settlement rules, and a local paper-trade calculator. |
| [`portfolio.html`](portfolio.html) | The simulator: equity, realized and unrealized P&L, and results broken down by strategy and by topic. |
| [`strategies.html`](strategies.html) | Each strategy's exact trigger, so any simulated trade can be reproduced by hand. |
| [`demo-account.html`](demo-account.html) | The **real** demo account's balance, positions, fills and settlements, captured by GitHub Actions. |
| [`executive-summary.html`](executive-summary.html) | The short version: requirement-by-requirement status, verified findings, and what is deliberately blank. |
| [`sources.html`](sources.html) | Every source, split into official docs, live API observations, primary publishers and project rules. |
| [`methodology.html`](methodology.html) | Exact formulas for every number on the site. |
| [`suggestions.html`](suggestions.html) | Ideas for making the dashboard more live and more useful, with effort and blockers. |
| [`flagged.html`](flagged.html) | **Flagged for review** — every limitation, unverified value and irregularity, with sources. |
| [`api.html`](api.html) | The Kalshi endpoints used, the verified demo hosts, and the signing and rate-limit rules. |
| `categories/{gas,elections,culture,crypto,golf}.html` | One page per topic: how it is discovered, its events and markets, its resolutions, and its swings. |

---

## How the data flows

```
GitHub Actions (collect.yml, every 15 min)
        │
        ├── GET /exchange/status                     probe
        ├── GET /series?category=… / ?tags=…         topic discovery
        ├── GET /markets?series_ticker=…             open markets
        ├── GET /markets/{ticker}/orderbook          depth and spread
        └── GET /markets/{ticker}                    resolution watchdog
        │
        ▼
data/live/{state,feed,portfolio}.json  ──committed──▶  static site
                                                          │
GitHub Actions (demo-account.yml, hourly)                  │
        └── signed GET /portfolio/{balance,positions,…}    │
                └──▶ data/account.json ────────────────────┘
```

The browser also tries the public demo API directly on the board and market pages, and falls back
to `data/snapshot.json` when it cannot. The banner at the top of those pages always says which one
is on screen, with an observation time.

### Why collection is not done in the browser

Signed Kalshi requests need a private key and a timestamp within 30 seconds of Kalshi's clock. A
GitHub Pages site cannot hold a key. So all signing lives in Actions with repository secrets, and
the static site only ever reads committed files. This is flagged as **F-06**.

---

## Verified facts this build rests on

Every row below was read from the linked official page, and the API rows were additionally
exercised with a live demo request on 2026-11-22.

| Fact | Source |
| --- | --- |
| Demo REST root is `https://external-api.demo.kalshi.co/trade-api/v2`; `https://demo-api.kalshi.co/trade-api/v2` is also supported | [API Environments](https://docs.kalshi.com/getting_started/api_environments) |
| Demo WebSocket root is `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | [API Environments](https://docs.kalshi.com/getting_started/api_environments) |
| Demo uses mock funds, and prices may not reflect real markets | [Demo environment](https://docs.kalshi.com/getting_started/demo_env) |
| The order book returns **bids only**; a YES bid at X is a NO ask at 1−X | [Orderbook Responses](https://docs.kalshi.com/getting_started/orderbook_responses) |
| Market statuses are initialized → active → closed → determined → finalized | [Market Lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle) |
| `result` is `yes`, `no` or `scalar`; only `finalized` is terminal | [Market Lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle) |
| Taker fee = round up(M × 0.07 × C × P × (1−P)); maker uses 0.0175; no settlement fee | [Fee schedule PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf) |
| Sign `timestamp_ms + METHOD + path` without the query string; 30-second tolerance | [API Keys](https://docs.kalshi.com/getting_started/api_keys) |
| Legacy `/portfolio/orders` writes return 410; use `POST /portfolio/events/orders` | [Create Order V2](https://docs.kalshi.com/api-reference/orders/create-order-v2) |
| Public WS channels still need an authenticated handshake | [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets) |

### Facts about the demo catalogue that shaped the design

| Observation | Request | Consequence |
| --- | --- | --- |
| `Golf` is not a category; golf series are category `Sports` with tag `Golf` | [GET /series?category=Golf](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Golf) | Golf routes on the tag (**F-04**) |
| `Gas` returns only `DIESEL` and `DIESELM`; `Gasoline` returns nothing | [GET /series?tags=Gas](https://external-api.demo.kalshi.co/trade-api/v2/series?tags=Gas) | The gas topic is diesel-only in the demo (**F-03**) |
| `Culture` exists as a category with two series | [GET /series?category=Culture](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Culture) | Culture routes on the category |
| The unfiltered open-market list leads with `KXMVE*` combo markets | [GET /markets?status=open](https://external-api.demo.kalshi.co/trade-api/v2/markets?status=open&limit=3) | Combos are excluded from every topic (**F-05**) |
| The inspected golf markets quote YES bid $0.00 / YES ask $1.00, i.e. an empty book | [GET /markets?series_ticker=KXLIVCOMPETE](https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXLIVCOMPETE&status=open&limit=5) | No mid, no move, no fabricated price |

---

## Run it locally

```bash
npm install                 # jsdom, used only by the render test
npm test                    # logic tests, including the fee model vs Kalshi's own table
npm run check:data          # the committed JSON against its contract
npm run build               # regenerate the HTML from templates + data
npm run build:check         # fail if the committed HTML is stale
npm run check:links         # internal links, assets and anchors
npm run test:site           # headless render of every page with jsdom
npm run verify              # all of the above, in order
node tools/collector.mjs --dry-run    # fetch without writing (needs internet egress)
```

The published site has **no runtime dependencies** and no build step at serve time.

### Repository layout

| Path | What it is |
| --- | --- |
| `templates/*.tpl` | Page templates, stored as `.tpl` so the link checker never treats them as pages. |
| `scripts/build-site.mjs` | The generator. Fails the build if a data row has no source link. |
| `assets/` | Browser code: styling, the chart, the two alert streams, and one script per page. |
| `tools/kalshi.mjs` | REST client. Refuses any host that is not an official Kalshi root. |
| `tools/topics.mjs` | The five topic rules, with the request that proves each one. |
| `tools/alerts.mjs` | Swing detection, the research score, and resolution mapping. |
| `tools/fees.mjs` | The published fee formula and the table it is verified against. |
| `tools/strategies.mjs` | The five strategy rules and the simulated accounting. |
| `tools/collector.mjs` | The scheduled collector. |
| `tools/demo-account.mjs` | The only code that signs a request. Reads the demo account; places no orders. |
| `data/snapshot.json` | A point-in-time demo capture, with the raw response fragments kept so fields can be re-checked. |
| `data/sources.json`, `data/flags.json` | The source registry and the flag registry, rendered into the site. |
| `data/live/` | The collector's committed output. |
| `tests/` | Offline tests: fee model, alert logic, strategy accounting, client behaviour, topic routing. |
| `verification/` | The dated line-by-line verification record for this build. |
| `COORDINATION.md` | The shared task board for concurrent sessions. |

---

## Known limitations

The full list, with sources, is on the [Flagged for review](https://kanlerxz87-cyber.github.io/Tradebot1/flagged.html)
page. The ones that matter most:

- **The authoring sandbox could not reach Kalshi directly**, so the collector was written against
  the documented API and the responses quoted in this repo were read through a page-fetch proxy.
  The scheduled workflow is what exercises the client end to end (**F-01**).
- **No resolved market was captured**, so the resolution tables ship empty with an explanation
  rather than an invented row (**F-08**).
- **The demo account is not connected** until `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY` exist as
  repository secrets (**F-13**).
- **The filtered feed is a heuristic**, not return on investment (**F-10**).
- **No cause is ever claimed** for a price move; only the exchange's own settlement sources are
  linked (**F-12**).
- **One row of Kalshi's own fee table** cannot be reproduced from Kalshi's own fee formula, and is
  flagged rather than special-cased (**F-02**).

## Licence and attribution

Kalshi, the Kalshi logo and the market data are Kalshi's. This project is an independent
dashboard over the public demo API and is not affiliated with or endorsed by Kalshi.
