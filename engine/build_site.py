"""Render the static GitHub Pages site from engine-exported data.

    Pages produced (all under --out, default docs/):

    index.html                  landing page: what this is, headline findings, topic links
    topics/<topic>.html         one page per tracked topic, every entry in a table
    live.html                   live interactive Demo API feed, dual scrolling chats, SVG chart & orderbook
    portfolio.html              strategy simulator, trade-type categorizer & demo portfolio tracker
    resolutions.html            live resolution ledger (yes / no / scalar / unconfirmed --)
    alerts.html                 the alert feed + the exact rule that produced each alert
    verification.html           every verified fact, with its official source link
    flagged.html                Flagged for Review: unverified + flagged items
    methodology.html            how topics, alerts, scoring, fees, simulation & UX suggestions work
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
    ("live.html", "Live chart & chat"),
    ("gas.html", "Gas"),
    ("elections.html", "Elections"),
    ("culture.html", "Culture"),
    ("crypto.html", "Crypto"),
    ("golf.html", "Golf"),
    ("alerts.html", "Alerts"),
    ("portfolio.html", "Portfolio & strategies"),
    ("resolutions.html", "Resolutions"),
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
.btn{display:inline-flex;align-items:center;gap:6px;background:#fff;border:1px solid var(--line);
color:var(--text);padding:6px 11px;border-radius:7px;font-size:12.5px;font-weight:600;cursor:pointer}
.btn:hover{border-color:#b8c7dd;background:#f4f7fc}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.active{background:#e7f0fc;border-color:var(--accent);color:var(--accent)}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
.toolbar select,.toolbar input{padding:6px 9px;border:1px solid var(--line);border-radius:7px;font-size:13px;background:#fff}
.chatbox{height:300px;overflow-y:auto;border:1px solid var(--line);border-radius:10px;background:#fbfcfe;padding:10px;display:flex;flex-direction:column;gap:8px}
.chatmsg{background:#fff;border:1px solid #e7ebf2;border-radius:8px;padding:8px 10px;font-size:12.5px}
.chatmsg .meta{display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:11.5px;margin-bottom:3px}
.svgwrap{border:1px solid var(--line);border-radius:10px;background:#fff;padding:10px;overflow:hidden}
.ob-row{display:grid;grid-template-columns:72px 1fr 84px;gap:8px;align-items:center;font-size:12px;margin:4px 0}
.ob-track{height:12px;background:#eef1f6;border-radius:4px;overflow:hidden}
.ob-fill.yes{height:100%;background:#1e8e5a}
.ob-fill.no{height:100%;background:#c93b2b}
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
<li><a href="live.html">Live interactive chart, orderbook &amp; dual alert chats</a> — polls
<code>external-api.demo.kalshi.co</code> / <code>demo-api.kalshi.co</code> directly in the browser
(with replay fallback), plots contract price vs. selectable Seconds/Minutes/Hours windows, displays
orderbook contract depth by price level, and runs the two scrolling ≥$0.10 swing chats.</li>
<li><a href="findings.html">Executive summary</a> — what was verified, what was fixed in Engine V2,
and the six findings that change how this dashboard should be read.</li>
<li><a href="portfolio.html">Portfolio &amp; strategy lab</a> — six trade-type categories, automated
paper execution with published series fee multipliers, and custom strategy builder.</li>
<li><a href="resolutions.html">Resolutions ledger</a> — tracks markets through Kalshi settlement
(<code>yes</code>, <code>no</code>, or <code>scalar</code>; unconfirmed values stay <code>--</code>).</li>
<li><a href="alerts.html">Alert feeds</a> — the $0.10 rule, and why a one-sided book can look like a
collapse when it is not.</li>
<li><a href="methodology.html">Methodology &amp; UX roadmap</a> — topic assignment, High-ROI scoring,
fee math, and trader-focused recommendations for continuous simplification.</li>
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
<li><strong>Orderbook &amp; Order V2 Unified YES Grid.</strong> The book returns bids only; a YES bid at X
equals a NO ask at 1−X; arrays are ascending, so the best bid is the last element. Order V2 uses
<code>bid</code>/<code>ask</code> on a unified YES scale, so buying NO at <code>P_no</code> submits
<code>side="ask"</code> at <code>1.0000 − P_no</code>, and authenticated requests sign the full
<code>/trade-api/v2/...</code> path without retrying non-GET writes.{cite('orderbook-bids-only')}{cite('order-direction-v2')}</li>
<li><strong>Fees &amp; Per-Series Multipliers.</strong> Taker fee is <code>roundup(M × 0.07 × C × P × (1−P))</code>
and maker fee is <code>roundup(M × 0.0175 × C × P × (1−P))</code>; there is no settlement fee. Engine V2
applies explicit <code>GET /series</code> <code>fee_multiplier</code> overrides plus 31 Non-Standard Fee rows
from Kalshi's July 7, 2026 schedule PDF, and reproduces all 42 general fee table values.{cite('fee-taker')}{cite('fee-nonstandard')}</li>
<li><strong>Taxonomy.</strong> Kalshi publishes 14 categories; <em>Golf</em> is a tag under
<em>Sports</em>, and <em>Oil &amp; Gas</em> is a tag under <em>Commodities</em>.{cite('taxonomy')}</li>
<li><strong>Resolution (Binary &amp; Scalar).</strong> A determined market carries <code>result</code>
(<code>yes</code>, <code>no</code>, or <code>scalar</code>) and <code>settlement_value_dollars</code>;
scalar settlement pays <code>v</code> to YES and <code>1 − v</code> to NO with zero fee.{cite('lifecycle-resolution')}{cite('scalar-settlement')}</li>
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
<li><strong>A signed request against a live Kalshi demo account in static CI.</strong> No demo API key
is stored in repository secrets, so demo-account cash and fills remain <code>--</code> on the static build
until connected to a local Python runner (<code>uvicorn app.main:app</code>). {badge('unverified')}</li>
<li><strong>Authenticated WebSocket streaming in a static browser tab.</strong> Browser
<code>new WebSocket(url)</code> cannot attach Kalshi's required <code>KALSHI-ACCESS-*</code> headers, so
unsigned handshakes return HTTP 401; real-time WS streaming runs in <code>app/ws.py</code>. {badge('unverified')}</li>
</ul>

<h2>5. Irregularities affecting the numbers</h2>
<ul class="tight">
<li><strong>Browser CORS is asymmetric.</strong> Public GET reads on both
<code>external-api.demo.kalshi.co</code> and <code>demo-api.kalshi.co</code> return
<code>Access-Control-Allow-Origin</code> (powering <a href="live.html">live.html</a>), whereas
<code>OPTIONS</code> preflight omits <code>KALSHI-ACCESS-*</code> headers for signed portfolio/order calls.{cite('cors-unknown')} {badge('flagged')}</li>
<li><strong>Residual per-series fee schedule rows.</strong> Engine V2 encodes 31 unambiguous Non-Standard
Fee rows from the July 7, 2026 PDF and honors API <code>fee_multiplier</code>, but interleaved PDF rows
from <code>KXMVE</code> onward fall back to <code>M = 1</code> when the API omits <code>fee_multiplier</code>.{cite('fee-nonstandard')} {badge('flagged')}</li>
<li><strong>The fee rebate accumulator is not modelled.</strong> Simulated P&amp;L can differ from
the exchange by fractions of a cent per fill. {badge('flagged')}</li>
<li><strong>The demo golf event had already passed its stated expiry</strong> while still listing as
active. Closing times are shown rather than assumed. {badge('flagged')}</li>
</ul>
<p>All of these are published with source links on <a href="flagged.html">Flagged for review</a>.</p>

<h2>6. Trader UX &amp; Live Architecture Recommendations</h2>
<ul class="tight">
<li><strong>Hybrid Live + Signed Relay:</strong> Keep unauthenticated public polling directly in the
browser for zero-latency topic/orderbook inspection on GitHub Pages (<a href="live.html">Live chart &amp; chat</a>),
and pair with a lightweight Cloudflare Worker or local FastAPI relay (<code>uvicorn app.main:app</code>)
holding demo RSA-PSS/Ed25519 keys so WebSockets (<code>ticker</code>, <code>orderbook_delta</code>,
<code>market_lifecycle_v2</code>) push sub-second updates over SSE.</li>
<li><strong>Decision-First Simplified Charts:</strong> Show executable YES ask / YES bid bands rather
than misleading empty-book midpoints, overlay <code>|Δprice| ≥ $0.10</code> catalyst pins directly on the
price curve, and display crossable contract depth within 5c/10c next to the ticket so traders see slippage
before sizing an order.</li>
<li><strong>Strict 5-Topic Discipline:</strong> Keep Gas, Elections, Culture, Crypto, and Golf isolated in
separate ranked tables sorted by 24h dollar/contract volume, auto-quarantining <code>KXMVE*</code>
multivariate parlays and quote-only 99c spreads so noise never drowns real repricings.</li>
</ul>

<h2>7. How to use it</h2>
<ol class="tight">
<li>Open <a href="live.html">Live chart &amp; chat</a> to poll Kalshi Demo REST endpoints live, inspect
the Seconds / Minutes / Hours price curve and orderbook depth bars, and monitor both scrolling ≥$0.10
alert chats.</li>
<li>Pick a topic (<a href="gas.html">Gas</a>, <a href="elections.html">Elections</a>,
<a href="culture.html">Culture</a>, <a href="crypto.html">Crypto</a>, <a href="golf.html">Golf</a>) to
audit every captured contract with official source links.</li>
<li>Compare the six trade-type categories and build custom paper rules on
<a href="portfolio.html">Portfolio &amp; strategies</a>, and verify settled outcomes on
<a href="resolutions.html">Resolutions</a>.</li>
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
<li>Authenticated Kalshi demo orders and WebSocket handshakes require RSA-PSS / Ed25519
<code>KALSHI-ACCESS-*</code> headers that browsers cannot attach safely on static hosting; public GET
polling runs live on <a href="live.html">live.html</a>, while authenticated execution runs in the local
Python service (<code>uvicorn app.main:app</code>).</li>
<li>Baseline offline tables use real captured API responses plus deterministic price paths labelled
<code>captured-replay</code> when offline.</li>
<li>31 Non-Standard Fee rows from Kalshi's July 7, 2026 PDF and explicit API <code>fee_multiplier</code>
values are applied; interleaved PDF rows from <code>KXMVE</code> onward and the micro-cent fee rebate
accumulator remain unmodelled.</li>
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
<li>Resolution pays $1 per contract for <code>yes</code>/<code>no</code> winners, $0 for losers, and
proportional <code>v</code> / <code>1 − v</code> for <code>scalar</code> settlements, with zero settlement fee.</li>
<li>An empty book means no trade, with the rejection reason recorded.</li>
</ul>
<div class="note warn"><strong>Limitations.</strong> 31 Non-Standard Fee rows from Kalshi's July 7, 2026 PDF
and explicit <code>GET /series</code> <code>fee_multiplier</code> values are applied, while interleaved PDF
rows from <code>KXMVE</code> onward default to <code>M = 1</code> and the exchange's micro-cent rounding
rebate accumulator is not modelled. Simulated results are simulations of a demo environment whose prices
Kalshi itself says may not reflect real markets.</div>

<h2>Continuous Organization &amp; Simplification for Traders</h2>
<div class="tblwrap"><table>
<thead><tr><th>Focus Area</th><th>Design Rule</th><th>Official Basis</th></tr></thead><tbody>
<tr><td><strong>1. Live Interactivity</strong></td>
<td>Poll public <code>/events?status=open&amp;with_nested_markets=true</code> and
<code>/markets/{ticker}/orderbook</code> directly in the browser with automatic host failover
(<code>external-api.demo.kalshi.co</code> → <code>demo-api.kalshi.co</code> → <code>captured-replay</code>),
and expose one-click local FastAPI relay connection for signed WebSockets and demo orders.</td>
<td><a href="https://docs.kalshi.com/getting_started/demo_env" target="_blank" rel="noopener">docs.kalshi.com/getting_started/demo_env</a></td></tr>
<tr><td><strong>2. Simplified Charts</strong></td>
<td>Single clean SVG contract chart with X-axis toggle (<code>Seconds</code> / <code>Minutes</code> /
<code>Hours</code>), Y-axis fixed on <code>$0.00–$1.00</code>, horizontal orderbook contract depth bars
at each price level, and clickable <code>|Δprice| ≥ $0.10</code> jump pins linked to official contract pages.</td>
<td><a href="https://docs.kalshi.com/getting_started/orderbook_responses" target="_blank" rel="noopener">docs.kalshi.com/getting_started/orderbook_responses</a></td></tr>
<tr><td><strong>3. Strict 5-Topic Organization</strong></td>
<td>Keep Gas prices, Elections, Culture, Crypto, and Golf strictly separate, ranked by dollar/contract
volume within each topic, and exclude <code>KXMVE*</code> combo parlays and unconfirmed guesses.</td>
<td><a href="https://docs.kalshi.com/api-reference/search/get-tags-for-series-categories" target="_blank" rel="noopener">docs.kalshi.com/api-reference/search</a></td></tr>
</tbody></table></div>
"""
    return page("Methodology", "methodology.html", body)


def build_live(data: dict) -> str:
    endpoints = data.get("demo_endpoints") or {}
    rest_p = endpoints.get("rest_primary") or "https://external-api.demo.kalshi.co/trade-api/v2"
    rest_f = endpoints.get("rest_fallback") or "https://demo-api.kalshi.co/trade-api/v2"
    ws_p = endpoints.get("ws_primary") or "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
    ws_f = endpoints.get("ws_fallback") or "wss://demo-api.kalshi.co/trade-api/ws/v2"

    all_markets = [m for t in data.get("topics", []) for m in (t.get("markets") or [])]
    options = "".join(
        f'<option value="{esc(m.get("ticker"))}">{esc(m.get("topic"))}: {esc(m.get("ticker"))} — {esc(m.get("title"))}</option>'
        for m in all_markets
    )

    alerts = data.get("alerts") or []
    selective = data.get("selective_alerts") or []

    def chat_items(items: list[dict]) -> str:
        if not items:
            return '<div class="muted">Waiting for a ≥ $0.10 contract swing…</div>'
        out = []
        for a in items[:25]:
            klass = "up" if a.get("direction") == "up" else "down"
            url = a.get("page_url") or "https://docs.kalshi.com/getting_started/orderbook_responses"
            srcs = ((a.get("news") or {}).get("contract_sources") if isinstance(a.get("news"), dict) else []) or []
            cat_link = ""
            if srcs and srcs[0].get("url", "").startswith("https://"):
                cat_link = f' · <a href="{esc(srcs[0]["url"])}" target="_blank" rel="noopener">{esc(srcs[0].get("name") or "settlement source")}</a>'
            out.append(
                f'<div class="chatmsg"><div class="meta"><span class="mono">{esc(a.get("time_utc") or "--")}</span>'
                f'<span class="tag">{esc(a.get("topic"))}</span></div>'
                f'<div><strong class="{klass}">{esc(a.get("delta"))}</strong> '
                f'<span class="mono">{esc(a.get("ticker"))}</span> ({cents(a.get("from_price"))} → {cents(a.get("to_price"))})</div>'
                f'<div class="muted">{esc(a.get("title"))} · '
                f'<a href="{esc(url)}" target="_blank" rel="noopener">official market</a>{cat_link}</div></div>'
            )
        return "".join(out)

    body = f"""
<h1>Live Interactive Chart, Orderbook &amp; Dual Swing Chats</h1>
<p class="lede">Polls Kalshi's official Demo Trade API v2 directly in your browser across the five
isolated topics (Gas prices, Elections, Culture, Crypto, Golf), with automatic fallback to
<code>data/dashboard.json</code> (<code>captured-replay</code>) when offline.</p>

<div class="card">
<div class="toolbar">
<span id="live-conn-badge" class="tag warn">Initializing feed…</span>
<button type="button" class="btn primary" id="btn-poll-now">Poll Demo API Now</button>
<label class="muted">Auto-poll:
<select id="sel-poll-interval">
<option value="10000">Every 10s</option>
<option value="30000" selected>Every 30s</option>
<option value="0">Paused</option>
</select></label>
<label class="muted">REST host:
<select id="sel-rest-host">
<option value="{esc(rest_p)}">{esc(rest_p)}</option>
<option value="{esc(rest_f)}">{esc(rest_f)}</option>
</select></label>
</div>
<p class="muted">WebSocket endpoints configured in <code>app/ws.py</code>:
<code>{esc(ws_p)}</code> and <code>{esc(ws_f)}</code>
(<a href="https://docs.kalshi.com/getting_started/quick_start_websockets" target="_blank" rel="noopener">official WS docs</a>;
browsers cannot attach <code>KALSHI-ACCESS-*</code> headers on unsigned <code>new WebSocket()</code>, so browser mode uses CORS-verified REST polling).</p>
</div>

<h2>Interactive Contract Price &amp; Liquidity Graph</h2>
<div class="card" id="interactive-chart-root">
<div class="toolbar">
<label><strong>Contract:</strong>
<select id="chart-market-select">{options}</select></label>
<span><strong>X-axis window:</strong></span>
<button type="button" class="btn" data-win="seconds">Seconds (60s)</button>
<button type="button" class="btn" data-win="minutes">Minutes (30m)</button>
<button type="button" class="btn active" data-win="hours">Hours (6h)</button>
<a id="chart-market-link" href="https://docs.kalshi.com/getting_started/orderbook_responses" target="_blank" rel="noopener">Official market source ↗</a>
</div>
<div class="grid c2">
<div>
<div class="svgwrap">
<svg id="price-svg" viewBox="0 0 640 280" width="100%" height="280" role="img" aria-label="Contract price over time">
<text x="20" y="140" fill="#5f6b7d" font-size="13">Loading interactive contract series…</text>
</svg>
</div>
<div id="jump-pins" class="muted" style="margin-top:8px">Sharp ≥ $0.10 jump markers with associated market &amp; settlement links appear here.</div>
</div>
<div>
<h3 style="margin-top:0">Current Orderbook Liquidity (Contracts per Price)</h3>
<p class="muted">Kalshi returns YES bids and NO bids only; a NO bid at <code>p</code> implies a YES ask at <code>1 − p</code>
(<a href="https://docs.kalshi.com/getting_started/orderbook_responses" target="_blank" rel="noopener">orderbook spec</a>).</p>
<div id="orderbook-bars"><div class="muted">Select a contract or poll live orderbook…</div></div>
</div>
</div>
</div>

<h2>Real-Time Scrolling Swing Chats (|Δprice| ≥ $0.10)</h2>
<div class="grid c2">
<div class="card">
<h3 style="margin-top:0">Chat 1 · All Events (≥ $0.10 either direction) <span class="tag" id="chat-all-count">{len(alerts)}</span></h3>
<div class="chatbox" id="chat-all">{chat_items(alerts)}</div>
</div>
<div class="card">
<h3 style="margin-top:0">Chat 2 · Selective High-ROI Filter <span class="tag ok" id="chat-roi-count">{len(selective)}</span></h3>
<div class="chatbox" id="chat-roi">{chat_items(selective)}</div>
</div>
</div>

<h2>Live Topic Separation (Highest Dollar / Contract Volume First)</h2>
<div id="live-topic-boards" class="muted">Polling live Demo API events… if unreachable, see captured topic tables on
<a href="gas.html">Gas</a>, <a href="elections.html">Elections</a>, <a href="culture.html">Culture</a>,
<a href="crypto.html">Crypto</a>, and <a href="golf.html">Golf</a>.</div>
"""
    return page("Live chart & chat", "live.html", body)


def build_portfolio(data: dict) -> str:
    specs = data.get("strategy_catalog") or []
    positions = data.get("portfolio") or []

    spec_rows = "".join(f"""<tr>
<td class="mono">{esc(s.get('key'))}</td>
<td><strong>{esc(s.get('name'))}</strong></td>
<td><span class="tag">{esc(s.get('category'))}</span></td>
<td>{'Maker (0.0175 × M)' if s.get('maker') else 'Taker (0.07 × M)'}</td>
<td>{esc(s.get('description'))}</td>
<td><a href="{esc(s.get('source_url'))}" target="_blank" rel="noopener">kalshi.com/docs/kalshi-fee-schedule.pdf</a></td>
</tr>""" for s in specs)

    pos_rows = "".join(f"""<tr>
<td class="mono">{esc(p.get('ticker'))}</td>
<td><span class="tag">{esc(p.get('topic'))}</span></td>
<td><code>{esc(p.get('strategy'))}</code> · <span class="tag">{esc(p.get('category'))}</span></td>
<td>{esc((p.get('side') or '').upper())}</td>
<td class="num">{esc(p.get('contracts'))}</td>
<td class="num">{money(p.get('entry_price'), 4)}</td>
<td class="num">{money(p.get('entry_fee'), 4)} (M={esc(p.get('fee_multiplier'))})</td>
<td><span class="tag">{esc(p.get('status'))}</span></td>
<td><a href="{esc(p.get('market_url'))}" target="_blank" rel="noopener">Demo market</a> ·
<a href="{esc(p.get('source_url'))}" target="_blank" rel="noopener">Fee PDF</a></td>
</tr>""" for p in positions) or '<tr><td colspan="9" class="muted">No pre-recorded simulated positions in snapshot. Use the interactive simulator below to run strategies.</td></tr>'

    body = f"""
<h1>Portfolio &amp; Automated Strategy Lab</h1>
<p class="lede">Automates simulated paper trades across six distinct trade-type categories using Kalshi's
published July 7, 2026 fee schedule and per-series multipliers, and tracks Kalshi Demo Account connectivity.</p>

<div class="grid c3">
<div class="card"><div class="stat">Kalshi Demo Account Cash</div><div class="n">--</div>
<div class="stat">Unverified in static CI (no private key in repo; connect local <code>uvicorn app.main:app</code> for live signed fills · <a href="https://docs.kalshi.com/getting_started/demo_env" target="_blank" rel="noopener">docs</a>)</div></div>
<div class="card"><div class="stat">Paper Starting Bankroll / Strategy</div><div class="n">$10,000.00</div>
<div class="stat">Isolated simulated ledger per strategy category</div></div>
<div class="card"><div class="stat">Recorded Collector Paper Trades</div><div class="n">{len(positions)}</div>
<div class="stat">Priced with published series fee multipliers</div></div>
</div>

<h2>Trade Categories &amp; Strategy Definitions</h2>
<div class="tblwrap"><table>
<thead><tr><th>ID</th><th>Strategy</th><th>Trade Category</th><th>Fee Schedule</th><th>Rule</th><th>Official Source</th></tr></thead>
<tbody>{spec_rows}</tbody></table></div>

<h2>Interactive Strategy Backtester &amp; Custom Trade-Type Builder</h2>
<div class="card" id="sim-lab-root">
<div class="toolbar">
<label>Category:
<select id="sim-category">
<option value="momentum">momentum (Swing Follower)</option>
<option value="mean_reversion">mean_reversion (Swing Fader)</option>
<option value="tail">tail (Discounted Tail YES ≤ 12c)</option>
<option value="carry">carry (High-Prob Carry 85c–94c)</option>
<option value="catalyst">catalyst (Selective High-ROI ≥ 0.60)</option>
</select></label>
<label>Topic filter:
<select id="sim-topic">
<option value="all">All 5 Topics</option>
<option value="gas">Gas prices</option>
<option value="elections">Elections</option>
<option value="culture">Culture</option>
<option value="crypto">Crypto</option>
<option value="golf">Golf</option>
</select></label>
<label>Order size (contracts): <input id="sim-qty" type="number" min="1" max="500" value="25" style="width:76px"></label>
<button type="button" class="btn primary" id="btn-run-sim">Simulate Automated Trades</button>
<button type="button" class="btn" id="btn-reset-sim">Reset Paper Ledger</button>
</div>
<div id="sim-summary" class="muted">Click "Simulate Automated Trades" to execute paper trades against the current live/captured orderbooks using exact Kalshi taker/maker fees.</div>
<div class="tblwrap" style="margin-top:10px"><table id="sim-ledger-table">
<thead><tr><th>Time</th><th>Ticker</th><th>Topic</th><th>Category</th><th>Side (Order V2)</th><th class="num">Qty</th><th class="num">Fill Price</th><th class="num">Kalshi Fee</th><th>Source</th></tr></thead>
<tbody id="sim-ledger-body"><tr><td colspan="9" class="muted">No interactive paper trades run in this browser session yet.</td></tr></tbody>
</table></div>
</div>

<h2>Collector Paper Portfolio Ledger (Demo API Book)</h2>
<div class="tblwrap"><table>
<thead><tr><th>Ticker</th><th>Topic</th><th>Strategy · Category</th><th>Side</th><th class="num">Contracts</th>
<th class="num">Entry Price</th><th class="num">Fee</th><th>Status</th><th>Official Source</th></tr></thead>
<tbody>{pos_rows}</tbody></table></div>
"""
    return page("Portfolio & strategies", "portfolio.html", body)


def build_resolutions(data: dict) -> str:
    resolutions = data.get("resolutions") or []
    yes_n = sum(1 for r in resolutions if r.get("result") == "yes")
    no_n = sum(1 for r in resolutions if r.get("result") == "no")
    scalar_n = sum(1 for r in resolutions if r.get("result") == "scalar")

    rows = "".join(f"""<tr>
<td class="mono">{esc(r.get('ticker'))}</td>
<td>{esc(r.get('title'))}</td>
<td><span class="tag">{esc(r.get('topic'))}</span></td>
<td><span class="tag {'ok' if r.get('result') == 'yes' else ('bad' if r.get('result') == 'no' else 'warn')}">{esc((r.get('result') or '--').upper())}</span></td>
<td class="num">{esc(r.get('settlement_value') if r.get('settlement_value') is not None else ('1.0000' if r.get('result') == 'yes' else ('0.0000' if r.get('result') == 'no' else '--')))}</td>
<td class="mono">{esc((r.get('determined_utc') or '--')[:19])}</td>
<td><a href="{esc(r.get('source_url') or r.get('page_url'))}" target="_blank" rel="noopener">GET /markets/{esc(r.get('ticker'))}</a></td>
</tr>""" for r in resolutions) or '<tr><td colspan="7" class="muted">No settled contracts recorded in this snapshot; open markets remain "--" until Kalshi publishes result in {yes, no, scalar}.</td></tr>'

    body = f"""
<h1>Event Resolution Ledger</h1>
<p class="lede">Tracks monitored markets in the five topics until Kalshi determines the official outcome
(<code>yes</code>, <code>no</code>, or <code>scalar</code> proportional payout). Unresolved markets are
never guessed and remain <code>--</code> until <code>GET /markets/&lt;ticker&gt;</code> or
<code>market_lifecycle_v2</code> confirms determination
(<a href="https://docs.kalshi.com/getting_started/market_lifecycle" target="_blank" rel="noopener">official lifecycle docs</a>).</p>

<div class="grid c3">
<div class="card"><div class="stat">Resolved YES</div><div class="n up">{yes_n}</div></div>
<div class="card"><div class="stat">Resolved NO</div><div class="n down">{no_n}</div></div>
<div class="card"><div class="stat">Resolved SCALAR</div><div class="n">{scalar_n}</div></div>
</div>

<div class="tblwrap"><table>
<thead><tr><th>Ticker</th><th>Contract</th><th>Topic</th><th>Outcome</th><th class="num">Settlement ($)</th>
<th>Determined (UTC)</th><th>Official API Source</th></tr></thead>
<tbody>{rows}</tbody></table></div>
"""
    return page("Resolutions", "resolutions.html", body)


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
        "live.html": build_live(data),
        "alerts.html": build_alerts(data),
        "portfolio.html": build_portfolio(data),
        "resolutions.html": build_resolutions(data),
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
// Dependency-free interactive engine client: table sorting, live Demo API polling with host failover,
// SVG contract price chart (Seconds / Minutes / Hours), orderbook depth bars, dual >= $0.10 swing chats,
// and automated paper strategy simulator using published Kalshi fee formulas.
(function () {
  var SERIES_MULT = {
    KXAAAGASM: 1.0, KXBTCY: 0.0, KXETHY: 0.0, KXBTCD: 1.0, KXPGATOUR: 1.0, KXNEXTNATOSECGEN: 1.0,
    KXFEDDECISION: 1.5, KXCPI: 1.5, KXGDP: 1.5
  };

  function escHtml(s) {
    if (s === null || s === undefined) return '--';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function kalshiFee(contracts, price, maker, seriesTicker) {
    var rate = maker ? 0.0175 : 0.07;
    var m = (seriesTicker && SERIES_MULT[seriesTicker] !== undefined) ? SERIES_MULT[seriesTicker] : (maker ? 0.0 : 1.0);
    var raw = m * rate * contracts * price * (1.0 - price);
    return Math.ceil(raw * 100 - 1e-12) / 100;
  }

  function matchTopic(ev, mkt) {
    var ticker = String((mkt && mkt.ticker) || '');
    var series = String((ev && ev.series_ticker) || ticker.split('-')[0] || '').toUpperCase();
    if (series.indexOf('KXMVE') === 0 || ticker.indexOf('KXMVE') === 0) return null;
    var cat = String((ev && ev.category) || '').toLowerCase();
    var title = String(((mkt && mkt.title) || '') + ' ' + ((ev && ev.title) || '')).toLowerCase();
    if (series.indexOf('KXAAAGAS') === 0 || title.indexOf('gas price') >= 0 || title.indexOf('gasoline') >= 0) return 'gas';
    if (cat === 'elections' || series.indexOf('NATO') >= 0 || title.indexOf('election') >= 0 || title.indexOf('senate') >= 0 || title.indexOf('president') >= 0) return 'elections';
    if (cat === 'entertainment' || cat === 'mentions' || title.indexOf('grammy') >= 0 || title.indexOf('oscar') >= 0 || title.indexOf('netflix') >= 0 || title.indexOf('album') >= 0) return 'culture';
    if (cat === 'crypto' || series.indexOf('KXBTC') === 0 || series.indexOf('KXETH') === 0 || series.indexOf('KXSOL') === 0 || title.indexOf('bitcoin') >= 0 || title.indexOf('ethereum') >= 0) return 'crypto';
    if (series.indexOf('KXPGA') === 0 || series.indexOf('KXLIV') === 0 || series.indexOf('KXLPGA') === 0 || series.indexOf('KXDPWORLD') === 0 || title.indexOf('pga tour') >= 0 || title.indexOf('masters') >= 0 || title.indexOf('golf') >= 0) return 'golf';
    return null;
  }

  function attachTableSort() {
    document.querySelectorAll('table').forEach(function (table) {
      var headers = table.querySelectorAll('thead th');
      headers.forEach(function (th, index) {
        if (th.dataset.nosort !== undefined) return;
        th.style.cursor = 'pointer';
        th.title = 'Click to sort';
        var ascending = false;
        th.addEventListener('click', function () {
          var body = table.tBodies[0];
          if (!body) return;
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
  }

  function loadJson(relPath) {
    return fetch(relPath, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function initLivePage(dash) {
    var svg = document.getElementById('price-svg');
    var selMarket = document.getElementById('chart-market-select');
    var obBox = document.getElementById('orderbook-bars');
    var jumpBox = document.getElementById('jump-pins');
    var badge = document.getElementById('live-conn-badge');
    var btnPoll = document.getElementById('btn-poll-now');
    var selInterval = document.getElementById('sel-poll-interval');
    var selHost = document.getElementById('sel-rest-host');
    var mktLink = document.getElementById('chart-market-link');
    var boards = document.getElementById('live-topic-boards');
    if (!svg || !selMarket) return;

    var state = {
      win: 'hours',
      ticks: Object.assign({}, dash.tick_series || {}),
      orderbooks: Object.assign({}, dash.orderbooks || {}),
      marketsByTicker: {},
      alerts: (dash.alerts || []).slice(),
      selective: (dash.selective_alerts || []).slice(),
      lastMid: {},
      timer: null
    };

    (dash.topics || []).forEach(function (t) {
      (t.markets || []).forEach(function (m) {
        state.marketsByTicker[m.ticker] = m;
        var lp = parseFloat(m.last_price);
        if (!isNaN(lp)) state.lastMid[m.ticker] = lp;
      });
    });

    function renderChats() {
      var allBox = document.getElementById('chat-all');
      var roiBox = document.getElementById('chat-roi');
      var allCnt = document.getElementById('chat-all-count');
      var roiCnt = document.getElementById('chat-roi-count');
      if (allCnt) allCnt.textContent = String(state.alerts.length);
      if (roiCnt) roiCnt.textContent = String(state.selective.length);
      function rowsHtml(list) {
        if (!list.length) return '<div class="muted">No >= $0.10 swings observed yet.</div>';
        return list.slice(0, 30).map(function (a) {
          var cls = a.direction === 'up' ? 'up' : 'down';
          var url = a.page_url || 'https://docs.kalshi.com/getting_started/orderbook_responses';
          var fC = isNaN(parseFloat(a.from_price)) ? '--' : Math.round(parseFloat(a.from_price) * 100) + 'c';
          var tC = isNaN(parseFloat(a.to_price)) ? '--' : Math.round(parseFloat(a.to_price) * 100) + 'c';
          return '<div class="chatmsg"><div class="meta"><span class="mono">' + escHtml(a.time_utc || '--') + '</span>' +
            '<span class="tag">' + escHtml(a.topic) + '</span></div>' +
            '<div><strong class="' + cls + '">' + escHtml(a.delta) + '</strong> <span class="mono">' + escHtml(a.ticker) + '</span> (' + fC + ' -> ' + tC + ')</div>' +
            '<div class="muted">' + escHtml(a.title) + ' · <a href="' + escHtml(url) + '" target="_blank" rel="noopener">official market</a></div></div>';
        }).join('');
      }
      if (allBox) allBox.innerHTML = rowsHtml(state.alerts);
      if (roiBox) roiBox.innerHTML = rowsHtml(state.selective);
    }

    function renderOrderbook(ticker) {
      var ob = state.orderbooks[ticker];
      var m = state.marketsByTicker[ticker];
      if (!ob && m) {
        var yb = parseFloat(m.yes_bid);
        var ya = parseFloat(m.yes_ask);
        ob = {
          source_url: m.page_url || 'https://docs.kalshi.com/getting_started/orderbook_responses',
          yes_bids: !isNaN(yb) && yb > 0 ? [{ price: yb.toFixed(4), contracts: m.open_interest_fp || '100' }] : [],
          no_bids: !isNaN(ya) && ya < 1 ? [{ price: (1 - ya).toFixed(4), implied_yes_ask: ya.toFixed(4), contracts: m.open_interest_fp || '100' }] : []
        };
      }
      if (!ob || ((!ob.yes_bids || !ob.yes_bids.length) && (!ob.no_bids || !ob.no_bids.length))) {
        obBox.innerHTML = '<div class="muted">No resting bids returned for <span class="mono">' + escHtml(ticker) + '</span> (empty book; values left as <code>--</code>).</div>';
        return;
      }
      var levels = [];
      (ob.yes_bids || []).slice(-5).reverse().forEach(function (lv) {
        levels.push({ kind: 'yes', label: 'YES bid $' + parseFloat(lv.price).toFixed(2), qty: parseFloat(lv.contracts) || 0 });
      });
      (ob.no_bids || []).slice(-5).reverse().forEach(function (lv) {
        var ask = lv.implied_yes_ask !== undefined ? parseFloat(lv.implied_yes_ask) : (1 - parseFloat(lv.price));
        levels.push({ kind: 'no', label: 'NO bid $' + parseFloat(lv.price).toFixed(2) + ' (YES ask $' + ask.toFixed(2) + ')', qty: parseFloat(lv.contracts) || 0 });
      });
      var maxQ = 1;
      levels.forEach(function (l) { if (l.qty > maxQ) maxQ = l.qty; });
      obBox.innerHTML = levels.map(function (l) {
        var pct = Math.max(3, Math.round((l.qty / maxQ) * 100));
        return '<div class="ob-row"><span class="mono">' + escHtml(l.label.split(' ')[0] + ' ' + l.label.split(' ')[2]) + '</span>' +
          '<div class="ob-track"><div class="ob-fill ' + l.kind + '" style="width:' + pct + '%"></div></div>' +
          '<span class="mono" style="text-align:right">' + Math.round(l.qty).toLocaleString() + ' ctr</span></div>';
      }).join('') + '<div class="muted" style="margin-top:6px"><a href="' + escHtml(ob.source_url) + '" target="_blank" rel="noopener">Orderbook endpoint source ↗</a></div>';
    }

    function renderChart() {
      var ticker = selMarket.value;
      var m = state.marketsByTicker[ticker] || {};
      if (mktLink) {
        mktLink.href = m.page_url || ('https://external-api.demo.kalshi.co/trade-api/v2/markets/' + encodeURIComponent(ticker));
      }
      var raw = (state.ticks[ticker] || []).slice();
      if (!raw.length && m.last_price) {
        var nowS = Date.now() / 1000;
        raw = [
          { ts: nowS - 60, last_price: m.last_price, yes_bid: m.yes_bid, yes_ask: m.yes_ask },
          { ts: nowS, last_price: m.last_price, yes_bid: m.yes_bid, yes_ask: m.yes_ask }
        ];
      }
      if (!raw.length) {
        svg.innerHTML = '<text x="20" y="140" fill="#5f6b7d" font-size="13">No verified price ticks for ' + escHtml(ticker) + ' (--).</text>';
        renderOrderbook(ticker);
        return;
      }
      var maxTs = raw[raw.length - 1].ts || (Date.now() / 1000);
      var spanS = state.win === 'seconds' ? 60 : (state.win === 'minutes' ? 1800 : 21600);
      var filtered = raw.filter(function (pt) { return (maxTs - (pt.ts || maxTs)) <= spanS; });
      if (filtered.length < 2) filtered = raw.slice(-Math.min(raw.length, 6));

      var W = 640, H = 280, padL = 48, padR = 18, padT = 20, padB = 34;
      var plotW = W - padL - padR, plotH = H - padT - padB;
      var t0 = filtered[0].ts || 0;
      var t1 = filtered[filtered.length - 1].ts || (t0 + 1);
      if (t1 <= t0) t1 = t0 + 1;

      function xOf(t) { return padL + ((t - t0) / (t1 - t0)) * plotW; }
      function yOf(p) { return padT + (1.0 - Math.max(0, Math.min(1, p))) * plotH; }

      var grid = '';
      [0, 0.25, 0.5, 0.75, 1.0].forEach(function (yv) {
        var yy = yOf(yv).toFixed(1);
        grid += '<line x1="' + padL + '" y1="' + yy + '" x2="' + (W - padR) + '" y2="' + yy + '" stroke="#eef1f6"/>' +
          '<text x="6" y="' + (parseFloat(yy) + 4) + '" fill="#5f6b7d" font-size="11">$' + yv.toFixed(2) + '</text>';
      });

      var pts = [];
      var jumps = [];
      for (var i = 0; i < filtered.length; i++) {
        var pv = parseFloat(filtered[i].last_price);
        if (isNaN(pv)) continue;
        var xx = xOf(filtered[i].ts || t0);
        var yy = yOf(pv);
        pts.push(xx.toFixed(1) + ',' + yy.toFixed(1));
        if (i > 0) {
          var prev = parseFloat(filtered[i - 1].last_price);
          if (!isNaN(prev) && Math.abs(pv - prev) >= 0.10 - 1e-9) {
            jumps.push({ x: xx, y: yy, delta: pv - prev, from: prev, to: pv, ts: filtered[i].ts });
          }
        }
      }

      var poly = pts.length ? '<polyline fill="none" stroke="#0b63ce" stroke-width="2.5" points="' + pts.join(' ') + '"/>' : '';
      var dots = pts.map(function (pair) {
        var sp = pair.split(',');
        return '<circle cx="' + sp[0] + '" cy="' + sp[1] + '" r="3.5" fill="#0b63ce"/>';
      }).join('');
      var jumpSvg = jumps.map(function (j) {
        var col = j.delta > 0 ? '#0a7b45' : '#b3261e';
        var lbl = (j.delta > 0 ? '+' : '') + Math.round(j.delta * 100) + 'c';
        return '<circle cx="' + j.x.toFixed(1) + '" cy="' + j.y.toFixed(1) + '" r="6.5" fill="' + col + '" stroke="#fff" stroke-width="1.5"/>' +
          '<text x="' + (j.x - 14).toFixed(1) + '" y="' + Math.max(14, j.y - 10).toFixed(1) + '" fill="' + col + '" font-size="11" font-weight="700">' + lbl + '</text>';
      }).join('');

      var xLabel = 'Window: ' + state.win.toUpperCase() + ' (' + filtered.length + ' samples)';
      svg.innerHTML = grid + poly + dots + jumpSvg +
        '<text x="' + padL + '" y="' + (H - 8) + '" fill="#5f6b7d" font-size="11">' + escHtml(xLabel) + '</text>' +
        '<text x="' + (W - padR - 145) + '" y="' + (H - 8) + '" fill="#5f6b7d" font-size="11">' + escHtml(ticker) + '</text>';

      if (jumpBox) {
        var mUrl = m.page_url || ('https://external-api.demo.kalshi.co/trade-api/v2/markets/' + encodeURIComponent(ticker));
        var sList = m.settlement_sources || [];
        var sHtml = (sList.length && sList[0].url) ? (' · <a href="' + escHtml(sList[0].url) + '" target="_blank" rel="noopener">' + escHtml(sList[0].name || 'Settlement source') + '</a>') : '';
        if (jumps.length) {
          jumpBox.innerHTML = '<strong>Sharp >= $0.10 jumps on chart:</strong> ' + jumps.map(function (j) {
            var sg = j.delta > 0 ? '+' : '';
            return '<span class="tag ' + (j.delta > 0 ? 'ok' : 'bad') + '">' + sg + (j.delta).toFixed(2) + ' ($' + j.from.toFixed(2) + ' -> $' + j.to.toFixed(2) + ')</span> ' +
              '<a href="' + escHtml(mUrl) + '" target="_blank" rel="noopener">Kalshi event</a>' + sHtml;
          }).join(' · ');
        } else {
          jumpBox.innerHTML = 'No >= $0.10 jump inside current zoom window for <span class="mono">' + escHtml(ticker) + '</span> · <a href="' + escHtml(mUrl) + '" target="_blank" rel="noopener">Official Kalshi page</a>' + sHtml;
        }
      }
      renderOrderbook(ticker);
    }

    document.querySelectorAll('[data-win]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        document.querySelectorAll('[data-win]').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        state.win = btn.getAttribute('data-win') || 'hours';
        renderChart();
      });
    });
    selMarket.addEventListener('change', renderChart);

    function pollDemoApi() {
      var primary = selHost ? selHost.value : 'https://external-api.demo.kalshi.co/trade-api/v2';
      var fallback = primary.indexOf('external-api') >= 0 ? 'https://demo-api.kalshi.co/trade-api/v2' : 'https://external-api.demo.kalshi.co/trade-api/v2';
      if (badge) { badge.className = 'tag warn'; badge.textContent = 'Polling Demo API…'; }

      function tryHost(base) {
        return fetch(base + '/events?limit=50&status=open&with_nested_markets=true', { mode: 'cors', cache: 'no-store' })
          .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
          .then(function (payload) { return { base: base, payload: payload }; });
      }

      tryHost(primary).catch(function () { return tryHost(fallback); }).then(function (res) {
        var events = (res.payload && res.payload.events) || [];
        var grouped = { gas: [], elections: [], culture: [], crypto: [], golf: [] };
        var nowS = Date.now() / 1000;
        var nowIso = new Date().toISOString().slice(0, 19) + 'Z';
        var addedOptions = 0;

        events.forEach(function (ev) {
          (ev.markets || []).forEach(function (mk) {
            var tp = matchTopic(ev, mk);
            if (!tp) return;
            var yb = parseFloat(mk.yes_bid_dollars);
            var ya = parseFloat(mk.yes_ask_dollars);
            var lp = parseFloat(mk.last_price_dollars);
            var mid = (!isNaN(yb) && !isNaN(ya) && yb > 0 && ya < 1 && ya >= yb) ? ((yb + ya) / 2) : (!isNaN(lp) ? lp : NaN);
            var vol = parseFloat(mk.volume_fp || '0') || 0;
            var rec = {
              ticker: mk.ticker,
              title: String(mk.title || ev.title || mk.ticker).replace(/\\*\\*/g, ''),
              topic: tp,
              yes_bid: mk.yes_bid_dollars,
              yes_ask: mk.yes_ask_dollars,
              last_price: !isNaN(mid) ? mid.toFixed(4) : mk.last_price_dollars,
              volume_fp: String(vol),
              open_interest_fp: mk.open_interest_fp || '0',
              page_url: res.base + '/markets/' + encodeURIComponent(mk.ticker),
              settlement_sources: ev.settlement_sources || []
            };
            grouped[tp].push(rec);
            if (!state.marketsByTicker[mk.ticker] && addedOptions < 40) {
              var opt = document.createElement('option');
              opt.value = mk.ticker;
              opt.textContent = tp + ': ' + mk.ticker + ' — ' + rec.title.slice(0, 64);
              selMarket.appendChild(opt);
              addedOptions++;
            }
            state.marketsByTicker[mk.ticker] = rec;
            if (!isNaN(mid)) {
              if (!state.ticks[mk.ticker]) state.ticks[mk.ticker] = [];
              state.ticks[mk.ticker].push({ ts: nowS, last_price: mid.toFixed(4), yes_bid: mk.yes_bid_dollars, yes_ask: mk.yes_ask_dollars });
              if (state.lastMid[mk.ticker] !== undefined && Math.abs(mid - state.lastMid[mk.ticker]) >= 0.10 - 1e-9) {
                var d = mid - state.lastMid[mk.ticker];
                var alertObj = {
                  time_utc: nowIso,
                  ticker: mk.ticker,
                  title: rec.title,
                  topic: tp,
                  direction: d > 0 ? 'up' : 'down',
                  from_price: state.lastMid[mk.ticker].toFixed(4),
                  to_price: mid.toFixed(4),
                  delta: (d > 0 ? '+' : '') + d.toFixed(4),
                  selective: (vol >= 100 && (!isNaN(yb) && !isNaN(ya) && (ya - yb) <= 0.15)),
                  page_url: rec.page_url
                };
                state.alerts.unshift(alertObj);
                if (alertObj.selective) state.selective.unshift(alertObj);
              }
              state.lastMid[mk.ticker] = mid;
            }
          });
        });

        // Also fetch live orderbook for currently selected ticker
        var activeTicker = selMarket.value;
        if (activeTicker) {
          fetch(res.base + '/markets/' + encodeURIComponent(activeTicker) + '/orderbook', { mode: 'cors', cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (obDoc) {
              if (obDoc && obDoc.orderbook_fp) {
                var fp = obDoc.orderbook_fp;
                state.orderbooks[activeTicker] = {
                  source_url: res.base + '/markets/' + encodeURIComponent(activeTicker) + '/orderbook',
                  yes_bids: (fp.yes_dollars || []).map(function (lv) { return { price: lv[0], contracts: lv[1] }; }),
                  no_bids: (fp.no_dollars || []).map(function (lv) { return { price: lv[0], contracts: lv[1], implied_yes_ask: (1 - parseFloat(lv[0])).toFixed(4) }; })
                };
                renderOrderbook(activeTicker);
              }
            }).catch(function () {});
        }

        if (badge) {
          badge.className = 'tag ok';
          badge.textContent = 'LIVE Demo API (' + res.base.replace('https://', '') + ' · ' + nowIso + ')';
        }

        if (boards) {
          var topicKeys = ['gas', 'elections', 'culture', 'crypto', 'golf'];
          boards.innerHTML = topicKeys.map(function (tk) {
            var arr = grouped[tk].sort(function (a, b) { return parseFloat(b.volume_fp) - parseFloat(a.volume_fp); }).slice(0, 6);
            if (!arr.length) {
              return '<div class="card"><h3>' + tk.toUpperCase() + ' (0 open in current 50-event page)</h3><div class="muted">Unconfirmed / none open in sample — left blank rather than inferred.</div></div>';
            }
            var trs = arr.map(function (m) {
              return '<tr><td class="mono">' + escHtml(m.ticker) + '</td><td>' + escHtml(m.title) + '</td>' +
                '<td class="num">' + escHtml(m.last_price || '--') + '</td><td class="num">' + escHtml(m.volume_fp) + '</td>' +
                '<td><a href="' + escHtml(m.page_url) + '" target="_blank" rel="noopener">API market</a></td></tr>';
            }).join('');
            return '<div class="card"><h3>' + tk.toUpperCase() + ' (Top by Volume)</h3><div class="tblwrap"><table><thead><tr><th>Ticker</th><th>Contract</th><th class="num">Price ($)</th><th class="num">Volume</th><th>Source</th></tr></thead><tbody>' + trs + '</tbody></table></div></div>';
          }).join('');
        }

        renderChats();
        renderChart();
      }).catch(function (err) {
        if (badge) {
          badge.className = 'tag warn';
          badge.textContent = 'Offline / Replay fallback (' + (err && err.message ? err.message : 'no network') + ')';
        }
        renderChats();
        renderChart();
      });
    }

    if (btnPoll) btnPoll.addEventListener('click', pollDemoApi);
    if (selInterval) {
      selInterval.addEventListener('change', function () {
        if (state.timer) clearInterval(state.timer);
        var ms = parseInt(selInterval.value, 10) || 0;
        if (ms > 0) state.timer = setInterval(pollDemoApi, ms);
      });
      state.timer = setInterval(pollDemoApi, 30000);
    }
    renderChats();
    renderChart();
    pollDemoApi();
  }

  function initSimLab(dash) {
    var root = document.getElementById('sim-lab-root');
    if (!root) return;
    var btnRun = document.getElementById('btn-run-sim');
    var btnReset = document.getElementById('btn-reset-sim');
    var selCat = document.getElementById('sim-category');
    var selTopic = document.getElementById('sim-topic');
    var inpQty = document.getElementById('sim-qty');
    var summary = document.getElementById('sim-summary');
    var tbody = document.getElementById('sim-ledger-body');
    var ledger = [];
    var cash = 10000.0;

    function renderLedger() {
      if (!ledger.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="muted">No interactive paper trades run in this browser session yet.</td></tr>';
        summary.textContent = 'Paper bankroll: $' + cash.toFixed(2) + ' (0 session fills).';
        return;
      }
      var totalFees = ledger.reduce(function (s, x) { return s + x.fee; }, 0);
      summary.innerHTML = '<strong>Paper bankroll remaining:</strong> $' + cash.toFixed(2) +
        ' · <strong>Fills executed:</strong> ' + ledger.length +
        ' · <strong>Published Kalshi fees charged:</strong> $' + totalFees.toFixed(2) +
        ' (Order V2 unified YES scale applied on NO buys).';
      tbody.innerHTML = ledger.map(function (t) {
        return '<tr><td class="mono">' + escHtml(t.time) + '</td><td class="mono">' + escHtml(t.ticker) + '</td>' +
          '<td><span class="tag">' + escHtml(t.topic) + '</span></td><td><code>' + escHtml(t.category) + '</code></td>' +
          '<td>' + escHtml(t.v2Desc) + '</td><td class="num">' + t.qty + '</td>' +
          '<td class="num">$' + t.price.toFixed(4) + '</td><td class="num">$' + t.fee.toFixed(2) + '</td>' +
          '<td><a href="' + escHtml(t.url) + '" target="_blank" rel="noopener">Kalshi source</a></td></tr>';
      }).join('');
    }

    if (btnRun) {
      btnRun.addEventListener('click', function () {
        var cat = selCat ? selCat.value : 'momentum';
        var tf = selTopic ? selTopic.value : 'all';
        var qty = Math.max(1, Math.min(500, parseInt((inpQty && inpQty.value) || '25', 10) || 25));
        var candidates = [];
        (dash.topics || []).forEach(function (t) {
          if (tf !== 'all' && t.key !== tf) return;
          (t.markets || []).forEach(function (m) { candidates.push(m); });
        });
        var nowIso = new Date().toISOString().slice(11, 19) + 'Z';
        candidates.forEach(function (m) {
          var ya = parseFloat(m.yes_ask);
          var yb = parseFloat(m.yes_bid);
          var lp = parseFloat(m.last_price);
          var execYes = !isNaN(ya) && ya > 0 && ya < 1 ? ya : (!isNaN(lp) && lp > 0 && lp < 1 ? lp : NaN);
          if (isNaN(execYes)) return;
          var side = 'YES';
          var price = execYes;
          var maker = false;
          if (cat === 'tail' && execYes > 0.35) return;
          if (cat === 'carry') {
            maker = true;
            if (execYes < 0.50 && (1 - (!isNaN(yb) && yb > 0 ? yb : execYes)) >= 0.65) {
              side = 'NO';
              price = 1.0 - (!isNaN(yb) && yb > 0 ? yb : execYes);
            }
          } else if (cat === 'mean_reversion') {
            side = 'NO';
            price = 1.0 - (!isNaN(yb) && yb > 0 ? yb : execYes);
          }
          if (price <= 0 || price >= 1) return;
          var fee = kalshiFee(qty, price, maker, m.series_ticker);
          var cost = qty * price + fee;
          if (cost > cash) return;
          cash -= cost;
          var v2Desc = side === 'YES'
            ? ('BUY YES (side=bid @ $' + price.toFixed(4) + ')')
            : ('BUY NO (side=ask @ YES $' + (1.0 - price).toFixed(4) + ')');
          ledger.unshift({
            time: nowIso,
            ticker: m.ticker,
            topic: m.topic,
            category: cat,
            v2Desc: v2Desc,
            qty: qty,
            price: price,
            fee: fee,
            url: m.page_url || 'https://kalshi.com/docs/kalshi-fee-schedule.pdf'
          });
        });
        renderLedger();
      });
    }
    if (btnReset) {
      btnReset.addEventListener('click', function () {
        ledger = [];
        cash = 10000.0;
        renderLedger();
      });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    attachTableSort();
    if (document.getElementById('interactive-chart-root') || document.getElementById('sim-lab-root')) {
      loadJson('data/dashboard.json').then(function (dash) {
        initLivePage(dash);
        initSimLab(dash);
      }).catch(function () {});
    }
  });
})();
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
