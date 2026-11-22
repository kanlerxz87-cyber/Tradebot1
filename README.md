# Kalshi Trader

A live research desk for five Kalshi topics — **gas prices, elections, culture, crypto, golf** — that
detects ≥ $0.10 contract-price swings, publishes two alert feeds, charts price and liquidity, tracks
events to settlement, and trades the same signals autonomously in a simulated book.

**Live site:** <https://kanlerxz87-cyber.github.io/Tradebot1/>
**Executive summary:** [`EXECUTIVE_SUMMARY.md`](EXECUTIVE_SUMMARY.md) · [web version](https://kanlerxz87-cyber.github.io/Tradebot1/executive-summary.html)
**Verification log:** [`docs/verification.html`](docs/verification.html) · **Flagged items:** [`docs/flagged.html`](docs/flagged.html)

---

## What it does

| Capability | Where |
| - | - |
| Scans every open Kalshi event, keeps only the five requested topics | `kalshi_trader/topics.py`, `collector.py` |
| Ranks events by estimated 24h traded notional | `marketdata.aggregate_events` |
| Alerts on ≥ $0.10 moves, in both directions | `kalshi_trader/swings.py` |
| Two live chats: all alerts, and the model's high-ROI subset | `docs/index.html`, `docs/assets/js/app.js` |
| Price chart (x = time, y = price) with 30s → all windows | `docs/assets/js/charts.js` |
| Orderbook depth: contracts resting at each price | `marketdata.normalize_orderbook` |
| Resolution tracking (YES / NO) with verification links | `collector._collect_resolutions` |
| Four autonomous strategies, fixed-fraction sizing, settlements | `strategies.py`, `paper.py` |
| Portfolio analytics by strategy / topic / price band / exit | `portfolio.py`, `docs/portfolio.html` |
| Optional real demo-account mirroring | `kalshi_demo.py` |

## Quick start

```bash
git clone https://github.com/kanlerxz87-cyber/Tradebot1.git
cd Tradebot1
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

.venv/bin/python -m pytest -q                    # 48 unit tests
.venv/bin/python -m kalshi_trader.cli collect    # one live cycle → docs/data/*.json
.venv/bin/python tools/build_site.py             # regenerate the static tables
.venv/bin/python tools/check_links.py            # no broken internal links
.venv/bin/python -m kalshi_trader.cli serve      # site + API + WebSocket on :8000
```

No API key is required: market data comes from the public production endpoints.
`python -m kalshi_trader.cli demo-status` reports whether demo credentials are configured.

## How the automation works

```
GitHub Actions cron (*/15 * * * *)
        │
        ├─ collect  →  series catalogue → open events → topic markets → prices
        │              ↓
        │            swings ≥ $0.10 → alerts.json
        │            model score     → picks (second chat)
        │            paper engine    → entries / exits / settlements → app_data/paper_ledger.json
        │            resolutions     → resolved.json
        │              ↓
        ├─ build_site.py  → static tables + topic pages (source link on every row)
        └─ deploy-pages   → https://kanlerxz87-cyber.github.io/Tradebot1/
```

Nothing needs manual input. A stale snapshot is labelled amber after 30 minutes; collection errors are
written into the snapshot and shown on the page instead of being swallowed.

## Design decisions you should know

1. **Production data, paper execution.** Public production endpoints are keyless and real; the demo
   environment is a sandbox whose prices Kalshi warns may not match the real market. Execution stays in
   the internal ledger until demo credentials exist (flag F2, F6).
2. **Static site + scheduled collector.** GitHub Pages cannot poll an exchange, so a job collects,
   commits and deploys. The page always states the snapshot's age (flag F10).
3. **Nothing is invented.** Missing demo balance, unverified fee rates and unproven news causality are
   left blank and flagged, never filled in.
4. **The ROI model is a heuristic.** Six weighted components, published weights, version
   `heuristic-v1`, disclaimer next to every result (flag F12).

## Repository layout

```
kalshi_trader/          Python package (client, topics, alerts, model, paper book, server, CLI)
docs/                   GitHub Pages site (static HTML + vanilla JS, no CDN)
docs/data/              published snapshots: latest, alerts, history, paper, resolved, sources, flags
tools/                  build_site.py (generator) and check_links.py (link gate)
tests/                  48 unit tests with fixtures captured from the real API
app_data/               paper-trading ledger (committed so the book survives between runs)
COORDINATION.md         shared task board, source register and activity log
```

## Verification rules applied

Every factual row links to an official Kalshi source and carries a check date (2026-11-22). If a value
could not be confirmed from an official page it is blank and listed on the
[Flagged for Review](https://kanlerxz87-cyber.github.io/Tradebot1/flagged.html) page. Third-party
articles were used only for orientation and are never cited as evidence.

## Notes

* Not investment advice. Demo and paper trading only; no production order path exists in this code.
* Kalshi is a CFTC-regulated exchange; its [Developer Agreement](https://docs.kalshi.com/getting_started/api_keys)
  governs API use.
* Licensed for personal research use; Kalshi's API terms and market data remain Kalshi's property.
