# Tradebot1 — Kalshi Demo Trading Dashboard

A dashboard that tracks Kalshi's **demo** prediction-market environment
(gas prices, elections, culture, crypto, golf), alerts on contract-price
swings ≥ $0.10, runs disclosed paper-trading strategies, and tracks a
simulated portfolio — published as a static GitHub Pages site under `docs/`.

**Live site:** once GitHub Pages is enabled for this repo (Settings → Pages →
source: `main` branch, `/docs` folder), it will be served at
`https://kanlerxz87-cyber.github.io/Tradebot1/`.

## Start here

- [`docs/EXECUTIVE_SUMMARY.md`](docs/EXECUTIVE_SUMMARY.md) — what this is, what's real vs. simulated, sources
- [`docs/API_VERIFICATION.md`](docs/API_VERIFICATION.md) — line-by-line Kalshi API verification with source links
- [`docs/FLAGGED_FOR_REVIEW.md`](docs/FLAGGED_FOR_REVIEW.md) — open items and irregularities, none of which block the build
- [`COORDINATION.md`](COORDINATION.md) — shared task board for multi-session work on this repo
- [`scripts/README.md`](scripts/README.md) — the data-collection pipeline

## Repository layout

```
docs/                    GitHub Pages site (static HTML/CSS/JS + data)
  index.html             Landing page
  gas-prices.html, elections.html, culture.html, crypto.html, golf.html
  alerts.html            Two scrolling live-alert feeds (all events / high-ROI)
  portfolio.html         Simulated portfolio + strategy breakdown
  verification.html, flagged-for-review.html, executive-summary.html
  suggestions.html       Ideas for making the site more live/interactive
  assets/                style.css, app.js (no external JS dependencies)
  data/                  JSON written by the collector (starts empty)
scripts/                 Python collector (pure stdlib), see scripts/README.md
.github/workflows/
  collect-kalshi-data.yml   Scheduled job that fetches real Kalshi demo data
  ci.yml                    Tests + broken-link check on every push/PR
```

## Why the dashboard ships with empty data

The coding sandbox that built this project cannot reach Kalshi's API (see
`docs/EXECUTIVE_SUMMARY.md` section 3) — only GitHub Actions can, after
merge. No data was invented to fill the gap. Check the Actions tab after
merge to confirm `collect-kalshi-data.yml` has run.
