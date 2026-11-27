"""Tests for the live desk. Standard library only: ``python3 -m unittest discover -s live/tests``.

The tests assert the properties the dashboard's claims depend on:

* the $0.10 threshold is inclusive and symmetric;
* a price can never leave $0.00-$1.00;
* the simulated book's arithmetic reconciles (cash + marked positions = equity);
* no order path exists;
* every market row carries an official Kalshi source;
* resolution is only ever read from Kalshi's own status/result fields;
* the HTTP surface answers, and the chart/book endpoints match their documented shape.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "live"))

import desk as desk_module  # noqa: E402
import desk  # noqa: E402
import server as server_module  # noqa: E402
from desk import Desk, Market, STRATEGIES, TOPICS, THRESHOLD, read_quote, taker_fee  # noqa: E402

OFFICIAL_HOSTS = (
    # Both roots are documented in
    # https://docs.kalshi.com/getting_started/api_environments — a capture may come from
    # either, and /api/meta records which one.
    "kalshi.com",
    "docs.kalshi.com",
    "external-api.kalshi.com",
    "api.elections.kalshi.com",
    "external-api.demo.kalshi.co",
    "demo-api.kalshi.co",
)


def make_market(mid: float = 0.50) -> Market:
    return Market(
        ticker="TEST-1", event_ticker="TEST", series_ticker="TESTSERIES", topic="gas",
        title="Test contract", event_title="Test event", subtitle="Test", status="active",
        result=None, close_time="2027-01-01T00:00:00Z", rules="Resolves YES if the test passes.",
        series_url="https://kalshi.com/markets/testseries",
        api_url="https://external-api.demo.kalshi.co/trade-api/v2/markets/TEST-1",
        yes_bid=round(mid - 0.01, 4), yes_ask=round(mid + 0.01, 4), mid=mid, last=mid,
        volume_24h=1000.0, open_interest=500.0,
        yes_bids=[(round(mid - 0.01, 4), 500.0)], yes_asks=[(round(mid + 0.01, 4), 400.0)],
        anchor=mid, prev_mid=mid, updated_ts=time.time(),
    )


class SwingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.desk = Desk.__new__(Desk)
        import collections
        import random
        self.desk.alerts = collections.deque(maxlen=600)
        self.desk.filtered_ids = collections.deque(maxlen=600)
        self.desk.history = {"TEST-1": collections.deque(maxlen=100)}
        self.desk.markets = {}
        self.desk.positions = {}
        self.desk.closed = []
        self.desk.next_position_id = 1
        self.desk.cash = 1000.0
        self.desk.equity_curve = collections.deque(maxlen=100)
        self.desk.resolutions = []
        self.desk.rng = random.Random(1)
        self.desk.mode = "simulated"
        self.desk.market = make_market()

    def test_threshold_is_inclusive_at_ten_cents(self) -> None:
        market = self.desk.market
        self.desk._apply_mid(market, 0.60, time.time())
        self.assertEqual(len(self.desk.alerts), 1, "a move of exactly $0.10 must alert")
        self.assertAlmostEqual(self.desk.alerts[0]["absDelta"], 0.10, places=6)

    def test_no_alert_just_below_threshold(self) -> None:
        market = self.desk.market
        self.desk._apply_mid(market, 0.59, time.time())
        self.assertEqual(len(self.desk.alerts), 0, "a $0.09 move must not alert")

    def test_symmetric_in_both_directions(self) -> None:
        market = self.desk.market
        self.desk._apply_mid(market, 0.62, time.time())
        self.desk._apply_mid(market, 0.50, time.time())
        self.assertEqual(len(self.desk.alerts), 2)
        directions = {a["direction"] for a in self.desk.alerts}
        self.assertEqual(directions, {"up", "down"})

    def test_alert_carries_official_source_and_no_invented_cause(self) -> None:
        self.desk._apply_mid(self.desk.market, 0.65, time.time())
        alert = self.desk.alerts[0]
        self.assertTrue(alert["apiUrl"].startswith("https://external-api.demo.kalshi.co/"))
        self.assertIn("rules", alert)
        self.assertNotIn("cause", alert, "a cause would be an unsourced claim")
        self.assertNotIn("newsUrl", alert, "no news claim is made")
        self.assertEqual(alert["threshold"], THRESHOLD)


class PriceBoundsTests(unittest.TestCase):
    def test_simulation_never_leaves_the_binary_range(self) -> None:
        desk = Desk(mode="simulated", seed=7)
        for _ in range(400):
            desk.tick()
        for market in desk.markets.values():
            self.assertGreaterEqual(market.mid, 0.0)
            self.assertLessEqual(market.mid, 1.0)
            self.assertGreaterEqual(market.yes_bid, 0.0)
            self.assertLessEqual(market.yes_bid, 1.0)
            if market.yes_ask is not None:
                self.assertGreaterEqual(market.yes_ask, market.yes_bid - 1e-9)

    def test_every_captured_market_has_an_official_source_url(self) -> None:
        desk = Desk(mode="simulated")
        for market in desk.markets.values():
            self.assertTrue(market.api_url.startswith("https://"), market.ticker)
            host = market.api_url.split("/")[2]
            self.assertIn(host, OFFICIAL_HOSTS, f"{market.ticker} cites {host}")
            self.assertIn(market.topic, TOPICS)
            self.assertTrue(market.rules, f"{market.ticker} lost its rule text")


class FeeTests(unittest.TestCase):
    def test_fee_formula_matches_published_shape(self) -> None:
        # ceil_to_cent(0.07 * 100 * 0.50 * 0.50) = ceil(1.75) = 1.75
        self.assertAlmostEqual(taker_fee(100, 0.50), 1.75)
        self.assertAlmostEqual(taker_fee(100, 0.25), 1.32)  # 1.3125 rounds up to 1.32
        self.assertEqual(taker_fee(100, 0.0), 0.0)
        self.assertEqual(taker_fee(100, 1.0), 0.0)
        self.assertEqual(taker_fee(0, 0.5), 0.0)

    def test_fee_is_labelled_unverified_by_default(self) -> None:
        self.assertFalse(desk_module.FEE_VERIFIED)


class PortfolioTests(unittest.TestCase):
    def test_book_arithmetic_reconciles(self) -> None:
        desk = Desk(mode="simulated", seed=3)
        for _ in range(500):
            desk.tick()
        folio = desk.portfolio()
        marked = sum(p["markValue"] for p in folio["positions"])
        self.assertAlmostEqual(folio["cash"] + marked, folio["equity"], places=2)
        # Display rounding of marked positions can move this by a few cents; the identity
        # equity = cash + marks above is the exact one.
        self.assertLessEqual(abs(folio["realized"] + folio["unrealized"] - folio["totalPnl"]), 0.10)

    def test_position_cap_and_risk_budget(self) -> None:
        desk = Desk(mode="simulated", seed=11)
        for _ in range(600):
            desk.tick()
        self.assertLessEqual(len(desk.positions), desk_module.MAX_POSITIONS)
        self.assertGreaterEqual(desk.cash, -0.01, "the simulated book may not go cash-negative")
        for position in desk.positions.values():
            self.assertLessEqual(position.contracts * position.entry_price, 1000 * desk_module.RISK_FRACTION + 1e-6)

    def test_every_trade_has_a_documented_strategy_and_exit(self) -> None:
        desk = Desk(mode="simulated", seed=5)
        for _ in range(500):
            desk.tick()
        for trade in desk.portfolio()["trades"]:
            self.assertIn(trade["strategy"], STRATEGIES)
            self.assertIn(trade["side"], ("YES", "NO"))
            self.assertIn(trade["exitReason"], ("take-profit", "stop-loss", "time-stop", "settled"))

    def test_analytics_cover_four_groupings(self) -> None:
        desk = Desk(mode="simulated", seed=5)
        for _ in range(400):
            desk.tick()
        folio = desk.portfolio()
        for key in ("byStrategy", "byTopic", "byPriceBand", "byExitReason"):
            self.assertIsInstance(folio[key], list, key)


class ResolutionTests(unittest.TestCase):
    def test_only_final_states_are_recorded(self) -> None:
        desk = Desk(mode="simulated", seed=2)
        active = next(iter(desk.markets.values()))
        active.status = "active"
        active.result = None
        desk._sync_resolutions()
        self.assertEqual(desk.resolutions, [], "an active market is not a resolution")

        determined = next(iter(desk.markets.values()))
        determined.status = "determined"
        determined.result = "yes"
        desk._sync_resolutions()
        self.assertEqual(len(desk.resolutions), 1)
        self.assertEqual(desk.resolutions[0]["result"], "yes")

    def test_scalar_and_void_are_carried_through_not_coerced(self) -> None:
        desk = Desk(mode="simulated", seed=2)
        market = next(iter(desk.markets.values()))
        market.status = "finalized"
        market.result = "scalar"
        desk._sync_resolutions()
        self.assertEqual(desk.resolutions[0]["result"], "scalar")


class LiveQuoteTests(unittest.TestCase):
    def test_placeholder_book_is_not_a_collapse(self) -> None:
        row = {"yes_bid_dollars": "0.0000", "yes_ask_dollars": "1.0000", "last_price_dollars": "0.0000"}
        self.assertIsNone(read_quote(row), "0.00 x 1.00 with no trade is not a price")

    def test_crossed_book_falls_back_to_last_trade_and_is_quote_only(self) -> None:
        row = {"yes_bid_dollars": "0.5000", "yes_ask_dollars": "0.4000", "last_price_dollars": "0.4500"}
        quote = read_quote(row)
        self.assertIsNotNone(quote)
        mid, bid, ask, last = quote
        self.assertEqual(mid, 0.45)
        self.assertIsNone(ask, "a crossed ask must not be published as a quote")

    def test_wide_book_is_not_trusted_as_a_mid(self) -> None:
        row = {"yes_bid_dollars": "0.1000", "yes_ask_dollars": "0.9000", "last_price_dollars": "0.5000"}
        mid, _, ask, _ = read_quote(row)
        self.assertEqual(mid, 0.5)
        self.assertIsNone(ask)

    def test_two_sided_book_uses_its_mid(self) -> None:
        row = {"yes_bid_dollars": "0.4200", "yes_ask_dollars": "0.4400", "last_price_dollars": "0.4300"}
        self.assertEqual(read_quote(row), (0.43, 0.42, 0.44, 0.43))


class FakePoller:
    """A poller that replays scripted quotes, so live mode is tested without egress."""

    def __init__(self, script):
        self.script = script
        self.i = 0
        self.last_error = None

    def fetch_markets(self, prefix, limit=60):
        rows = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return rows

    def fetch_orderbook(self, ticker, depth=10):
        return {}

    def probe(self):
        return True


class LiveModeTests(unittest.TestCase):
    def _desk_with(self, script):
        desk = Desk(mode="live", poller=FakePoller(script))
        desk.mode = "live"
        # One series only, so the scripted rows are the only input.
        desk.markets = {"T": next(iter(desk.markets.values()))}
        desk.markets["T"].ticker = "T"
        desk.markets["T"].series_ticker = "S"
        desk.alerts.clear()
        return desk

    def test_a_real_move_in_live_mode_alerts(self) -> None:
        first = [{"ticker": "T", "yes_bid_dollars": "0.4200", "yes_ask_dollars": "0.4400",
                  "last_price_dollars": "0.4300", "status": "active"}]
        second = [{"ticker": "T", "yes_bid_dollars": "0.5500", "yes_ask_dollars": "0.5700",
                   "last_price_dollars": "0.5600", "status": "active"}]
        desk = self._desk_with([first, second])
        market = desk.markets["T"]
        market.mid, market.prev_mid = 0.43, 0.43
        desk._poll_live()
        self.assertEqual(len(desk.alerts), 0)
        desk._poll_live()
        self.assertEqual(len(desk.alerts), 1)
        self.assertAlmostEqual(desk.alerts[0]["absDelta"], 0.13, places=6)
        self.assertFalse(desk.alerts[0]["simulated"], "live alerts must not be labelled simulated")

    def test_placeholders_never_alert(self) -> None:
        placeholder = [{"ticker": "T", "yes_bid_dollars": "0.0000", "yes_ask_dollars": "1.0000",
                        "last_price_dollars": "0.0000", "status": "active"}]
        desk = self._desk_with([placeholder])
        desk.markets["T"].mid = 0.5
        for _ in range(3):
            desk._poll_live()
        self.assertEqual(len(desk.alerts), 0)
        self.assertTrue(desk.markets["T"].quote_only)


class NoOrderPathTests(unittest.TestCase):
    def test_server_handler_has_no_write_verbs(self) -> None:
        for verb in ("do_POST", "do_PUT", "do_DELETE", "do_PATCH"):
            self.assertFalse(hasattr(server_module.Handler, verb), f"{verb} exists — this file is read-only")

    def test_desk_never_calls_a_portfolio_endpoint(self) -> None:
        source = (ROOT / "live" / "desk.py").read_text()
        self.assertNotIn("/portfolio/orders", source)
        self.assertNotIn("/portfolio/balance", source)
        self.assertIn("No order is ever sent", source)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.httpd = server_module.build("127.0.0.1", cls.port, "simulated", 0.05)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path: str) -> tuple[int, str, bytes]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()

    def test_health(self) -> None:
        status, _, body = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_meta_carries_disclosure_sources_and_mode(self) -> None:
        _, _, body = self.get("/api/meta")
        meta = json.loads(body)
        self.assertEqual(meta["mode"], "simulated")
        self.assertTrue(meta["simulated"])
        self.assertIn("SIMULATED", meta["disclosure"])
        self.assertEqual(meta["threshold"], 0.10)
        self.assertIn("demo.kalshi.co", meta["endpoints"]["rest"])
        self.assertIn("docs.kalshi.com", meta["sources"]["orderbook"])
        self.assertFalse(meta["fees"]["verified"])

    def test_state_has_five_topics_every_market_sourced(self) -> None:
        _, _, body = self.get("/api/state")
        state = json.loads(body)
        self.assertEqual(set(state["topics"]), set(TOPICS))
        total = 0
        for events in state["topics"].values():
            for event in events:
                for market in event["markets"]:
                    total += 1
                    self.assertTrue(market["apiUrl"].startswith("https://"))
        self.assertEqual(total, 300)
        for key in ("alerts", "portfolio", "resolutions", "resolvingSoon", "meta"):
            self.assertIn(key, state)

    def test_series_and_book_shapes(self) -> None:
        _, _, body = self.get("/api/state")
        state = json.loads(body)
        ticker = state["topics"]["crypto"][0]["markets"][0]["ticker"]
        _, _, body = self.get(f"/api/series?ticker={ticker}&seconds=300")
        series = json.loads(body)
        self.assertEqual(series["ticker"], ticker)
        self.assertIn("points", series)
        self.assertIn("book", series)
        _, _, body = self.get(f"/api/book?ticker={ticker}")
        book = json.loads(body)
        self.assertIn("yesBids", book)
        self.assertIn("yesAsks", book)
        self.assertIn("docs.kalshi.com", book["docs"])

    def test_index_is_served(self) -> None:
        status, ctype, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"KALSHI", body)

    def test_unknown_ticker_is_reported_not_guessed(self) -> None:
        _, _, body = self.get("/api/series?ticker=NOPE&seconds=60")
        self.assertEqual(json.loads(body)["error"], "unknown ticker")

    def test_path_traversal_is_refused(self) -> None:
        try:
            status, _, body = self.get("/../desk.py")
        except urllib.error.HTTPError as exc:  # 404 is a pass
            self.assertIn(exc.code, (400, 404))
            return
        self.assertIn(b"not found", body)


if __name__ == "__main__":
    unittest.main()


class FeeMultiplierTests(unittest.TestCase):
    """The published per-series multiplier M is applied to simulated fills.

    Source: https://kalshi.com/docs/kalshi-fee-schedule.pdf ("Non-Standard Fees",
    effective 2026-07-07) — KXBTCY is listed 0/0, KXAAAGASM and KXCPI are listed 1/1.
    """

    def test_zero_multiplier_series_pays_no_fee(self):
        self.assertEqual(desk.fee_multiplier("KXBTCY-27JAN0100-T20000.00"), 0.0)
        self.assertEqual(
            desk.taker_fee(100, 0.5, desk.FEE_RATE_TAKER * desk.fee_multiplier("KXBTCY-1")), 0.0
        )

    def test_general_multiplier_series_keeps_the_published_fee(self):
        self.assertEqual(desk.fee_multiplier("KXAAAGASM-26DEC-T3.50"), 1.0)
        self.assertEqual(desk.fee_multiplier("KXCPI-1"), 1.0)
        self.assertEqual(
            desk.taker_fee(100, 0.5, desk.FEE_RATE_TAKER * desk.fee_multiplier("KXCPI-1")), 1.75
        )

    def test_unlisted_series_falls_back_to_the_general_multiplier(self):
        self.assertEqual(desk.fee_multiplier("KXNOTINTHEPUBLISHEDTABLE-1"), 1.0)
        self.assertEqual(desk.fee_multiplier(""), 1.0)

    def test_the_fee_source_is_the_published_schedule_not_a_missing_page(self):
        self.assertTrue(desk.DOCS["fees"].endswith("kalshi-fee-schedule.pdf"))
        self.assertIn("fee_rounding", desk.DOCS["feeRounding"])
