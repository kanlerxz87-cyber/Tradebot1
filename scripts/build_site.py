"""Generate a consistent static shell. Data comes only from source-linked observations."""

from html import escape
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ICONS = {
    "overview": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "gas": '<path d="M4 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16M3 21h12M5 7h8M14 10h2a2 2 0 0 1 2 2v5a1.5 1.5 0 0 0 3 0V8l-3-3"/>',
    "elections": '<path d="m9 6 3 3 6-6M6 10l-3 5v6h18v-6l-3-5M3 15h18M8 11h8"/>',
    "culture": '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9L12 3Z"/>',
    "crypto": '<path d="M9 3v18M13 3v3m0 12v3M7 6h8a3 3 0 0 1 0 6H7m2 0h7a3 3 0 0 1 0 6H7"/>',
    "golf": '<path d="M8 21V3l11 5-11 5M5 21h6"/><ellipse cx="16" cy="20" rx="5" ry="2"/>',
    "portfolio": '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v3M3 12h18M10 12v3h4v-3"/>',
    "review": '<path d="m12 3 10 18H2L12 3ZM12 9v5m0 3v1"/>',
    "summary": '<path d="M6 3h9l4 4v14H6V3ZM14 3v5h5M9 12h7m-7 4h7"/>',
    "arrow": '<path d="M7 17 17 7M7 7h10v10"/>',
    "refresh": '<path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    "activity": '<path d="M2 12h4l3-8 5 16 3-8h5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "shield": '<path d="m12 3 8 3v5c0 5-8 10-8 10S4 16 4 11V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
}
TOPICS = {"gas": "Gas prices", "elections": "Elections", "culture": "Culture", "crypto": "Crypto", "golf": "Golf"}


def icon(name, cls=""):
    return f'<svg class="icon {cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>'


def external(url, label="Official source"):
    return f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(label)} ↗</a>'


def shell(page, title, content, depth=0, script=False):
    prefix = "../" * depth or "./"
    nav = [("all", "overview", "Overview", ""), *[(key,key,value,key+"/") for key,value in TOPICS.items()],
           ("portfolio", "portfolio", "Portfolio & strategies", "portfolio/")]
    links = []
    for key, glyph, label, href in nav:
        active = ' class="active" aria-current="page"' if key == page else ''
        links.append(f'<a href="{prefix}{href}"{active}>{icon(glyph)}<span>{label}</span>{"<span class=nav-count>5</span>" if key == "all" else ""}</a>')
    research = []
    for key,glyph,label,href in [("summary","summary","Executive summary","executive-summary.html"),("review","review","Flagged for Review","review/")]:
        active = ' class="active" aria-current="page"' if key == page else ''
        research.append(f'<a href="{prefix}{href}"{active}>{icon(glyph)}<span>{label}</span></a>')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0b1114"><meta name="description" content="A source-linked Kalshi demo research desk for gas prices, elections, culture, crypto and golf. No real-money trading."><title>{escape(title)} · Kalshi Demo Desk</title><link rel="icon" href="{prefix}assets/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="{prefix}assets/style.css"></head>
<body data-topic="{page if page in TOPICS else 'all'}" data-view="{page}"><a class="skip-link" href="#main">Skip to workspace</a><div class="shell">
<aside class="sidebar"><a class="brand" href="{prefix}"><span class="brand-mark">{icon('activity')}</span><span>KALSHI<span class="brand-sub">RESEARCH DESK</span></span></a>
<div class="workspace"><span class="workspace-icon">D</span><div>Demo workspace<small>Independent research</small></div><span class="workspace-chevron">⌄</span></div>
<div class="sidebar-label">WORKSPACE</div><nav class="nav" aria-label="Workspace">{''.join(links)}</nav><div class="sidebar-label research-label">RESEARCH</div><nav class="nav" aria-label="Research">{''.join(research)}</nav>
<div class="sidebar-bottom"><div class="safe-icon">{icon('shield')}</div><strong>Research. Not real money.</strong><p>Official demo observations.<br>Clearly separated simulations.</p><a href="https://demo.kalshi.co/" target="_blank" rel="noopener noreferrer">Open Kalshi Demo {icon('arrow')}</a></div><div class="sidebar-version"><span class="dot"></span> DEMO ENVIRONMENT <span>v2.0</span></div></aside>
<main class="main" id="main"><header class="topbar"><div class="breadcrumb">Workspace <span>/</span> <strong>{escape(title)}</strong></div><div class="top-right"><span class="environment-tag">DEMO ONLY</span><span id="utc-clock" class="utc-clock">UTC</span><a class="icon-button" href="{prefix}executive-summary.html" aria-label="Read methodology">{icon('summary')}</a></div></header>
{content}
<footer class="footer"><span>Independent research. Not affiliated with Kalshi. No investment advice.</span><div><a href="{prefix}executive-summary.html">Methodology</a><a href="{prefix}review/">Data & limitations</a>{external('https://docs.kalshi.com/getting_started/demo_env','Official API docs')}</div></footer></main></div>{f'<script type="module" src="{prefix}assets/app.mjs"></script>' if script else ''}</body></html>'''


def ledger():
    return '''<div class="panel table-wrap"><table><thead><tr><th>Strategy / topic</th><th>Contract</th><th>Side / quantity</th><th class="num">Entry</th><th>Status</th><th class="num">Gross P&amp;L</th><th>Source</th></tr></thead><tbody id="paper-rows"><tr><td colspan="7" class="empty">No hypothetical trades yet. <a href="https://docs.kalshi.com/api-reference/orders/create-order-v2" target="_blank" rel="noopener noreferrer">Execution specification ↗</a></td></tr></tbody></table></div>'''


def dashboard(topic):
    label = TOPICS.get(topic, "Market overview")
    headline = f"{TOPICS[topic]} markets" if topic in TOPICS else "The market, in focus."
    prefix = "../" if topic in TOPICS else "./"
    tabs = '<a class="topic-tab '+('active' if topic=='all' else '')+f'" href="{prefix}">All topics <span data-topic-count="all">—</span></a>'
    for key,value in TOPICS.items():
        tabs += f'<a class="topic-tab {"active" if key==topic else ""}" href="{prefix}{key}/">{icon(key)}{value}<span data-topic-count="{key}">—</span></a>'
    return f'''<section class="page-heading"><div><div class="eyebrow">FIVE TOPICS. ONE CLEARER PICTURE.</div><h1>{headline}</h1><p>Track activity. Catch the 10¢ move. Check the evidence.</p></div><div class="heading-actions"><button id="export" class="button secondary">{icon('download')} Export data</button><button id="refresh" class="button primary">{icon('refresh')} Refresh feed</button></div></section>
<div class="data-banner" id="data-banner"><div>{icon('shield')}<span id="data-mode">Checking source availability…</span></div><span id="connection" class="status pending" role="status">Connecting</span></div>
<section class="metrics" aria-label="Observed market summary"><article class="metric"><div class="metric-top">EVENTS TRACKED{icon('overview')}</div><strong id="stat-events">—</strong><div class="metric-foot"><span class="mini-dot"></span><span>Across the selected topics</span></div></article><article class="metric"><div class="metric-top">CONTRACTS IN VIEW{icon('activity')}</div><strong id="stat-markets">—</strong><div class="metric-foot">Source-linked observations</div></article><article class="metric"><div class="metric-top">10¢+ MOVEMENTS{icon('activity')}</div><strong id="stat-alerts">—</strong><div class="metric-foot">Both directions · 60-second window</div></article><article class="metric"><div class="metric-top">REPORTED $ NOTIONAL{icon('portfolio')}</div><strong id="stat-notional">—</strong><div class="metric-foot" id="notional-note">Unverified until reported by exchange</div></article></section>
<nav class="topic-tabs" aria-label="Market topics">{tabs}</nav>
<section class="panel watchlist"><div class="panel-head"><div><h2>Event watchlist <span id="row-count" class="count-badge">0</span></h2><p id="coverage">Awaiting a source-confirmed observation.</p></div><div class="table-controls"><label class="search">{icon('search')}<input id="search" type="search" placeholder="Search events or tickers" aria-label="Search events or tickers"></label><label class="sort-control"><span class="sr-only">Sort events by</span><select id="sort"><option value="contracts">24h contracts ↓</option><option value="notional">Reported $ notional ↓</option></select></label></div></div><div class="table-wrap"><table><thead><tr><th>Event / contract</th><th class="num">YES price</th><th class="num">Bid / ask</th><th class="num">24h contracts</th><th class="num">$ notional <span title="Cumulative exchange-reported notional, not dollars spent">ⓘ</span></th><th>Status</th><th>Source</th></tr></thead><tbody id="market-rows"><tr><td colspan="7" class="empty">Retrieving official demo observations. Missing values stay blank. {external('https://docs.kalshi.com/api-reference/market/get-markets','Market specification')}</td></tr></tbody></table></div><div class="table-footer"><span id="table-note">No complete-exchange ranking is claimed.</span><button id="show-more" class="text-button" hidden>Show more contracts ↓</button></div></section>
<div class="section-heading"><div><div class="eyebrow">LOOK CLOSER</div><h2>Contract intelligence</h2></div><span class="section-aside">Observed prices. Visible liquidity.</span></div>
<div class="detail-grid"><section class="panel chart-panel"><div class="panel-head"><div><div class="eyebrow" id="detail-topic">SELECT A CONTRACT</div><h2 id="detail-title">Price movement</h2><p id="detail-sub">Choose a contract from the watchlist</p></div><div class="range-controls" role="group" aria-label="Chart time window"><button data-range="seconds" aria-pressed="false">1m</button><button data-range="minutes" class="active" aria-pressed="true">1h</button><button data-range="hours" aria-pressed="false">24h</button></div></div><div class="chart-summary"><strong id="detail-price">—</strong><span id="detail-meta">YES contract · unverified</span><span class="chart-key"><i></i> YES price</span></div><div class="chart-area"><svg id="chart" viewBox="0 0 760 260" role="img" aria-label="Contract price in dollars by time"></svg><div id="chart-tooltip" class="chart-tooltip" hidden></div><div id="chart-caption" class="caption">Seconds, minutes and hours use actual observation timestamps.</div></div><div class="chart-bottom"><span>{icon('clock')} Time on x-axis · USD on y-axis</span><a id="detail-source" href="https://docs.kalshi.com/api-reference/market/get-market" target="_blank" rel="noopener noreferrer">Market source ↗</a></div></section>
<section class="panel book-panel"><div class="panel-head"><div><h2>Orderbook depth</h2><p id="book-time">Select a contract</p></div><div class="range-controls" role="group" aria-label="Orderbook outcome"><button data-book-side="yes" class="active" aria-pressed="true">YES</button><button data-book-side="no" aria-pressed="false">NO</button></div></div><div class="table-wrap"><table class="book-table"><thead><tr><th class="num">Bid / contracts</th><th class="num">Ask / contracts</th><th>Source</th></tr></thead><tbody id="book-rows"><tr><td colspan="3" class="empty">No confirmed depth. {external('https://docs.kalshi.com/api-reference/market/get-market-orderbook','Orderbook docs')}</td></tr></tbody></table></div><div class="book-note">Asks = $1 − opposite bids. Sizes are aggregate contracts, not order counts. Displayed depth is not a fill guarantee.</div></section></div>
<details class="panel evidence"><summary>{icon('shield')} Contract rules & source context <span>Open evidence ↓</span></summary><div class="evidence-body"><div><h3>Official contract rules</h3><p id="rule-text">Select a market to read its supplied rules.</p><a id="event-source" href="https://docs.kalshi.com/api-reference/events/get-event" target="_blank" rel="noopener noreferrer">Event API ↗</a></div><div><h3>Potential catalysts</h3><p id="catalyst-note">No verified publication is linked to a price move. Coincidence is not evidence of causation.</p><h3>Listed settlement sources</h3><div id="settlement-sources" class="source-links">No source supplied yet.</div></div></div></details>
<div class="section-heading"><div><div class="eyebrow">THE SIGNAL DESK</div><h2>Movement alerts <span class="count-badge">± 10¢</span></h2></div><button id="pause" class="button subtle" aria-pressed="false">Pause feed display</button></div>
<div class="feed-grid"><section class="panel"><div class="panel-head"><div class="feed-title"><span class="feed-icon">{icon('activity')}</span><div><h2>All movements</h2><p>Every observed qualifying swing</p></div></div><span id="all-count" class="count-badge">0</span></div><div id="all-feed" class="feed-body" role="log" aria-live="polite"></div><div class="feed-footer"><span class="mini-dot"></span><span id="feed-mode">Waiting for observed updates</span><span>± $0.10</span></div></section><section class="panel model-panel"><div class="panel-head"><div class="feed-title"><span class="feed-icon model">{icon('culture')}</span><div><h2>Model watch</h2><p id="model-caption">A research filter. Not an ROI promise.</p></div></div><span class="research-badge">RESEARCH</span></div><div id="screen-feed" class="feed-body" role="log" aria-live="polite"></div><div class="feed-footer"><span>Unvalidated hypotheses · fees unknown</span><span id="screen-count">0 signals</span></div></section></div>
<div class="section-heading"><div><div class="eyebrow">LEARN BEFORE YOU TRADE</div><h2>Paper strategy ledger</h2><p id="paper-summary">Hypothetical results are separate from a Kalshi demo account.</p></div><a class="text-link" href="{prefix}portfolio/">Portfolio & strategies ↗</a></div>{ledger()}
<details class="panel evidence lifecycle-panel"><summary>{icon('clock')} Tracked event lifecycle <span>Resolution history ↓</span></summary><div class="table-wrap"><table><thead><tr><th>Event / contract</th><th>State</th><th>Final outcome</th><th>Source</th></tr></thead><tbody id="resolution-rows"><tr><td colspan="4" class="empty">No finalized outcomes observed. {external('https://docs.kalshi.com/getting_started/market_lifecycle','Lifecycle specification')}</td></tr></tbody></table></div></details>
<div class="notice"><span>{icon('shield')}</span><p><strong>Evidence first. Always.</strong> Snapshots are not live prices. Missing values are not zeros. REST can miss between-poll moves. Demo funds, hypothetical trades and account execution remain separate. <a href="{prefix}review/">See all limitations ↗</a></p></div>'''


def portfolio():
    return f'''<section class="page-heading"><div><div class="eyebrow">LEARN BEFORE YOU TRADE</div><h1>Portfolio & strategies</h1><p>Separate the hypothesis from the account. Measure what actually happened.</p></div><button id="refresh" class="button primary">{icon('refresh')} Refresh feed</button></section><div class="data-banner"><div>{icon('shield')}<span id="data-mode">Research simulation · never real money</span></div><span id="connection" class="status pending" role="status">Checking service</span></div>
<section class="panel account-panel"><div class="panel-head"><div><h2>Kalshi demo account</h2><p>Private balance, fills and positions require the trusted backend.</p></div><span class="status pending">Not connected</span></div><div class="account-metrics"><div><span>AVAILABLE BALANCE</span><strong>—</strong></div><div><span>PORTFOLIO VALUE</span><strong>—</strong></div><div><span>CONFIRMED FILLS</span><strong>—</strong></div><div><span>NET RETURN</span><strong>—</strong></div></div><div class="account-note">No account values have been verified. This public page never requests a Kalshi private key. {external('https://docs.kalshi.com/getting_started/quick_start_authenticated_requests','Account access specification')}</div></section>
<div class="section-heading"><div><div class="eyebrow">TWO INDEPENDENT HYPOTHESES</div><h2>Paper strategy comparison</h2><p>$1,000 starting cash per strategy is an explicit simulation assumption, not an account balance.</p></div><span class="research-badge">GROSS ONLY</span></div><div id="strategy-cards" class="strategy-grid"></div>
<div class="section-heading"><div><h2>Trade journal</h2><p id="paper-summary">No exchange executions are implied by hypothetical entries.</p></div><button id="export" class="button secondary">{icon('download')} Export public observations</button></div>{ledger()}
<div class="section-heading"><div><h2>Performance by topic, strategy & side</h2><p>Derived from the hypothetical journal above. Realized gross P&amp;L only; fees and net returns remain unknown.</p></div></div><div class="panel table-wrap"><table><thead><tr><th>Topic</th><th>Strategy</th><th>Side</th><th class="num">Entries</th><th class="num">Settled</th><th class="num">Realized gross</th><th>Source / derivation</th></tr></thead><tbody id="analysis-rows"><tr><td colspan="7" class="empty">No hypothetical performance to aggregate. {external('https://docs.kalshi.com/api-reference/portfolio/get-positions','Performance fields')}</td></tr></tbody></table></div>
<div class="section-heading"><div><h2>Research controls</h2></div></div><div class="panel table-wrap"><table><thead><tr><th>Control</th><th>Implementation</th><th>Specification / limitation</th></tr></thead><tbody>
<tr><td>Mean reversion</td><td>Server hypothesis: average earlier observed prices. Browser-only hypothesis: fade an observed swing. Not a calibrated fair-value forecast.</td><td>{external('https://docs.kalshi.com/websockets/market-ticker','Price observations')}</td></tr>
<tr><td>Momentum</td><td>Server hypothesis: extrapolate recent observed direction. Browser-only hypothesis: follow a swing. Accounted independently.</td><td>{external('https://docs.kalshi.com/websockets/public-trades','Trade observations')}</td></tr>
<tr><td>Executable liquidity</td><td>Server simulations consume fresh opposing book depth. Browser paper entries require fresh displayed quote size. Last price alone never fills an order.</td><td>{external('https://docs.kalshi.com/api-reference/market/get-market-orderbook','Depth fields')}</td></tr>
<tr><td>Risk cap</td><td>Local simulated open cost ≤ $20 per event and strategy. No leverage. Demo execution is disabled by default; server-side limits and a kill switch apply.</td><td>{external('https://docs.kalshi.com/api-reference/orders/create-order-v2','Order semantics')}</td></tr>
<tr><td>Resolution</td><td>YES/NO finalization only; disputed/scalar outcomes remain unresolved for this binary simulator. No payout at mere market close.</td><td>{external('https://docs.kalshi.com/getting_started/market_lifecycle','Official states')}</td></tr>
<tr><td>Fees & return</td><td>Gross hypothetical P&amp;L only. Net ROI stays blank until fees and execution are verified. Demo-account cash flows are not treated as returns.</td><td>{external('https://docs.kalshi.com/api-reference/portfolio/get-positions','Portfolio fields')}</td></tr>
</tbody></table></div><div class="notice"><span>{icon('review')}</span><p><strong>Research is not validation.</strong> Neither strategy has a validated out-of-sample ROI. No automated demo-account submission is enabled. <a href="../review/">Review open items ↗</a></p></div>'''


def research_pages(manifest):
    flags = manifest["flagged_for_review"] + [
        {"id":"legacy-prototype", "detail":"Preserved site/ prototype uses synthetic fallback values and an unvalidated score. It is not the primary verified dashboard. Never interpret those values as official observations.", "source_url":"https://docs.kalshi.com/getting_started/demo_env"},
        {"id":"legacy-client", "detail":"Preserved python/kalshi_client.py signs a relative path and uses removed /portfolio/orders writes. It is not suitable for current execution. Use services/kalshi/ instead; its live account integration is still unverified.", "source_url":"https://docs.kalshi.com/api-reference/orders/create-order-v2"},
        {"id":"pages-publishing", "detail":"Earlier deployments had legacy main-root and Actions publishing paths. The workflow attempts to select Actions as the single source; if repository permission denies it, tracked timestamped snapshot data remains the legacy fallback. Deployment evidence is recorded in COORDINATION.md.", "source_url":"https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site"},
    ]
    rows = ''.join(f'<tr><td><span class="flag-id">{escape(row["id"].replace("-"," "))}</span></td><td class="unverified-value" aria-label="Unverified; no confirmed value"></td><td>{escape(row["detail"])}</td><td>{external(row["source_url"])}</td></tr>' for row in flags)
    review = f'''<section class="page-heading"><div><div class="eyebrow">TRANSPARENCY IS PART OF THE PRODUCT</div><h1>Flagged for Review</h1><p>What is known. What is missing. Nothing filled in between.</p></div><span class="review-total">{len(flags)} open items</span></section><div class="data-banner"><div>{icon('shield')}Unconfirmed values are intentionally blank.</div><span class="research-badge">NOT BLOCKING PUBLICATION</span></div><div class="panel table-wrap research-table"><table><thead><tr><th>Item</th><th>Verified value</th><th>Reason / next verification</th><th>Official source</th></tr></thead><tbody>{rows}</tbody></table></div><div class="notice"><span>{icon('review')}</span><p>Specification checks and automated tests do not prove a live account connection. Source observations carry timestamps; model outputs and simulation assumptions are labeled separately.</p></div>'''
    fact_rows = ''.join(f'<tr><td>{escape(row["id"].replace("-"," "))}</td><td>{escape(row["fact"])}</td><td><span class="verification-tag">{escape(row["status"].replace("_"," "))}</span></td><td>{external(row["source_url"])}</td></tr>' for row in manifest["facts"])
    summary = f'''<section class="page-heading"><div><div class="eyebrow">TECHNICAL BRIEF · 22 NOVEMBER 2026</div><h1>Executive summary</h1><p>A focused research desk, with a clear line between evidence and execution.</p></div><a class="button secondary" href="https://github.com/kanlerxz87-cyber/Tradebot1/blob/main/EXECUTIVE_SUMMARY.md" target="_blank" rel="noopener noreferrer">Read the full brief ↗</a></section>
<section class="summary-intro panel"><div><span class="eyebrow">THE OBJECTIVE</span><h2>Five topics. Source-linked decisions.</h2><p>Collect and organize official Kalshi demo observations for gas prices, elections, culture, crypto and golf. Follow ≥10¢ movements, inspect depth, compare hypothetical strategies and retain tracked contracts through final settlement.</p></div><div class="summary-facts"><div><b>Evidence</b><span>Every market row links to its official source.</span></div><div><b>Separation</b><span>Published snapshots ≠ live feeds ≠ paper accounts ≠ demo execution.</span></div><div><b>Honesty</b><span>No verified ROI, causal news, live account balance or exchange-wide ranking is claimed.</span></div></div></section>
<div class="section-heading"><div><h2>What is delivered</h2><p>Software capability is distinct from verified deployment connectivity.</p></div></div><div class="delivery-grid"><article class="panel delivery-card">{icon('overview')}<h3>Public research dashboard</h3><p>Five topic subpages, grouped events, source timestamps, search, CSV export, time-window charts, depth and dual scrolling feeds.</p></article><article class="panel delivery-card">{icon('activity')}<h3>Demo-only service</h3><p>REST collection, authenticated WebSocket adapter, sequence recovery, SQLite history, SSE and protected V2 order routes. Not connected to an account here.</p></article><article class="panel delivery-card">{icon('portfolio')}<h3>Strategy laboratory</h3><p>Independent momentum and mean-reversion paper ledgers, exposure caps, final YES/NO settlement and gross-only analysis.</p></article></div>
<div class="section-heading"><div><h2>Official specification checks</h2><p>Read on {manifest['checked_on']}. Values and schemas are not inferred. Internal policy decisions are labeled.</p></div></div><div class="panel table-wrap research-table"><table><thead><tr><th>Area</th><th>Checked fact / explicit policy</th><th>Verification scope</th><th>Official source</th></tr></thead><tbody>{fact_rows}</tbody></table></div>
<div class="section-heading"><div><h2>Suggestions for the next research cycle</h2></div></div><div class="panel suggestions"><article><span>01</span><div><h3>Deploy the trusted stream service</h3><p>Use a continuously running host with demo-network access, a secret store and persistent storage. Never deploy private keys to Pages. {external('https://docs.kalshi.com/getting_started/quick_start_websockets','Streaming requirements')}</p></div></article><article><span>02</span><div><h3>Validate before calling a signal high ROI</h3><p>Use walk-forward cohorts, fee-aware fills, exposure limits and calibration by topic. Demo performance is not production evidence. {external('https://docs.kalshi.com/getting_started/demo_env','Demo limitations')}</p></div></article><article><span>03</span><div><h3>Add timestamped primary-source announcements</h3><p>Link official releases only with verified publication times. Annotate association separately from causation, with a source and confidence note. {external('https://docs.kalshi.com/api-reference/market/get-series-list','Settlement source metadata')}</p></div></article><article><span>04</span><div><h3>Reconcile the full account</h3><p>Join live and historical fills and positions, include subaccounts, distinguish deposits from P&amp;L, and compare actual fees with hypotheses. {external('https://docs.kalshi.com/getting_started/historical_data','Historical handoff')}</p></div></article></div><div class="notice"><span>{icon('shield')}</span><p>See the <a href="review/">Flagged for Review page</a> for unverified deployment and research items. No secret or manual account input was requested in this session.</p></div>'''
    return review, summary


def main():
    for topic in ("all", *TOPICS):
        path = DOCS / "index.html" if topic == "all" else DOCS / topic / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(shell(topic, TOPICS.get(topic, "Market overview"), dashboard(topic), topic != "all", True))
    path = DOCS / "portfolio/index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(shell("portfolio", "Portfolio & strategies", portfolio(), 1, True))
    manifest = json.loads((ROOT / "services/kalshi/verification.json").read_text())
    review, summary = research_pages(manifest)
    (DOCS / "review/index.html").write_text(shell("review", "Flagged for Review", review, 1))
    (DOCS / "executive-summary.html").write_text(shell("summary", "Executive summary", summary))
    (DOCS / "data/verification.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print("Generated 9 consistent, source-linked static pages.")


if __name__ == "__main__":
    main()
