"""
Unit tests using synthetic, clearly-fictional fixture data (NOT real Kalshi
market data) to validate the swing-detection, scoring, strategy, and
portfolio math. Run with: python -m pytest scripts/tests -q
(or python -m unittest discover scripts/tests if pytest isn't installed).
"""
import unittest

from .. import alerts as alerts_mod
from .. import strategies as strat_mod
from .. import portfolio as pf_mod
from .. import categorize as cat_mod
from .. import config


def fake_market(ticker="TEST-MKT-1", price_dollars="0.45", volume=1000, category=None,
                 title="Synthetic test market — not a real Kalshi market"):
    return {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0],
        "title": title,
        "yes_bid_dollars": price_dollars,
        "yes_ask_dollars": price_dollars,
        "volume": volume,
        "status": "open",
        "category": category,
    }


class TestMidPrice(unittest.TestCase):
    def test_dollars_fields_preferred(self):
        m = fake_market(price_dollars="0.37")
        self.assertAlmostEqual(alerts_mod.market_mid_price(m), 0.37)

    def test_legacy_cent_fields_fallback(self):
        m = {"yes_bid": 40, "yes_ask": 44}
        self.assertAlmostEqual(alerts_mod.market_mid_price(m), 0.42)

    def test_missing_price_returns_none(self):
        self.assertIsNone(alerts_mod.market_mid_price({}))


class TestSwingDetection(unittest.TestCase):
    def test_detects_swing_at_or_above_threshold(self):
        current = [{"ticker": "T1", "price": 0.60, "title": "x", "event_ticker": "T1EV",
                    "volume": 10, "kalshi_url": "u", "source_endpoint": "s"}]
        prev = {"T1": 0.50}
        swings, new_prices = alerts_mod.detect_swings("crypto", "Crypto", current, prev)
        self.assertEqual(len(swings), 1)
        self.assertEqual(swings[0]["direction"], "up")
        self.assertAlmostEqual(swings[0]["delta"], 0.10)
        self.assertEqual(new_prices["T1"], 0.60)

    def test_no_alert_below_threshold(self):
        current = [{"ticker": "T1", "price": 0.55, "title": "x", "event_ticker": "T1EV",
                    "volume": 10, "kalshi_url": "u", "source_endpoint": "s"}]
        prev = {"T1": 0.50}
        swings, _ = alerts_mod.detect_swings("crypto", "Crypto", current, prev)
        self.assertEqual(len(swings), 0)

    def test_downward_swing_detected(self):
        current = [{"ticker": "T1", "price": 0.30, "title": "x", "event_ticker": "T1EV",
                    "volume": 10, "kalshi_url": "u", "source_endpoint": "s"}]
        prev = {"T1": 0.45}
        swings, _ = alerts_mod.detect_swings("gas_prices", "Gas Prices", current, prev)
        self.assertEqual(len(swings), 1)
        self.assertEqual(swings[0]["direction"], "down")

    def test_first_sighting_no_alert(self):
        current = [{"ticker": "NEWTICKER", "price": 0.90, "title": "x", "event_ticker": "EV",
                    "volume": 10, "kalshi_url": "u", "source_endpoint": "s"}]
        swings, new_prices = alerts_mod.detect_swings("golf", "Golf", current, {})
        self.assertEqual(len(swings), 0)
        self.assertEqual(new_prices["NEWTICKER"], 0.90)


class TestCategorize(unittest.TestCase):
    def test_golf_requires_keyword_even_with_sports_category(self):
        m = fake_market(ticker="KXNFLGAME-1", title="Chiefs vs Bills winner")
        self.assertIsNone(cat_mod.categorize_market(m, event_category="Sports"))

    def test_golf_series_hint_matches(self):
        m = fake_market(ticker="KXPGATOUR-MAST26-SCHEFFLER", title="The Masters Champion")
        self.assertEqual(cat_mod.categorize_market(m, event_category="Sports"), "golf")

    def test_crypto_keyword_fallback(self):
        m = fake_market(ticker="SOMETICKER-1", title="Will Bitcoin close above $100k?")
        self.assertEqual(cat_mod.categorize_market(m, event_category=None), "crypto")

    def test_unmatched_returns_none(self):
        m = fake_market(ticker="RANDOM-1", title="Totally unrelated synthetic test topic")
        self.assertIsNone(cat_mod.categorize_market(m, event_category="Some Other Category"))


class TestStrategies(unittest.TestCase):
    def test_momentum_follow_buys_direction_of_move(self):
        alert = {"ticker": "T1", "topic": "crypto", "direction": "up", "delta": 0.12,
                 "title": "synthetic", "kalshi_url": "u"}
        market_by_ticker = {"T1": {"price": 0.60, "ticker": "T1", "topic": "crypto", "volume": 50}}
        trades = strat_mod.generate_momentum_trades([alert], market_by_ticker)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["side"], "yes")
        self.assertAlmostEqual(trades[0]["entry_price"], 0.60)

    def test_mean_reversion_fades_large_thin_moves_only(self):
        big_thin_alert = {"ticker": "T1", "topic": "culture", "direction": "up", "delta": 0.20,
                           "title": "synthetic", "kalshi_url": "u"}
        small_alert = {"ticker": "T2", "topic": "culture", "direction": "up", "delta": 0.10,
                        "title": "synthetic", "kalshi_url": "u"}
        thick_alert = {"ticker": "T3", "topic": "culture", "direction": "up", "delta": 0.20,
                       "title": "synthetic", "kalshi_url": "u"}
        market_by_ticker = {
            "T1": {"price": 0.70, "ticker": "T1", "topic": "culture", "volume": 10},
            "T2": {"price": 0.70, "ticker": "T2", "topic": "culture", "volume": 10},
            "T3": {"price": 0.70, "ticker": "T3", "topic": "culture", "volume": 5000},
        }
        trades = strat_mod.generate_mean_reversion_trades(
            [big_thin_alert, small_alert, thick_alert], market_by_ticker
        )
        tickers_traded = {t["ticker"] for t in trades}
        self.assertEqual(tickers_traded, {"T1"})
        self.assertEqual(trades[0]["side"], "no")  # faded the upward move

    def test_settlement_pays_winner_and_zeros_loser(self):
        trade_win = {"ticker": "T1", "side": "yes", "status": "open", "contracts": 10,
                     "cost_basis": 4.0, "entry_price": 0.40}
        trade_lose = {"ticker": "T2", "side": "yes", "status": "open", "contracts": 10,
                      "cost_basis": 7.0, "entry_price": 0.70}
        resolved = {"T1": {"result": "yes"}, "T2": {"result": "no"}}
        t1 = strat_mod.settle_trade_if_resolved(dict(trade_win), resolved)
        t2 = strat_mod.settle_trade_if_resolved(dict(trade_lose), resolved)
        self.assertEqual(t1["status"], "closed_won")
        self.assertAlmostEqual(t1["pnl"], 10 * 1.0 - 4.0)
        self.assertEqual(t2["status"], "closed_lost")
        self.assertAlmostEqual(t2["pnl"], -7.0)


class TestPortfolio(unittest.TestCase):
    def test_recompute_from_mixed_trades(self):
        trades = [
            {"ticker": "T1", "side": "yes", "status": "closed_won", "contracts": 10,
             "cost_basis": 4.0, "entry_price": 0.40, "exit_price": 1.0, "pnl": 6.0,
             "strategy": "momentum_follow", "topic": "crypto"},
            {"ticker": "T2", "side": "no", "status": "open", "contracts": 10,
             "cost_basis": 3.0, "entry_price": 0.30, "exit_price": None, "pnl": None,
             "strategy": "high_liquidity_value", "topic": "golf"},
        ]
        price_by_ticker = {"T2": 0.40}  # "no" side worth (1-0.40)=0.60 now, up from 0.30 entry
        pf = pf_mod.recompute_portfolio(trades, price_by_ticker)
        self.assertAlmostEqual(pf["realized_pnl_usd"], 6.0)
        self.assertAlmostEqual(pf["unrealized_pnl_usd"], (0.60 - 0.30) * 10)
        self.assertEqual(pf["win_count"], 1)
        self.assertEqual(pf["open_positions_count"], 1)
        expected_cash = config.STARTING_PAPER_BALANCE_USD - 4.0 + 10.0 - 3.0
        self.assertAlmostEqual(pf["cash_usd"], round(expected_cash, 2))


if __name__ == "__main__":
    unittest.main()
