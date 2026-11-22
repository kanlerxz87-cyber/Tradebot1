"""Guards on the published site and the exported data.

These tests exist because the site is the deliverable that a reviewer reads. They
fail if a claim loses its source, if a captured row is mislabelled, or if an
internal link breaks.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def built(tmp_path):
    """Build the site into a temp dir the same way the release job does."""
    out = tmp_path / "docs"
    data = tmp_path / "data"
    env = {"KALSHI_NEWS_LOOKBACK_HOURS": "480", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    subprocess.run([sys.executable, "-m", "engine.export_site_data", "--out", str(data), "--replay"],
                   cwd=ROOT, check=True, capture_output=True, env={**env})
    subprocess.run([sys.executable, "-m", "engine.build_site", "--out", str(out), "--data", str(data)],
                   cwd=ROOT, check=True, capture_output=True, env={**env})
    return out, data


def test_every_page_builds_and_links_resolve(built):
    out, _ = built
    from engine.check_site import check
    report = check(out)
    assert report["errors"] == [], report["errors"]
    assert report["pages"] >= 11


def test_no_market_row_is_labelled_live_in_a_replay_build(built):
    _, data = built
    payload = json.loads((data / "dashboard.json").read_text())
    assert payload["provenance"] == "captured-replay"
    rows = [m for topic in payload["topics"] for m in topic["markets"]]
    assert rows, "the replay must produce at least one market row"
    for row in rows:
        assert row["provenance"] == "captured-replay", row["ticker"]
        assert row["capture_url"], f"{row['ticker']} has no capture URL"


def test_every_market_row_has_a_source_link(built):
    _, data = built
    payload = json.loads((data / "dashboard.json").read_text())
    for topic in payload["topics"]:
        for row in topic["markets"]:
            assert row.get("page_url") or row.get("capture_url"), row["ticker"]
            assert row["page_url"].startswith("https://kalshi.com/"), row["ticker"]


def test_alerts_respect_the_ten_cent_rule(built):
    _, data = built
    payload = json.loads((data / "dashboard.json").read_text())
    assert payload["alerts"], "the replay must exercise the alert path"
    for alert in payload["alerts"]:
        assert abs(float(alert["delta"])) >= 0.10 - 1e-9, alert


def test_selective_alerts_are_a_subset_of_all_alerts(built):
    _, data = built
    payload = json.loads((data / "dashboard.json").read_text())
    all_ids = {f"{a['ticker']}@{a['ts']}" for a in payload["alerts"]}
    selective_ids = {f"{a['ticker']}@{a['ts']}" for a in payload["selective_alerts"]}
    assert selective_ids <= all_ids
    for alert in payload["selective_alerts"]:
        assert alert["score"] is not None
        assert float(alert["score"]) > 0


def test_verification_registry_has_a_source_on_every_fact():
    from engine.verification import FACTS
    for fact in FACTS:
        assert fact["source"].startswith("http"), fact["id"]
        assert fact["status"] in {"verified", "flagged", "unverified"}, fact["id"]
        assert fact["check"], fact["id"]
        # A verified fact must never be the one we could not check.
        if fact["status"] == "verified":
            assert "NOT PERFORMED" not in fact["check"], fact["id"]


def test_flagged_page_lists_every_non_verified_fact(built):
    out, _ = built
    html = (out / "flagged.html").read_text()
    from engine.verification import FACTS
    for fact in FACTS:
        if fact["status"] != "verified":
            assert fact["id"] in html, fact["id"]


def test_culture_page_explains_an_empty_topic_honestly(built):
    out, _ = built
    html = (out / "topics" / "culture.html").read_text()
    assert "No live entries in this topic at capture time" in html
    assert "instead of inventing a price" in html


def test_portal_backlink_is_reported_not_failed():
    """A link above the site root points at the hosting portal; it must be reported,
    never silently treated as a broken internal link, and never fail the build."""
    from engine.check_site import _climbs_out
    from pathlib import Path
    root = Path("/site").resolve()
    assert _climbs_out(root / "index.html", root, "../../index.html") is True
    assert _climbs_out(root / "topics/gas.html", root, "../flagged.html") is False
    assert _climbs_out(root / "index.html", root, "topics/gas.html") is False


def test_no_markdown_emphasis_leaks_into_titles(built):
    _, data = built
    payload = json.loads((data / "dashboard.json").read_text())
    for topic in payload["topics"]:
        for row in topic["markets"]:
            assert "**" not in (row.get("title") or ""), row["ticker"]


def test_docs_directory_matches_a_fresh_build(built):
    """The committed docs/ output must be reproducible from the generators."""
    out, _ = built
    committed = ROOT / "docs" / "engine"
    if not (committed / "index.html").exists():
        pytest.skip("docs/engine not built yet")
    fresh = (out / "index.html").read_text()
    assert "Kalshi live-event dashboard" in fresh
    assert (committed / ".nojekyll").exists()
    # The published copy must carry the same verification register as a fresh build.
    for name in ("verification.json", "dashboard.json", "captures.json"):
        assert (committed / "data" / name).exists(), name
