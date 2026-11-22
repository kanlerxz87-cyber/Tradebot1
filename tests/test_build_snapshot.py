"""Tests for scripts/build_snapshot.py — the monitor's published demo snapshot.

The implementation was rewritten by a parallel session around series-based discovery and a
last-known fallback. These tests pin the two properties that make it safe to publish:

  * a total refresh failure must retain the previous observations with their original timestamps,
    not blank the file and not invent new values;
  * a request that fails with a client error must not be retried, so a bad parameter cannot turn
    into a retry storm against the exchange.

Network access is not required: `collect()` is replaced, and `fetch()` is exercised against a
local HTTP server.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from scripts import build_snapshot


class Handler(BaseHTTPRequestHandler):
    status = 200
    body = b"{}"
    hits = 0

    def log_message(self, *args):  # silence test output
        pass

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        # Read from the subclass so a test can retarget the response.
        type(self).hits += 1
        body = type(self).body
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def server(monkeypatch):
    handler = type("Handler", (Handler,), {"status": 200, "body": b"{}", "hits": 0})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(build_snapshot, "BASE", f"http://127.0.0.1:{httpd.server_port}/trade-api/v2")
    yield handler
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def no_retry_sleeps(monkeypatch):
    monkeypatch.setattr(build_snapshot.time, "sleep", lambda _seconds: None)


def test_activity_rejects_values_that_are_not_a_non_negative_number():
    assert build_snapshot.activity("12.5") == pytest.approx(12.5)
    assert build_snapshot.activity(None) == -1
    assert build_snapshot.activity("not a number") == -1
    assert build_snapshot.activity("-3") == -1


def test_a_client_error_is_not_retried(server, monkeypatch):
    server.status = 400
    with pytest.raises(Exception):
        build_snapshot.fetch("/events", {"limit": 1})
    assert server.hits == 1, "a 4xx will not improve on retry, so it must not be retried"


def test_a_transient_server_error_is_retried(server, monkeypatch):
    server.status = 503
    with pytest.raises(Exception):
        build_snapshot.fetch("/events", {"limit": 1})
    assert server.hits == 3, "5xx is retried up to the documented three attempts"


def test_a_refresh_failure_retains_the_previous_snapshot(tmp_path, monkeypatch):
    out = tmp_path / "snapshot.json"
    previous = {
        "generated_at": "2026-11-20T00:00:00+00:00",
        "events": [{"event_ticker": "KXOLD", "observed_at": "2026-11-20T00:00:00+00:00"}],
    }
    out.write_text(json.dumps(previous))
    monkeypatch.setattr(build_snapshot, "OUT", out)

    def boom():
        raise OSError("connection reset")
    monkeypatch.setattr(build_snapshot, "collect", boom)
    build_snapshot.main()

    kept = json.loads(out.read_text())
    assert [event["event_ticker"] for event in kept["events"]] == ["KXOLD"], "observations must survive"
    assert kept["generated_at"] == "2026-11-20T00:00:00+00:00", "the original timestamp must not be rewritten"
    assert kept["partial"] is True
    assert kept["last_refresh_error"] == "OSError"
    assert kept["attempted_at"], "the failed attempt must be visible"


def test_a_failure_with_no_previous_snapshot_writes_an_explicit_stub(tmp_path, monkeypatch):
    out = tmp_path / "snapshot.json"
    monkeypatch.setattr(build_snapshot, "OUT", out)
    monkeypatch.setattr(build_snapshot, "collect", lambda: (_ for _ in ()).throw(ValueError("no series")))
    build_snapshot.main()

    written = json.loads(out.read_text())
    assert written["events"] == []
    assert written["generated_at"] is None, "an empty file must not claim an observation time"
    assert written["last_refresh_error"] == "ValueError"


def test_a_successful_refresh_is_written_through(tmp_path, monkeypatch):
    out = tmp_path / "snapshot.json"
    monkeypatch.setattr(build_snapshot, "OUT", out)
    monkeypatch.setattr(build_snapshot, "collect", lambda: {
        "generated_at": "2026-11-22T00:00:00+00:00", "partial": True,
        "events": [{"event_ticker": "KXNEW", "markets": [{"ticker": "KXNEW-M"}]}], "errors": [],
    })
    build_snapshot.main()
    written = json.loads(out.read_text())
    assert written["generated_at"] == "2026-11-22T00:00:00+00:00"
    assert "last_refresh_error" not in written
    assert written["events"][0]["event_ticker"] == "KXNEW"


def test_add_event_ignores_a_series_outside_the_five_topics():
    events: dict = {}
    build_snapshot.add_event(events, {"event_ticker": "KXFOOT", "series_ticker": "KXFOOT",
                                      "title": "Will the Chiefs win?", "markets": []}, {})
    assert events == {}


def test_add_event_stamps_a_source_url_on_every_market():
    series = {"KXBTC": {"ticker": "KXBTC", "title": "Bitcoin", "category": "Crypto", "tags": ["Crypto"]}}
    event = {"event_ticker": "KXBTC-26NOV", "series_ticker": "KXBTC", "title": "Bitcoin price?",
             "markets": [{"ticker": "KXBTC-26NOV-T50000", "last_price_dollars": 0.5, "volume_24h_fp": 10}]}
    events: dict = {}
    build_snapshot.add_event(events, event, series)

    assert len(events) == 1, "a crypto series is one of the five topics"
    record = next(iter(events.values()))
    assert record["source_url"].endswith("/events/KXBTC-26NOV")
    market = record["markets"][0]
    assert market["source_url"].endswith("/markets/KXBTC-26NOV-T50000")
    assert market["observed_at"], "each observation carries its own timestamp"
    assert market["verification"] == "official_public_demo_api_observation"


def test_the_published_snapshot_is_valid_json_with_a_source_per_event():
    path = Path(__file__).resolve().parent.parent / "docs" / "data" / "snapshot.json"
    if not path.exists():
        pytest.skip("no published snapshot committed yet")
    payload = json.loads(path.read_text())
    for event in payload.get("events", []):
        assert event.get("source_url"), f"{event.get('event_ticker')} has no source link"
        for market in event.get("markets", []):
            assert market.get("source_url"), f"{market.get('ticker')} has no source link"
