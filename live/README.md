# Live desk (`live/`)

A dependency-free server and a single-page dashboard for the Kalshi **demo** environment:
five topics only, alerts on moves of **$0.10 or more** in either direction, two scrolling
chats, a price chart with seconds-to-hours windows, resting liquidity at each price, four
automatic simulated strategies, and resolution tracking.

```sh
python3 live/server.py --port 8000              # http://localhost:8000
python3 live/server.py --mode live              # poll external-api.demo.kalshi.co
python3 -m unittest discover -s live/tests      # 29 tests, no network required
python3 live/build_page.py                      # regenerate the published live.html
```

Only the Python standard library is used, so the server runs on any machine with Python 3.10+
— no `pip install`, no build step, no API key.

## What it actually does

| Requirement | Implementation |
| - | - |
| Highest-dollar live events, five topics | `Desk.state()` groups markets by event inside each of gas / elections / culture / crypto / golf and ranks events by estimated 24h notional |
| Alert on ≥ $0.10 either direction | `Desk._apply_mid` and `Desk._poll_live`: `abs(mid − previous mid) >= 0.10`, inclusive and symmetric |
| Two scrolling chats | `/api/state.alerts` plus `filteredIds`; the second feed is the subset scoring ≥ 55 on the published six-part screen |
| Price chart, x = time, selectable window | `app.js` canvas; 30s / 1m / 5m / 15m / 1h / 4h; `/api/series` |
| Liquidity: contracts at each price | `/api/book` returns both ladders; the panel draws a bar per level and a "within 5¢" total |
| Track until resolved, show YES/NO | `_sync_resolutions()` records only `determined`/`finalized` with `result` in yes/no/scalar; `_manage_positions` settles at $1/$0 |
| Automated simulated trades + analysis | Four rules (momentum, fade, cheap upside, late favourite) with 2% risk, 12-position cap, spread and fee; grouped by strategy, topic, price band and exit reason |
| No manual input | The ticker thread trades and settles on its own; the only user action is choosing which contract to chart |

## Modes, and why the label matters

| Mode | What drives prices | Honest reading |
| - | - | - |
| `live` | `GET {demo}/markets?series_ticker=…` and `/markets/{ticker}/orderbook`, unauthenticated | Every number came from Kalshi; a move between two polls can still be missed |
| `simulated` | Seeded random walk anchored to the committed capture | Mechanics demo. Alerts are **not** Kalshi events and carry `simulated: true` |

`--mode auto` (default) probes `/exchange/status` once and falls back to `simulated` when
there is no egress. The badge in the header and the banner under it always name the live mode,
and `/api/meta.disclosure` says it in words.

The fallback simulation mean-reverts to the captured mid, which mechanically penalises
momentum rules. Strategy P&L in simulation tests the plumbing, not an edge.

## Quote hygiene

`read_quote()` refuses to publish a mid unless the book is two-sided, uncrossed, away from the
0.00 × 1.00 placeholder states and no wider than 20 cents. Otherwise it falls back to the last
trade and marks the market quote-only; with no last trade, nothing is published. This is what
stops a placeholder book from looking like a $0.50 market and firing false alerts — one of the
irregularities an earlier session flagged (`F-05` on `flagged.html`).

## Routes

| Route | Returns |
| - | - |
| `GET /api/meta` | mode, disclosure, threshold, strategies, fee model, endpoints, source links, limits |
| `GET /api/state` | topics → events → markets, alerts, portfolio, resolution watch |
| `GET /api/series?ticker=&seconds=` | chart points and the contract's book |
| `GET /api/book?ticker=` | YES bid/ask ladders with resting contracts |
| `GET /api/stream` | Server-Sent Events, one `tick` per interval |
| `GET /api/health` | liveness |

There is no POST handler: the server cannot place an order, and no credential is read.

## Fees

The model is `ceil_to_cent(rate × contracts × price × (1 − price))` with taker 0.07 / maker
0.0175. The constants are the published general schedule, but the schedule page could not be
re-read from the authoring sandbox, so `FEE_VERIFIED` is `False` and `/api/meta` reports the
model as unverified. Set it to `True` only after re-reading
<https://docs.kalshi.com/getting_started/fees>.

## Sources

* <https://docs.kalshi.com/getting_started/api_environments> — demo REST and WebSocket hosts
* <https://docs.kalshi.com/getting_started/orderbook_responses> — bids only, implied asks, ascending arrays
* <https://docs.kalshi.com/getting_started/market_lifecycle> — statuses, `result` values, finalisation
* <https://docs.kalshi.com/getting_started/fees> — fee schedule (unverified in this branch)
* <https://docs.kalshi.com/getting_started/quick_start_websockets> — the channel this process does not use

Cross-implementation audit: [`qa/report.md`](../qa/report.md) · published page [`live.html`](../live.html).
