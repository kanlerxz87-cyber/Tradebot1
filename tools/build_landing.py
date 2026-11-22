"""Render the root landing page (index.html) from the published desk snapshot.

Why a generator and not a hand-written page
-------------------------------------------
The landing page is the one shared surface every session's work is reachable from, and the brief
requires that every table row carry a source link and that no value be inferred. A generator makes
both properties checkable in CI: `--check` fails the build if `index.html` is not byte-identical to
a fresh render, so a stale or hand-edited table cannot reach the published site.

Inputs (all read-only, all produced by the existing collector):
    docs/desk/data/latest.json     markets, events, topics, performance, errors
    docs/desk/data/alerts.json     >= $0.10 swing archive
    docs/desk/data/resolved.json   settled markets with the exchange result
    docs/desk/data/paper.json      simulated book

Output:
    index.html   (from tools/landing_template.html)

Usage:
    python tools/build_landing.py           # write index.html
    python tools/build_landing.py --check   # exit 1 if index.html is stale
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESK = ROOT / "docs" / "desk" / "data"
TEMPLATE = ROOT / "tools" / "landing_template.html"
OUT = ROOT / "index.html"

TOPIC_ORDER = ["gas", "elections", "culture", "crypto", "golf"]
TOPIC_LABEL = {
    "gas": "Gas prices",
    "elections": "Elections",
    "culture": "Culture",
    "crypto": "Crypto",
    "golf": "Golf",
}
TOPIC_PAGE = {
    "gas": "docs/desk/topics/gas-prices.html",
    "elections": "docs/desk/topics/elections.html",
    "culture": "docs/desk/topics/culture.html",
    "crypto": "docs/desk/topics/crypto.html",
    "golf": "docs/desk/topics/golf.html",
}
# Each topic card names the rule that places a series in it, so the mapping is auditable.
TOPIC_RULE = {
    "gas": "Economics + Commodities categories, gas-price keyword fallback",
    "elections": "official Elections category",
    "culture": "official Entertainment and Social categories — there is no Culture category",
    "crypto": "official Crypto category",
    "golf": "Sports category, Golf tag, keyword fallback",
}
THRESHOLD = 0.10


# --------------------------------------------------------------------- helpers
def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def num(value, digits=0) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def usd(value, digits=0) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    try:
        return "${:,.{d}f}".format(float(value), d=digits)
    except (TypeError, ValueError):
        return "—"


def cents(value) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    try:
        return f"{round(float(value) * 100)}¢"
    except (TypeError, ValueError):
        return "—"


def signed(value, digits=2) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if n > 0 else ("−" if n < 0 else "")
    return f"{sign}{abs(n):,.{digits}f}"


def clamp(text, limit) -> str:
    # Kalshi titles arrive with markdown emphasis ("**gas prices**"). Stripping the markers is a
    # presentation change only; no character of the market's own wording is added or removed.
    text = ("" if text is None else str(text)).replace("**", "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def load(name):
    path = DESK / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def age_text(snapshot) -> str:
    stamp = snapshot.get("generated_at") if snapshot else None
    if not stamp:
        return "no snapshot yet"
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return "unknown age"
    seconds = max(0, int((datetime.now(timezone.utc) - then).total_seconds()))
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{round(seconds / 60)}m ago"
    if seconds < 172800:
        return f"{round(seconds / 3600)}h ago"
    return f"{round(seconds / 86400)}d ago"


def stale(snapshot) -> bool:
    stamp = snapshot.get("generated_at") if snapshot else None
    if not stamp:
        return True
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - then).total_seconds() > 1800


# --------------------------------------------------------------- data shaping
def topic_events(snapshot, topic_id):
    """Events for one topic, or all events when topic_id is None."""
    topics = (snapshot or {}).get("topics") or {}
    if topic_id is None:
        pool = []
        for key, block in topics.items():
            pool.extend(block.get("events") or [])
        return pool
    block = topics.get(topic_id) or {}
    return list(block.get("events") or [])


def events_sorted(events):
    return sorted(events, key=lambda e: (e.get("notional_24h_est") or 0), reverse=True)


# ------------------------------------------------------------------ fragments
def render_status(snapshot) -> str:
    fresh = not stale(snapshot)
    alerts = (snapshot or {}).get("alerts") or []
    return (
        '<div class="status-line">'
        f'<span class="pulse {"on" if fresh else "off"}" aria-hidden="true"></span>'
        f'<span><b>{"Published snapshot" if snapshot else "No snapshot"}</b> · {esc(age_text(snapshot))} · '
        f'{num((snapshot or {}).get("market_count"))} markets · {num(len(alerts))} new alerts</span>'
        f'<span class="chip {"ok" if fresh else "warn"}">{"fresh" if fresh else "over 30 min old"}</span>'
        "</div>"
    )


def render_snapshot_note(snapshot) -> str:
    if not snapshot:
        return (
            '<div class="banner warn" style="margin-top:14px"><b>Waiting for the first collection.</b>'
            '<span class="grow">No desk snapshot is published yet. The tables below stay empty rather than '
            "showing invented values. Run <code>python -m kalshi_trader.cli collect</code> or wait for the "
            "next scheduled cycle.</span></div>"
        )
    env = "demo" if snapshot.get("data_env") == "demo" else "production"
    base = snapshot.get("rest_base") or ""
    demo = snapshot.get("demo") or {}
    connected = bool(demo.get("connected"))
    return (
        '<div class="banner" style="margin-top:14px">'
        f"<b>Data source: Kalshi {esc(env)}.</b>"
        f'<span class="grow">Read from <code>{esc(base)}</code> and refreshed by a scheduled collector. '
        "The page you are reading is static hosting; this banner and the numbers below update when a new "
        f"cycle is published. Demo account: <b>{'connected' if connected else 'not connected'}</b> — the book is simulated."
        "</span></div>"
    )


def render_kpis(snapshot, alerts, paper) -> str:
    topics = (snapshot or {}).get("topics") or {}
    notional = sum((t.get("notional_24h_est") or 0) for t in topics.values())
    open_interest = sum((t.get("open_interest") or 0) for t in topics.values())
    perf = ((snapshot or {}).get("performance") or {}).get("headline") or {}
    headline = (paper or {}).get("headline") or {}
    equity = headline.get("equity", perf.get("equity"))
    pnl = headline.get("total_pnl", perf.get("total_pnl"))
    picks = len((snapshot or {}).get("picks") or [])
    demo_connected = bool(((snapshot or {}).get("demo") or {}).get("connected"))

    tiles = [
        ("Tracked markets", num((snapshot or {}).get("market_count")), f"{num((snapshot or {}).get('event_count'))} open events scanned"),
        ("Est. 24h notional · 5 topics", usd(notional), "last price × 24h volume, derived"),
        ("Open interest", num(open_interest), "sum of open_interest_fp"),
        ("Swing alerts archived", num(len(alerts)), f"threshold ≥ {usd(THRESHOLD, 2)}"),
        ("High-ROI picks this cycle", num(picks), "model heuristic-v1, not a forecast"),
        (
            "Paper equity",
            usd(equity, 2),
            f"{signed(pnl)} vs {usd(headline.get('bankroll_start', perf.get('bankroll_start')), 2)} start",
            "up" if (pnl or 0) >= 0 else "down",
        ),
    ]
    cells = []
    for tile in tiles:
        label, value, foot = tile[0], tile[1], tile[2]
        cls = tile[3] if len(tile) > 3 else ""
        cells.append(
            '<div class="card">'
            f'<span class="label">{esc(label)}</span>'
            f'<span class="value {cls}">{value}</span>'
            f"<span class=\"foot\">{foot}</span>"
            "</div>"
        )
    demo_line = (
        '<div class="banner warn" style="margin:2px 0 0"><b>Demo account not connected.</b>'
        '<span class="grow">Positions, balances and fills below are simulated in an internal ledger. '
        "A Kalshi demo API key can only be created by the account holder, so nothing was invented in its place."
        "</span></div>"
        if not demo_connected
        else ""
    )
    return '<div class="kpi">' + "".join(cells) + "</div>" + demo_line


def render_topic_cards(snapshot) -> str:
    topics = (snapshot or {}).get("topics") or {}
    cards = []
    for topic_id in TOPIC_ORDER:
        block = topics.get(topic_id) or {}
        events = events_sorted(block.get("events") or [])
        rows = []
        for event in events[:3]:
            rows.append(
                "<li>"
                f'<span class="amt">{usd(event.get("notional_24h_est"))}</span> '
                f'{esc(clamp(event.get("title"), 62))}'
                "</li>"
            )
        if not rows:
            rows.append("<li>No open events in the current snapshot.</li>")
        cards.append(
            '<a class="topic" href="' + TOPIC_PAGE[topic_id] + '">'
            f'<h3><span class="chip {topic_id}">{esc(TOPIC_LABEL[topic_id])}</span></h3>'
            f'<div class="tstats"><span><b>{num(block.get("markets_count"))}</b> markets</span>'
            f'<span><b>{num(len(events))}</b> events</span>'
            f'<span><b>{usd(block.get("notional_24h_est"))}</b> est. 24h</span></div>'
            "<ol>" + "".join(rows) + "</ol>"
            f'<span class="go">Open the {esc(TOPIC_LABEL[topic_id].lower())} desk →</span>'
            f'<div class="note" style="font-size:10px;color:var(--muted)">{esc(TOPIC_RULE[topic_id])}</div>'
            "</a>"
        )
    return "\n".join(cards)


def render_leaderboard(snapshot, limit=10) -> str:
    events = events_sorted(topic_events(snapshot, None))[:limit]
    if not events:
        return '<div class="chat-empty">No open events in the current snapshot.</div>'
    head = (
        "<table><thead><tr>"
        "<th>Event</th><th>Topic</th><th class=\"num\">Markets</th>"
        '<th class="num">Est. 24h $</th><th class="num">Open interest</th><th>Closes</th><th>Source</th>'
        "</tr></thead><tbody>"
    )
    rows = []
    for event in events:
        topic = event.get("topic") or ""
        rows.append(
            "<tr>"
            f'<td><span class="title">{esc(clamp(event.get("title"), 84))}</span>'
            f'<span class="meta mono">{esc(event.get("event_ticker"))}</span></td>'
            f'<td><span class="chip {esc(topic)}">{esc(TOPIC_LABEL.get(topic, topic))}</span></td>'
            f'<td class="num">{num(event.get("markets_count"))}</td>'
            f'<td class="num">{usd(event.get("notional_24h_est"))}</td>'
            f'<td class="num">{num(event.get("open_interest"))}</td>'
            f'<td class="meta">{esc(str(event.get("close_time") or "—")[:16].replace("T", " "))}</td>'
            '<td class="src"><a href="' + esc(event.get("series_page_url") or "#") + '" target="_blank" rel="noopener">Kalshi</a></td>'
            "</tr>"
        )
    return head + "".join(rows) + "</tbody></table>"


def render_chat(alerts, model_only, limit=40) -> str:
    if model_only:
        alerts = [a for a in alerts if (a.get("model") or {}).get("eligible") is True]
    if not alerts:
        if model_only:
            return (
                '<div class="chat-empty">No alert has passed the model filter yet.<br>'
                "It requires score ≥ 0.45, estimated ROI ≥ 6%, spread ≤ $0.06 and 24h volume ≥ 100 contracts."
                "</div>"
            )
        return (
            '<div class="chat-empty">No ≥ $0.10 swings recorded yet.<br>'
            "The chat fills as scheduled cycles detect moves — nothing is pre-seeded.</div>"
        )
    rows = []
    for alert in alerts[-limit:]:
        direction = "up" if alert.get("direction") == "up" else "down"
        arrow = "▲" if direction == "up" else "▼"
        model = alert.get("model") or {}
        score = (
            f'<span class="chip ok">score {float(model["score"]):.2f}</span>'
            if isinstance(model.get("score"), (int, float))
            else ""
        )
        when = str(alert.get("iso") or "")[11:19] or "—"
        rows.append(
            '<div class="msg">'
            f'<div class="ts">{esc(when)}<br>UTC</div>'
            "<div>"
            '<div class="head">'
            f'<span class="chip {esc(alert.get("topic"))}">{esc(TOPIC_LABEL.get(alert.get("topic"), alert.get("topic")))}</span>'
            f'<span class="dir {direction}">{arrow} {signed(alert.get("delta"))}</span>'
            f'<span class="meta">{cents(alert.get("from_price"))} → {cents(alert.get("to_price"))}</span>'
            f"{score}"
            "</div>"
            f'<div class="title">{esc(clamp(alert.get("title"), 104))}</div>'
            '<div class="links">'
            f'<span class="mono">{esc(alert.get("ticker"))}</span>'
            f'<a href="{esc(alert.get("api_url") or "#")}" target="_blank" rel="noopener">market API</a>'
            f'<a href="{esc(alert.get("series_page_url") or "#")}" target="_blank" rel="noopener">Kalshi page</a>'
            "</div>"
            "</div></div>"
        )
    return "\n".join(rows)


def render_paper(snapshot, paper) -> str:
    headline = (paper or {}).get("headline") or {}
    perf = ((snapshot or {}).get("performance") or {}).get("headline") or {}
    summary = ((snapshot or {}).get("performance") or {}).get("summary") or {}
    equity = headline.get("equity", perf.get("equity"))
    pnl = headline.get("total_pnl", perf.get("total_pnl"))
    roi = headline.get("roi_pct", perf.get("roi_pct"))
    positions = (paper or {}).get("open_positions") or (snapshot or {}).get("paper", {}).get("open_positions") or []
    cash = headline.get("cash", perf.get("cash"))
    verified = bool(headline.get("fee_verified", perf.get("fee_verified")))

    head = (
        '<div class="kpi" style="grid-template-columns:repeat(auto-fit,minmax(120px,1fr))">'
        f'<div class="card"><span class="label">Equity</span><span class="value">{usd(equity, 2)}</span>'
        f'<span class="foot">start {usd(headline.get("bankroll_start", perf.get("bankroll_start")), 2)}</span></div>'
        f'<div class="card"><span class="label">Total P&amp;L</span>'
        f'<span class="value {"up" if (pnl or 0) >= 0 else "down"}">{signed(pnl)}</span>'
        f'<span class="foot">{signed(roi)}%</span></div>'
        f'<div class="card"><span class="label">Open positions</span><span class="value">{num(len(positions))}</span>'
        f'<span class="foot">cash {usd(cash, 2)}</span></div>'
        f'<div class="card"><span class="label">Closed trades</span><span class="value">{num(summary.get("trades"))}</span>'
        f'<span class="foot">win rate {num(summary.get("win_rate_pct"), 1)}%</span></div>'
        "</div>"
    )
    if positions:
        rows = []
        for pos in positions[:6]:
            rows.append(
                "<tr>"
                f'<td><span class="title">{esc(clamp(pos.get("title"), 58))}</span>'
                f'<span class="meta mono">{esc(pos.get("ticker"))}</span></td>'
                f'<td><span class="chip {esc(pos.get("topic"))}">{esc(TOPIC_LABEL.get(pos.get("topic"), pos.get("topic")))}</span></td>'
                f'<td class="num">{num(pos.get("contracts"))}</td>'
                f'<td class="num">{cents(pos.get("entry_price"))}</td>'
                f'<td class="meta">{esc(clamp(pos.get("strategy_name") or pos.get("strategy"), 30))}</td>'
                '<td class="src"><a href="' + esc(pos.get("api_url") or pos.get("series_page_url") or "#") + '" target="_blank" rel="noopener">API</a></td>'
                "</tr>"
            )
        table = (
            '<div class="table-wrap" style="max-height:250px;margin-top:10px"><table>'
            "<thead><tr><th>Open position</th><th>Topic</th><th class=\"num\">Contracts</th>"
            '<th class="num">Entry</th><th>Strategy</th><th>Source</th></tr></thead><tbody>'
            + "".join(rows)
            + "</tbody></table></div>"
        )
    else:
        table = '<div class="chat-empty">No open positions. The book opens positions when a strategy entry rule fires.</div>'

    fee_note = (
        "Fees charged with the published formula." if verified
        else "Fees modelled at 7% × contracts × price × (1 − price), rounded up to the cent — <b>unverified</b> against Kalshi's current fee schedule."
    )
    return (
        "<h3>Simulated book</h3>" + head + table
        + f'<div class="note" style="margin-top:10px">{fee_note} '
        "<a href=\"docs/desk/flagged.html\">See the flagged list</a>.</div>"
    )


def render_resolved(resolved, limit=10) -> str:
    items = (resolved or {}).get("items") or []
    if not items:
        return (
            "<h3>Resolution tracker</h3>"
            '<div class="chat-empty">No settled markets recorded yet. Every followed event is polled until Kalshi '
            "marks it finalized, then recorded as YES or NO from the exchange's own <code>result</code> field.</div>"
            '<div class="note" style="margin-top:8px">Lifecycle reference: '
            '<a href="https://docs.kalshi.com/getting_started/market_lifecycle" target="_blank" rel="noopener">'
            "docs.kalshi.com/getting_started/market_lifecycle</a></div>"
        )
    yes = sum(1 for r in items if str(r.get("resolution")).upper() == "YES")
    rows = []
    for item in items[:limit]:
        outcome = str(item.get("resolution") or "—").upper()
        cls = "ok" if outcome == "YES" else ("bad" if outcome == "NO" else "warn")
        rows.append(
            "<tr>"
            f'<td><span class="title">{esc(clamp(item.get("title"), 66))}</span>'
            f'<span class="meta mono">{esc(item.get("ticker"))}</span></td>'
            f'<td><span class="chip {cls}">{esc(outcome)}</span></td>'
            f'<td class="meta">{esc(str(item.get("close_time") or item.get("settled_ts") or "—")[:16].replace("T", " "))}</td>'
            '<td class="src"><a href="' + esc(item.get("api_url") or item.get("source") or "#") + '" target="_blank" rel="noopener">verify</a></td>'
            "</tr>"
        )
    return (
        "<h3>Resolution tracker</h3>"
        f'<div class="tstats" style="display:flex;gap:12px;font-size:11px;color:var(--muted);margin-bottom:8px">'
        f"<span><b>{len(items)}</b> settled</span><span><b>{yes}</b> YES</span>"
        f"<span><b>{len(items) - yes}</b> NO</span></div>"
        '<div class="table-wrap" style="max-height:250px"><table>'
        "<thead><tr><th>Market</th><th>Outcome</th><th>Closed</th><th>Source</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def render_errors(snapshot) -> str:
    errors = (snapshot or {}).get("errors") or []
    if not errors:
        return ""
    shown = "".join(f"<li>{esc(clamp(str(e), 190))}</li>" for e in errors[:10])
    return (
        '<div class="banner warn" style="margin-top:12px"><b>'
        f"{len(errors)} collection warning(s) in the published snapshot.</b>"
        '<span class="grow"><ul style="margin:4px 0 0;padding-left:16px">'
        f"{shown}</ul>These are printed, not suppressed. A failed request never becomes an invented value.</span></div>"
    )


def render_engine_card() -> str:
    """Only rendered if the parallel engine site is present in this tree."""
    if not (ROOT / "docs" / "engine" / "index.html").exists():
        return ""
    return (
        '      <a class="doc archived" href="docs/engine/index.html"><b>Engine site — parallel build</b>'
        "<span>Independent engine and verification-first site from a parallel session. Kept and labelled, "
        "not merged into the desk.</span></a>"
    )


# --------------------------------------------------------------------- render
def build() -> str:
    snapshot = load("latest.json")
    alerts = (load("alerts.json") or {}).get("items") or []
    resolved = load("resolved.json") or {}
    paper = load("paper.json")

    template = TEMPLATE.read_text(encoding="utf-8")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    replacements = {
        "{{STATUS_HTML}}": render_status(snapshot),
        "{{SNAPSHOT_NOTE_HTML}}": render_snapshot_note(snapshot),
        "{{KPI_HTML}}": render_kpis(snapshot, alerts, paper),
        "{{TOPIC_CARDS_HTML}}": render_topic_cards(snapshot),
        "{{LEADERBOARD_HTML}}": render_leaderboard(snapshot),
        "{{CHAT_ALL_HTML}}": render_chat(alerts, model_only=False),
        "{{CHAT_MODEL_HTML}}": render_chat(alerts, model_only=True),
        "{{PAPER_HTML}}": render_paper(snapshot, paper),
        "{{RESOLVED_HTML}}": render_resolved(resolved),
        "{{ERRORS_HTML}}": render_errors(snapshot),
        "{{ENGINE_CARD_HTML}}": render_engine_card(),
        "{{GENERATED_AT}}": esc(generated_at),
    }
    page = template
    for key, value in replacements.items():
        page = page.replace(key, value)
    leftover = [token for token in ("{{", "}}") if token in page]
    if leftover:
        raise SystemExit(f"unreplaced template token(s) in index.html: {leftover}")
    return page


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in argv
    page = build()
    if check_only:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != page:
            print(f"STALE: {OUT.relative_to(ROOT)} does not match a fresh render. Run: python tools/build_landing.py")
            return 1
        print(f"OK — {OUT.relative_to(ROOT)} is current")
        return 0
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
