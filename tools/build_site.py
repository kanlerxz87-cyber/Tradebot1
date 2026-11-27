#!/usr/bin/env python3
"""Generate the static parts of the site from the collected JSON.

Why a generator: GitHub Pages serves static files, and a table rendered only by JavaScript
cannot be verified by reading the HTML. Everything factual is therefore written into the HTML
(source link per row) and the JavaScript layer only adds live behaviour on top.

    python tools/build_site.py            # regenerate
    python tools/build_site.py --check    # fail if regeneration would change a file

Generated files
---------------
docs/desk/topics/*.html          full category pages
docs/desk/index.html             static market table between DATA markers
docs/desk/portfolio.html         static performance tables between DATA markers
docs/desk/verification.html      source table between DATA markers
docs/desk/flagged.html           flag rows between DATA markers
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "desk"
DATA = DOCS / "data"

NAV = [
    ("index.html", "Dashboard"),
    ("topics/gas-prices.html", "Gas"),
    ("topics/elections.html", "Elections"),
    ("topics/culture.html", "Culture"),
    ("topics/crypto.html", "Crypto"),
    ("topics/golf.html", "Golf"),
    ("portfolio.html", "Portfolio"),
    ("strategies.html", "Strategies"),
    ("api-reference.html", "API"),
    ("verification.html", "Verification"),
    ("repo-review.html", "Repo review"),
    ("flagged.html", "Flagged"),
    ("executive-summary.html", "Summary"),
]

TOPIC_DEFS = {
    "gas": {
        "label": "Gas prices",
        "slug": "gas-prices",
        "blurb": "US average retail gasoline markets. Kalshi's monthly US gas-price series is "
                 "struck in dollars-and-cents increments and settles on the AAA national average.",
        "match": "Primary category <code>Economics</code>; discovery categories "
                 "<code>Economics</code>, <code>Commodities</code>; tags <code>Oil and energy</code>, "
                 "<code>Oil &amp; Gas</code>; known series <code>KXAAAGASM</code>.",
        "sources": [
            ("Kalshi glossary — KXAAAGASM worked example", "https://docs.kalshi.com/getting_started/terms"),
            ("Get Series List — category filter", "https://docs.kalshi.com/api-reference/market/get-series-list"),
        ],
        "note": "Every market carries its own settlement rule text from the API "
                "(<code>rules_primary</code>), which names the AAA source and the exact strike date. "
                "That rule text is the authoritative resolution criterion, not this page.",
    },
    "elections": {
        "label": "Elections",
        "slug": "elections",
        "blurb": "Elections, nominations, leadership races, seat control and ballot measures — "
                 "US and international.",
        "match": "Primary category <code>Elections</code> (subcategories are exposed as tags such as "
                 "<code>US Elections</code>, <code>Senate</code>, <code>Governor</code>).",
        "sources": [
            ("Kalshi glossary — category and tag semantics", "https://docs.kalshi.com/getting_started/terms"),
            ("Get Tags for Series Categories — official tag map", "https://docs.kalshi.com/api-reference/search/get-tags-for-series-categories"),
        ],
        "note": "Elections contracts are mutually exclusive within a race, so only one strike of an "
                "event resolves YES. The dashboard shows per-market prices, which is what the book quotes.",
    },
    "culture": {
        "label": "Culture",
        "slug": "culture",
        "blurb": "Awards, music, film, television, video games and other cultural moments.",
        "match": "There is <b>no</b> official <code>Culture</code> category. This page maps the brief's "
                 "culture topic to the official <code>Entertainment</code> category, plus "
                 "<code>Social</code> when a series carries it.",
        "sources": [
            ("Official category → tag map (no Culture entry)", "https://docs.kalshi.com/api-reference/search/get-tags-for-series-categories"),
            ("Kalshi glossary", "https://docs.kalshi.com/getting_started/terms"),
        ],
        "note": "This is the one topic where the mapping is an editorial decision rather than an "
                "official label; it is listed on the Flagged for Review page as F3.",
    },
    "crypto": {
        "label": "Crypto",
        "slug": "crypto",
        "blurb": "Bitcoin, Ethereum, Solana and other digital-asset price ladders and event markets.",
        "match": "Primary category <code>Crypto</code>; tags include <code>BTC</code>, <code>ETH</code>, "
                 "<code>SOL</code>, <code>Hourly</code>, <code>15 min</code>.",
        "sources": [
            ("Get Series List — Crypto category", "https://docs.kalshi.com/api-reference/market/get-series-list"),
            ("Get Tags for Series Categories", "https://docs.kalshi.com/api-reference/search/get-tags-for-series-categories"),
        ],
        "note": "Many crypto series settle on CF Benchmarks indices; the settlement source for each "
                "series is listed in the series table below and in the contract terms PDF.",
    },
    "golf": {
        "label": "Golf",
        "slug": "golf",
        "blurb": "PGA Tour, LIV and Ryder Cup markets — round leaders, achievements and outright winners.",
        "match": "Category <code>Sports</code> with the official <code>Golf</code> subcategory tag.",
        "sources": [
            ("Official tag map — Golf is a Sports tag", "https://docs.kalshi.com/api-reference/search/get-tags-for-series-categories"),
            ("Get Series List — tags filter", "https://docs.kalshi.com/api-reference/market/get-series-list"),
        ],
        "note": "Golf markets often close early when the outcome is determined; the close time shown is "
                "the exchange's latest close, not the tee time.",
    },
}

TOPIC_ORDER = ["gas", "elections", "culture", "crypto", "golf"]


# --------------------------------------------------------------------- helpers
def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def read_json(name: str, default: Any = None) -> Any:
    path = DATA / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def usd(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"${number:,.{digits}f}"


def cents(value: Any) -> str:
    try:
        return f"{round(float(value) * 100)}¢"
    except (TypeError, ValueError):
        return "—"


def count(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "—"


def signed(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if number > 0 else ("−" if number < 0 else "")
    return f"{sign}{abs(number):,.{digits}f}"


def stamp(iso: str | None) -> str:
    if not iso:
        return "never"
    return esc(str(iso).replace("T", " ").replace("Z", " UTC"))


def is_demo_snapshot(latest: dict[str, Any] | None) -> bool:
    """Accept only snapshots explicitly sourced from an official demo REST root."""
    if not isinstance(latest, dict) or latest.get("data_env") != "demo":
        return False
    return latest.get("rest_base", "").rstrip("/") in {
        "https://external-api.demo.kalshi.co/trade-api/v2",
        "https://demo-api.kalshi.co/trade-api/v2",
    }


def head(title: str, prefix: str, active: str) -> str:
    nav = []
    for href, label in NAV:
        full = prefix + href
        cls = ' class="active"' if href == active else ""
        nav.append(f'<a{cls} href="{full}">{esc(label)}</a>')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="Kalshi market dashboard for gas prices, elections, culture, crypto and golf — verified against official Kalshi documentation.">
<link rel="stylesheet" href="{prefix}assets/css/site.css">
</head>
<body>
<header class="top">
  <div class="top-inner">
    <div class="brand"><span class="dot"></span><span>Kalshi Trader<br><small>demo / paper research desk</small></span></div>
    <nav class="main">
      {"".join(nav)}
    </nav>
  </div>
</header>
<main class="wrap">
"""


def foot(prefix: str, generated_at: str | None) -> str:
    return f"""
  <footer class="site">
    <span>Data collected {stamp(generated_at)}.</span>
    <span>·</span><a href="{prefix}verification.html">Sources &amp; verification</a>
    <span>·</span><a href="{prefix}flagged.html">Flagged for review</a>
    <span>·</span><a href="{prefix}requirements.html">Requirements</a>
    <span>·</span><a href="{prefix}api-reference.html">API reference</a>
    <span>·</span><span>Not investment advice. Demo/paper only.</span>
  </footer>
</main>
</body>
</html>
"""


def replace_between(text: str, start: str, end: str, body: str) -> str:
    if start not in text or end not in text:
        raise SystemExit(f"markers not found: {start!r} / {end!r}")
    pre, rest = text.split(start, 1)
    _, post = rest.split(end, 1)
    return f"{pre}{start}\n{body}\n{end}{post}"


def empty_row(cols: int, message: str) -> str:
    return f'<tr><td colspan="{cols}"><div class="empty">{esc(message)}</div></td></tr>'


# ---------------------------------------------------------------------- tables
def market_table(markets: Iterable[dict[str, Any]], *, limit: int = 60) -> str:
    rows = list(markets)[:limit]
    if not rows:
        return f'<div class="table-wrap"><table><tbody>{empty_row(10, "No open markets in the current snapshot for this topic.")}</tbody></table></div>'
    body = []
    for market in rows:
        title = market.get("title") or market.get("ticker")
        body.append(
            f"""<tr>
  <td><span class="title">{esc(title)}</span><div class="meta mono">{esc(market.get("ticker"))}</div></td>
  <td>{cents(market.get("price"))}</td>
  <td>{cents(market.get("yes_bid"))} / {cents(market.get("yes_ask"))}</td>
  <td>{cents(market.get("spread"))}</td>
  <td class="num">{count(market.get("volume_24h"))}</td>
  <td class="num">{count(market.get("open_interest"))}</td>
  <td class="num">{count(market.get("top_book_contracts"))}</td>
  <td class="num">{usd(market.get("notional_24h_est"), 0)}</td>
  <td class="meta">{esc((market.get("close_time") or "—")[:16].replace("T", " "))}</td>
  <td><a href="{esc(market.get("api_url"))}" target="_blank" rel="noopener">API</a> ·
      <a href="{esc(market.get("series_page_url"))}" target="_blank" rel="noopener">Kalshi</a></td>
</tr>"""
        )
    return f"""<div class="table-wrap"><table>
<thead><tr>
<th>Market</th><th>Price</th><th>YES bid / ask</th><th>Spread</th><th class="num">24h vol</th>
<th class="num">Open interest</th><th class="num">At best price</th><th class="num">Est. 24h $</th>
<th>Closes</th><th>Source</th>
</tr></thead>
<tbody>{"".join(body)}</tbody></table></div>"""


def event_table(events: Iterable[dict[str, Any]], *, limit: int = 20) -> str:
    rows = list(events)[:limit]
    if not rows:
        return f'<div class="table-wrap"><table><tbody>{empty_row(6, "No open events in the current snapshot.")}</tbody></table></div>'
    body = "".join(
        f"""<tr>
  <td><span class="title">{esc(event.get("title"))}</span><div class="meta mono">{esc(event.get("event_ticker"))}</div></td>
  <td class="num">{count(event.get("markets_count"))}</td>
  <td class="num">{usd(event.get("notional_24h_est"), 0)}</td>
  <td class="num">{count(event.get("open_interest"))}</td>
  <td class="meta">{esc((event.get("close_time") or "—")[:16].replace("T", " "))}</td>
  <td><a href="{esc(event.get("series_page_url"))}" target="_blank" rel="noopener">Kalshi</a></td>
</tr>"""
        for event in rows
    )
    return f"""<div class="table-wrap" style="max-height:380px"><table>
<thead><tr><th>Event</th><th class="num">Markets</th><th class="num">Est. 24h $</th><th class="num">Open interest</th><th>Closes</th><th>Source</th></tr></thead>
<tbody>{body}</tbody></table></div>"""


def resolved_table(items: Iterable[dict[str, Any]], *, limit: int = 60) -> str:
    rows = list(items)[:limit]
    if not rows:
        return f'<div class="table-wrap"><table><tbody>{empty_row(5, "No settled markets recorded yet — resolution tracking starts with the first collection cycle.")}</tbody></table></div>'
    body = "".join(
        f"""<tr>
  <td><span class="title">{esc(item.get("title"))}</span><div class="meta mono">{esc(item.get("ticker"))}</div></td>
  <td><span class="chip {'ok' if item.get("resolution") == 'YES' else 'bad'}">{esc(item.get("resolution") or "—")}</span></td>
  <td class="meta">{esc((item.get("close_time") or item.get("settled_ts") or "—")[:16].replace("T", " "))}</td>
  <td class="meta">{esc(item.get("result"))}</td>
  <td><a href="{esc(item.get("api_url") or item.get("source"))}" target="_blank" rel="noopener">verify</a></td>
</tr>"""
        for item in rows
    )
    return f"""<div class="table-wrap" style="max-height:340px"><table>
<thead><tr><th>Market</th><th>Outcome</th><th>Closed</th><th>result field</th><th>Source</th></tr></thead>
<tbody>{body}</tbody></table></div>"""


def series_table(series: Iterable[dict[str, Any]], *, limit: int = 25) -> str:
    rows = sorted(
        [s for s in series if s.get("ticker")],
        key=lambda s: (s.get("volume") or 0),
        reverse=True,
    )[:limit]
    if not rows:
        return f'<div class="table-wrap"><table><tbody>{empty_row(6, "Series catalogue not built yet. The next collection cycle populates it.")}</tbody></table></div>'
    body = "".join(
        f"""<tr>
  <td class="ticker">{esc(row.get("ticker"))}</td>
  <td>{esc(row.get("title"))}</td>
  <td class="meta">{esc(", ".join(row.get("categories") or [row.get("category") or ""]))}</td>
  <td class="meta">{esc(", ".join(row.get("tags") or []) or "—")}</td>
  <td class="num">{count(row.get("volume"))}</td>
  <td>{f'<a href="{esc(row.get("contract_terms_url"))}" target="_blank" rel="noopener">terms</a>' if row.get("contract_terms_url") else "—"}</td>
  <td><a href="https://external-api.demo.kalshi.co/trade-api/v2/series/{esc(row.get('ticker'))}" target="_blank" rel="noopener">API</a></td>
</tr>"""
        for row in rows
    )
    return f"""<div class="table-wrap" style="max-height:420px"><table>
<thead><tr><th>Series</th><th>Title</th><th>Official categories</th><th>Tags</th><th class="num">Lifetime contracts</th><th>Terms</th><th>Source</th></tr></thead>
<tbody>{body}</tbody></table></div>"""


# ----------------------------------------------------------------- topic pages
def build_topic_page(topic_id: str, latest: dict[str, Any], series_catalog: dict[str, Any]) -> str:
    meta = TOPIC_DEFS[topic_id]
    demo_ok = is_demo_snapshot(latest)
    if not demo_ok:
        latest = {}
        series_catalog = {}
    block = (latest.get("topics") or {}).get(topic_id) or {}
    markets = block.get("markets") or []
    events = block.get("events") or []
    series = [s for s in (series_catalog.get("series") or {}).values() if s.get("topic") == topic_id]
    # A resolution row written by an older collector carried topic=None; fall back to the
    # series taxonomy that is already in the payload so the row cannot vanish from its topic.
    series_for_topic = {s.get("ticker") for s in series}
    resolved = [
        r
        for r in (latest.get("resolved") or [])
        if r.get("topic") == topic_id
        or (not r.get("topic") and r.get("series_ticker") in series_for_topic)
    ]
    series_total = (series_catalog.get("totals") or {}).get(topic_id, len(series))
    generated = latest.get("generated_at")

    sources = "".join(
        f'<li><a href="{esc(url)}" target="_blank" rel="noopener">{esc(label)}</a></li>' for label, url in meta["sources"]
    )

    page = head(f"{meta['label']} — Kalshi Trader", "../", f"topics/{meta['slug']}.html")
    page += f"""
  <h1 class="page-title">{esc(meta['label'])}</h1>
  <p class="page-sub">{esc(meta['blurb'])}</p>
  {'' if demo_ok else '<div class="banner warn"><b>Demo data withheld.</b><span class="grow">The committed snapshot is not verified as Kalshi demo data. This page will populate after a successful demo-only collection cycle.</span></div>'}

  <div class="grid kpi">
    <div class="card"><span class="label">Markets tracked</span><span class="value">{count(block.get('markets_count'))}</span><span class="foot">top {count(len(markets))} kept by estimated notional</span></div>
    <div class="card"><span class="label">Series scanned</span><span class="value">{count(block.get('series_count'))}</span><span class="foot">{count(series_total)} series in the catalogue for this topic</span></div>
    <div class="card"><span class="label">Est. 24h notional</span><span class="value">{usd(block.get('notional_24h_est'), 0)}</span><span class="foot">volume × price, derived</span></div>
    <div class="card"><span class="label">Open interest</span><span class="value">{count(block.get('open_interest'))}</span><span class="foot">contracts, exchange-reported</span></div>
  </div>

  <section class="section">
    <h2>How this topic is defined</h2>
    <p class="hint">{meta['match']}</p>
    <div class="card tight">
      <div class="note-box">{meta['note']}</div>
      <p class="small" style="margin:10px 0 4px">Official sources for this definition:</p>
      <ul class="clean">{sources}</ul>
    </div>
  </section>

  <section class="section">
    <h2>Markets</h2>
    <p class="hint">Snapshot {stamp(generated)}. Price is the YES midpoint of the best bid and ask.
      “At best price” is the visible contract count resting at the top of the book; — means Kalshi did not report it.</p>
    {market_table(markets)}
  </section>

  <section class="section">
    <h2>Highest-dollar events in this topic</h2>
    <p class="hint">Ranked by estimated 24h traded notional across the events' open markets.</p>
    {event_table(events)}
  </section>

  <section class="section">
    <h2>Resolved — YES or NO</h2>
    <p class="hint">Markets tracked until they settled. The outcome is the exchange's own
      <code>result</code> field; the link re-reads the market from the API so the value can be checked.</p>
    {resolved_table(resolved)}
  </section>

  <section class="section">
    <h2>Series in this topic</h2>
    <p class="hint">The official series objects this topic is built from, with their published categories and tags.</p>
    {series_table(series)}
  </section>
"""
    page += foot("../", generated)
    return page


# ------------------------------------------------------------- other injections
def build_index_static(latest: dict[str, Any]) -> str:
    if not is_demo_snapshot(latest):
        return (
            '<div class="banner warn"><b>Demo data withheld.</b><span class="grow">'
            'The committed snapshot is not verified as Kalshi demo data. This table will populate '
            'after a successful demo-only collection cycle.</span></div>'
        )
    markets = []
    for topic_id in TOPIC_ORDER:
        block = (latest.get("topics") or {}).get(topic_id) or {}
        for market in block.get("markets") or []:
            markets.append({**market, "topic": topic_id})
    markets.sort(key=lambda m: m.get("notional_24h_est") or 0, reverse=True)
    generated = latest.get("generated_at")
    if not markets:
        return (
            '<div class="card tight"><div class="empty">No snapshot has been collected yet. '
            "The scheduled collector writes <code>docs/desk/data/latest.json</code>; this block renders "
            "server-side as soon as that file exists.</div></div>"
        )
    rows = []
    for market in markets[:45]:
        rows.append(
            f"""<tr>
  <td><span class="title">{esc(market.get("title"))}</span><div class="meta mono">{esc(market.get("ticker"))}</div></td>
  <td><span class="chip {esc(market.get('topic'))}">{esc(TOPIC_DEFS[market['topic']]['label'])}</span></td>
  <td class="num">{cents(market.get("price"))}</td>
  <td class="num">{cents(market.get("yes_bid"))} / {cents(market.get("yes_ask"))}</td>
  <td class="num">{count(market.get("volume_24h"))}</td>
  <td class="num">{count(market.get("open_interest"))}</td>
  <td class="num">{usd(market.get("notional_24h_est"), 0)}</td>
  <td><a href="{esc(market.get("api_url"))}" target="_blank" rel="noopener">API</a> ·
      <a href="{esc(market.get("series_page_url"))}" target="_blank" rel="noopener">Kalshi</a></td>
</tr>"""
        )
    return f"""<p class="hint" style="margin-top:10px">Server-rendered from the committed snapshot ({stamp(generated)}) so the data is readable without JavaScript.</p>
<div class="table-wrap"><table>
<thead><tr><th>Market</th><th>Topic</th><th class="num">Price</th><th class="num">YES bid / ask</th>
<th class="num">24h vol</th><th class="num">Open interest</th><th class="num">Est. 24h $</th><th>Source</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>"""


def build_portfolio_static(paper: dict[str, Any], latest: dict[str, Any]) -> str:
    if not is_demo_snapshot(latest):
        return (
            '<div class="banner warn"><b>Paper history withheld.</b><span class="grow">'
            'The current market snapshot is not verified as Kalshi demo data, so its simulated '
            'performance is not combined with a demo ledger.</span></div>'
        )
    headline = (paper or {}).get("headline") or {}
    summary = (paper or {}).get("summary") or {}
    trades = (paper or {}).get("trades") or []
    # paper.json is written without the open-position rows, while latest.json carries them under
    # `paper`. Without this fallback the page prints "12 positions" in the headline and
    # "No open positions." two lines below it, from the same book.
    positions = (paper or {}).get("open_positions") or (latest or {}).get("paper", {}).get("open_positions") or []
    if not headline:
        return '<div class="card"><div class="empty">No paper ledger yet.</div></div>'

    def metric_rows() -> str:
        items = [
            ("Closed trades", count(summary.get("trades"))),
            ("Wins / losses / flat", f'{count(summary.get("wins"))} / {count(summary.get("losses"))} / {count(summary.get("flat"))}'),
            ("Win rate", f'{summary.get("win_rate_pct", "—")}%'),
            ("Gross win / gross loss", f'{usd(summary.get("gross_win"))} / {usd(summary.get("gross_loss"))}'),
            ("Profit factor", summary.get("profit_factor") if summary.get("profit_factor") is not None else "n/a"),
            ("Expectancy per trade", usd(summary.get("expectancy"))),
            ("Average win / average loss", f'{usd(summary.get("avg_win"))} / {usd(summary.get("avg_loss"))}'),
            ("Fees paid", usd(summary.get("fees_paid"))),
            ("Average hold", f'{summary.get("avg_hold_hours", "—")} h'),
            ("Max drawdown", f'{usd(summary.get("max_drawdown"))} ({summary.get("max_drawdown_pct", "—")}%)'),
        ]
        return "".join(f"<tr><td>{esc(k)}</td><td class=\"num\">{esc(v)}</td></tr>" for k, v in items)

    def group_table(rows: list[dict[str, Any]], label: str) -> str:
        if not rows:
            return f'<div class="card"><h3>{esc(label)}</h3><div class="empty">No closed trades yet.</div></div>'
        body = "".join(
            f"""<tr><td>{esc(row.get("label"))}</td><td class="num">{count(row.get("trades"))}</td>
<td class="num">{row.get("win_rate_pct")}%</td><td class="num">{usd(row.get("pnl"))}</td>
<td class="num">{row.get("avg_roi_pct")}%</td><td class="num">{usd(row.get("fees"))}</td></tr>"""
            for row in rows
        )
        return f"""<div class="card"><h3>{esc(label)}</h3>
<div class="table-wrap" style="max-height:260px"><table>
<thead><tr><th>Group</th><th class="num">Trades</th><th class="num">Win %</th><th class="num">P&L</th><th class="num">Avg ROI</th><th class="num">Fees</th></tr></thead>
<tbody>{body}</tbody></table></div></div>"""

    trade_rows = "".join(
        f"""<tr>
  <td class="meta">{esc((t.get("exit_iso") or "")[:16].replace("T", " "))}</td>
  <td><span class="title">{esc(t.get("title"))}</span><div class="meta mono">{esc(t.get("ticker"))}</div></td>
  <td><span class="chip {esc(t.get("topic"))}">{esc(TOPIC_DEFS.get(t.get("topic") or "", {}).get("label", t.get("topic") or "—"))}</span></td>
  <td>{esc(t.get("strategy"))}</td>
  <td class="center">{esc((t.get("side") or "").upper())}</td>
  <td class="num">{count(t.get("contracts"))}</td>
  <td class="num">{cents(t.get("entry_price"))} → {cents(t.get("exit_price"))}</td>
  <td class="num">{usd(t.get("fees"))}</td>
  <td class="num {'up' if (t.get('pnl') or 0) > 0 else ('down' if (t.get('pnl') or 0) < 0 else '')}">{signed(t.get("pnl"))}</td>
  <td class="num">{signed(t.get("roi_pct"), 1)}%</td>
  <td class="meta">{esc((t.get("exit_reason") or "")[:46])}</td>
</tr>"""
        for t in trades[:60]
    )

    return f"""
<div class="grid kpi">
  <div class="card"><span class="label">Equity</span><span class="value">{usd(headline.get('equity'))}</span><span class="foot">start {usd(headline.get('bankroll_start'))}</span></div>
  <div class="card"><span class="label">Total P&L</span><span class="value {'up' if (headline.get('total_pnl') or 0) >= 0 else 'down'}">{signed(headline.get('total_pnl'))}</span><span class="foot">{signed(headline.get('roi_pct'), 2)}% on bankroll</span></div>
  <div class="card"><span class="label">Realised</span><span class="value">{signed(headline.get('realized_pnl'))}</span><span class="foot">unrealised {signed(headline.get('unrealized_pnl'))}</span></div>
  <div class="card"><span class="label">Cash / open</span><span class="value">{usd(headline.get('cash'))}</span><span class="foot">{count(headline.get('open_positions'))} positions</span></div>
</div>

<div class="banner {'warn' if not headline.get('fee_verified') else 'ok'}" style="margin-top:14px">
  <b>Fee model:</b>&nbsp;<span class="grow">{esc(headline.get('fee_model'))} —
  {"verified against an official Kalshi schedule." if headline.get('fee_verified') else
   "0.07 × contracts × price × (1 − price) rounded up to the cent, per the published Kalshi fee schedule (effective 2026-07-07). The round-up can only overstate a fee, never understate it. The published per-series multiplier is applied for the rows of the schedule's Non-Standard Fees table that are unambiguous in the PDF; the remaining rows fall back to 1 (flag F1)."}</span>
</div>

<div class="grid two" style="margin-top:16px">
  <div class="card"><h3>Ledger metrics</h3>
    <div class="table-wrap" style="max-height:none"><table><tbody>{metric_rows()}</tbody></table></div>
  </div>
  <div class="card"><h3>Open positions</h3>
    {open_positions_table(positions)}
  </div>
</div>

<div class="grid two" style="margin-top:16px">
  {group_table(paper.get("by_strategy") or [], "By strategy")}
  {group_table(paper.get("by_topic") or [], "By topic")}
</div>
<div class="grid two" style="margin-top:16px">
  {group_table(paper.get("by_price_band") or [], "By entry price band")}
  {group_table(paper.get("by_exit_reason") or [], "By exit reason")}
</div>

<div class="section">
  <h2>Trade ledger</h2>
  <p class="hint">Most recent {min(len(trades), 60)} closed trades. Every entry is reproducible from the
    recorded entry/exit prices, contract count and fee model.</p>
  <div class="table-wrap" style="max-height:520px"><table>
  <thead><tr><th>Closed</th><th>Market</th><th>Topic</th><th>Strategy</th><th class="center">Side</th>
  <th class="num">Contracts</th><th class="num">Entry → exit</th><th class="num">Fees</th><th class="num">P&L</th>
  <th class="num">ROI</th><th>Exit reason</th></tr></thead>
  <tbody>{trade_rows or empty_row(11, "No closed trades yet.")}</tbody></table></div>
</div>
"""


def open_positions_table(positions: list[dict[str, Any]]) -> str:
    if not positions:
        return '<div class="empty">No open positions.</div>'
    body = "".join(
        f"""<tr>
  <td><span class="title">{esc(p.get("title"))}</span><div class="meta mono">{esc(p.get("ticker"))}</div></td>
  <td>{esc(p.get("strategy"))}</td>
  <td class="center">{esc((p.get("side") or "").upper())}</td>
  <td class="num">{count(p.get("contracts"))}</td>
  <td class="num">{cents(p.get("entry_price"))} → {cents(p.get("last_mark"))}</td>
  <td><a href="{esc(p.get("api_url"))}" target="_blank" rel="noopener">API</a></td>
</tr>"""
        for p in positions[:20]
    )
    return f"""<div class="table-wrap" style="max-height:340px"><table>
<thead><tr><th>Position</th><th>Strategy</th><th class="center">Side</th><th class="num">Contracts</th><th class="num">Entry → mark</th><th>Source</th></tr></thead>
<tbody>{body}</tbody></table></div>"""


def build_sources_table(sources: dict[str, Any]) -> str:
    rows = sources.get("sources") or []
    body = "".join(
        f"""<tr>
  <td class="ticker">{esc(row.get("id"))}</td>
  <td>{esc(row.get("claim"))}</td>
  <td class="meta">{esc(row.get("publisher"))}</td>
  <td><a href="{esc(row.get("url"))}" target="_blank" rel="noopener">official source</a></td>
  <td class="center">{'<span class="chip ok">verified</span>' if row.get("verified") else '<span class="chip warn">unverified</span>'}</td>
</tr>"""
        for row in rows
    )
    return f"""<div class="table-wrap"><table>
<thead><tr><th>ID</th><th>Claim</th><th>Publisher</th><th>Link</th><th class="center">Status</th></tr></thead>
<tbody>{body}</tbody></table></div>"""


def build_flags_table(flags: dict[str, Any]) -> str:
    rows = flags.get("flags") or []
    severity_chip = {"warn": "warn", "info": "", "blocker": "bad"}
    body = "".join(
        f"""<tr id="{esc(row.get('id'))}">
  <td class="ticker">{esc(row.get('id'))}</td>
  <td><span class="chip {severity_chip.get(row.get('severity'), '')}">{esc(row.get('severity'))}</span></td>
  <td>
    <b>{esc(row.get('title'))}</b>
    <div class="meta" style="margin-top:4px">{esc(row.get('detail'))}</div>
    <div class="small" style="margin-top:6px"><b>Handling:</b> {esc(row.get('handling'))}</div>
    <div class="small" style="margin-top:4px"><b>Would be cleared by:</b> {esc(row.get('resolve'))}</div>
    <div class="links small" style="margin-top:6px">{" · ".join(f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(url.split("//")[-1][:52])}</a>' for url in row.get("sources") or [])}</div>
  </td>
</tr>"""
        for row in rows
    )
    return f"""<div class="table-wrap"><table>
<thead><tr><th>ID</th><th>Severity</th><th>Item</th></tr></thead>
<tbody>{body}</tbody></table></div>"""


# ------------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify generated files are current")
    args = parser.parse_args(argv)

    latest = read_json("latest.json", {}) or {}
    paper = read_json("paper.json", {}) or {}
    catalog = read_json("series.json", {}) or {}
    sources = read_json("sources.json", {}) or {}
    flags = read_json("flags.json", {}) or {}

    outputs: dict[Path, str] = {}
    (DOCS / "topics").mkdir(parents=True, exist_ok=True)
    for topic_id in TOPIC_ORDER:
        path = DOCS / "topics" / f"{TOPIC_DEFS[topic_id]['slug']}.html"
        outputs[path] = build_topic_page(topic_id, latest, catalog)

    # injection pages
    injections = {
        DOCS / "index.html": build_index_static(latest),
        DOCS / "portfolio.html": build_portfolio_static(paper, latest),
        DOCS / "verification.html": build_sources_table(sources),
        DOCS / "flagged.html": build_flags_table(flags),
    }
    changed, unchanged = [], []
    for path, body in outputs.items():
        new = body
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        if old != new:
            path.write_text(new, encoding="utf-8")
            changed.append(path)
        else:
            unchanged.append(path)

    for path, body in injections.items():
        if not path.exists():
            print(f"skip (missing template): {path.relative_to(ROOT)}")
            continue
        old = path.read_text(encoding="utf-8")
        new = replace_between(old, "<!-- DATA:START -->", "<!-- DATA:END -->", body)
        if new != old:
            path.write_text(new, encoding="utf-8")
            changed.append(path)
        else:
            unchanged.append(path)

    if args.check:
        if changed:
            print("Generated output is stale:", file=sys.stderr)
            for path in changed:
                print(" -", path.relative_to(ROOT), file=sys.stderr)
            return 1
        print("generated output is current")
        return 0

    print(f"wrote {len(changed)} file(s); {len(unchanged)} already current")
    for path in changed:
        print(" -", path.relative_to(ROOT))
    print("generated at", datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
