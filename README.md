# Tradebot1 — Kalshi Demo Trading Dashboard

Live dashboard for the **Kalshi demo environment** tracking the highest-dollar
events in **gas prices, elections, culture, crypto, and golf** — with ≥ $0.10
swing alerts (dual scrolling chats), price charts, order-book liquidity,
yes/no resolution tracking, and automated simulated trading.

**Site:** GitHub Pages from `site/` (enable in repo Settings → Pages →
Source: **GitHub Actions**; workflow: `.github/workflows/pages.yml`).

## Start here
- [`EXECUTIVE_SUMMARY.md`](EXECUTIVE_SUMMARY.md) — executive summary
- [`docs/VERIFICATION.md`](docs/VERIFICATION.md) — every claim traced to an official source; unverified items left blank
- [`site/flagged.html`](site/flagged.html) — Flagged for Review page
- [`python/README.md`](python/README.md) — credentialed demo trading setup

## Layout
```
site/            Static GitHub Pages site (no build step)
python/          Signed Kalshi client + paper simulator + tests
docs/            Verification table
COORDINATION.md  Shared task board / session log
```

## Quick checks
```bash
python3 python/test_simulator.py   # mocked unit tests, no network
node --check site/assets/app.js    # JS syntax check
```

Paper/simulated trading only — not financial advice. Demo prices may not
reflect real markets (https://docs.kalshi.com/getting_started/demo_env).
