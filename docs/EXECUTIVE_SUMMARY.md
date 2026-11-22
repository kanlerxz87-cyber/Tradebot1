# Executive Summary — Kalshi Demo Trading Dashboard

_Last updated: 2026-11-22. Prepared by session `arena/ef466564-tradebot1`._

## 1. What this project is

A dashboard + automated pipeline that tracks Kalshi's **demo** prediction-market
environment across five topics the user specified — **gas prices, elections,
culture, crypto, and golf** — alerts in near-real time on contract-price swings
of **$0.10 or more**, runs simulated ("paper") trading strategies against that
data, tracks simulated portfolio performance, and presents everything on a
public GitHub Pages dashboard, organized by topic, with every data row linked
back to an official source.

## 2. The Kalshi Trade API (verified against official docs)

| Item | Value | Source |
|---|---|---|
| REST base URL (prod) | `https://external-api.kalshi.com/trade-api/v2` | [docs.kalshi.com — Quick Start](https://docs.kalshi.com/getting_started/quick_start_market_data) |
| REST base URL (demo, recommended) | `https://external-api.demo.kalshi.co/trade-api/v2` | [docs.kalshi.com — Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| REST base URL (demo, also supported) | `https://demo-api.kalshi.co/trade-api/v2` | [docs.kalshi.com — Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| WebSocket (demo, recommended) | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | [docs.kalshi.com — Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |
| WebSocket (demo, also supported) | `wss://demo-api.kalshi.co/trade-api/ws/v2` | [docs.kalshi.com — Demo Environment](https://docs.kalshi.com/getting_started/demo_env) |

**The two REST URLs and two WebSocket URLs the user supplied in the prompt
match the official docs exactly** — confirmed directly against
`docs.kalshi.com` on 2026-11-22. See `docs/API_VERIFICATION.md` for the
line-by-line endpoint table.

Public market-data endpoints (`/series`, `/events`, `/markets`,
`/markets/{ticker}/orderbook`, `/markets/trades`, candlesticks) require **no
API key**. Placing orders and reading portfolio/balance/positions requires a
Kalshi account's API key pair (RSA-PSS or Ed25519 signed requests). This
project only uses the public, unauthenticated endpoints: no Kalshi account
credentials were available or requested in this autonomous session, so **all
trade execution in this project is a local paper-trading simulation**, not
real orders placed on the user's Kalshi demo account. See Section 5.

## 3. Critical environment constraint (read this first)

The coding sandbox that built this project has outbound network access to
only `github.com`, `codeload.github.com`, `api.github.com`,
`registry.npmjs.org`, `pypi.org`, and `files.pythonhosted.org`. Direct
requests from the sandbox to `external-api.demo.kalshi.co` and
`demo-api.kalshi.co` both fail at the network layer (verified with `curl`,
exit status `000` for both, 2026-11-22). **No Kalshi market data could be
fetched from inside the coding session**, and per the user's explicit
"no hallucinations" / "never infer or fill in values" instruction, none was
invented.

The fix: the real data collector (`scripts/collect_kalshi_data.py`) is a
correct, runnable client for the public Kalshi demo API, but it only actually
executes **on GitHub Actions**, whose runners have full outbound internet
access unlike this sandbox. `.github/workflows/collect-kalshi-data.yml` runs
it on a schedule after this branch is merged to `main`. Until that workflow's
first successful run, every JSON file under `docs/data/` is intentionally
shipped empty with a `status: "awaiting_first_collection_run"` flag — the
dashboard will visibly say "no data yet" rather than show fabricated numbers.

## 4. Topic → Kalshi series mapping

Kalshi groups markets by a `category` field returned on `/series` and
`/events` (seen directly in the official quick-start example:
`series_data['series']['category']`,
[source](https://docs.kalshi.com/getting_started/quick_start_market_data)).
The five user-requested topics map to Kalshi's own categories/series as
follows. Ticker families below were confirmed either on official
`docs.kalshi.com`/`kalshi.com` pages or (where flagged) secondary trading
write-ups; the live collector re-derives and re-verifies the exact set at
run time directly from the API rather than trusting this static list.

| Our topic | Kalshi category (as seen on kalshi.com / API) | Example series tickers | Source |
|---|---|---|---|
| Gas prices | Economics / Commodities | `KXAAAGASM` (monthly US avg.), `KXAAAGASMAX` / `KXAAAGASMIN` (yearly high/low), state variants e.g. `KXAAAGASMINFL` | Settlement source is AAA's national average regular-gas price, confirmed by [CNBC](https://www.cnbc.com/2026/09/14/prediction-markets-traders-think-gas-prices-will-hit-new-highs-in-2026.html) reporting live Kalshi odds tied to AAA data; ticker names per secondary trading write-up (oddsshopper.com) — **flagged unverified-secondary** until the collector confirms tickers live against `GET /series` |
| Elections | Elections / Politics | Series vary by election cycle (e.g. presidential, gubernatorial, special elections) | [docs.kalshi.com](https://docs.kalshi.com/getting_started/quick_start_market_data) confirms `category` field exists; exact live election series are enumerated by the collector at run time via `GET /events?category=Elections` style filtering, not hardcoded |
| Culture | Entertainment / Culture | Awards shows, reality TV, box office, etc. | kalshi.com navigation groups these under "Culture"/"Entertainment"; collector enumerates live |
| Crypto | Crypto | `KXBTC*`, `KXETH*` price-range/price-milestone series | [docs.kalshi.com Kalshi API guide examples](https://docs.kalshi.com/getting_started/quick_start_market_data) use the same ticker pattern style; collector enumerates live |
| Golf | Sports → Golf | `KXPGATOUR`, `KXMASTERS`, `KXPGA`, `KXUSOPEN`, `KXTHEOPEN` | Confirmed directly on **official kalshi.com pages**: [kalshi.com/golf/majors](https://kalshi.com/golf/majors), [kalshi.com/markets/kxpgatour/pga-tour/kxpgatour-mast26](https://kalshi.com/markets/kxpgatour/pga-tour/kxpgatour-mast26) |

The collector does **not** hardcode a market list for "high dollar amount"
tracking — it queries `GET /markets?status=open` filtered to the above
categories/keywords, sorts by `volume`/open interest (the API's own
dollar-exposure proxies), and keeps the top markets per topic. This avoids
guessing which markets matter and lets the live exchange data decide.

## 5. What is simulated vs. real

| Capability | Real or simulated | Detail |
|---|---|---|
| Market prices, order books, volumes, resolutions | **Real**, pulled live from the Kalshi **demo** API once GitHub Actions runs | Public endpoints, no auth needed |
| Price-swing alerts (≥ $0.10 move) | **Real-time derived** from real price data | Computed by the collector from consecutive snapshots |
| Trade execution | **Simulated (paper trading)** | No Kalshi API key was available/requested; the collector never calls `/portfolio/orders`. A local strategy engine "paper-fills" at the live quoted price and logs it |
| Portfolio performance | **Simulated**, tracked against paper fills | Not the user's real Kalshi demo-account balance, because no account credentials exist in this automated session |
| Event resolution (Yes/No) | **Real**, read from the `result` field once a market settles | Public, no auth |

**If the user wants true execution against their own Kalshi demo account**
(not a simulation), they must supply a Kalshi demo API key pair through a
GitHub Actions secret — this was not requested automatically because doing so
would require the user's credentials, which this autonomous session was
explicitly told not to solicit ("no manual input on my part"). This is logged
as a flagged item, not a blocker.

## 6. Deliverables in this repository

1. `docs/EXECUTIVE_SUMMARY.md`, `docs/API_VERIFICATION.md`, `docs/FLAGGED_FOR_REVIEW.md` — written reports, also published as site pages.
2. `scripts/` — the Kalshi API client, the swing-alert engine, the paper-trading
   strategy engine, and the portfolio tracker (Python, tested with unit tests
   using clearly-labeled synthetic fixtures, never presented as real data).
3. `.github/workflows/collect-kalshi-data.yml` — scheduled collector (every 10
   minutes) that is the only component that ever touches real Kalshi data.
4. `docs/` (site root, GitHub Pages "docs/ on main" source) — the dashboard:
   landing page, five topic pages, two live-alert scrolling feeds (all events
   / high-ROI filtered), price/liquidity charts with a seconds/minutes/hours
   time-range selector, portfolio & strategy-analysis page, verification page,
   flagged-for-review page, and a live-interactivity suggestions page.

## 7. Suggestions to make the site more live & interactive

See `docs/suggestions.html` (also summarized here): WebSocket streaming via a
small serverless relay (GitHub Pages can't hold a socket open itself);
sparkline mini-charts per market row; desktop/browser push notifications on
alerts; a "replay" scrubber over historical snapshots; per-market news-link
enrichment (auto-attaching the headline that coincided with a ≥$0.10 move);
user-configurable alert thresholds and topic filters stored in `localStorage`;
dark mode; and a comparison view against Polymarket where an equivalent market
exists, clearly labeled as a separate, non-Kalshi data source if ever added.
