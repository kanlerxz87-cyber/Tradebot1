#!/usr/bin/env python3
"""Generate ``live.html`` — the published page for the live desk.

GitHub Pages serves static files only, so the process in ``live/`` cannot run there.
Rather than publish a screenshot, this page publishes what *can* be verified from the
repository: the exact routes, the two data modes with their disclosures, the current
captured snapshot as source-linked tables, and the verification log for every API fact the
desk depends on.

    python3 live/build_page.py            # write live.html
    python3 live/build_page.py --check    # fail if live.html is stale
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "live"))
from desk import DEMO_REST, DEMO_WS, FEE_RATE_MAKER, clean_title, FEE_RATE_TAKER, THRESHOLD, TOPIC_LABELS  # noqa: E402

OUT = ROOT / "live.html"
SNAPSHOT = ROOT / "docs/desk/data/latest.json"

VERIFICATION = [
    ("Demo REST base URL and alternate", "https://external-api.demo.kalshi.co/trade-api/v2",
     "https://docs.kalshi.com/getting_started/api_environments", "2026-11-22"),
    ("Demo WebSocket URL and alternate", "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
     "https://docs.kalshi.com/getting_started/api_environments", "2026-11-22"),
    ("Dedicated user hosts for fill/order updates (not used here)",
     "wss://user-ws.demo.kalshi.co/trade-api/ws/v2",
     "https://docs.kalshi.com/getting_started/api_environments", "2026-11-22"),
    ("Order book returns bids only; yes_ask = $1 − best NO bid; arrays ascending, best bid last; no auth",
     "orderbook_fp → yes_dollars / no_dollars, [price, count] as strings",
     "https://docs.kalshi.com/getting_started/orderbook_responses", "2026-11-22"),
    ("Market statuses are initialized / active / inactive / closed / determined / disputed / amended / finalized",
     "open and settled are *filter* values that map to active and finalized",
     "https://docs.kalshi.com/getting_started/market_lifecycle", "2026-11-22"),
    ("result is yes, no or scalar; settled markets appear as finalized with settlement_ts set",
     "used to render resolution; no other value is invented",
     "https://docs.kalshi.com/getting_started/market_lifecycle", "2026-11-22"),
    ("GET /markets on the demo root returns yes_bid_dollars, yes_ask_dollars, last_price_dollars, "
     "volume_24h_fp, open_interest_fp, status, result, close_time, rules_primary",
     "field names read from a live demo response for KXAAAGASM-26NOV30-5.00 (bid $0.00 / ask $1.00, i.e. a placeholder book)",
     "https://external-api.demo.kalshi.co/trade-api/v2/markets?status=open&limit=1&series_ticker=KXAAAGASM", "2026-11-22"),
    ("Demo exchange status reports four exchange indexes, all active",
     "GET /exchange/status returned exchange_active true",
     "https://external-api.demo.kalshi.co/trade-api/v2/exchange/status", "2026-11-22"),
]

UNVERIFIED = [
    ("Fee schedule (taker 0.07 / maker 0.0175 in the model)", "https://docs.kalshi.com/getting_started/fees",
     "The page did not load from the authoring sandbox on 2026-11-22. /api/meta reports the model as "
     "UNVERIFIED and no page claims the fee is confirmed."),
    ("WebSocket handshake and channels", "https://docs.kalshi.com/getting_started/quick_start_websockets",
     "The desk ships an SSE push channel that runs on the standard library; the Kalshi WS endpoint is "
     "documented in /api/meta but was never connected to from here."),
    ("Credentialed demo account, balances and orders",
     "https://docs.kalshi.com/getting_started/api_keys",
     "No API key exists in this repository. No order path is implemented: the server has no POST handler "
     "and the desk never calls /portfolio/*."),
    ("Whether the captured demo quotes match production",
     "https://docs.kalshi.com/getting_started/demo_env",
     "The demo environment is documented as capable of differing from production. The anchor capture in "
     "this branch (docs/desk/data/latest.json) came from the production root, and the page says so."),
]


def load_topics() -> tuple[dict, str, str]:
    """Return (topics, generated_at, rest_base) from the committed capture."""
    if not SNAPSHOT.exists():
        return {}, "", ""
    payload = json.loads(SNAPSHOT.read_text())
    return (
        payload.get("topics") or {},
        payload.get("generated_at") or "",
        payload.get("rest_base") or "",
    )


def count(value) -> str:
    try:
        return format(float(value), ",.0f")
    except (TypeError, ValueError):
        return "—"


def money(value) -> str:
    try:
        return "$" + format(float(value), ",.0f")
    except (TypeError, ValueError):
        return "—"


def cents(value) -> str:
    try:
        return f"{float(value) * 100:.1f}¢"
    except (TypeError, ValueError):
        return "—"


def topic_rows(topics: dict) -> str:
    blocks = []
    for topic, label in TOPIC_LABELS.items():
        block = topics.get(topic) or {}
        markets = sorted(block.get("markets") or [], key=lambda m: m.get("notional_24h_est") or 0, reverse=True)[:6]
        rows = "".join(
            f"<tr><td>{html.escape(clean_title(m.get('title')) or str(m.get('ticker') or ''))}"
            f"<br><code>{html.escape(str(m.get('ticker') or ''))}</code></td>"
            f"<td class='num'>{cents(m.get('yes_bid'))}</td>"
            f"<td class='num'>{cents(m.get('yes_ask'))}</td>"
            f"<td class='num'>{cents(m.get('mid'))}</td>"
            f"<td class='num'>{count(m.get('volume_24h'))}</td>"
            f"<td class='num'>{money(m.get('notional_24h_est'))}</td>"
            f"<td class='num'>{count(m.get('top_book_contracts'))}</td>"
            f"<td><a href='{html.escape(str(m.get('api_url') or ''))}' rel='noopener noreferrer'>API ↗</a> "
            f"<a href='{html.escape(str(m.get('series_page_url') or ''))}' rel='noopener noreferrer'>page ↗</a></td></tr>"
            for m in markets
        ) or "<tr><td colspan='8' class='empty'>No market captured for this topic.</td></tr>"
        blocks.append(f"""
      <h3>{html.escape(label)} <span class="dim">· {block.get('markets_count', '—')} markets in the capture</span></h3>
      <div class="wrap"><table>
        <thead><tr><th>Contract</th><th class="num">YES bid</th><th class="num">YES ask</th><th class="num">Mid</th>
        <th class="num">24h contracts</th><th class="num">Est. 24h $</th><th class="num">At best</th><th>Source</th></tr></thead>
        <tbody>{rows}</tbody>
      </table></div>""")
    return "".join(blocks)


def render() -> str:
    topics, captured_at, rest_base = load_topics()
    verification_rows = "".join(
        f"<tr><td>{html.escape(fact)}</td><td>{html.escape(observed)}</td>"
        f"<td><a href='{html.escape(url)}' rel='noopener noreferrer'>{html.escape(url.split('//')[-1][:52])} ↗</a></td>"
        f"<td class='num'>{checked}</td></tr>"
        for fact, observed, url, checked in VERIFICATION
    )
    unverified_rows = "".join(
        f"<tr><td>{html.escape(item)}</td><td><a href='{html.escape(url)}' rel='noopener noreferrer'>source ↗</a></td>"
        f"<td class='dim'>{html.escape(note)}</td></tr>"
        for item, url, note in UNVERIFIED
    )
    routes = [
        ("GET /api/meta", "mode, disclosure, threshold, strategies, fees, endpoints, sources"),
        ("GET /api/state", "topics → events → markets, alerts, portfolio, resolution watch"),
        ("GET /api/series?ticker=&seconds=", "price history for the chart window (30s–4h)"),
        ("GET /api/book?ticker=", "YES bid/ask ladder with resting contracts at each price"),
        ("GET /api/stream", "Server-Sent Events: one tick message per second"),
        ("GET /api/health", "liveness"),
    ]
    route_rows = "".join(f"<tr><td><code>{html.escape(r)}</code></td><td>{html.escape(d)}</td></tr>" for r, d in routes)
    requirements = [
        ("Highest-dollar live events, five topics only",
         "Topic tabs for gas, elections, culture, crypto and golf; events grouped inside each topic and ranked by "
         "estimated 24h notional", "shipped"),
        ("Alert on swings ≥ $0.10 either direction",
         "Server-side detector, inclusive and symmetric, on the mid of a two-sided book with a last-trade fallback", "shipped"),
        ("Two scrolling chats (all moves, model-filtered)",
         "Two feeds; the filtered one uses a published six-part screen, not a forecast", "shipped"),
        ("Price chart: time on x, contract price on y, choose seconds/minutes/hours",
         "Canvas chart with 30s, 1m, 5m, 15m, 1h and 4h windows", "shipped"),
        ("Liquidity: contracts available at a given price",
         "Order-book ladder with a bar per level, plus contracts within 5¢ of the best bid", "shipped"),
        ("Track events until resolved; show YES/NO",
         "Resolution watch by close time; resolved table filled only from Kalshi's own status/result", "shipped"),
        ("Automate simulated trades and analyse by trade type",
         "Four rules, per-strategy / topic / price-band / exit-reason analytics, reconciled book", "shipped"),
        ("Track portfolio performance on the Kalshi demo account",
         "Not connected: no API key exists. The simulated book is clearly labelled and is not the demo account", "flagged"),
        ("Live charts with links to what may have caused a jump",
         "Every alert links to the contract, its Kalshi page and a news search, and states that no cause is asserted", "shipped"),
        ("No manual input",
         "The desk ticks, alerts, trades and settles on its own; the only interaction is choosing what to chart", "shipped"),
    ]
    requirement_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(how)}</td>"
        f"<td><span class='pill {status}'>{status}</span></td></tr>"
        for name, how, status in requirements
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live desk — Tradebot1</title>
<meta name="description" content="The live Kalshi desk: a dependency-free server and interactive dashboard for five topics, $0.10 swing alerts, price and liquidity charts, a simulated book and resolution tracking. Routes, modes, and the verification log.">
<link rel="stylesheet" href="docs/desk/assets/css/site.css">
<style>
  .live-wrap {{ max-width: 1180px; margin: 0 auto; padding: 34px 20px 70px; }}
  .live-wrap h1 {{ font-size: 28px; letter-spacing: -.02em; margin: 8px 0 8px; }}
  .live-wrap h2 {{ font-size: 17px; margin: 30px 0 8px; }}
  .live-wrap h3 {{ font-size: 13.5px; margin: 18px 0 6px; }}
  .lede {{ color: var(--text-dim); max-width: 84ch; line-height: 1.65; }}
  .wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
  th, td {{ text-align: left; padding: 7px 9px; border-bottom: 1px solid var(--line); vertical-align: top; }}
  th {{ font-size: 10px; letter-spacing: .07em; text-transform: uppercase; color: var(--text-dim); }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  code {{ font-family: var(--mono); font-size: 11px; color: var(--accent); }}
  .dim {{ color: var(--text-dim); }}
  .empty {{ color: var(--text-dim); }}
  .pill {{ font-size: 10px; text-transform: uppercase; letter-spacing: .06em; padding: 2px 7px; border-radius: 999px; border: 1px solid currentColor; }}
  .pill.shipped {{ color: var(--up); }} .pill.flagged {{ color: var(--warn); }}
  .note {{ border-left: 2px solid var(--warn); padding: 8px 12px; background: rgba(255,196,107,.07); font-size: 12px; color: var(--text-dim); margin: 12px 0; }}
  pre {{ background: rgba(255,255,255,.04); padding: 12px; border-radius: 8px; overflow-x: auto; font-size: 12px; }}
  .two {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 18px; }}
  .card {{ border: 1px solid var(--line); border-radius: 10px; padding: 14px; background: var(--panel); }}
  .card h3 {{ margin-top: 0; }}
  .card p {{ font-size: 12.5px; color: var(--text-dim); line-height: 1.6; }}
</style>
</head>
<body>
<main class="live-wrap">
  <p class="dim"><a href="index.html">← All dashboards</a> · <a href="qa.html">Audit</a> · Kalshi research, not advice</p>
  <h1>Live desk: one process, five topics, two alert chats</h1>
  <p class="lede">A dependency-free Python server (<code>live/</code>) plus a single-page dashboard. It tracks
  gas prices, elections, culture, crypto and golf; alerts on every move of
  <b>{THRESHOLD * 100:.0f}¢ ($0.10) or more</b>
  in either direction; charts price against time with selectable windows; shows resting contracts at each
  price; runs four automatic strategies in a simulated book; and keeps each market until Kalshi finalises it.
  This page is the published record of what it does and what has been verified — the process itself runs on
  a machine with network access to Kalshi, which GitHub Pages does not provide.</p>

  <div class="note"><b>Two data modes, always labelled.</b> <code>--mode live</code> polls the official demo
  REST API and shows only quotes that came from a response. <code>--mode simulated</code> (the default when
  there is no egress) replays a seeded random walk anchored to the committed capture so the mechanics can be
  inspected offline. Every surface names which one is running, and the simulation's alerts are never
  presented as Kalshi events.</div>

  <h2>Run it</h2>
<pre>python3 live/server.py --port 8000                 # auto: try live, fall back to labelled simulation
python3 live/server.py --mode live --interval 1    # poll the demo REST root
python3 -m unittest discover -s live/tests         # 29 tests, no network needed
python3 live/build_page.py --check                 # this page is current</pre>

  <h2>Surface</h2>
  <div class="wrap"><table>
    <thead><tr><th>Route</th><th>Returns</th></tr></thead>
    <tbody>{route_rows}</tbody>
  </table></div>
  <p class="dim" style="font-size:12px">REST root <code>{DEMO_REST}</code> · WebSocket endpoint
  <code>{DEMO_WS}</code> (documented, not connected by this process). SSE is used for push because the
  standard library cannot speak WebSocket and adding a dependency would break the "runs anywhere" property.</p>

  <h2>Requirements → implementation</h2>
  <div class="wrap"><table>
    <thead><tr><th>Requirement</th><th>How this build meets it</th><th>Status</th></tr></thead>
    <tbody>{requirement_rows}</tbody>
  </table></div>

  <h2>The snapshot the dashboard starts from</h2>
  <p class="dim" style="font-size:12px">Captured {html.escape(captured_at or "—")} from
  <code>{html.escape(rest_base or "the committed research-desk capture")}</code> — the research desk's
  capture, recorded in <code>docs/desk/data/latest.json</code>.
  Rows are the top six per topic by estimated 24h notional — a derived figure (price × 24h contracts), not
  exchange-reported turnover. Every row links to the API URL and the public market page it came from.</p>
  {topic_rows(topics)}

  <h2>Verification log — checked against official sources</h2>
  <div class="wrap"><table>
    <thead><tr><th>Fact</th><th>What was observed</th><th>Official source</th><th class="num">Checked</th></tr></thead>
    <tbody>{verification_rows}</tbody>
  </table></div>

  <h2>Unverified — do not read these as confirmed</h2>
  <div class="wrap"><table>
    <thead><tr><th>Item</th><th>Source</th><th>Why it is not confirmed</th></tr></thead>
    <tbody>{unverified_rows}</tbody>
  </table></div>
  <p class="dim" style="font-size:12px">Fee constants in the engine are taker {FEE_RATE_TAKER} and maker
  {FEE_RATE_MAKER}. They are the published general schedule, but the schedule page could not be re-read
  from the authoring sandbox, so <code>/api/meta</code> reports <code>verified: false</code> and no page
  claims otherwise. Full finding list, including cross-implementation issues: <a href="qa.html">the audit</a>.</p>

  <h2>Corrections to earlier notes in this repository</h2>
  <div class="two">
    <div class="card">
      <h3>Status vocabulary</h3>
      <p>An earlier register read the documentation as saying markets are <code>open</code> or
      <code>settled</code> and flagged the API's <code>active</code>/<code>finalized</code> as a
      contradiction. The lifecycle page lists <code>active</code> and <code>finalized</code> as the statuses,
      and <code>open</code>/<code>settled</code> as <i>filter</i> values that map onto them. The API is
      consistent with its documentation; the earlier reading was not.</p>
    </div>
    <div class="card">
      <h3>result can be scalar</h3>
      <p>The lifecycle page states <code>result</code> is <code>yes</code>, <code>no</code> or
      <code>scalar</code>. A resolver that accepts only yes/no will mis-handle a scalar market, so this desk
      carries the value through unchanged and never coerces it.</p>
    </div>
  </div>

  <h2>What it will not do</h2>
  <ul class="lede">
    <li>Place an order. There is no POST handler, no order path and no credential read anywhere in <code>live/</code>.</li>
    <li>Invent a cause for a price move. Each alert shows the rule text, the contract link and a news
    <i>search</i>, labelled as a search.</li>
    <li>Present a simulated price as a Kalshi quote. The mode badge and the banner say which is running, and
    the JSON carries <code>simulated: true</code> on every simulated alert.</li>
    <li>Treat a resolved market as open or vice versa: only Kalshi's own status and result fill that table.</li>
  </ul>

  <p class="dim" style="font-size:12px;margin-top:22px">Sources:
    <a href="https://docs.kalshi.com/getting_started/api_environments" rel="noopener noreferrer">environments</a> ·
    <a href="https://docs.kalshi.com/getting_started/orderbook_responses" rel="noopener noreferrer">order book</a> ·
    <a href="https://docs.kalshi.com/getting_started/market_lifecycle" rel="noopener noreferrer">lifecycle</a> ·
    <a href="https://docs.kalshi.com/getting_started/fees" rel="noopener noreferrer">fees</a> ·
    <a href="https://docs.kalshi.com/getting_started/quick_start_websockets" rel="noopener noreferrer">WebSockets</a> ·
    <a href="https://github.com/kanlerxz87-cyber/Tradebot1/tree/main/live" rel="noopener noreferrer">source</a>.
    Generated {dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")} by <code>live/build_page.py</code>.
  </p>
</main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render()
    if args.check:
        current = OUT.read_text() if OUT.exists() else ""
        # The generated timestamp changes every run; compare everything else.
        def body(text: str) -> str:
            return text.split("Generated ")[0]
        if body(current) != body(rendered):
            print("live.html is stale — run: python3 live/build_page.py")
            return 1
        print("live.html is current")
        return 0
    OUT.write_text(rendered)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(rendered)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
