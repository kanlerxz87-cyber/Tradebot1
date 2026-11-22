"""Payloads captured from the live Kalshi demo API on 2026-11-22.

Each fixture records the exact request path it came from so the source of every
number in the tests is traceable. Values are copied, not invented; timestamps and
identifiers are the only edits (markets that resolved would otherwise disappear
from the feed and make the fixture rot).
"""

CAPTURED_AT = "2026-11-22T07:00:00Z"

# GET https://external-api.demo.kalshi.co/trade-api/v2/exchange/status
EXCHANGE_STATUS = {
    "exchange_active": True,
    "trading_active": True,
    "intra_exchange_transfers_active": True,
    "exchange_index_statuses": [
        {"exchange_index": 0, "description": "Default", "exchange_active": True, "trading_active": True,
         "intra_exchange_transfers_active": True},
    ],
}

# GET /events?status=open&with_nested_markets=true&series_ticker=KXPGATOUR
# Note: real Kalshi events carry `category` but NOT `tags`; the Golf tag lives on
# the series (GET /series/KXPGATOUR), which is why the fixture supplies both.
GOLF_EVENTS = {
    "cursor": "",
    "events": [
        {
            "category": "Sports",
            "event_ticker": "KXPGATOUR-THRC26",
            "series_ticker": "KXPGATOUR",
            "settlement_sources": [
                {"name": "the Governing League", "url": "https://www.pgatour.com/"},
                {"name": "ESPN", "url": "https://www.espn.com"},
            ],
            "mutually_exclusive": True,
            "markets": [
                {
                    "ticker": "KXPGATOUR-THRC26-CBEZ",
                    "event_ticker": "KXPGATOUR-THRC26",
                    "title": "The RSM Classic: Christiaan Bezuidenhout wins",
                    "yes_sub_title": "Christiaan Bezuidenhout",
                    "status": "active",
                    "close_time": "2026-12-06T00:00:00Z",
                    "expected_expiration_time": "2026-11-22T00:00:00Z",
                    "last_price_dollars": "0.0030",
                    "yes_bid_dollars": "0.0020",
                    "yes_ask_dollars": "0.0030",
                    "yes_bid_size_fp": "83333.33",
                    "yes_ask_size_fp": "55553.54",
                    "no_bid_dollars": "0.9970",
                    "no_ask_dollars": "0.9980",
                    "volume_fp": "180379.74",
                    "volume_24h_fp": "6579.54",
                    "open_interest_fp": "179921.97",
                    "notional_value_dollars": "1.0000",
                    "price_level_structure": "tapered_deci_cent",
                    "result": "",
                    "rules_primary": "If Christiaan Bezuidenhout wins the The RSM Classic, then the market resolves to Yes.",
                },
                {
                    "ticker": "KXPGATOUR-THRC26-ZBAU",
                    "event_ticker": "KXPGATOUR-THRC26",
                    "title": "The RSM Classic: Zachary Bauchou wins",
                    "yes_sub_title": "Zachary Bauchou",
                    "status": "active",
                    "close_time": "2026-12-06T00:00:00Z",
                    "last_price_dollars": "0.0030",
                    "yes_bid_dollars": "0.0000",
                    "yes_ask_dollars": "1.0000",
                    "no_bid_dollars": "0.0000",
                    "volume_fp": "80931.04",
                    "volume_24h_fp": "0.00",
                    "open_interest_fp": "77683.83",
                    "notional_value_dollars": "1.0000",
                    "result": "",
                },
            ],
        }
    ],
}

# GET /events?status=open&with_nested_markets=true&category=Crypto
CRYPTO_EVENTS = {
    "cursor": "",
    "events": [
        {
            "category": "Crypto",
            "event_ticker": "KXBTCD-26NOV22",
            "series_ticker": "KXBTCD",
            "settlement_sources": [{"name": "CF Benchmarks", "url": "https://www.cfbenchmarks.com/"}],
            "markets": [
                {
                    "ticker": "KXBTCD-26NOV22-T95000",
                    "event_ticker": "KXBTCD-26NOV22",
                    "title": "Will Bitcoin be above $95,000 at 5pm EST on Nov 22?",
                    "yes_sub_title": "$95,000 or above",
                    "status": "active",
                    "close_time": "2026-11-22T22:00:00Z",
                    "last_price_dollars": "0.4200",
                    "yes_bid_dollars": "0.4100",
                    "yes_ask_dollars": "0.4300",
                    "no_bid_dollars": "0.5700",
                    "volume_fp": "1250000.00",
                    "volume_24h_fp": "450000.00",
                    "open_interest_fp": "880000.00",
                    "notional_value_dollars": "1.0000",
                    "result": "",
                }
            ],
        }
    ],
}

# GET /events?status=open&with_nested_markets=true&category=Elections (demo)
ELECTIONS_EVENTS = {
    "cursor": "",
    "events": [
        {
            "category": "Elections",
            "event_ticker": "KXNEXTNATOSECGEN-99",
            "series_ticker": "KXNEXTNATOSECGEN",
            "settlement_sources": [{"name": "North Atlantic Treaty Organization", "url": "https://www.nato.int/"}],
            "markets": [
                {
                    "ticker": "KXNEXTNATOSECGEN-99-KIOH",
                    "event_ticker": "KXNEXTNATOSECGEN-99",
                    "title": "Will Klaus Iohannis be the next Secretary General of NATO?",
                    "yes_sub_title": "Klaus Iohannis",
                    "status": "active",
                    "close_time": "2099-01-08T15:00:00Z",
                    "last_price_dollars": "0.0200",
                    "yes_bid_dollars": "0.0200",
                    "yes_ask_dollars": "1.0000",
                    "no_bid_dollars": "0.0000",
                    "volume_fp": "13.16",
                    "volume_24h_fp": "0.00",
                    "open_interest_fp": "4.00",
                    "notional_value_dollars": "1.0000",
                    "result": "",
                }
            ],
        }
    ],
}

# GET /series/{series_ticker}
SERIES = {
    "KXPGATOUR": {"ticker": "KXPGATOUR", "title": "PGA Tour", "category": "Sports", "tags": ["Golf"]},
    "KXBTCD": {"ticker": "KXBTCD", "title": "Bitcoin daily", "category": "Crypto", "tags": ["BTC"]},
    "KXNEXTNATOSECGEN": {"ticker": "KXNEXTNATOSECGEN", "title": "Next NATO Secretary General",
                         "category": "Elections", "tags": ["International elections"]},
}

# GET /markets/{ticker}/orderbook  (shape from the orderbook documentation page)
ORDERBOOK_CBEZ = {
    "orderbook_fp": {
        "yes_dollars": [["0.0010", "1200.00"], ["0.0020", "83333.33"]],
        "no_dollars": [["0.9960", "400.00"], ["0.9970", "2500.00"]],
    }
}

# GET /search/tags_by_categories (trimmed to the categories this project uses)
TAGS_BY_CATEGORIES = {
    "tags_by_categories": {
        "Business": None,
        "Commodities": ["Metals", "Oil & Gas", "Gold", "Silver"],
        "Crypto": ["BTC", "ETH", "SOL", "Bitcoin", "Ethereum"],
        "Elections": ["US Elections", "International elections", "Senate", "Governor"],
        "Entertainment": ["Music", "Television", "Oscars", "Movies", "Awards"],
        "Mentions": ["Earnings", "Politicians"],
        "Sports": ["Golf", "Basketball", "Football", "Tennis"],
        "Politics": ["Trump", "Congress"],
    }
}
