#!/usr/bin/env python3
"""Generate the audit site under docs/audit/ from docs/audit/data/audit.json.

Every data row on every page carries at least one https source link; check_site.py
fails the build otherwise. Nothing here invents a value: a finding without a
source cannot be written, and a check result is printed exactly as verify.py
observed it.

    python3 audit/build_site.py           # write the pages
    python3 audit/build_site.py --check   # fail if the committed pages are stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "audit"
DATA = OUT / "data" / "audit.json"
CHECK = "--check" in sys.argv

NAV = [
    ("index.html", "Overview"),
    ("findings.html", "Findings"),
    ("flagged.html", "Flagged for review"),
    ("sources.html", "Official sources"),
    ("methodology.html", "Method"),
]

STATUS_LABEL = {
    "fixed": "Fixed, re-checked on every build",
    "open": "Open — flagged",
    "verified": "Verified",
    "resolved": "Flag withdrawn",
}


def esc(value) -> str:
    return (
        str(value if value is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def link(url: str, label: str) -> str:
    return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(label)}</a>'


def severity_pill(severity: str) -> str:
    return f'<span class="pill sev-{esc(severity)}">{esc(severity)}</span>'


def status_pill(status: str) -> str:
    return f'<span class="pill st-{esc(status)}">{esc(STATUS_LABEL[status])}</span>'


def source_links(sources: list[dict]) -> str:
    if not sources:
        return '<span class="muted">no official page applies</span>'
    return " · ".join(link(s["url"], s["id"]) for s in sources)


def repo_links(item: dict) -> str:
    parts = [link(s["url"], s["label"]) for s in item.get("repoSources") or []]
    if item.get("sources"):
        parts.append(source_links(item["sources"]))
    return " · ".join(parts)


def no_source_note(item: dict) -> str:
    note = item.get("noOfficialSource")
    return f'<p class="src"><strong>Why there is no official source.</strong> {esc(note)}</p>' if note else ""


def page(title: str, current: str, body: str, doc: dict) -> str:
    meta = doc["meta"]
    nav = "".join(
        f'<a class="{"on" if href == current else ""}" href="{href}">{esc(label)}</a>' for href, label in NAV
    )
    counts = meta["counts"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · Kalshi audit</title>
<link rel="stylesheet" href="assets/style.css">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><circle cx='16' cy='16' r='13' fill='%2322c98a'/></svg>">
</head>
<body>
<header class="site"><div class="wrap bar">
  <a class="brand" href="index.html">Kalshi audit <span>· line by line</span></a>
  <nav>{nav}</nav>
  <a class="back" href="../">All dashboards</a>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="wrap">
  <p>Read against <strong>{meta["factCount"]} official statements</strong> checked on {esc(meta["checkedOn"])}:
  {meta["counts"]["fixed"]} finding(s) fixed and re-checked, {counts["open"]} published as open,
  {counts["resolved"]} earlier flag withdrawn. Demo and paper trading only; no production order path exists in this repository.</p>
  <p><a href="https://github.com/kanlerxz87-cyber/Tradebot1">Repository</a> ·
     <a href="../desk/flagged.html">Desk flags</a> ·
     <a href="../../flagged.html">Board flags</a> ·
     <a href="https://docs.kalshi.com/getting_started/api_environments">Official API documentation</a></p>
</footer>
</body>
</html>
"""


def index(doc: dict) -> str:
    meta = doc["meta"]
    counts = meta["counts"]
    fixed = [i for i in doc["items"] if i["status"] == "fixed"]
    open_items = [i for i in doc["items"] if i["status"] == "open"]
    rows = "".join(
        f"<tr><td class='mono'>{esc(i['id'])}</td><td>{esc(i['title'])}</td>"
        f"<td>{status_pill(i['status'])}</td><td class='src'>{repo_links(i)}</td></tr>"
        for i in doc["items"]
    )
    body = f"""
<section class="hero">
  <p class="tag">Audit · {esc(meta["checkedOn"])} · session {esc(meta["session"])}</p>
  <h1>Every factual claim in this repository, checked against Kalshi's own pages.</h1>
  <p class="lede">Four independent implementations of the same brief are published here. This page treats them
  as code to be audited, not as documentation to be trusted: each claim below is matched to an official
  statement, each finding to a line of code, and each fix to a test that re-runs on every build.</p>
  <div class="stats">
    <div><b>{meta["factCount"]}</b><span>official statements read and quoted</span></div>
    <div><b>{meta["itemCount"]}</b><span>findings, each with a file and a line</span></div>
    <div><b>{counts["fixed"]}</b><span>corrected, each with a regression test</span></div>
    <div><b>{counts["open"]}</b><span>published unresolved</span></div>
  </div>
</section>

<h2>What the audit found</h2>
<ul class="outcomes">
""" + "".join(
        f"<li><strong>{esc(i['id'])}</strong> — {esc(i['title'])}. "
        f"{status_pill(i['status'])}</li>"
        for i in fixed + open_items
    ) + f"""
</ul>

<h2>All findings</h2>
<table class="grid">
<thead><tr><th>ID</th><th>Finding</th><th>Status</th><th>Sources</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<p class="note">Line numbers, file paths and check output for each row are on
<a href="findings.html">Findings</a>. Anything unresolved is on
<a href="flagged.html">Flagged for review</a>, with the source that decides it.</p>

<p class="note">A sibling page in this folder, <a href="fee-audit.html">Fee audit</a>, checks the same fee model and
the series taxonomy from a different session; it is linked rather than merged so both readings stay visible.</p>

<h2>How the audit was done</h2>
<div class="cols">
  <div class="card">
    <h3>Read, then quote</h3>
    <p>Each official page was fetched on {esc(meta["checkedOn"])} and a short excerpt stored with its URL in
    <code>audit/facts.json</code>. The published page shows the excerpt next to the claim, so a reader can
    disagree with the reading rather than with a summary.</p>
  </div>
  <div class="card">
    <h3>Check the code, not the comment</h3>
    <p><code>audit/verify.py</code> runs the JavaScript with node and the Python with the repository's own
    modules. A finding marked fixed must pass its check; a finding marked open must still reproduce. If
    either changes, the build fails and the page cannot publish a stale verdict.</p>
  </div>
  <div class="card">
    <h3>Only what can be shown</h3>
    <p>No credential was available, so nothing here claims an authenticated read, an executed order, a live
    WebSocket session or a browser CORS result. Those remain on the <a href="flagged.html">flagged page</a>
    where earlier sessions left them.</p>
  </div>
</div>

<h2>Where each fix landed</h2>
<table class="grid">
<thead><tr><th>File</th><th>Change</th><th>Finding</th><th>Test</th><th>Deciding source</th></tr></thead>
<tbody>
<tr><td class="mono">tools/alerts.mjs</td><td>A midpoint is refused when either side of the book is empty</td><td>AUD-01 {status_pill("fixed")}</td><td class="mono">tests/alerts-strategies.test.mjs</td><td class="src"><a href="https://docs.kalshi.com/getting_started/orderbook_responses">order book semantics</a></td></tr>
<tr><td class="mono">kalshi_trader/marketdata.py</td><td>An ask of 1.0000 with no NO bid is treated as no offer</td><td>AUD-02 {status_pill("fixed")}</td><td class="mono">tests/test_audit.py</td><td class="src"><a href="https://docs.kalshi.com/getting_started/orderbook_responses">order book semantics</a></td></tr>
<tr><td class="mono">kalshi_trader/collector.py</td><td>Settled sweep uses <code>min_settled_ts</code> (landed on main by PR #16 first; verified here, test kept)</td><td>AUD-03 {status_pill("fixed")}</td><td class="mono">tests/test_collector.py</td><td class="src"><a href="https://docs.kalshi.com/api-reference/market/get-markets">Get Markets filters</a></td></tr>
<tr><td class="mono">tools/fees.mjs</td><td>Fee table read across all four columns; 21 of 21 rows reproduce</td><td>AUD-05 {status_pill("fixed")}</td><td class="mono">tests/fees.test.mjs</td><td class="src"><a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf">fee schedule</a></td></tr>
<tr><td class="mono">tools/topics.mjs</td><td>Topic comment synced with Culture probe and live series filters</td><td>AUD-07 {status_pill("fixed")}</td><td class="mono">tests/kalshi.test.mjs</td><td class="src"><a href="https://docs.kalshi.com/getting_started/demo_env">demo catalogue</a></td></tr>
<tr><td class="mono">scripts/build-site.mjs</td><td>The staleness gate ignores wall-clock text again</td><td>AUD-08 {status_pill("fixed")}</td><td class="mono">audit/verify.py</td><td class="src"><a href="https://github.com/kanlerxz87-cyber/Tradebot1/blob/main/scripts/build-site.mjs">the gate itself</a></td></tr>
<tr><td class="mono">kalshi_trader/marketdata.py</td><td>Explicit None checks keep <code>0.0000</code> quotes as <code>0.0</code></td><td>AUD-12 {status_pill("fixed")}</td><td class="mono">tests/test_audit.py</td><td class="src"><a href="https://docs.kalshi.com/getting_started/fixed_point_migration">fixed-point migration</a></td></tr>
</tbody>
</table>
"""
    return page("Overview", "index.html", body, doc)


def findings(doc: dict) -> str:
    blocks = []
    for item in doc["items"]:
        evidence = "".join(
            f"<li><code>{esc(ev['file'])}:{ev['line']}</code> — {esc(ev['note'])}"
            f"<pre>{esc(ev['needle'])}</pre></li>"
            for ev in item["evidence"]
        )
        check = item["check"]
        check_html = (
            f"<p class='check ok'><strong>Re-checked:</strong> observed "
            f"<code>{esc(check.get('observed'))}</code>"
            + (f" against expected <code>{esc(check['expected'])}</code>" if check.get("expected") else "")
            + "</p>"
            if check["kind"] != "none"
            else "<p class='check muted'>No executable check: this finding is a documentation reconciliation.</p>"
        )
        fix = f"<p><strong>Correction.</strong> {esc(item['fix'])}</p>" if item.get("fix") else ""
        blocks.append(f"""
<article class="finding" id="{esc(item['id'])}">
  <header>
    <span class="mono id">{esc(item['id'])}</span>
    {status_pill(item['status'])} {severity_pill(item['severity'])}
    <h3>{esc(item['title'])}</h3>
  </header>
  <p>{esc(item['finding'])}</p>
  <p><strong>Impact.</strong> {esc(item['impact'])}</p>
  {fix}
  <h4>Evidence in this repository</h4>
  <ul class="evidence">{evidence}</ul>
  {check_html}
  <p class="src"><strong>Sources:</strong> {repo_links(item)}</p>
  {no_source_note(item)}
  <p class="src"><strong>Re-check it yourself:</strong> {esc(item['howToCheck'])}</p>
</article>""")
    body = f"""
<section class="hero tight">
  <p class="tag">Findings · {doc["meta"]["itemCount"]}</p>
  <h1>Every finding, with the line that proves it</h1>
  <p class="lede">Line numbers are resolved at build time from a stored snippet, so they stay correct as the
  code moves. Each finding ends with the command or page that re-checks it.</p>
</section>
{''.join(blocks)}
"""
    return page("Findings", "findings.html", body, doc)


def flagged(doc: dict) -> str:
    items = [i for i in doc["items"] if i["status"] == "open"]
    rows = "".join(
        f"""
<article class="finding" id="{esc(i['id'])}">
  <header><span class="mono id">{esc(i['id'])}</span> {severity_pill(i['severity'])}
    <h3>{esc(i['title'])}</h3></header>
  <p>{esc(i['finding'])}</p>
  <p><strong>Impact.</strong> {esc(i['impact'])}</p>
  <p class="src"><strong>Deciding source:</strong> {repo_links(i)}</p>
  {no_source_note(i)}
  <p class="src"><strong>How to check:</strong> {esc(i['howToCheck'])}</p>
</article>"""
        for i in items
    )
    body = f"""
<section class="hero tight">
  <p class="tag">Flagged for review</p>
  <h1>{len(items)} items that are proved but not corrected here, or cannot be proved at all</h1>
  <p class="lede">Nothing on this page blocks publication, and nothing on it is silently smoothed over: each
  item says what is wrong, who it affects, which official page decides it, and what would fix it. Items that
  need a credential, a browser or an API call this session could not make are listed with that reason rather
  than guessed at.</p>
</section>
{rows}
<p class="note">Not on this list, because no evidence was found for them either way: authenticated demo-account
reads, executed orders, live WebSocket sessions and browser CORS behaviour. They stay unclaimed on the
individual dashboards' own review pages, where they were first raised.</p>
"""
    return page("Flagged for review", "flagged.html", body, doc)


def sources(doc: dict) -> str:
    rows = "".join(
        f"""<tr>
  <td class="mono">{esc(f['id'])}</td>
  <td><a href="{esc(f['url'])}" target="_blank" rel="noopener noreferrer">{esc(f['page'])}</a>
      <div class="quote">{esc(f['quote'])}</div></td>
  <td>{esc(f['claim'])}
      <div class="src">{link(f['url'], f['url'].replace('https://', ''))}</div></td>
</tr>"""
        for f in doc["facts"]
    )
    body = f"""
<section class="hero tight">
  <p class="tag">Official sources · {doc["meta"]["factCount"]} statements</p>
  <h1>What Kalshi's own pages say, quoted</h1>
  <p class="lede">These are the statements every verdict above rests on. Each was read on
  {esc(doc["meta"]["checkedOn"])}; the quote is deliberately short and verbatim so it can be checked against
  the page in a few seconds.</p>
</section>
<table class="grid quotes">
<thead><tr><th>ID</th><th>Statement, quoted</th><th>The claim it settles</th></tr></thead>
<tbody>{rows}</tbody>
</table>
"""
    return page("Official sources", "sources.html", body, doc)


def methodology(doc: dict) -> str:
    meta = doc["meta"]
    body = f"""
<section class="hero tight">
  <p class="tag">Method</p>
  <h1>How to reproduce this page</h1>
  <p class="lede">{esc(meta["howRead"])}</p>
</section>

<h2>Command line</h2>
<pre class="block">python3 audit/verify.py          # re-run every check, rewrite the data file
python3 audit/build_site.py      # regenerate these pages
python3 audit/check_site.py      # gates: source on every row, no broken links, pages current
python3 -m pytest -q             # the repository's Python suite, including the audit regressions
node --test tests/*.test.mjs     # the repository's JavaScript suite</pre>

<h2>Rules this page follows</h2>
<ol class="rules">
  <li><strong>A verdict needs a statement.</strong> If no official page says it, the row does not exist;
  the item goes to <a href="flagged.html">Flagged for review</a> instead.</li>
  <li><strong>A quote, not a paraphrase.</strong> Every source row carries the excerpt it rests on.</li>
  <li><strong>A line, not an impression.</strong> Evidence is stored as a snippet and the printed line number
  is resolved at build time.</li>
  <li><strong>A check, not an assertion.</strong> <code>verify.py</code> executes the code and compares the
  result with what the page claims; a mismatch fails the build.</li>
  <li><strong>Nothing inferred.</strong> An absent value stays absent. Where a number could not be observed -
  an authenticated balance, an executed fill, a live socket - no number is printed.</li>
  <li><strong>Two vocabularies are not a contradiction.</strong> Where the documentation and an earlier flag
  disagree, both are quoted and the point is settled, not repeated.</li>
</ol>

<h2>Scope and its limits</h2>
<table class="grid">
<thead><tr><th>Area</th><th>What this session could do</th><th>Source</th></tr></thead>
<tbody>
<tr><td>Official documentation</td><td>Read and quote directly (page fetch works from this sandbox)</td>
    <td class="src">{link("https://docs.kalshi.com/llms.txt", "docs index")}</td></tr>
<tr><td>Kalshi REST from a shell</td><td>Not possible: TLS reset on every kalshi host, as earlier sessions reported</td>
    <td class="src">{link("https://docs.kalshi.com/getting_started/api_environments", "environments")}</td></tr>
<tr><td>Live market data</td><td>Only the committed captures, read as data, never re-captured here</td>
    <td class="src">{link("https://docs.kalshi.com/api-reference/market/get-markets", "get markets")}</td></tr>
<tr><td>Authenticated demo account</td><td>Not attempted: no credentials exist in this repository and none were requested</td>
    <td class="src">{link("https://docs.kalshi.com/getting_started/demo_env", "demo environment")}</td></tr>
<tr><td>Browser behaviour</td><td>Not tested: no browser session in this environment</td>
    <td class="src">{link("https://docs.kalshi.com/getting_started/quick_start_market_data", "market data quick start")}</td></tr>
</tbody>
</table>
"""
    return page("Method", "methodology.html", body, doc)


CSS = """:root{--bg:#0b0f14;--panel:#121922;--line:#1f2a37;--text:#e6edf5;--dim:#93a2b5;--ok:#22c98a;--warn:#f2b233;--bad:#f4645f;--blue:#5aa9f7}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1060px;margin:0 auto;padding:0 20px}
header.site{border-bottom:1px solid var(--line);background:#0d131a;position:sticky;top:0;z-index:5}
.bar{display:flex;gap:16px;align-items:center;justify-content:space-between;padding:12px 20px;flex-wrap:wrap}
.brand{font-weight:650;color:var(--text)}.brand span{color:var(--dim);font-weight:400}
nav{display:flex;gap:14px;flex-wrap:wrap;font-size:14px}
nav a{color:var(--dim)}nav a.on{color:var(--text);border-bottom:2px solid var(--ok);padding-bottom:2px}
.back{font-size:13px;color:var(--dim)}
main{padding:28px 20px 10px}
.hero{margin-bottom:26px}.hero.tight h1{font-size:26px}
h1{font-size:32px;line-height:1.2;margin:6px 0 12px;letter-spacing:-.02em}
h2{font-size:18px;margin:34px 0 10px}
h3{font-size:16px;margin:6px 0 8px}
h4{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);margin:16px 0 6px}
.tag{margin:0;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--ok)}
.lede{color:#c4d0de;max-width:76ch}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:20px}
.stats div{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.stats b{display:block;font-size:26px;line-height:1.1}.stats span{color:var(--dim);font-size:13px}
.outcomes{padding-left:20px}.outcomes li{margin:8px 0}
table.grid{width:100%;border-collapse:collapse;margin:10px 0 8px;font-size:14px}
table.grid th{text-align:left;color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.07em;border-bottom:1px solid var(--line);padding:8px}
table.grid td{border-bottom:1px solid var(--line);padding:10px 8px;vertical-align:top}
table.quotes td{width:33%}
.quote{color:var(--dim);font-size:13px;margin-top:6px;border-left:2px solid var(--line);padding-left:10px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
.pill{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--dim);white-space:nowrap}
.st-fixed{color:#07130d;background:var(--ok);border-color:var(--ok)}
.st-open{color:#231703;background:var(--warn);border-color:var(--warn)}
.st-verified{color:#06121f;background:var(--blue);border-color:var(--blue)}
.st-resolved{color:var(--dim)}
.sev-high{color:var(--bad);border-color:#4a2321}.sev-medium{color:#f0a35e;border-color:#4a3520}.sev-low{color:var(--dim)}.sev-info{color:var(--dim)}
.finding{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin:16px 0}
.finding header{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.finding header h3{flex:1 1 100%;margin:2px 0 6px}
.id{color:var(--dim)}
.evidence{padding-left:0;list-style:none;margin:0}
.evidence li{margin:10px 0}
pre{background:#0a0f15;border:1px solid var(--line);border-radius:6px;padding:8px 10px;overflow:auto;font-size:12.5px;margin:4px 0 0}
pre.block{white-space:pre-wrap}
.check{font-size:13px;margin:12px 0 6px}.check.ok code{color:var(--ok)}.muted{color:var(--dim)}
.src{color:var(--dim);font-size:13px}
.note{color:var(--dim);font-size:13px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
.card p{color:#c4d0de;font-size:14px;margin:0}
.rules{padding-left:20px}.rules li{margin:8px 0;color:#c4d0de}
footer{border-top:1px solid var(--line);margin-top:34px;padding:16px 20px 40px;color:var(--dim);font-size:13px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;background:#0a0f15;padding:1px 4px;border-radius:4px}
"""


def main() -> int:
    doc = json.loads(DATA.read_text())
    pages = {
        "index.html": index(doc),
        "findings.html": findings(doc),
        "flagged.html": flagged(doc),
        "sources.html": sources(doc),
        "methodology.html": methodology(doc),
        "assets/style.css": CSS,
    }
    if CHECK:
        stale = [
            name for name, html in pages.items()
            if not (OUT / name).exists() or (OUT / name).read_text() != html
        ]
        if stale:
            print(f"stale audit pages: {', '.join(stale)} — run python3 audit/build_site.py", file=sys.stderr)
            return 1
        print(f"audit site is current ({len(pages)} files)")
        return 0
    for name, html in pages.items():
        path = OUT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html)
    print(f"wrote {len(pages)} files under docs/audit/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
