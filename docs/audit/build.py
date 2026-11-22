#!/usr/bin/env python3
"""Official-source audit of the fee model and series fields (session arena/1662b94b).

What this does, and nothing more:

1. Recomputes every row of Kalshi's published general trading-fee table with the repo's own
   ``kalshi_trader.fees.taker_fee`` (the function the paper ledger calls). A mismatch exits 1.
2. Compares the repo's single global fee assumption with the per-series fields returned by the
   official Series endpoint (``fee_type``, ``fee_multiplier``) for the sampled series.
3. Counts ledger records on series the official schedule says carry no fee.
4. Renders ``docs/audit/fee-audit.html`` from the evidence below. Every row carries its official link.

Values were transcribed on 2026-11-22 (UTC) from the URLs in ``SOURCES``. Nothing here is inferred:
anything the official source did not state is left out and listed under "Not verified".

Usage:
    python docs/audit/build.py          # write docs/audit/fee-audit.html
    python docs/audit/build.py --check  # verify only; exit 1 on any failed check
"""
from __future__ import annotations

import html
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kalshi_trader import fees  # noqa: E402  (the repo's own fee function)

CHECKED = "2026-11-22"

SOURCES = {
    "pdf": "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
    "page": "https://kalshi.com/fee-schedule",
    "rounding": "https://docs.kalshi.com/getting_started/fee_rounding",
    "series_doc": "https://docs.kalshi.com/api-reference/market/get-series",
    "glossary": "https://docs.kalshi.com/getting_started/terms",
    "api": "https://external-api.kalshi.com/trade-api/v2/series/{}",
}

# Official general trading-fee table, PDF "General Trading Fees Table" (effective July 7, 2026).
# (price of 1 contract, fee for 1 contract, price for 100 contracts, fee for 100 contracts)
OFFICIAL_FEE_TABLE = [
    (0.01, 0.01, 1.00, 0.07), (0.05, 0.01, 5.00, 0.34), (0.10, 0.01, 10.00, 0.63),
    (0.15, 0.01, 15.00, 0.90), (0.20, 0.02, 20.00, 1.12), (0.25, 0.02, 25.00, 1.32),
    (0.30, 0.02, 30.00, 1.47), (0.35, 0.02, 35.00, 1.60), (0.40, 0.02, 40.00, 1.68),
    (0.45, 0.02, 45.00, 1.74), (0.50, 0.02, 50.00, 1.75), (0.55, 0.02, 55.00, 1.74),
    (0.60, 0.02, 60.00, 1.68), (0.65, 0.02, 65.00, 1.60), (0.70, 0.02, 70.00, 1.47),
    (0.75, 0.02, 75.00, 1.32), (0.80, 0.02, 80.00, 1.12), (0.85, 0.01, 85.00, 0.90),
    (0.90, 0.01, 90.00, 0.63), (0.95, 0.01, 95.00, 0.34), (0.99, 0.01, 99.00, 0.07),
]

# Official Series endpoint responses (GET /trade-api/v2/series/{ticker}, production host),
# fetched 2026-11-22 (UTC). Only fields the endpoint returned are recorded.
SERIES = [
    {"ticker": "KXAAAGASM", "title": "US gas price", "category": "Economics", "tags": ["Oil & Gas", "Oil and energy"],
     "fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1, "last_updated": "2026-11-13T01:36:48.263936Z"},
    {"ticker": "KXPGATOUR", "title": "PGA Tour", "category": "Sports", "tags": ["Golf"],
     "fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1, "last_updated": "2026-11-11T16:24:46.311366Z"},
    {"ticker": "KXMASTERS", "title": "Masters Tournament", "category": "Sports", "tags": ["Golf"],
     "fee_type": "quadratic", "fee_multiplier": 1, "last_updated": "2026-09-22T23:17:42.905361Z"},
    {"ticker": "KXUSOPEN", "title": "US Open", "category": "Sports", "tags": ["Golf"],
     "fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1, "last_updated": "2026-11-11T16:24:45.874355Z"},
    {"ticker": "KXBTCY", "title": "BTC price range EOY", "category": "Crypto", "tags": ["Crypto", "BTC", "Bitcoin"],
     "fee_type": "quadratic", "fee_multiplier": 0, "last_updated": "2026-11-13T01:45:46.503173Z"},
    {"ticker": "KXETHY", "title": "ETH price EOY", "category": "Crypto", "tags": ["Crypto", "Ethereum", "ETH"],
     "fee_type": "quadratic", "fee_multiplier": 0, "last_updated": "2026-11-13T01:45:31.164441Z"},
    {"ticker": "KXBTC15M", "title": "BTC 15 min", "category": "Crypto", "tags": ["Crypto", "BTC", "15 min", "Bitcoin"],
     "fee_type": "quadratic", "fee_multiplier": 1, "last_updated": "2026-11-13T01:38:05.898217Z"},
    {"ticker": "KXBTCD", "title": "Bitcoin price Above/below", "category": "Crypto", "tags": ["Crypto", "Hourly", "BTC", "Bitcoin"],
     "fee_type": "quadratic", "fee_multiplier": 1, "last_updated": "2026-11-13T01:40:31.21665Z"},
    {"ticker": "PRES", "title": "Presidential elections", "category": "Elections", "tags": ["US Elections"],
     "fee_type": "quadratic", "fee_multiplier": 1, "last_updated": "2026-10-07T01:15:41.849338Z"},
    {"ticker": "KXPRESNOMD", "title": "Democratic Primary winner", "category": "Elections", "tags": ["2028", "Nomination race", "US Elections"],
     "fee_type": "quadratic", "fee_multiplier": 1, "last_updated": "2026-11-19T16:52:00.763008Z"},
    {"ticker": "CONTROLH", "title": "House winner", "category": "Elections", "tags": ["House control", "House", "US Elections"],
     "fee_type": "quadratic", "fee_multiplier": 1, "last_updated": "2026-11-13T23:00:57.444628Z"},
    {"ticker": "KXFIRSTSUPERBOWLSONG", "title": "What will be the first Super Bowl Song played during halfitme?", "category": "Entertainment",
     "tags": ["Live Music"], "fee_type": "quadratic", "fee_multiplier": 1, "last_updated": "2026-10-27T14:30:18.569213Z"},
    {"ticker": "KXRT", "title": "Rotten Tomatoes Scores", "category": "Entertainment", "tags": ["Rotten Tomatoes"],
     "fee_type": "quadratic", "fee_multiplier": 1, "last_updated": "2026-11-17T22:16:53.576403Z"},
]

# Ledger and snapshot records are read from the repo, not typed in.
LEDGER = ROOT / "app_data" / "paper_ledger.json"
SERIES_JSON = ROOT / "docs" / "desk" / "data" / "series.json"


def fee_rows_check() -> list[dict]:
    rows = []
    for price, fee1, price100, fee100 in OFFICIAL_FEE_TABLE:
        calc1 = fees.taker_fee(1, price, "quadratic")
        calc100 = fees.taker_fee(100, price, "quadratic")
        ok = math.isclose(calc1, fee1, abs_tol=1e-9) and math.isclose(calc100, fee100, abs_tol=1e-9) \
            and math.isclose(price100, round(price * 100, 2), abs_tol=1e-9)
        rows.append({"price": price, "fee1": fee1, "price100": price100, "fee100": fee100,
                     "calc1": calc1, "calc100": calc100, "ok": ok})
    return rows


def repo_topics() -> dict[str, str]:
    data = json.loads(SERIES_JSON.read_text())["series"]
    return {t: v.get("topic", "") for t, v in data.items()}


def ledger_zero_fee_records() -> tuple[int, float]:
    """Count ledger records on series the official Series endpoint lists with fee_multiplier 0."""
    zero = {s["ticker"] for s in SERIES if s["fee_multiplier"] == 0}
    ledger = json.loads(LEDGER.read_text())
    count, fees_sum = 0, 0.0

    def walk(obj):
        if isinstance(obj, dict):
            yield obj
            for v in obj.values():
                yield from walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v)

    for rec in walk(ledger):
        ticker = rec.get("ticker") or ""
        series = rec.get("series_ticker") or ticker.split("-")[0]
        if series in zero:
            count += 1
            fees_sum += float(rec.get("entry_fee") or 0) + float(rec.get("exit_fee") or 0) + float(rec.get("fees") or 0)
    return count, round(fees_sum, 2)


def esc(v) -> str:
    return html.escape(str(v))


def link(url: str, label: str = "source") -> str:
    return f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(label)}</a>'


def render(fee_rows: list[dict], topics: dict[str, str], zero_count: int, zero_fees: float) -> str:
    failed = [r for r in fee_rows if not r["ok"]]
    passed = len(fee_rows) - len(failed)

    fee_table = "\n".join(
        f'<tr><td>${r["price"]:.2f}</td><td>${r["fee1"]:.2f}</td><td>${r["calc1"]:.2f}</td>'
        f'<td>${r["fee100"]:.2f}</td><td>${r["calc100"]:.2f}</td>'
        f'<td><span class="chip {"ok" if r["ok"] else "bad"}">{"matches" if r["ok"] else "MISMATCH"}</span></td>'
        f'<td>{link(SOURCES["pdf"], "PDF table")}</td></tr>'
        for r in fee_rows
    )

    series_rows = []
    for s in SERIES:
        repo_topic = topics.get(s["ticker"], "")
        if s["fee_multiplier"] == 0:
            result = '<span class="chip bad">mismatch — repo charges a fee; official: no fee</span>'
        elif "maker" in s["fee_type"]:
            result = '<span class="chip warn">taker formula consistent; maker fills not modeled</span>'
        else:
            result = '<span class="chip ok">consistent with repo model</span>'
        series_rows.append(
            f'<tr><td class="mono"><a href="{esc(SOURCES["api"].format(s["ticker"]))}" target="_blank" rel="noopener">{esc(s["ticker"])}</a></td>'
            f'<td>{esc(s["title"])}</td><td>{esc(s["category"])}</td><td>{esc(", ".join(s["tags"]))}</td>'
            f'<td class="mono">{esc(s["fee_type"])}</td><td>{esc(s["fee_multiplier"])}</td>'
            f'<td>{esc(s["last_updated"][:10])}</td><td>{esc(repo_topic or "—")}</td>'
            f'<td>{result}</td>'
            f'<td>{link(SOURCES["api"].format(s["ticker"]), "official API")}</td></tr>'
        )

    irregular = [
        ("warn", "Fee model ignores per-series fee_multiplier",
         "The paper book applies one global formula to every series. The official Series endpoint returns "
         "<code>fee_multiplier: 0</code> for <code>KXBTCY</code> and <code>KXETHY</code>, and the official schedule lists both as <b>no fees</b>. "
         f"Ledger records on these series: <b>{zero_count}</b> (fees charged: ${zero_fees:.2f}). The impact is latent, not current.",
         "e3e5f70f: read <code>fee_multiplier</code> per series in <code>kalshi_trader/fees.py</code> / <code>paper.py</code>.",
         [SOURCES["series_doc"], SOURCES["page"]]),
        ("warn", "Flag F1 says the fee schedule could not be retrieved — it can now",
         "Kalshi's fee schedule PDF (\"Last updated and effective: July 7, 2026\") and the fee-schedule page (\"No upcoming fee changes scheduled\") "
         f"are both retrievable. The general taker formula matches <b>{passed} of {len(fee_rows)}</b> official table rows recomputed with the repo's function.",
         "e3e5f70f: update <code>docs/desk/data/flags.json</code> F1 and <code>fees.VERIFIED</code> with these links, after the per-series change above.",
         [SOURCES["pdf"], SOURCES["page"]]),
        ("warn", "Source S10 conflicts with the live Series record",
         "S10 states the gas series has <code>categories [Economics, Commodities]</code>. The glossary's worked example says the same, but it is introduced as an example. "
         "The live Series endpoint returns <code>categories: [\"Economics\"]</code> (the repo's own <code>series.json</code> also stores only Economics).",
         "e3e5f70f: correct S10 in <code>docs/desk/data/sources.json</code> and <code>docs/desk/verification.html</code>, or cite the live record.",
         [SOURCES["glossary"], SOURCES["series_doc"].replace("get-series", "get-series-list")]),
        ("info", "Maker fees are not modeled",
         "Official maker formula: <code>round up(M × 0.0175 × C × P × (1−P))</code>, default M = 0 unless a series says otherwise. "
         "The sampled gas, PGA Tour and US Open series are <code>quadratic_with_maker_fees</code>. The repo defines <code>maker_fee()</code> but nothing calls it; every simulated fill is taker-priced.",
         "e3e5f70f: state in the paper results that maker fills are excluded, or model them.",
         [SOURCES["pdf"], SOURCES["page"]]),
        ("info", "Rounding mechanics differ in sub-cent detail",
         "The repo rounds each fee up to the cent. Kalshi documents a trade fee rounded up to $0.000001, then a rounding fee and a rebate that align the balance to $0.01 (non-direct members) or $0.0001 (direct). "
         "The cent-level result is not shown to be identical for every fill, so this is unverified.",
         "e3e5f70f: note the difference on the fees page.",
         [SOURCES["rounding"]]),
        ("info", "Confirmed: Golf is the tag 'Golf' under category 'Sports'",
         "KXPGATOUR, KXMASTERS and KXUSOPEN all return <code>category: Sports</code> and <code>tags: [\"Golf\"]</code>, matching S9.",
         "No action.", [SOURCES["series_doc"]]),
        ("info", "Confirmed: Entertainment series present for the Culture mapping",
         "KXFIRSTSUPERBOWLSONG and KXRT return <code>category: Entertainment</code>, which the repo's Culture mapping (flag F3) uses.",
         "No action.", [SOURCES["series_doc"]]),
    ]
    irr_rows = "\n".join(
        f'<tr><td><span class="chip {sev}">{ {"warn": "review", "info": "note"}[sev] }</span></td>'
        f'<td><b>{title}</b></td><td>{detail}</td><td>{owner}</td>'
        f'<td>{" · ".join(link(u, f"link {i+1}") for i, u in enumerate(urls))}</td></tr>'
        for sev, title, detail, owner, urls in irregular
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Official-source audit — fee model and series fields</title>
<meta name="description" content="Line-by-line check of the paper fee model and series fields against Kalshi's official fee schedule and Series API, with every row linked to its source.">
<link rel="stylesheet" href="../desk/assets/css/site.css">
<style>
.kpi-num {{ font-size: 26px; font-weight: 700; margin: 4px 0; font-variant-numeric: tabular-nums; }}
.audit-cards .card {{ min-height: 0; }}
</style>
</head>
<body>
<header class="top">
  <div class="top-inner">
    <div class="brand"><span class="dot"></span><span>Kalshi Trader<br><small>demo / paper research desk</small></span></div>
    <nav class="main">
      <a href="../desk/index.html">Dashboard</a>
      <a href="../desk/topics/gas-prices.html">Gas</a>
      <a href="../desk/topics/elections.html">Elections</a>
      <a href="../desk/topics/culture.html">Culture</a>
      <a href="../desk/topics/crypto.html">Crypto</a>
      <a href="../desk/topics/golf.html">Golf</a>
      <a href="../desk/portfolio.html">Portfolio</a>
      <a href="../desk/verification.html">Verification</a>
      <a class="active" href="fee-audit.html">Fee audit</a>
      <a href="../desk/flagged.html">Flagged</a>
    </nav>
  </div>
</header>

<main class="wrap">
  <h1 class="page-title">Fee model and series fields — official-source audit</h1>
  <p class="page-sub">
    Checked {CHECKED} (UTC). Every row links the official page or endpoint it came from. A value Kalshi did not state is left out
    and listed under <a href="#unverified">Not verified</a>. Nothing here is a trading recommendation.
  </p>

  <section class="section">
    <h2>1 · Summary</h2>
    <div class="grid audit-cards" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
      <div class="card"><div class="small">Official table rows recomputed</div><div class="kpi-num">{passed} / {len(fee_rows)}</div><div class="small">with the repo's <code>fees.taker_fee</code></div></div>
      <div class="card"><div class="small">Series checked against the official API</div><div class="kpi-num">{len(SERIES)}</div><div class="small">across gas, golf, crypto, elections, culture</div></div>
      <div class="card"><div class="small">Series where the repo model is wrong</div><div class="kpi-num">{sum(1 for s in SERIES if s['fee_multiplier'] == 0)}</div><div class="small">fee_multiplier 0 (no fees)</div></div>
      <div class="card"><div class="small">Ledger records on those series</div><div class="kpi-num">{zero_count}</div><div class="small">latent: none traded yet</div></div>
    </div>
    <p class="small">Verdict: the taker formula the repo uses is the one Kalshi publishes. The model is still incomplete: it ignores per-series multipliers and maker fills. See section 4.</p>
  </section>

  <section class="section">
    <h2>2 · General fee table, line by line</h2>
    <p class="hint">Each official row was recomputed with <code>kalshi_trader.fees.taker_fee</code> (the function the paper ledger calls). The formula is <code>round up(M × 0.07 × C × P × (1 − P))</code>, M = 1 by default.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Price (1 contract)</th><th>Official fee, 1</th><th>Repo fee, 1</th><th>Official fee, 100</th><th>Repo fee, 100</th><th>Result</th><th>Source</th></tr></thead>
      <tbody>
{fee_table}
      </tbody>
    </table></div>
  </section>

  <section class="section">
    <h2>3 · Series fields from the official Series endpoint</h2>
    <p class="hint">Fields as returned by <code>GET /trade-api/v2/series/{{ticker}}</code> on the production host. "Repo topic" is read from <code>docs/desk/data/series.json</code>.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Ticker</th><th>Title (official)</th><th>Category</th><th>Tags</th><th>fee_type</th><th>fee_multiplier</th><th>Last updated</th><th>Repo topic</th><th>Repo model vs official</th><th>Source</th></tr></thead>
      <tbody>
{chr(10).join(series_rows)}
      </tbody>
    </table></div>
  </section>

  <section class="section">
    <h2>4 · Irregularities and requests for review</h2>
    <p class="hint">Owned by other sessions, so this page records them rather than editing their files. Scope requests are also logged in <code>COORDINATION.md</code>.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Status</th><th>Item</th><th>Finding</th><th>Requested action (owner)</th><th>Sources</th></tr></thead>
      <tbody>
{irr_rows}
      </tbody>
    </table></div>
  </section>

  <section class="section" id="unverified">
    <h2>5 · Not verified</h2>
    <ul>
      <li>The official <a href="https://kalshi.com/fee-schedule">fee-schedule page</a> lists 160 non-standard series; only the 13 sampled series above were reconciled against the official endpoint. The other tracked series are not checked.</li>
      <li>Maker-fee table values: the PDF gives the formula (0.0175 × C × P × (1−P)) but no printed maker table rows, so no maker row is recomputed.</li>
      <li>Demo account balances, positions, fills and fees: no demo credentials exist in this repository, so none were read.</li>
      <li>Browser access to Kalshi APIs: not tested from this page.</li>
    </ul>
  </section>

  <footer class="site">
    <span>Verification performed {CHECKED} UTC.</span>
    <span>·</span><a href="../desk/flagged.html">Flagged for review</a>
    <span>·</span><a href="../desk/verification.html">Verification log</a>
    <span>·</span><span>Not investment advice.</span>
  </footer>
</main>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    fee_rows = fee_rows_check()
    failed = [r for r in fee_rows if not r["ok"]]
    for r in failed:
        print(f"MISMATCH price={r['price']} official=({r['fee1']},{r['fee100']}) repo=({r['calc1']},{r['calc100']})")
    topics = repo_topics()
    expected = {"KXAAAGASM": "gas", "KXPGATOUR": "golf", "KXMASTERS": "golf", "KXUSOPEN": "golf",
                "KXBTCY": "crypto", "KXETHY": "crypto", "KXBTC15M": "crypto", "KXBTCD": "crypto",
                "PRES": "elections", "KXPRESNOMD": "elections", "CONTROLH": "elections",
                "KXFIRSTSUPERBOWLSONG": "culture", "KXRT": "culture"}
    topic_mismatch = [t for t, want in expected.items() if topics.get(t) != want]
    for t in topic_mismatch:
        print(f"TOPIC {t}: repo={topics.get(t)!r} expected={expected[t]!r}")
    zero_count, zero_fees = ledger_zero_fee_records()
    print(f"fee table: {len(fee_rows) - len(failed)}/{len(fee_rows)} rows match; "
          f"zero-fee series in ledger: {zero_count} records, ${zero_fees:.2f} fees")
    if "--check" in argv:
        return 1 if (failed or topic_mismatch) else 0
    out = ROOT / "docs" / "audit" / "fee-audit.html"
    out.write_text(render(fee_rows, topics, zero_count, zero_fees), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 1 if (failed or topic_mismatch) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
