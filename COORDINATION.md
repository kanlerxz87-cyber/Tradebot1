# Coordination board

Repository branch for this Arena session: `arena/c9075e75-tradebot1` (session ID `c9075e75`). Arena fixes this branch; this session cannot create or switch to `session-<id>/<task>` or an integration branch. Do not edit files claimed below from another session. No other tasks were listed when this board was created on 2026-11-22.

| Task | Status | Owner | File scope | Claimed (UTC) | Sources / verification / irregularities |
| --- | --- | --- | --- | --- | --- |
| Kalshi demo research, static Pages dashboard, simulation, documentation, tests, and integration | In progress | c9075e75 | `COORDINATION.md`, `README.md`, `index.html`, `.nojekyll`, `.gitignore`, `docs/**`, `scripts/**`, `.github/**`, `tests/**` | 2026-11-22 | Checked [official Kalshi environments](https://docs.kalshi.com/getting_started/api_environments), [events](https://docs.kalshi.com/api-reference/events/get-events.md), [markets](https://docs.kalshi.com/api-reference/market/get-markets.md), [lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle.md), [candles](https://docs.kalshi.com/api-reference/market/get-market-candlesticks), [orderbook](https://docs.kalshi.com/getting_started/orderbook_responses) and [WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets); fetched demo market/event API examples including `tickers=` and `mve_filter=exclude`. Node tests and local link checker pass. Irregularities: public static site cannot safely authenticate WS/orders/portfolio; limited sampled coverage, no causal attribution or verified ROI; Pages source is legacy `main /` and update to workflow mode returned HTTP 403 (integration permission), listed on Flagged for Review. Root redirects to `docs/` as fallback. Deployment/PR pending. |

## Handoffs and cross-scope requests

None at creation. A claim older than 60 minutes with no commits can be taken over if the handoff is documented here. Do not overwrite another session's changes.
