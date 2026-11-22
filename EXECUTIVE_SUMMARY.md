# Executive summary — Kalshi Demo Research Desk

**Reviewed:** 2026-11-22 · **Repository:** `kanlerxz87-cyber/Tradebot1`

**Primary publication:** [Research dashboard](https://kanlerxz87-cyber.github.io/Tradebot1/docs/)

**Evidence register:** [Flagged for Review](https://kanlerxz87-cyber.github.io/Tradebot1/docs/review/) · [Verification table](docs/VERIFICATION.md)

## Decision summary

The project now has a unified, source-linked research dashboard and a separately runnable **demo-only** service. It covers the requested five topics, grouped event/contract inspection, dual ≥10¢ alert feeds, interactive time/price charts, liquidity, retained lifecycle tracking, two automated hypothetical strategies, categorized gross performance, and guarded demo-account API adapters.

**Publication is not proof of live execution.** Public snapshots were collected from official demo endpoints in GitHub Actions, and representative market/series responses were independently inspected. The local service starts and serves the integrated UI, but its outbound Kalshi network is restricted and it has no configured demo credentials. No authenticated WebSocket, account balance, exchange-executed trade, net ROI, complete highest-dollar ranking or causal news link is claimed. Those values remain blank and the gaps are published, as requested.

## Requirements and delivery status

The “status” column describes this repository's implementation and observed checks. Official links establish the underlying API/hosting behavior, not independent certification of the software.

| Requirement | Implemented behavior and verification boundary | Official reference |
| --- | --- | --- |
| Only gas prices, elections, culture, crypto and golf | Separate topic pages; explicit local rules over official series metadata; unmatched/ambiguous records excluded. Current bounded sample has no Culture contracts, rather than substituted data. | [Series metadata](https://docs.kalshi.com/api-reference/market/get-series-list) |
| Highest-dollar live events, grouped by topic/event | Event grouping and reported cumulative dollar-notional sorting implemented. Missing notional stays blank. Default 24h contract-count sort is not dollar turnover; incomplete exchange coverage is disclosed. A complete highest-dollar ranking remains unverified. | [Ticker notional fields](https://docs.kalshi.com/websockets/market-ticker) |
| Follow through YES/NO resolution | Browser retains its watchlist; server persists unresolved contracts, reconciles those missing from open listings, and uses the historical endpoint on 404. Only REST `finalized` with compatible YES/NO result settles the binary paper ledger. | [Lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle), [Archives](https://docs.kalshi.com/getting_started/historical_data) |
| ≥$0.10 movement in either direction | Inclusive threshold in a rolling 60-second observed window, re-anchored after an alert. Both cumulative smaller ticks and reversals are tested. Snapshots cannot create alerts; REST can miss intrapoll movements. | [Trade stream](https://docs.kalshi.com/websockets/public-trades) |
| Two scrolling chats | All observed qualifying alerts plus “Model watch.” Server selection uses prior data and executable depth; browser-only screening is a quote/spread check without an ROI estimate. Both are unvalidated research, not profit predictions. | [Market data](https://docs.kalshi.com/websockets/market-ticker) |
| Automated simulated trades and experiments | Independent momentum and mean-reversion paper accounts; explicit $1,000 starting assumption, fresh ask/depth fills, no leverage, cumulative open cost ≤$20/event/strategy, and idempotent binary settlement. Synthetic test results never become public market data. | [Orderbook semantics](https://docs.kalshi.com/api-reference/market/get-market-orderbook), [Settlement](https://docs.kalshi.com/getting_started/market_settlement) |
| Execute demo-account trades | Protected V2 IOC buy/cancel endpoints, signature verification tests, persistent pre-submission reservation, duplicate/ambiguity guards and a kill switch implemented. Disabled by default; no actual demo order or fill verified. | [Create Order V2](https://docs.kalshi.com/api-reference/orders/create-order-v2), [Uncertain submissions](https://docs.kalshi.com/getting_started/quick_start_create_order) |
| Portfolio, P&L and categorized strategy performance | Paper cash, gross equity and topic × strategy × side analysis implemented. Private adapter reads balance, live/historical positions, orders, fills and live settlements, scoped to primary subaccount 0. Public account metrics stay blank. Net ROI/fees and atomic account reconciliation remain unverified. | [Balance](https://docs.kalshi.com/api-reference/portfolio/get-balance), [Positions](https://docs.kalshi.com/api-reference/portfolio/get-positions) |
| Time/price chart with seconds/minutes/hours | SVG hover and 1m/1h/24h windows; real observed timestamps or official candle closes. Published candle snapshots are historical, never invented points. Lines connect observations, not a claim about prices between them. | [Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) |
| Liquidity/contracts at each price | YES/NO bids and complementary asks with aggregate contract quantities. Source time, stale state and snapshot-vs-current mode shown. Depth is not an order count or fill guarantee. | [Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) |
| Official news/event links around moves | Each alert links market evidence; the detail panel shows contract rules and supplied settlement references. No publication has been verified as associated with, or causing, a particular jump; catalyst lists remain empty. | [Series settlement-source metadata](https://docs.kalshi.com/api-reference/market/get-series-list) |
| Source per factual table row; flag unknowns | Static and browser checks require official source links on every primary factual table row. Missing numeric fields are null/blank, not zero; unverified values appear on the dedicated review page. | [Official market fields](https://docs.kalshi.com/api-reference/market/get-markets) |
| GitHub Pages and clean subpages | Nine generated, responsive pages and root redirect. CI gates publication on backend, frontend, link and browser checks. Pages cannot run the trusted backend. Release evidence is recorded on the board. | [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages) |

## Architecture and source modes

1. **Public static research (`docs/`).** Credential-free HTML/CSS/ES modules. Original observation timestamps survive refresh failures. Every source mode is visible. Public pages never request a Kalshi private key or call private account/order routes.
2. **Public snapshot collector (`scripts/build_snapshot.py`).** Bounded series/new-market sampling, up to eight events/topic and eight contracts/event, with a small sourced historical candle/depth fallback. The sampling preference is reported contract volume, not dollars. No price × volume estimate is used.
3. **Trusted service (`services/kalshi/`).** Exact official demo-host allowlist, full-queryless-path RSA-PSS/Ed25519 signatures, rate-aware reads, WebSocket book sequence checks, SQLite observations/order journal, and relative same-origin SSE/API access. Static Pages does not host it.
4. **Two distinct simulation implementations.** The browser tests one-contract momentum/fade hypotheses on fresh displayed quote size. The server screens ≥20 prior samples and consumes fresh opposing book depth in independent accounts. They are labeled separately and are not pooled as one performance record.
5. **Private account boundary.** Separate operator bearer authorization, no private state in SSE or Pages artifacts, default-disabled IOC execution and conservative durable payout-notional caps. An accepted order is not a confirmed fill. No production URL, withdrawal, short-sale or leveraged path is offered.

## Repository review: material corrections

- Replaced the earlier inferred `last price × volume` “dollar” proxy with exchange-reported notional only. Missing child notional invalidates an aggregate instead of silently counting zero.
- Stopped stamping published observations as newly live. Snapshots do not seed movement alerts, hypothetical fills or current-liquidity claims.
- Corrected lifecycle accounting: determined, disputed, amended and merely closed markets are not finalized. Scalar/nonstandard payouts are not forced into YES/NO.
- Fixed separate quote/trade clocks: a fresh last trade cannot refresh an old bid for mark-to-market. A later ticker flush does not suppress an earlier trade notification.
- Added atomic SQLite migration from the initial timestamp-keyed observation schema to event-ID deduplication; existing history is preserved and future schema versions are not silently downgraded.
- Preserved the original `site/` and `python/` implementations for history. The prototype's synthetic fallback is not official data. The old `python/kalshi_client.py` signs a relative path and writes to a removed order endpoint; it is explicitly not the supported execution client.
- Reconciled conflicting summaries, source tables and deployment claims. Source/specification checks, mocked tests, browser behavior, public observations and authenticated integration are no longer conflated.

## Verification performed

- **96 backend tests:** synthetic fixtures and mocked transport; normalization, signing, demo-host guards, pagination, archive fallback, channel ordering, depth, settlement, persistence migration, exposure, idempotency, protected routes and private/public separation.
- **17 Node tests:** strict null handling, reported-notional grouping, topic exclusion, inclusive rolling swings, complementary books, formula-safe CSV and browser paper accounting.
- **12 real Chromium scenarios:** desktop/mobile layout, topic isolation, navigation, search/sorting, chart controls, book side, CSV, official row sources, offline snapshots, deterministic REST paper fills/settlement and mocked same-origin SSE/history/depth. No live account is involved.
- **Nine primary pages:** local paths, anchors, module imports, unique IDs, required view controls and public snapshot source/timestamp structure checked. The preserved simulator test also passes.
- **Public source rechecks:** official gas, Bitcoin and golf market responses, Culture series metadata, and the open-event query for both Culture series returned at review time. Changing quotes are not expected to equal an earlier timestamped snapshot.
- **Runtime boundary:** same-origin preview responds; health reports `credentials_configured=false`, demo execution disabled, and upstream network unavailable. No secret was requested or used.

External link structure/source provenance checks are not a guarantee that every external website is currently reachable. Latest CI, PR/merge and publicly fetched deployment details belong in [`COORDINATION.md`](COORDINATION.md), rather than a perpetual “live” claim in this brief.

## Recommended next research cycle

1. **Operate the trusted service on a continuously running host** with permitted demo-network access, TLS, synchronized clock, secret storage and durable private SQLite backups. Keep signing off Pages.
2. **Reconcile actual account data before trading claims.** Verify a demo handshake, balance units, accepted-vs-filled IOC behavior, fee fields and live/archive overlap. Preserve ambiguous reservations; never retry an uncertain write automatically.
3. **Validate model selection out of sample.** Walk-forward cohorts, topic/side attribution, execution/fee stress tests, exposure caps and slippage analysis should precede any “high ROI” label.
4. **Broaden discovery with explicit coverage accounting.** Obtain reported notional for all observed children and track notional timestamps independently. Do not relabel bounded contract-volume sampling as an exchange-wide dollar ranking.
5. **Add timestamped primary-source announcements.** Store publication URL/time and distinguish a temporal association from causal evidence. Empty catalyst fields are preferable to fabricated explanations.

These are operational/research limitations, not excuses to publish fabricated values. The software and documentation are released with the outstanding items visible, as instructed.
