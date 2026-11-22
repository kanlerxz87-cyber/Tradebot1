from kalshi_trader.marketdata import (
    aggregate_events,
    normalize_market,
    normalize_orderbook,
    price_from_cents,
)
from tests.fixtures import GAS_MARKET_345, GAS_MARKET_355


def test_normalize_market_reads_dollar_fields_and_derives():
    market = normalize_market(
        GAS_MARKET_345,
        topic="gas",
        series_ticker="KXAAAGASM",
        api_base="https://external-api.kalshi.com/trade-api/v2",
    )
    assert market["yes_bid"] == 0.96
    assert market["yes_ask"] == 0.97
    assert market["mid"] == 0.965
    assert market["spread"] == 0.01
    assert market["price"] == 0.965
    assert market["volume_24h"] == 7018.55
    assert market["open_interest"] == 35410.59
    assert market["notional_24h_est"] == round(7018.55 * 0.965, 2)
    assert market["api_url"].endswith("/markets/KXAAAGASM-26NOV30-3.45")
    assert market["series_page_url"] == "https://kalshi.com/markets/kxaaagasm"


def test_normalize_market_implied_ask_when_missing():
    raw = {"ticker": "TEST-1", "yes_bid_dollars": "0.4000", "no_bid_dollars": "0.5500"}
    market = normalize_market(raw)
    assert market["yes_ask"] == 0.45
    assert market["no_ask"] == 0.6
    assert market["mid"] == 0.425


def test_price_from_cents_legacy():
    assert price_from_cents({"yes_bid": 42}, "yes_bid") == 0.42
    assert price_from_cents({"yes_bid": ""}, "yes_bid") is None


def test_orderbook_implied_asks_and_depth():
    book = normalize_orderbook(
        {
            "yes_dollars": [["0.0100", "200.00"], ["0.5500", "250.00"]],
            "no_dollars": [["0.4000", "50.00"], ["0.4300", "120.00"]],
        }
    )
    assert book["best_yes_bid"]["price"] == 0.55
    assert book["best_yes_bid"]["contracts"] == 250
    # best YES ask is implied by the best NO bid: 1 - 0.43 = 0.57
    assert book["best_yes_ask"]["price"] == 0.57
    assert book["spread"] == 0.02
    assert book["yes_depth_contracts"] == 450
    assert book["no_depth_contracts"] == 170


def test_orderbook_legacy_cent_format():
    book = normalize_orderbook({"yes": [[40, 10]], "no": [[55, 5]]})
    assert book["best_yes_bid"]["price"] == 0.4
    assert book["best_yes_ask"]["price"] == 0.45


def test_aggregate_events_ranks_by_est_notional():
    a = normalize_market(GAS_MARKET_345, series_ticker="KXAAAGASM", topic="gas")
    b = normalize_market(GAS_MARKET_355, series_ticker="KXAAAGASM", topic="gas")
    events = aggregate_events([a, b])
    assert len(events) == 1
    assert events[0]["event_ticker"] == "KXAAAGASM-26NOV30"
    assert events[0]["markets_count"] == 2
    assert events[0]["notional_24h_est"] > 0
