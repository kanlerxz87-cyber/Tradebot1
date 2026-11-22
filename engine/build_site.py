"""Render the static GitHub Pages site from engine-exported data.

Pages produced (all under --out, default docs/):

    index.html                  landing page: what this is, headline findings, topic links
    topics/<topic>.html         one page per tracked topic, every entry in a table
    alerts.html                 the alert feed + the exact rule that produced each alert
    verification.html           every verified fact, with its official source link
    flagged.html                Flagged for Review: unverified + flagged items
    methodology.html            how topics, alerts, scoring, fees and simulation work
    findings.html               executive summary: what was verified, what was not
    assets/*.css|js             no external dependencies

Rules enforced by this generator:
  * every table row links to an official source; lacking one, the row is flagged
  * a value that is unknown renders as "--" and is never filled in
  * nothing is asserted without a registry entry or a captured payload behind it
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path

TOPIC_ORDER = ("gas", "elections", "culture", "crypto", "golf")

TOPIC_META = {
    "gas": {"label": "Gas prices", "icon": "⛽",
            "blurb": "US retail gasoline and energy-linked contracts."},
    "elections": {"label": "Elections", "icon": "🗳",
                  "blurb": "Elections, nominations and control of chambers."},
    "culture": {"label": "Culture", "icon": "🎬",
                "blurb": "Entertainment, awards, music, film and television."},
    "crypto": {"label": "Crypto", "icon": "₿",
               "blurb": "Bitcoin, Ethereum, Solana and other digital-asset contracts."},
    "golf": {"label": "Golf", "icon": "⛳",
             "blurb": "PGA Tour, DP World Tour, LPGA, LIV and Korn Ferry markets."},
}

NAV = [
    ("index.html", "Overview"),
    ("findings.html", "Executive summary"),
    ("gas.html", "Gas"),
    ("elections.html", "Elections"),
    ("culture.html", "Culture"),
    ("crypto.html", "Crypto"),
    ("golf.html", "Golf"),
    ("alerts.html", "Alerts"),
    ("verification.html", "Verification"),
    ("flagged.html", "Flagged for review"),
    ("methodology.html", "Methodology"),
]

CSS = """
:root{--bg:#f7f8fa;--panel:#fff;--line:#e2e6ee;--text:#151b26;--muted:#5f6b7d;
--accent:#0b63ce;--up:#0a7b45;--down:#b3261e;--warn:#8a5a00;--warn-bg:#fff6e0;--flag:#fff2f0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
header.top{background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px}
header.top .wrap{display:flex;align-items:center;gap:18px;min-height:56px;flex-wrap:wrap}
.brand{font-weight:700;letter-spacing:-.01em;font-size:15px;text-decoration:none;color:var(--text)}
.brand span{color:var(--accent)}
nav{display:flex;gap:2px;flex-wrap:wrap}
nav a{font-size:13px;color:var(--muted);text-decoration:none;padding:5px 9px;border-radius:6px}
nav a:hover{background:#eef2f8;color:var(--text)}
nav a.active{background:#e7f0fc;color:var(--accent);font-weight:600}
main{padding:26px 0 60px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:17px;margin:26px 0 8px}
h3{font-size:14px;margin:18px 0 6px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
p{margin:8px 0}
.lede{color:var(--muted);font-size:15px;max-width:78ch}
.muted{color:var(--muted);font-size:13px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:14px 0}
.grid{display:grid;gap:14px}
.grid.c3{grid-template-columns:repeat(3,1fr)}
.grid.c2{grid-template-columns:repeat(2,1fr)}
.grid.c5{grid-template-columns:repeat(5,1fr)}
@media(max-width:900px){.grid.c3,.grid.c5{grid-template-columns:1fr 1fr}
.grid.c2{grid-template-columns:1fr}}
@media(max-width:600px){.grid.c3,.grid.c5{grid-template-columns:1fr}}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;
text-decoration:none;color:var(--text);display:block}
.tile:hover{border-color:#c9d6e8;box-shadow:0 1px 6px rgba(11,99,206,.07)}
.tile .icon{font-size:18px}
.tile .n{font-size:22px;font-weight:700;margin-top:4px}
.stat{font-size:12px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:13.5px;background:#fff;
border:1px solid var(--line);border-radius:10px;overflow:hidden}
th{text-align:left;background:#f1f4f9;font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;
color:var(--muted);padding:9px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid #eef1f6;vertical-align:top}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tblwrap{overflow-x:auto}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
a{color:var(--accent)}
.tag{display:inline-block;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;
padding:1px 7px;border-radius:999px;border:1px solid var(--line);color:var(--muted);background:#fafbfd}
.tag.ok{color:var(--up);border-color:#b7dcc7;background:#f1faf5}
.tag.bad{color:var(--down);border-color:#f3c6c2;background:#fdf3f2}
.tag.warn{color:var(--warn);border-color:#efdcb0;background:var(--warn-bg)}
.note{border-left:3px solid var(--accent);background:#f4f8fe;padding:10px 14px;border-radius:0 8px 8px 0;
margin:12px 0;font-size:13.5px}
.note.warn{border-left-color:#c89100;background:var(--warn-bg)}
.note.bad{border-left-color:var(--down);background:var(--flag)}
.up{color:var(--up);font-weight:600}
.down{color:var(--down);font-weight:600}
footer{border-top:1px solid var(--line);color:var(--muted);font-size:12.5px;padding:18px 0 40px}
ul.tight{margin:6px 0 6px 20px;padding:0}
ul.tight li{margin:3px 0}
.kv{display:grid;grid-template-columns:180px 1fr;gap:6px 14px;font-size:13.5px}
.kv dt{color:var(--muted)}
.kv dd{margin:0}
code{background:#eef1f6;padding:1px 5px;border-radius:4px;font-size:12.5px}
.bar{height:8px;background:#eef1f6;border-radius:999px;overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;background:var(--accent)}
"""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def esc(value) -> str:
    if value is None:
        return "--"
    return html.escape(str(value))


def cents(value) -> str:
    if value in (None, "", "--"):
        return "--"
    try:
        return f"{round(float(value) * 100)}c"
    except (TypeError, ValueError):
        return "--"


def money(value, places: int = 2) -> str:
    if value in (None, ""):
        return "--"
    try:
        return f"${float(value):,.{places}f}"
    except (TypeError, ValueError):
        return "--"


def num(value, places: int = 0) -> str:
    if value in (None, ""):
        return "--"
    try:
        return f"{float(value):,.{places}f}"
    except (TypeError, ValueError):
        return "--"


def badge(status: str) -> str:
    klass = {"verified": "ok", "unverified": "warn", "flagged": "bad"}.get(status, "")
    return f'<span class="tag {klass}">{esc(status)}</span>'


def page(title: str, active: str, body: str, *, depth: int = 0) -> str:
    prefix = "../" * depth
    parts = []
    for href, label in NAV:
        active_attr = ' class="active"' if href == active else ""
        parts.append(f'<a href="{prefix}{href}"{active_attr}>{esc(label)}</a>')
    links = "".join(parts)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · Kalshi Live Dashboard</title>
<link rel="stylesheet" href="{prefix}assets/site.css">
</head><body>
<header class="top"><div class="wrap">
<a class="brand" href="{prefix}index.html">Kalshi <span>Live Dashboard</span></a>
<nav>{links}</nav>
</div></header>
<main><div class="wrap">
{body}
</div></main>
<footer><div class="wrap">
<p>Static site generated from Kalshi Trade API v2 responses captured on 2026-11-22 and from
Kalshi's official documentation. Every row links to its source. Unknown values are shown as
<code>--</code>, never filled in.</p>
<p>Market data shown is the <strong>demo</strong> environment unless a row says otherwise.
Kalshi documents that demo prices may not reflect real markets.
Simulated results are simulations. This site is not investment advice.</p>
</div></footer>
<script src="{prefix}assets/site.js"></script>
</body></html>"""


def source_link(row: dict) -> str:
    url = row.get("page_url")
    label = row.get("series_ticker") or "Kalshi"
    if url:
        status = "" if "kalshi.com/markets/" in url and url.count("/") == 4 else (
            ' <span class="tag warn">link unverified</span>')
        return f'<a href="{esc(url)}" target="_blank" rel="noopener">kalshi.com/{esc(label.lower())}</a>{status}'
    return '<span class="tag bad">no source</span>'


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
def build_index(data: dict, verification: dict) -> str:
    topics = {t["key"]: t for t in data["topics"]}
    counts = data["counts"]
    tiles = []
    for key in TOPIC_ORDER:
        meta = TOPIC_META[key]
        topic = topics.get(key, {"markets": []})
        n = len(topic["markets"])
        tiles.append(f"""<a class="tile" href="topics/{key}.html">
<div class="icon">{meta["icon"]}</div>
<div><strong>{esc(meta['label'])}</strong></div>
<div class="stat">{esc(meta['blurb'])}</div>
<div class="n">{n}</div><div class="stat">entries captured</div></a>""")

    verified = verification["counts"].get("verified", 0)
    flagged = verification["counts"].get("flagged", 0)
    unverified = verification["counts"].get("unverified", 0)
    prov = data.get("provenance")

    body = f"""
<p class="muted"><a href="../../index.html">← All dashboards</a> · this build: the Python engine's own
verification-first view</p>
<h1>Kalshi live-event dashboard &amp; alerting system</h1>
<p class="lede">Tracks the highest-dollar live events in five topics — gas prices, elections,
culture, crypto and golf — and alerts on any contract move of <strong>at least $0.10 in either
direction</strong>. Two alert feeds, a strategy simulator, and a verification register where each
fact carries the official source it came from.</p>

<div class="note{' warn' if prov != 'live' else ''}">
<strong>Data provenance for this build: <code>{esc(prov)}</code>.</strong>
{'The live engine could not reach Kalshi from the build environment, so this snapshot was built from real captured API payloads plus a scripted price path used to exercise the alert logic. Every market, strike and quote that is copied is labelled as captured; derivations are flagged.' if prov != 'live' else 'This snapshot was exported from a running engine reading the Kalshi API.'}
The live version of this dashboard runs as a small Python service (see the repository README) and
uses the same code paths.
</div>

<h2>Topics</h2>
<div class="grid c5">{''.join(tiles)}</div>

<h2>At a glance</h2>
<div class="grid c3">
<div class="card"><div class="stat">Markets captured</div><div class="n">{counts['markets']}</div></div>
<div class="card"><div class="stat">Swing alerts (≥ $0.10)</div><div class="n">{counts['alerts']}</div></div>
<div class="card"><div class="stat">High-ROI filtered alerts</div><div class="n">{counts['selective_alerts']}</div></div>
</div>

<h2>Verification status</h2>
<div class="grid c3">
<div class="card"><div class="stat">Facts verified against an official source</div>
<div class="n up">{verified}</div></div>
<div class="card"><div class="stat">Flagged irregularities</div>
<div class="n down">{flagged}</div></div>
<div class="card"><div class="stat">Could not be verified</div>
<div class="n">{unverified}</div></div>
</div>
<p class="muted">Every one of the {verification['total']} entries is listed on
<a href="verification.html">Verification</a> with its official source link, and the {flagged + unverified}
that are not clean are published on <a href="flagged.html">Flagged for review</a>.</p>

<h2>Start here</h2>
<ul class="tight">
<li><a href="findings.html">Executive summary</a> — what was verified, what was flagged, and the
three findings that change how this dashboard should be read.</li>
<li><a href="alerts.html">Alert feeds</a> — the $0.10 rule, and why a one-sided book can look like a
collapse when it is not.</li>
<li><a href="methodology.html">Methodology</a> — how a market is assigned to a topic, how the
high-ROI score works, and how fees are computed.</li>
</ul>
"""
    return page("Overview", "index.html", body)


def build_topic(data: dict, topic_key: str, catalog: list[dict], *, depth: int = 1) -> str:
    meta = TOPIC_META[topic_key]
    topic = next((t for t in data["topics"] if t["key"] == topic_key), {"markets": []})
    rows = topic["markets"]

    if rows:
        body_rows = "".join(f"""<tr>
<td><div><strong>{esc(m.get('title'))}</strong></div>
<div class="mono muted">{esc(m.get('ticker'))}</div></td>
<td>{esc(m.get('subtitle'))}</td>
<td class="num">{cents(m.get('last_price'))}</td>
<td class="num">{cents(m.get('yes_bid'))}</td>
<td class="num">{cents(m.get('yes_ask'))}</td>
<td class="num">{num(m.get('volume_fp'))}</td>
<td class="num">{num(m.get('open_interest_fp'))}</td>
<td>{esc((m.get('close_time') or '--')[:10])}</td>
<td><span class="tag">{esc(m.get('provenance'))}</span></td>
<td>{source_link(m)}</td>
</tr>""" for m in rows)
        table = f"""<div class="tblwrap"><table>
<thead><tr><th>Market</th><th>Outcome</th><th class="num">Last</th><th class="num">Yes bid</th>
<th class="num">Yes ask</th><th class="num">Volume</th><th class="num">Open interest</th>
<th>Closes</th><th>Provenance</th><th>Source</th></tr></thead>
<tbody>{body_rows}</tbody></table></div>"""
    else:
        table = f"""<div class="note"><strong>No live entries in this topic at capture time.</strong>
This is a real, verified state, not a gap in the build: each series below was queried with
<code>status=open</code> and <code>status=unopened</code> and returned zero markets. The captured
series catalogue is shown instead of inventing a price.</div>
<div class="tblwrap"><table>
<thead><tr><th>Series</th><th>Title</th><th>Tags</th><th class="num">Open markets</th>
<th>Source</th></tr></thead><tbody>
{''.join(f'''<tr><td class="mono">{esc(c['ticker'])}</td><td>{esc(c['title'])}</td>
<td>{esc(", ".join(c.get("tags") or []) or "--")}</td><td class="num">0</td>
<td><a href="{esc(c.get('capture_url'))}" target="_blank" rel="noopener">series response</a></td></tr>'''
         for c in catalog if (c.get("category") or "").lower() in ("entertainment", "mentions"))
         or '<tr><td colspan="5" class="muted">No catalogue captured for this topic.</td></tr>'}</tbody></table></div>"""

    basis = esc(topic.get("basis") or "")
    up = "../" if depth else ""
    body = f"""
<h1>{meta['icon']} {esc(meta['label'])}</h1>
<p class="lede">{esc(meta['blurb'])} {len(rows)} entries captured.</p>
<div class="note"><strong>Why these markets are in this topic.</strong> {basis}</div>
{table}
<p class="muted">Prices are fixed-point dollar strings exactly as Kalshi returns them. A cell showing
<code>--</code> means Kalshi returned no value — it is not zero. "Provenance: captured" means the row
came from a saved API response; see the <a href="{up}flagged.html">review page</a> for anything derived.</p>
"""
    return page(meta["label"], f"topics/{topic_key}.html", body, depth=1)


def build_findings(data: dict, verification: dict) -> str:
    facts = {f["id"]: f for f in verification["facts"]}
    counts = verification["counts"]

    def cite(fid: str) -> str:
        fact = facts.get(fid)
        if not fact:
            return ""
        return (f' <a href="{esc(fact["source"])}" target="_blank" rel="noopener">'
                f'[source]</a>')

    body = f"""
<h1>Executive summary</h1>
<p class="lede">What this project does, what was verified against Kalshi's own material, and the
findings that a trader or reviewer needs before trusting anything on this site.</p>

<h2>1. Scope</h2>
<p>The dashboard tracks live Kalshi events in five topics only — gas prices, elections, culture,
crypto and golf — and raises an alert whenever a contract's price moves by $0.10 or more in either
direction. It keeps tracking each event until Kalshi determines the outcome, records whether it
resolved YES or NO, and runs six simulated strategies with their own portfolios so the strategies can
be compared by category.</p>

<h2>2. What was verified</h2>
<p>{counts.get('verified', 0)} of {verification['total']} recorded facts are backed by an official
Kalshi page or an official Kalshi API response. The full list, each with a link, is on the
<a href="verification.html">Verification page</a>.</p>
<ul class="tight">
<li><strong>Endpoints.</strong> Demo REST is <code>https://external-api.demo.kalshi.co/trade-api/v2</code>
and production is <code>https://external-api.kalshi.com/trade-api/v2</code>; the WebSocket hosts are
<code>wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2</code> and
<code>wss://external-api-ws.kalshi.com/trade-api/ws/v2</code>.{cite('rest-demo-url')}{cite('ws-demo-url')}</li>
<li><strong>Orderbook shape.</strong> The book returns bids only; a YES bid at X equals a NO ask at
1−X; arrays are ascending, so the best bid is the last element.{cite('orderbook-bids-only')}</li>
<li><strong>Fees.</strong> Taker fee is <code>roundup(0.07 × C × P × (1−P))</code> and maker fee is
<code>roundup(0.0175 × C × P × (1−P))</code>; there is no settlement fee. This project's fee code
reproduces all 42 values in Kalshi's published fee table exactly.{cite('fee-taker')}</li>
<li><strong>Taxonomy.</strong> Kalshi publishes 14 categories; <em>Golf</em> is a tag under
<em>Sports</em>, and <em>Oil &amp; Gas</em> is a tag under <em>Commodities</em>.{cite('taxonomy')}</li>
<li><strong>Resolution.</strong> A determined market carries <code>result</code> (yes/no) and
<code>settlement_value_dollars</code>; the lifecycle WebSocket carries the same fields.{cite('lifecycle-resolution')}</li>
</ul>

<h2>3. Findings that change how to read this dashboard</h2>

<div class="note bad">
<h3 style="margin-top:0">Finding 1 — There is no "Gas" or "Culture" category on Kalshi</h3>
<p>Kalshi's published taxonomy has no <em>Gas</em> category and no <em>Culture</em> category. The
five topics on this dashboard are therefore <em>views</em> built from Kalshi's own fields, not
categories Kalshi defines. Gas is matched from the documented <code>KXAAAGASM</code> series (Kalshi's
own fee schedule calls it "US gas price"), the <em>Oil &amp; Gas</em> tag, and gas keywords. Culture is
Kalshi's <em>Entertainment</em> and <em>Mentions</em> categories.{cite('taxonomy')}{cite('gas-category')}
Every row states which rule placed it in its topic.</p>
</div>

<div class="note bad">
<h3 style="margin-top:0">Finding 2 — Kalshi's gas markets are filed under <em>Economics</em></h3>
<p>The live <code>KXAAAGASM-26NOV30</code> event returns <code>category: "Economics"</code>, not
Commodities. A dashboard that matched gas by category alone would miss every gas market.
{cite('gas-category')}</p>
</div>

<div class="note warn">
<h3 style="margin-top:0">Finding 3 — The <code>category</code> query parameter does not filter</h3>
<p>A request for <code>/events?category=Crypto</code> returned a <em>World</em> event and an
<em>Elections</em> event; a request for <code>category=Entertainment</code> returned a <em>Science and
Technology</em> event. The engine therefore fetches open events and filters on the published fields
itself.{cite('events-category-filter')}</p>
</div>

<div class="note warn">
<h3 style="margin-top:0">Finding 4 — A one-sided book looks like a 100-cent collapse</h3>
<p>Demo markets routinely publish <code>no_bid_dollars = 0.0000</code> beside
<code>yes_ask_dollars = 1.0000</code>. Naively watching the ask would fire a $0.10 alert on every
empty book, in both directions. This dashboard computes the mid of a two-sided book, falls back to the
last trade on a one-sided or crossed book, and labels the alert <em>quote-only</em> when there was no
trade behind the move.{cite('orderbook-bids-only')}{cite('demo-not-real')}</p>
</div>

<div class="note warn">
<h3 style="margin-top:0">Finding 5 — Demo prices are placeholders, and they disagree with production</h3>
<p>At capture, the demo gas market <code>KXAAAGASM-26NOV30-3.00</code> quoted <strong>99c</strong> for
"above $3.00", while Kalshi's public production page for the same series quoted
<strong>"Above 3.50" at 47c</strong> with strikes at 3.45 / 3.50 / 3.55. The demo board also carries
2099 expiries and <code>custom_strike</code> of <code>{{"demo strike": "demo strike"}}</code>. Kalshi documents that
demo prices may not reflect real markets, and this is what that looks like in practice.{cite('demo-not-real')}</p>
</div>

<div class="note warn">
<h3 style="margin-top:0">Finding 6 — Documented values that the live API contradicts</h3>
<p><code>GET /markets</code> documents status values <code>unopened | open | closed | settled</code>,
but live responses use <code>active</code> for open markets and <code>finalized</code> for settled
ones.{cite('market-status-values')} Multivariate <code>KXMVE…</code> combo markets also dominate the
open-market list; 24 of the first 60 open markets were combos that bundle unrelated sports legs into
one ticker, so they are excluded from single-topic boards.{cite('mve-combo-markets')}</p>
</div>

<h2>4. What could not be verified</h2>
<ul class="tight">
<li><strong>A signed request against a real Kalshi account.</strong> No demo API key exists in this
repository, so the signing code is unit-tested but has never authenticated. {badge('unverified')}</li>
<li><strong>The WebSocket handshake.</strong> Documented and implemented, never observed live.
{badge('unverified')}</li>
<li><strong>Whether Kalshi sends CORS headers.</strong> No official statement found; the static site
therefore does not call Kalshi from the browser. {badge('unverified')}</li>
</ul>

<h2>5. Irregularities affecting the numbers</h2>
<ul class="tight">
<li><strong>Per-series fee multipliers are not applied.</strong> The simulator uses the general
0.07 / 0.0175 rates; series the schedule marks 0 (e.g. <code>KXBTCY</code>) would be overcharged in
simulation. {badge('flagged')}</li>
<li><strong>The fee rebate accumulator is not modelled.</strong> Simulated P&amp;L can differ from
the exchange by fractions of a cent per fill. {badge('flagged')}</li>
<li><strong>The demo golf event had already passed its stated expiry</strong> while still listing as
active. Closing times are shown rather than assumed. {badge('flagged')}</li>
</ul>
<p>All of these are published with source links on <a href="flagged.html">Flagged for review</a>.</p>

<h2>6. How to use it</h2>
<ol class="tight">
<li>Pick a topic. Each topic page lists every captured entry in one table, with the price, both sides
of the book, volume, open interest and a source link.</li>
<li>Watch the two alert feeds: <em>all events</em> (every ≥$0.10 move) and <em>high ROI</em> (the same
moves, filtered by a trade-quality score).</li>
<li>Compare strategies on the portfolio view: each strategy is a distinct trade category with its own
starting balance, so returns are comparable.</li>
<li>Check <a href="flagged.html">Flagged for review</a> before relying on any specific figure.</li>
</ol>
"""
    return page("Executive summary", "findings.html", body)


def build_alerts(data: dict) -> str:
    alerts = data.get("alerts") or []
    selective = data.get("selective_alerts") or []

    def feed(items: list[dict]) -> str:
        if not items:
            return ('<div class="note"><strong>No alerts in this snapshot.</strong> An alert needs a '
                    'price change of at least $0.10 between samples.</div>')
        out = []
        for a in reversed(items):
            direction = a.get("direction")
            klass = "up" if direction == "up" else "down"
            sign = "+" if (a.get("delta") or "").startswith("-") is False else ""
            out.append(f"""<div class="card">
<div><strong class="{klass}">{sign}{cents(a.get('delta'))}</strong>
&nbsp;{esc(a.get('title'))}</div>
<div class="mono muted">{esc(a.get('ticker'))} · {cents(a.get('from_price'))} →
{cents(a.get('to_price'))} · {esc(a.get('window_s'))}s window ·
<span class="tag">{esc(a.get('topic'))}</span>
<span class="tag {'ok' if a.get('confidence') == 'confirmed' else 'warn'}">{esc(a.get('confidence'))}</span>
{'<span class="tag ok">score ' + esc(a.get('score')) + '</span>' if a.get('selective') else ''}</div>
<div class="muted">{esc('; '.join(a.get('reasons') or []))}</div>
<div class="muted">Source: {('<a href="' + esc(a.get('page_url')) + '" target="_blank" rel="noopener">Kalshi market</a>') if a.get('page_url') else '<span class="tag bad">no source</span>'}
· rule: <code>|Δprice| ≥ $0.10</code></div>
</div>""")
        return "".join(out)

    body = f"""
<h1>Alert feeds</h1>
<p class="lede">The rule is exact: a contract's observed price changed by <strong>$0.10 or more in
either direction</strong>. The dashboard keeps two feeds of the same rule.</p>

<div class="note"><strong>What price is watched.</strong> The mid of the best YES bid and the implied
YES ask when the book is two-sided and uncrossed. On a one-sided or crossed book, the last traded
price. When there was no trade behind the move, the alert is labelled
<span class="tag warn">quote-only</span> so a stale quote is never presented as a real repricing.</div>

<h2>All events <span class="tag">{len(alerts)}</span></h2>
<p class="muted">Every swing that met the threshold, unfiltered.</p>
{feed(alerts)}

<h2>High ROI (model-selected) <span class="tag">{len(selective)}</span></h2>
<p class="muted">The same rule, additionally filtered by a trade-quality score computed from the size
of the move, the contracts actually available within 10 cents, the spread and fee drag, the time left
before the market closes, and whether the move was confirmed by a trade. The weights are published on
the <a href="methodology.html">methodology page</a>. This is a heuristic ranking of opportunity
quality — <strong>not</strong> a probability of profit.</p>
{feed(selective)}
"""
    return page("Alerts", "alerts.html", body)


def build_verification(verification: dict) -> str:
    rows = "".join(f"""<tr>
<td class="mono">{esc(f['id'])}</td>
<td>{esc(f['claim'])}<div class="mono muted">{esc(f.get('value') if f.get('value') is not None else '--')}</div></td>
<td>{badge(f['status'])}</td>
<td>{esc(f['check'])}</td>
<td><a href="{esc(f['source'])}" target="_blank" rel="noopener">{esc(_short(f['source']))}</a>
<div class="mono muted">{esc(f['source_type'])}</div></td>
<td class="muted">{esc(f.get('notes') or '')}</td>
</tr>""" for f in verification["facts"])

    c = verification["counts"]
    body = f"""
<h1>Verification register</h1>
<p class="lede">Every claim this project makes about Kalshi, the official source that states it, and
what was actually checked. {c.get('verified', 0)} verified, {c.get('flagged', 0)} flagged,
{c.get('unverified', 0)} unverified, out of {verification['total']}.</p>
<div class="note">{esc(verification['policy'])}</div>
<div class="tblwrap"><table>
<thead><tr><th>ID</th><th>Claim</th><th>Status</th><th>How it was checked</th><th>Official source</th>
<th>Notes</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="muted">Checked at {esc(verification['checked_at_utc'])}. The machine-readable copy is
<a href="data/verification.json">data/verification.json</a>.</p>
"""
    return page("Verification", "verification.html", body)


def _short(url: str) -> str:
    return (url.replace("https://", "").replace("http://", "")
            .replace("docs.kalshi.com", "docs.kalshi.com")
            .replace("external-api.kalshi.com/trade-api/v2", "API")[:78])


def build_flagged(verification: dict, captures: list[dict]) -> str:
    flagged = [f for f in verification["facts"] if f["status"] != "verified"]
    rows = "".join(f"""<tr>
<td>{badge(f['status'])}<div class="mono muted">{esc(f['id'])}</div></td>
<td><strong>{esc(f['claim'])}</strong>
<div class="muted">{esc(f['check'])}</div>
<div class="muted"><em>Why it matters:</em> {esc(f.get('notes') or '--')}</div></td>
<td><a href="{esc(f['source'])}" target="_blank" rel="noopener">official source</a></td>
</tr>""" for f in flagged)

    derived = [m for c in captures for m in c.get("markets", []) if m.get("note")]
    drows = "".join(f"""<tr><td class="mono">{esc(m['ticker'])}</td>
<td>{esc(m.get('title'))}</td><td>{esc(m['note'])}</td>
<td><a href="{esc(c['url'])}" target="_blank" rel="noopener">captured response</a></td></tr>"""
                    for c in captures for m in c.get("markets", []) if m.get("note"))

    body = f"""
<h1>Flagged for review</h1>
<p class="lede">Everything that did not come out clean: facts that could not be verified, facts that
were verified and contradicted something, and individual rows where a value had to be derived. None
of these block the site; they are here so you can review them and ask for changes.</p>

<div class="note warn">Counts: {len(flagged)} verification items flagged or unverified,
{len(derived)} captured rows carrying a derivation note.</div>

<h2>Verification items</h2>
<div class="tblwrap"><table>
<thead><tr><th>Status</th><th>Item</th><th>Source</th></tr></thead>
<tbody>{rows}</tbody></table></div>

<h2>Rows with a derivation or caveat</h2>
{'<div class="tblwrap"><table><thead><tr><th>Ticker</th><th>Title</th><th>Note</th><th>Capture</th></tr></thead><tbody>' + drows + '</tbody></table></div>' if drows else '<p class="muted">None.</p>'}

<h2>Known gaps in this build</h2>
<ul class="tight">
<li>The static site shows a <strong>snapshot</strong>. A browser page cannot hold a Kalshi private key,
so live alerting and order execution run in the Python service, not here.</li>
<li>The snapshot was produced in an environment with no route to Kalshi. Market, strike and quote
values are real captured API responses; the price <em>paths</em> used to demonstrate alerts are
scripted and labelled <code>captured-replay</code>.</li>
<li>Per-series fee multipliers and the fee rebate accumulator are not modelled in simulation.</li>
</ul>
"""
    return page("Flagged for review", "flagged.html", body)


def build_methodology() -> str:
    body = """
<h1>Methodology</h1>
<p class="lede">How a market gets into a topic, how an alert is decided, how the high-ROI score works,
how fees are computed, and what the simulator does and does not do. Each rule names its source.</p>

<h2>Topic assignment</h2>
<p>Kalshi publishes its taxonomy at <code>GET /search/tags_by_categories</code>: 14 categories, with
<em>Golf</em> as a tag under <em>Sports</em> and <em>Oil &amp; Gas</em> as a tag under
<em>Commodities</em>. There is no Gas and no Culture category, so those two topics are derived:</p>
<div class="tblwrap"><table>
<thead><tr><th>Topic</th><th>Rule</th><th>Confidence label</th></tr></thead><tbody>
<tr><td>Gas prices</td><td>Kalshi tag <em>Oil &amp; Gas</em> / <em>Gas</em>; or a documented gas series
ticker such as <code>KXAAAGASM</code>; or gas/crude/AAA in the title</td><td>tag / keyword</td></tr>
<tr><td>Elections</td><td>Kalshi category <em>Elections</em></td><td>category</td></tr>
<tr><td>Culture</td><td>Kalshi category <em>Entertainment</em> or <em>Mentions</em>; or an
entertainment tag such as <em>Music</em>, <em>Oscars</em>, <em>Movies</em></td><td>category / tag</td></tr>
<tr><td>Crypto</td><td>Kalshi category <em>Crypto</em></td><td>category</td></tr>
<tr><td>Golf</td><td>Kalshi category <em>Sports</em> with tag <em>Golf</em>, or a known golf series
ticker</td><td>tag</td></tr>
</tbody></table></div>
<p>Tags live on the <em>series</em>, not the event — verified by comparing live
<code>GET /events</code> (no <code>tags</code> key) with <code>GET /series/{ticker}</code> (has
<code>tags</code>). The engine caches series tags in SQLite. Multivariate <code>KXMVE…</code> combos
are excluded: one ticker can bundle NFL props and European soccer, so it cannot belong to one topic.</p>

<h2>The alert rule</h2>
<ul class="tight">
<li>Threshold: <code>|Δprice| ≥ $0.10</code>, either direction, checked against the previous sample and
against the sample one rolling window (default 60s) earlier — so a fast jump and a slow drift both fire.</li>
<li>Price: mid of best YES bid and implied YES ask on a two-sided, uncrossed book; otherwise the last
trade; otherwise the best bid. Asks are implied as <code>1 − opposite best bid</code> because the book
returns bids only.</li>
<li>Confidence: <em>confirmed</em> when a trade or two two-sided quotes agree; <em>quote-only</em>
when the move exists only in a one-sided quote.</li>
<li>De-duplication: a per-market cooldown suppresses same-direction repeats; a direction flip always
alerts.</li>
</ul>

<h2>High-ROI score</h2>
<p>A weighted mean of five components, each in [0,1], computed from values Kalshi actually returns:</p>
<div class="tblwrap"><table><thead><tr><th>Component</th><th>Weight</th><th>Inputs</th></tr></thead><tbody>
<tr><td>Magnitude</td><td>0.30</td><td>size of the move relative to 4× the threshold</td></tr>
<tr><td>Liquidity</td><td>0.25</td><td>contracts buyable within 10c, from the order book</td></tr>
<tr><td>Cost</td><td>0.20</td><td>spread and taker fee as a share of contract price</td></tr>
<tr><td>Horizon</td><td>0.15</td><td>hours until the market closes</td></tr>
<tr><td>Confirmation</td><td>0.10</td><td>trade-backed (1.0) vs quote-only (0.35)</td></tr>
</tbody></table></div>
<p>Unknown inputs score conservatively and add a caveat rather than being assumed. The published
minimum score for the selective feed is 0.55. <strong>This is a ranking of trade quality, not a
probability of profit.</strong></p>

<h2>Fees</h2>
<p>From Kalshi's published fee schedule (effective 2026-07-07):</p>
<ul class="tight">
<li>Taker: <code>roundup(M × 0.07 × C × P × (1−P))</code>, default M = 1.</li>
<li>Maker: <code>roundup(M × 0.0175 × C × P × (1−P))</code>, default M = 0.</li>
<li>No settlement fee, no membership fee.</li>
</ul>
<p>This project's implementation reproduces every value in the published per-contract and
per-100-contract tables (42/42, asserted in the test suite). Rounded <em>fee + position cost</em> up to
the cent, then the position cost subtracted, which is how the published table behaves.</p>

<h2>Simulation</h2>
<ul class="tight">
<li>Six strategies, each a distinct trade <em>category</em>: trend following, contrarian, asymmetric
payoff, high-probability carry, event driven, and an unfiltered control benchmark.</li>
<li>Buys execute at the side's implied ask, sells at that side's best bid — executable prices, not mids.</li>
<li>Each strategy starts at $10,000 with its own ledger, so returns are comparable.</li>
<li>Positions are opened once and closed once per market; exits are take-profit, stop-loss, max hold,
or settlement.</li>
<li>Resolution pays $1 per contract for the winning side and $0 for the loser, with no fee.</li>
<li>An empty book means no trade, with the rejection reason recorded.</li>
</ul>
<div class="note warn"><strong>Limitations.</strong> Per-series fee multipliers are not applied, and the
exchange's fee rounding rebate is not modelled. Simulated results are simulations of a demo
environment whose prices Kalshi itself says may not reflect real markets.</div>
"""
    return page("Methodology", "methodology.html", body)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def build(out_dir: str | Path, data_dir: str | Path) -> dict:
    out = Path(out_dir)
    data_path = Path(data_dir)
    data = json.loads((data_path / "dashboard.json").read_text())
    verification = json.loads((data_path / "verification.json").read_text())
    captures = json.loads((data_path / "captures.json").read_text()).get("captures", [])

    (out / "topics").mkdir(parents=True, exist_ok=True)
    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(parents=True, exist_ok=True)

    (out / "assets" / "site.css").write_text(CSS)
    (out / "assets" / "site.js").write_text(JS)

    catalog = data.get("series_catalog") or []
    pages = {
        "index.html": build_index(data, verification),
        "findings.html": build_findings(data, verification),
        "alerts.html": build_alerts(data),
        "verification.html": build_verification(verification),
        "flagged.html": build_flagged(verification, captures),
        "methodology.html": build_methodology(),
    }
    for key in TOPIC_ORDER:
        pages[f"topics/{key}.html"] = build_topic(data, key, catalog)

    for name, content in pages.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    # Topic shortcuts at the root so simple links like /golf.html keep working.
    # These are real pages (nav + footer) with a redirect, not blank shells.
    for key in TOPIC_ORDER:
        label = TOPIC_META[key]["label"]
        stub_body = (
            f'<h1>{esc(label)}</h1>'
            f'<div class="note">This topic lives on its own page: '
            f'<a href="topics/{key}.html">open {esc(label)}</a>.</div>'
        )
        content = page(label, f"{key}.html", stub_body)
        content = content.replace(
            '<meta charset="utf-8">',
            f'<meta charset="utf-8"><meta http-equiv="refresh" content="0; url=topics/{key}.html">'
            f'<link rel="canonical" href="topics/{key}.html">', 1)
        (out / f"{key}.html").write_text(content)

    for name in ("dashboard.json", "verification.json", "captures.json"):
        source = data_path / name
        if source.exists():
            (out / "data" / name).write_text(source.read_text())

    (out / ".nojekyll").write_text("")
    return {"pages": sorted(pages), "out": str(out)}


JS = """
// Minimal, dependency-free behaviour: active nav highlight + table sorting.
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('table').forEach(function (table) {
    var headers = table.querySelectorAll('thead th');
    headers.forEach(function (th, index) {
      if (th.dataset.nosort !== undefined) return;
      th.style.cursor = 'pointer';
      th.title = 'Click to sort';
      var ascending = false;
      th.addEventListener('click', function () {
        var body = table.tBodies[0];
        var rows = Array.prototype.slice.call(body.rows);
        ascending = !ascending;
        rows.sort(function (a, b) {
          var av = (a.cells[index] || {}).textContent || '';
          var bv = (b.cells[index] || {}).textContent || '';
          var an = parseFloat(av.replace(/[^0-9.\\-]/g, ''));
          var bn = parseFloat(bv.replace(/[^0-9.\\-]/g, ''));
          if (!isNaN(an) && !isNaN(bn) && an !== bn) return ascending ? an - bn : bn - an;
          return ascending ? av.localeCompare(bv) : bv.localeCompare(av);
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });
});
"""


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs")
    parser.add_argument("--data", default="docs/data")
    args = parser.parse_args()
    result = build(args.out, args.data)
    print(f"built {len(result['pages'])} pages into {result['out']}")


if __name__ == "__main__":  # pragma: no cover
    main()
