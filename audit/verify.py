#!/usr/bin/env python3
"""Re-check every audit finding against the code, then write docs/audit/data/audit.json.

The published page is generated from this output, so a finding cannot drift away
from the code it describes:

  * evidence is stored as a needle, and the line number printed on the page is
    resolved here, every run;
  * a finding marked `fixed` must pass its check, or this script exits 1;
  * a finding marked `open` must still be observable for the same reason - if
    someone fixes it, this script exits 1 and says which item to re-verify.

Checks are run with the repository's own runtime (node for the JavaScript, this
interpreter for the Python) so the page reports what the code does, not what a
comment says it does.

    python3 audit/verify.py            # verify and write the data file
    python3 audit/verify.py --check    # verify and fail if the file is stale
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_OUT = ROOT / "docs" / "audit" / "data" / "audit.json"

# Import the package under test from the repository, not from site-packages.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Which ES module each JavaScript check is evaluated against.
CHECK_MODULE = {
    "AUD-01": "tools/alerts.mjs",
    "AUD-04": "tools/fees.mjs",
    "AUD-05": "tools/fees.mjs",
}


class AuditError(RuntimeError):
    pass


def load(name: str) -> dict:
    path = ROOT / "audit" / name
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:  # pragma: no cover - repo corruption
        raise AuditError(f"missing {path.relative_to(ROOT)}") from exc


# --------------------------------------------------------------------- checks
def run_node(module: str, expr: str) -> str:
    script = (
        f"import('{ (ROOT / module).as_uri() }').then((m) => {{\n"
        f"  const value = {expr};\n"
        "  const flat = (v) => (Array.isArray(v) ? v.map((x) => (x === null ? 'null' : String(x))).join(',') : (v === null ? 'null' : String(v)));\n"
        "  process.stdout.write(flat(value));\n"
        "}).catch((e) => { process.stderr.write(String(e)); process.exit(1); });"
    )
    proc = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise AuditError(f"node check failed for {module}: {proc.stderr.strip()[:400]}")
    return proc.stdout.strip()


def check_python(name: str) -> str:
    if name == "sentinel_mid":
        from kalshi_trader.marketdata import normalize_market

        row = normalize_market(
            {
                "ticker": "KXELONMARS-99",
                "status": "active",
                "yes_bid_dollars": "0.1400",
                "yes_ask_dollars": "1.0000",
                "no_bid_dollars": "0.0000",
                "last_price_dollars": "0.3000",
                "volume_fp": "1.00",
                "volume_24h_fp": "1.00",
                "open_interest_fp": "1.00",
                "yes_bid_size_fp": "1.00",
                "yes_ask_size_fp": "0.00",
                "result": "",
            }
        )
        return f"{'null' if row['yes_ask'] is None else row['yes_ask']},{row['mid']}"
    if name == "settled_sweep":
        from kalshi_trader.collector import _collect_resolutions

        seen: list[dict] = []

        class Client:
            def paginate(self, path, key, params=None, page_size=100, max_pages=1):
                seen.append(dict(params or {}))
                return []

        errors: list[str] = []
        _collect_resolutions(Client(), {}, {"crypto": ["KXBTCD"]}, [], errors, now=0)
        if errors:
            raise AuditError(f"settled sweep raised {errors[0][:120]}")
        params = seen[0] if seen else {}
        return (
            f"{'min_settled_ts' in params},{'min_close_ts' in params},"
            f"{type(params.get('min_settled_ts')).__name__}"
        )
    raise AuditError(f"unknown python check {name}")


EXPECTED = {
    ("python", "sentinel_mid"): "null,0.3",
    ("python", "settled_sweep"): "True,False,int",
}


def run_check(item: dict) -> dict:
    spec = item.get("check") or {"kind": "none"}
    kind = spec.get("kind", "none")
    if kind == "none":
        return {"kind": kind, "ok": True, "observed": "no executable check"}
    if kind == "node":
        observed = run_node(CHECK_MODULE[item["id"]], spec["expr"])
        return {"kind": kind, "ok": observed == spec["expect"], "observed": observed, "expected": spec["expect"]}
    if kind == "python":
        observed = check_python(spec["name"])
        expected = EXPECTED[(kind, spec["name"])]
        return {"kind": kind, "ok": observed == expected, "observed": observed, "expected": expected}
    if kind == "text":
        text = (ROOT / spec["file"]).read_text()
        ok = spec["needle"] in text
        return {"kind": kind, "ok": ok, "observed": f"needle present: {ok}", "expected": "needle present: True"}
    if kind == "shell":
        proc = subprocess.run(spec["argv"], cwd=ROOT, capture_output=True, text=True, timeout=300)
        want = spec.get("expectExit", 0)
        return {
            "kind": kind,
            "ok": proc.returncode == want,
            "observed": f"exit {proc.returncode}",
            "expected": f"exit {want}",
            "tail": (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [],
        }
    raise AuditError(f"{item['id']}: unknown check kind {kind}")


# ------------------------------------------------------------------ validation
def resolve_evidence(item: dict) -> list[dict]:
    out = []
    for ev in item.get("evidence", []):
        path = ROOT / ev["file"]
        if not path.exists():
            raise AuditError(f"{item['id']}: evidence file {ev['file']} does not exist")
        lines = path.read_text().splitlines()
        hit = next((i for i, line in enumerate(lines, start=1) if ev["needle"] in line), None)
        if hit is None:
            raise AuditError(f"{item['id']}: needle not found in {ev['file']}: {ev['needle']!r}")
        out.append({**ev, "line": hit})
    if not out:
        raise AuditError(f"{item['id']}: no evidence")
    return out


def build() -> dict:
    facts_doc = load("facts.json")
    items_doc = load("items.json")
    facts = facts_doc["facts"]
    items = items_doc["items"]

    fact_ids = [f["id"] for f in facts]
    if len(fact_ids) != len(set(fact_ids)):
        raise AuditError("duplicate fact id")
    for fact in facts:
        if not fact.get("url", "").startswith("https://"):
            raise AuditError(f"{fact['id']}: source is not https")
        if not fact.get("quote"):
            raise AuditError(f"{fact['id']}: no quote")

    seen = set()
    results = []
    for item in items:
        if item["id"] in seen:
            raise AuditError(f"duplicate item id {item['id']}")
        seen.add(item["id"])
        if item["status"] not in {"fixed", "open", "verified", "resolved"}:
            raise AuditError(f"{item['id']}: bad status {item['status']}")
        if not item.get("sources"):
            raise AuditError(f"{item['id']}: no source")
        for fid in item["sources"]:
            if fid not in fact_ids:
                raise AuditError(f"{item['id']}: unknown fact {fid}")
        check = run_check(item)
        # A finding whose stated status and observed state disagree is an error in
        # one of the two, and this page must not publish either until they agree.
        if item["status"] == "fixed" and not check["ok"]:
            raise AuditError(f"{item['id']}: marked fixed but its check failed ({check['observed']})")
        if item["status"] == "open" and not check["ok"]:
            raise AuditError(
                f"{item['id']}: marked open but its check now passes - the finding is fixed; "
                "re-verify it and change its status"
            )
        results.append({**item, "evidence": resolve_evidence(item), "check": check, "sources": [
            next(f for f in facts if f["id"] == fid) for fid in item["sources"]
        ]})

    counts = {status: sum(1 for i in results if i["status"] == status) for status in ("fixed", "open", "verified", "resolved")}
    return {
        "meta": {
            "checkedOn": facts_doc["meta"]["checkedOn"],
            "session": facts_doc["meta"]["session"],
            "howRead": facts_doc["meta"]["howRead"],
            "statusLegend": items_doc["meta"]["statusLegend"],
            "factCount": len(facts),
            "itemCount": len(results),
            "counts": counts,
        },
        "facts": facts,
        "items": results,
    }


def main() -> int:
    check_only = "--check" in sys.argv
    try:
        doc = build()
    except AuditError as exc:
        print(f"audit verification FAILED: {exc}", file=sys.stderr)
        # Annotations are the one part of an Actions log the API can read back, so a
        # failure in CI says why without needing the log archive.
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error::audit verification failed: {exc}")
        return 1
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if check_only:
        current = DATA_OUT.read_text() if DATA_OUT.exists() else ""
        if current != text:
            print("docs/audit/data/audit.json is stale - run python3 audit/verify.py", file=sys.stderr)
            if os.environ.get("GITHUB_ACTIONS"):
                print("::error::docs/audit/data/audit.json is stale - run python3 audit/verify.py")
            return 1
        print(f"audit data is current ({doc['meta']['itemCount']} findings, {doc['meta']['factCount']} facts)")
        return 0
    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(text)
    counts = doc["meta"]["counts"]
    print(
        f"wrote {DATA_OUT.relative_to(ROOT)} - {doc['meta']['itemCount']} findings "
        f"({counts['fixed']} fixed, {counts['open']} open, {counts['verified']} verified, {counts['resolved']} resolved), "
        f"{doc['meta']['factCount']} official facts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
