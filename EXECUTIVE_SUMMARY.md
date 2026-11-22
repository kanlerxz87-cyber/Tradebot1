# Executive summary — Kalshi Trader

**Prepared:** 2026-11-22 (UTC) · **Web version:** <https://kanlerxz87-cyber.github.io/Tradebot1/executive-summary.html>
**Scope:** a live dashboard, an alerting desk and an autonomous simulated trading book for five Kalshi
topics (gas prices, elections, culture, crypto, golf), built from an empty repository.

---

## 1. What was built

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

## 2. Verified API facts the build rests on

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

## 3. Key decisions

| Decision | Rationale | Flag |
| - | - | - |
| Market data from production (read-only), execution in paper | Production data is keyless, real and liquid; demo prices may not reflect real markets | F6 |
| Static site + scheduled collector rather than a fake “live” label | GitHub Pages cannot poll an exchange; the snapshot age is always displayed | F10 |
| Culture mapped to the official Entertainment category (+ Social) | No official Culture category exists | F3 |
| Golf by Sports/Golf tag; gas by KXAAAGASM + gas-price matching | Both are official fields; a keyword fallback is used only when the fields miss | F4 |
| Fee model applied but marked unverified | The official fee-schedule PDF could not be retrieved; P&L must not silently depend on it | F1 |
| Demo account left blank rather than estimated | A demo account and key can only be created by the account holder | F2 |
| ROI score is a published heuristic | Six weights, versioned, disclaimed; its value will be measured, not asserted | F12 |

## 4. What the numbers mean (and do not)

* Performance figures are **paper**, not exchange fills. Fees are modelled (unverified).
* Alerts are cycle-resolution: the cron runs every 15 minutes; the live server and direct mode raise
  that to seconds.
* Dollar-volume rankings use `volume_24h × price`, a derived figure labelled `_est` everywhere.
* The high-ROI chat is a noise filter, not a forecast. Its accuracy is whatever the ledger records.

## 5. Status at hand-off

| Item | Status |
| - | - |
| Dashboard, five topic pages, portfolio, strategies, API reference, verification, flagged, requirements | shipped |
| Alerting at ≥ $0.10 with two chats | shipped |
| Resolution tracking to YES/NO | shipped |
| Paper trading + analytics (4 strategies) | shipped and running on a schedule |
| Kalshi demo account integration | implemented, dormant — needs credentials (F2) |
| Official fee schedule | unverified (F1) |
| Breakages | 0 open; 14 flagged items, 0 blocking |

## 6. Next three moves

1. Create the demo account, add `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY` as repository secrets: paper
   results become exchange-confirmed demo results.
2. Retrieve the current fee schedule and flip `VERIFIED = True` in `kalshi_trader/fees.py` (clears F1).
3. Move collection to `orderbook_delta` WebSocket streaming once credentialed, so alerts fire on ticks
   rather than cycles.
