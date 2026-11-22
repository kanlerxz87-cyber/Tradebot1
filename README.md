# Tradebot1 — Kalshi Demo research

[Primary research dashboard](https://kanlerxz87-cyber.github.io/Tradebot1/docs/) · [Executive summary](https://kanlerxz87-cyber.github.io/Tradebot1/docs/executive-summary.html) · [Flagged for Review](https://kanlerxz87-cyber.github.io/Tradebot1/docs/review/) · [Alternative prototype](https://kanlerxz87-cyber.github.io/Tradebot1/site/)

The repository began as a one-line README. Two parallel sessions built independent implementations. **`docs/` is the primary credential-free research dashboard**: it never substitutes simulated prices for missing official observations. The previously merged `site/` prototype and `python/` client are preserved for comparison, but its clearly labeled simulated fallback is *not* official market data. Neither frontend accesses a real demo account.

## Primary dashboard (`docs/`)

- Five separate topic pages: gas prices, elections, culture, crypto and golf. Every market, orderbook, paper ledger and lifecycle table row links to its official Kalshi public endpoint. Ranking is a derived **estimated 24h $ proxy**: sum per event of `last YES price × 24h contract volume` over scanned contracts, not exchange-reported turnover or a complete exchange ranking. The scan covers up to four event pages and two newest non-combo market pages; title/category rules can omit events.
- Public REST discovery every 90 seconds, tracked tickers every 45 seconds, minute/hour Kalshi candles and seconds-level *browser session observations*, public orderbook snapshots. Listings can be cached; cross-origin browser access remains unverified.
- Two scrolling lists of **observed** ≥$0.10 last-YES-price changes: all and an explicit spread/volume/ask-price screen. A published snapshot is a baseline, never an alert; ≥3-minute observation gaps suppress alerts. This screen does not predict ROI.
- Automatic local **paper YES buys** at reported ask, marked at reported bid, finalized YES/NO payout per Kalshi `status=finalized` and `result=yes/no`. No fees, slippage, order-fill verification or actual trading. Local paper state persists only in this browser. Watched contracts appear in a lifecycle table until finalized while the session stays open.
- A scheduled GitHub Pages workflow generates a bounded public demo API snapshot in its deployment artifact; empty/unavailable API responses never become invented values. A root redirect to `docs/` supports the existing legacy Pages `main /` source.

## Other parallel-session deliverables (preserved)

- [`EXECUTIVE_SUMMARY.md`](EXECUTIVE_SUMMARY.md), [`docs/VERIFICATION.md`](docs/VERIFICATION.md), [`site/`](site/) and [`python/`](python/) were merged separately by session `arena-39ef3867` before this integration. The alternative prototype includes clearly labeled simulated display values if browser API access fails. Treat them as examples, **not verified quotes**.
- [`python/README.md`](python/README.md) describes a separate local demo API client requiring your own API credentials. Do not put any private key in this repository, the public website or localStorage.
- [`COORDINATION.md`](COORDINATION.md) records both owners, verification and cross-session merge conflict handling.

## Verification and local preview

```sh
node --test tests/*.test.mjs
python3 tests/check_site.py
python3 python/test_simulator.py
node --check docs/assets/app.mjs
node --check site/assets/app.js
python3 -m http.server 8000 --bind 0.0.0.0
```

Open `http://localhost:8000/docs/` for the primary dashboard or `http://localhost:8000/site/` for the alternative. No npm dependencies. `scripts/build_snapshot.py` fetches public demo observations only; GitHub Actions runs it on push and on its 30-minute schedule. Main-branch deployments succeeded.

## Official sources checked 2026-11-22

- [Demo endpoints and separate credentials](https://docs.kalshi.com/getting_started/api_environments)
- [Public events, nested markets, pagination, multivariate exclusion](https://docs.kalshi.com/api-reference/events/get-events.md)
- [Market quote/result/volume fields and caching](https://docs.kalshi.com/api-reference/market/get-markets.md)
- [Lifecycle: REST finalized corresponds to settled filter](https://docs.kalshi.com/getting_started/market_lifecycle.md)
- [Public orderbook levels](https://docs.kalshi.com/getting_started/orderbook_responses) and [candlestick intervals](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)
- [Signed WebSocket handshake](https://docs.kalshi.com/getting_started/quick_start_websockets), [signed account requests](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests), [V2 demo orders](https://docs.kalshi.com/api-reference/orders/create-order-v2)
- [Sample public demo market](https://external-api.demo.kalshi.co/trade-api/v2/markets?status=open&mve_filter=exclude&limit=3) and [sample event ticker filter](https://external-api.demo.kalshi.co/trade-api/v2/events?tickers=KXDEMOFUTHOURLY-26NOV22H07,KXSENATEIAD-28&limit=200) checked point-in-time; no quotes from those samples are frozen into the dashboard.

## Limits

No authenticated demo portfolio or executed orders, secure WebSocket stream, calibrated ROI model, complete ranking, or verified news-price causal links. A separate private backend is required to sign WebSocket handshakes and demo-account orders. The repository Pages setting is legacy `main /`; a Pages-source API update returned HTTP 403 for this integration, although the earlier `site/` deployment workflow succeeded. Root `index.html` redirects to `docs/` as fallback. Main-branch Pages workflow runs [44996474051](https://github.com/kanlerxz87-cyber/Tradebot1/actions/runs/44996474051) and [44996547389](https://github.com/kanlerxz87-cyber/Tradebot1/actions/runs/44996547389) succeeded; the second published a timestamped, explicitly partial public API snapshot. Browser CORS remains unverified. See the [Flagged for Review page](docs/review/index.html).
