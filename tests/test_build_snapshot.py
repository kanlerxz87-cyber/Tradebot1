"""Tests for scripts/build_snapshot.py — the monitor's public demo-API snapshot builder.

The point of these tests is the failure behaviour: a single failed request must not destroy
already-collected events, and an empty run must not overwrite a good snapshot.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts import build_snapshot


class Handler(BaseHTTPRequestHandler):
    routes: dict[str, object] = {}

    def log_message(self, *args):  # silence the test output
        pass

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        # The fake host serves the full /trade-api/v2 prefix; key routes on the final segment.
        path = "/" + self.path.split("?")[0].rstrip("/").split("/")[-1]
        payload = self.routes.get(path)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return
        if isinstance(payload, int):
            self.send_response(payload)
            self.end_headers()
            return
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    """Fail fast: no backoff sleeps inside the unit tests."""
    monkeypatch.setattr(build_snapshot, "RETRY_SLEEP", 0)
    monkeypatch.setattr(build_snapshot.time, "sleep", lambda _seconds: None)


@pytest.fixture()
def server():
    handler = type("Handler", (Handler,), {"routes": {}})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/trade-api/v2", handler
    httpd.shutdown()
    httpd.server_close()


def market(event_ticker, title, price=0.5, volume=1000):
    return {
        "ticker": f"{event_ticker}-M", "event_ticker": event_ticker, "title": title,
        "status": "open", "result": None, "last_price_dollars": price,
        "yes_bid_dollars": price - 0.01, "yes_ask_dollars": price + 0.01,
        "yes_bid_size_fp": 10, "yes_ask_size_fp": 10, "volume_24h_fp": volume,
        "volume_fp": volume, "close_time": "2026-12-01T00:00:00Z",
    }


def event_page(events, cursor=None):
    return {"events": events, "cursor": cursor}


def test_collects_topic_events_and_marks_generated_at(server):
    base, handler = server
    handler.routes["/events"] = event_page([
        {"event_ticker": "KXBTC", "title": "Bitcoin price on Nov 30?", "category": "Crypto",
         "markets": [market("KXBTC", "Bitcoin price on Nov 30?")]},
    ])
    handler.routes["/markets"] = {"markets": [market("KXBTC", "Bitcoin price on Nov 30?")], "cursor": None}

    snapshot = build_snapshot.build((base,))

    assert [e["event_ticker"] for e in snapshot["events"]] == ["KXBTC"]
    assert snapshot["generated_at"] is not None, "a non-empty scan must be timestamped"
    assert snapshot["partial"] is False
    assert snapshot["errors"] == []


def test_off_topic_events_are_excluded(server):
    base, handler = server
    handler.routes["/events"] = event_page([
        {"event_ticker": "KXFOOTBALL", "title": "Will the Chiefs win?", "category": "Sports",
         "markets": [market("KXFOOTBALL", "Will the Chiefs win?")]},
    ])
    handler.routes["/markets"] = {"markets": [market("KXFOOTBALL", "Will the Chiefs win?")], "cursor": None}

    snapshot = build_snapshot.build((base,))
    assert snapshot["events"] == []


def test_one_failed_request_keeps_the_events_already_collected(server):
    base, handler = server
    handler.routes["/events"] = event_page([
        {"event_ticker": "KXGAS", "title": "Will average gas prices be above $3.60?",
         "category": "Economics", "markets": [market("KXGAS", "Will average gas prices be above $3.60?")]},
    ])
    handler.routes["/markets"] = 500  # the secondary scan fails outright

    snapshot = build_snapshot.build((base,))

    assert [e["event_ticker"] for e in snapshot["events"]] == ["KXGAS"], "collected events must survive"
    assert snapshot["partial"] is True
    assert any("/markets" in message for message in snapshot["errors"]), "the failure must be reported"
    assert snapshot["generated_at"] is not None, "a partial scan is still a real observation"


def test_second_documented_host_is_used_when_the_first_is_down(server):
    base, handler = server
    handler.routes["/events"] = event_page([
        {"event_ticker": "KXETH", "title": "Ethereum price on Nov 30?", "category": "Crypto",
         "markets": [market("KXETH", "Ethereum price on Nov 30?")]},
    ])
    handler.routes["/markets"] = {"markets": [market("KXETH", "Ethereum price on Nov 30?")], "cursor": None}

    snapshot = build_snapshot.build(("http://127.0.0.1:1/trade-api/v2", base))

    assert [e["event_ticker"] for e in snapshot["events"]] == ["KXETH"]
    assert any("127.0.0.1:1" in message for message in snapshot["errors"])


def test_empty_run_keeps_the_previous_snapshot(tmp_path, monkeypatch, server):
    base, handler = server
    handler.routes["/events"] = 500
    handler.routes["/markets"] = 500
    out = tmp_path / "snapshot.json"
    out.write_text(json.dumps({"generated_at": "2026-11-01T00:00:00Z", "events": [{"event_ticker": "KXOLD"}]}))

    monkeypatch.setattr(build_snapshot, "BASES", (base,))
    code = build_snapshot.main(["--out", str(out)])

    assert code == 0
    kept = json.loads(out.read_text())
    assert [e["event_ticker"] for e in kept["events"]] == ["KXOLD"], "a good snapshot must not be blanked"


def test_empty_run_without_a_previous_snapshot_reports_an_error(tmp_path, monkeypatch, server):
    base, handler = server
    handler.routes["/events"] = 500
    handler.routes["/markets"] = 500
    out = tmp_path / "snapshot.json"

    monkeypatch.setattr(build_snapshot, "BASES", (base,))
    code = build_snapshot.main(["--out", str(out)])

    assert code == 0, "the deploy step must not be broken by an unreachable API"
    written = json.loads(out.read_text())
    assert written["events"] == []
    assert written["generated_at"] is None
    assert written["error"], "the stub must say why it is empty"


def test_require_data_fails_the_check_when_nothing_was_collected(tmp_path, monkeypatch, server):
    base, handler = server
    handler.routes["/events"] = 500
    handler.routes["/markets"] = 500

    monkeypatch.setattr(build_snapshot, "BASES", (base,))
    assert build_snapshot.main(["--out", str(tmp_path / "s.json"), "--require-data"]) == 2


def test_every_published_event_carries_a_market_with_a_source_identifier(server):
    base, handler = server
    handler.routes["/events"] = event_page([
        {"event_ticker": "KXBTCD", "title": "Bitcoin price on Nov 22, 2026?", "category": "Crypto",
         "series_ticker": "KXBTCD", "markets": [market("KXBTCD", "Bitcoin price on Nov 22, 2026?")]},
    ])
    handler.routes["/markets"] = {"markets": [market("KXBTCD", "Bitcoin price on Nov 22, 2026?")], "cursor": None}

    snapshot = build_snapshot.build((base,))
    for event in snapshot["events"]:
        assert event["event_ticker"], "an event without a ticker cannot be linked to a source"
        for contract in event["markets"]:
            assert contract["ticker"], "a market without a ticker cannot be linked to a source"
