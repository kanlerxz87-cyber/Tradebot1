# Verification Table — every claim traced to an official source

Rule applied throughout: **if a value cannot be confirmed from an official
source, the cell is left blank and the item is flagged as unverified.**
Nothing below is inferred. Checked 2026-11-22 against docs.kalshi.com.

## A. Kalshi API facts (official docs)

| # | Claim | Value | Official source |
|---|-------|-------|-----------------|
| A1 | Demo REST base URL (recommended) | `https://external-api.demo.kalshi.co/trade-api/v2` | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| A2 | Demo REST base URL (also supported) | `https://demo-api.kalshi.co/trade-api/v2` | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| A3 | Demo WebSocket URL (recommended) | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| A4 | Demo WebSocket URL (also supported) | `wss://demo-api.kalshi.co/trade-api/ws/v2` | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| A5 | Demo web app | `https://demo.kalshi.co/` | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| A6 | Demo uses mock funds; credentials not shared with production | stated | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| A7 | Demo prices/behavior may not reflect real markets | stated | [Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| A8 | Production REST base URL | `https://external-api.kalshi.com/trade-api/v2` | [API Environments](https://docs.kalshi.com/getting_started/api_environments) |
| A9 | Demo and production credentials are not interchangeable | stated | [API Environments](https://docs.kalshi.com/getting_started/api_environments) |
| A10 | Public endpoints such as Get Markets need no authentication | stated | [Making Your First Request](https://docs.kalshi.com/getting_started/making_your_first_request) |
| A11 | `GET /markets` response fields include `ticker`, `event_ticker`, `status`, `yes_bid_dollars`, `yes_ask_dollars`, `last_price_dollars`, `volume_fp`, `open_interest_fp`, `result` | as listed | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) |
| A12 | Market `status` possible values include `unopened`, `open`, `closed`, `settled` | as listed | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) |
| A13 | `GET /markets/{ticker}/orderbook` returns `orderbook_fp.yes_dollars` and `no_dollars` as `[price, size]` pairs; `depth` param 0–100 | as listed | [Get Market Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) |
| A14 | Auth headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE` | as listed | [API Keys](https://docs.kalshi.com/getting_started/api_keys) |
| A15 | Signature pre-sign text = timestamp + HTTP method + path (no query string) | stated | [API Keys](https://docs.kalshi.com/getting_started/api_keys) |
| A16 | Timestamp must be within 30 seconds of Kalshi's clock (ms epoch) | stated | [API Keys](https://docs.kalshi.com/getting_started/api_keys) |
| A17 | Key types: Ed25519 (recommended) or RSA-2048 with RSA-PSS/SHA-256 | stated | [API Keys](https://docs.kalshi.com/getting_started/api_keys) |
| A18 | API keys are created in Account/Profile settings (demo: demo.kalshi.co) | stated | [API Keys](https://docs.kalshi.com/getting_started/api_keys) |
| A19 | OpenAPI spec for Predictions REST | `https://docs.kalshi.com/openapi.yaml` | [Welcome](https://docs.kalshi.com/welcome) |
| A20 | AsyncAPI spec for Predictions WebSocket | `https://docs.kalshi.com/asyncapi.yaml` | [Welcome](https://docs.kalshi.com/welcome) |

## B. Project requirements (from the task brief — not external facts)

| # | Requirement | How it is met | Where |
|---|-------------|---------------|-------|
| B1 | Topics: gas prices, elections, culture, crypto, golf only | Topic filter + keyword mapping | `site/assets/app.js` (`TOPICS`) |
| B2 | Alert on swings ≥ $0.10 either direction | Poll-to-poll `last_price_dollars` diff ≥ 0.10 | `site/assets/app.js` (`ALERT_THRESHOLD`) |
| B3 | Two scrolling chats: all events + high-ROI filtered | `#chat-all`, `#chat-roi` | `site/dashboard.html` |
| B4 | Track until resolved; record yes/no | `status`/`result` polling + Resolutions table | `site/assets/app.js` |
| B5 | Automated simulated trades, multiple strategies | 4 paper strategies | `site/assets/app.js`, `python/simulator.py` |
| B6 | Portfolio performance + categorization | Equity curve + topic×strategy×side tables | `site/portfolio.html` |
| B7 | Price graph: X=time (s/m/h windows), Y=price | Canvas chart with window buttons | `site/assets/app.js` |
| B8 | Liquidity: contracts available at each price | Order-book table | `site/assets/app.js` |
| B9 | Jump-adjacent source links | Curated official links per topic (not causal claims) | `site/assets/app.js` (`TOPIC_SOURCES`) |
| B10 | GitHub Pages site, clean landing + subpages | Static site in `site/` + Pages workflow | `.github/workflows/pages.yml` |

## C. Unverified — left blank on purpose (see also `site/flagged.html`)

| # | Item | Status | Why |
|---|------|--------|-----|
| C1 | Live market values (prices, volumes) | **Unverified from sandbox** | Sandbox cannot reach `*.kalshi.co` (TLS EOF / HTTP 000, tested 2026-11-22). Dashboard fetches live in the visitor's browser; simulated fallback is labeled. |
| C2 | Browser CORS for demo REST API | **Unverified** | Could not test cross-origin fetch from this sandbox. Dashboard handles failure by switching to simulated mode with a banner. |
| C3 | Topic → series-ticker mapping | **Unverified heuristic** | Series tickers could not be enumerated from the sandbox. Mapping uses keywords in ticker/title; review in browser and correct in `TOPICS`. |
| C4 | Demo account balance / real fills | **Blank — no credentials** | Requires the user's own demo API key + private key. Paper portfolio is the default; credentialed path documented in `python/README.md`. |
| C5 | News cause of any specific price jump | **Not claimed** | No news API available. Site shows curated official links to *check*, labeled as such. |
| C6 | Model "high ROI" predictions | **Heuristic, not verified** | Score formula is transparent and documented; it is not a guarantee of returns. Paper results only. |

## D. Sandbox connectivity test (2026-11-22)
- `https://external-api.demo.kalshi.co/trade-api/v2/markets` → TLS EOF / HTTP 000 (blocked/unreachable from sandbox).
- `https://demo-api.kalshi.co/trade-api/v2/markets` → HTTP 000.
- `https://pypi.org`, `https://github.com` → reachable (sandbox allowlist).
- Conclusion: live Kalshi data must be fetched client-side (visitor browser)
  or from a network that allows `*.kalshi.co`. All live values on the site
  are therefore fetched at runtime and labeled live vs simulated.
