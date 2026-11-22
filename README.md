# Kalshi Demo Research Dashboard

[Dashboard (GitHub Pages)](https://kanlerxz87-cyber.github.io/Tradebot1/) · [Executive summary](https://kanlerxz87-cyber.github.io/Tradebot1/executive-summary.html) · [Flagged for Review](https://kanlerxz87-cyber.github.io/Tradebot1/review/) · [Coordination board](COORDINATION.md)

A credential-free **public demo** market-research dashboard for gas prices, elections, culture, crypto and golf. This repository initially contained only `# Tradebot1`; there was no existing application or account integration to audit. All new functionality is separate from a real Kalshi portfolio.

## What works

- Category subpages; source-linked market rows and event/market URLs. The ranking is a **derived proxy**, `last YES price × 24h contract volume`, over **up to four event pages and two non-combo market pages** (not all exchange events or official dollar volume). Conservative title/category matching may omit events.
- Public REST fetch every 90 seconds, tracked tickers every 45 seconds, Kalshi candlesticks for minute/hour charts, in-session observations for seconds; a public orderbook snapshot for the selected contract. Data can lag and browser access to cross-origin REST has not been validated at the deployed origin.
- Two scrolling lists of *observed* ±$0.10 last-YES-price moves: all matching moves and those meeting an explicitly disclosed spread/volume/price heuristic. A snapshot is never treated as a preceding observation, and a gap of ≥3 minutes suppresses alerts.
- One automatic **local paper YES buy** per screened market at the reported ask, with localStorage persistence, marked at the reported bid, and payout only after the API says `status=finalized` and `result=yes/no`. No fees, slippage, order fills or trading-performance claims. Paper data is not synchronized across devices.
- A scheduled 30-minute GitHub Pages workflow generates a **bounded public demo API snapshot** as a fallback when the browser cannot fetch. The timestamp and partial-coverage status are shown; build failures in the API fetch do not become fabricated market values.

## Explicitly not implemented

No authenticated demo account balance, real demo orders, WebSocket stream, ROI model, complete ranking, guaranteed seconds-level resolution, or news-price causal attribution. **Do not put API keys or signing private keys into GitHub Pages, frontend JavaScript, the repository, or localStorage.** A private authenticated backend is required for secure WebSocket subscriptions and demo-account execution. See [Flagged for Review](docs/review/index.html) for the item-by-item sources and status.

## Local development & verification

```sh
node --test tests/*.test.mjs
python3 tests/check_site.py
python3 -m http.server 8000 --bind 0.0.0.0 --directory docs
```

Open `http://localhost:8000/` locally. The site has no npm dependencies. `scripts/build_snapshot.py` is for an environment that can reach the official Kalshi demo API; it uses no account credentials. Run it only if you want to replace `docs/data/snapshot.json` with a newly observed public-data snapshot. GitHub Actions builds this automatically when deployed.

## Official sources checked on 2026-11-22

- [Demo REST / WebSocket base URLs and credential separation](https://docs.kalshi.com/getting_started/api_environments)
- [Public events, nested markets, pagination, multivariate exclusion](https://docs.kalshi.com/api-reference/events/get-events.md)
- [Market quote, result and volume fields; cached listings](https://docs.kalshi.com/api-reference/market/get-markets.md)
- [Public orderbook depth and bid-only representation](https://docs.kalshi.com/getting_started/orderbook_responses)
- [Market candlestick intervals](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)
- [Signed WebSocket handshake, including public channels](https://docs.kalshi.com/getting_started/quick_start_websockets)
- [Signed account requests](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests) and [V2 demo order endpoint](https://docs.kalshi.com/api-reference/orders/create-order-v2)
- [Public demo endpoint response checked](https://external-api.demo.kalshi.co/trade-api/v2/markets?limit=3&status=open) (point-in-time example, not a stored claim about current quotes)

## Publication

`.github/workflows/pages.yml` tests, fetches a fresh bounded public snapshot and deploys `docs/` to GitHub Pages on pushes to `main`, on its 30-minute schedule, or via workflow dispatch. Enable repository Pages with source **GitHub Actions** if it is not already configured. Never use the live production API for this demo dashboard.
