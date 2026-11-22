# `scripts/` — Kalshi demo data collector

Pure-stdlib Python package (no third-party runtime dependency) that:

1. Pulls public, unauthenticated market data from the Kalshi **demo** Trade
   API v2 (`scripts/kalshi_client.py`).
2. Buckets each market into one of five topics — gas prices, elections,
   culture, crypto, golf — using Kalshi's own `category` field plus a narrow
   keyword fallback (`scripts/categorize.py`).
3. Detects price swings ≥ $0.10 and emits alerts to two feeds: "all events"
   and a transparently-scored "high ROI" subset (`scripts/alerts.py`).
4. Runs three disclosed paper-trading strategies and settles them once the
   underlying market resolves (`scripts/strategies.py`).
5. Tracks a simulated portfolio from those paper trades
   (`scripts/portfolio.py`).
6. Orchestrates all of the above and writes every output file the dashboard
   reads under `docs/data/` (`scripts/collect_kalshi_data.py`).

## Why everything here is a *simulation*, not real trading

This pipeline never calls an authenticated Kalshi endpoint and never places a
real order. See `docs/FLAGGED_FOR_REVIEW.md` item 3 for the full reasoning —
short version: real order placement requires the user's own Kalshi demo API
key, and this autonomous session was told not to solicit credentials.

### If you want to wire up real demo-account execution

1. Generate a Kalshi **demo** API key pair (key ID + private key) per
   [docs.kalshi.com's demo environment guide](https://docs.kalshi.com/getting_started/demo_env).
2. Add two GitHub Actions repository secrets: `KALSHI_DEMO_KEY_ID` and
   `KALSHI_DEMO_PRIVATE_KEY_PEM`.
3. Implement request signing (RSA-PSS/Ed25519 over
   `timestamp + method + path`, headers `KALSHI-ACCESS-KEY` /
   `KALSHI-ACCESS-TIMESTAMP` / `KALSHI-ACCESS-SIGNATURE`) in a new
   `scripts/kalshi_authed_client.py`, and call `/portfolio/events/orders`
   instead of (or alongside) the paper-trading strategy engine.
4. This was deliberately left undone by default — flip it on only with your
   own credentials and own risk tolerance; it is real money in a demo
   environment whose "price and behavior... may not be reflective of those in
   real markets" (direct quote,
   [docs.kalshi.com](https://docs.kalshi.com/getting_started/demo_env)).

## Running locally

```bash
# Run the full collector once (requires real internet access to
# external-api.demo.kalshi.co — will fail fast in network-restricted
# sandboxes, by design, rather than inventing data; see
# docs/EXECUTIVE_SUMMARY.md section 3).
python3 -m scripts.collect_kalshi_data

# Re-seed the intentionally-empty placeholder files (used once, before the
# first real collection run):
python3 -m scripts.seed_empty_data

# Run the unit tests (synthetic fixtures only, never real market data):
python3 -m unittest discover -s scripts/tests -t . -v
# or, if pytest is installed:
python3 -m pytest scripts/tests -q
```

## File layout

| File | Purpose |
|---|---|
| `config.py` | Base URLs, topic→category mapping, thresholds, paths |
| `kalshi_client.py` | Public REST client (series/events/markets/orderbook) |
| `categorize.py` | Topic classification logic |
| `alerts.py` | Swing detection + "high ROI" scoring |
| `strategies.py` | Paper-trading strategy engine + settlement |
| `portfolio.py` | Simulated portfolio roll-up, by strategy and by topic |
| `io_utils.py` | Atomic JSON read/write helpers |
| `collect_kalshi_data.py` | Orchestrator — the GitHub Actions entry point |
| `seed_empty_data.py` | One-time seeding of empty placeholder data files |
| `tests/` | Unit tests against synthetic fixtures only |
