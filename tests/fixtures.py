"""Test fixtures built from real API responses captured during verification.

The market objects below are verbatim field subsets from
``GET https://external-api.kalshi.com/trade-api/v2/markets?series_ticker=KXAAAGASM&status=open``
captured on 2026-11-22 (see docs/data/sources.json, source S10/S5).
"""

from __future__ import annotations

GAS_MARKET_345 = {
    "ticker": "KXAAAGASM-26NOV30-3.45",
    "event_ticker": "KXAAAGASM-26NOV30",
    "market_type": "binary",
    "title": "Will average **gas prices** be above $3.45?",
    "yes_sub_title": "Above 3.45",
    "no_sub_title": "Above 3.45",
    "status": "active",
    "close_time": "2026-11-30T04:59:00Z",
    "expected_expiration_time": "2026-11-30T15:00:00Z",
    "yes_bid_dollars": "0.9600",
    "yes_ask_dollars": "0.9700",
    "no_bid_dollars": "0.0300",
    "no_ask_dollars": "0.0400",
    "last_price_dollars": "0.9700",
    "previous_price_dollars": "0.9200",
    "yes_bid_size_fp": "1997.00",
    "yes_ask_size_fp": "5009.00",
    "volume_fp": "43036.56",
    "volume_24h_fp": "7018.55",
    "open_interest_fp": "35410.59",
    "result": "",
    "rules_primary": (
        "If average regular gas prices for United States are strictly greater than $3.45 on "
        "Nov 30, 2026 according to AAA, then the market resolves to Yes."
    ),
}

GAS_MARKET_355 = {
    "ticker": "KXAAAGASM-26NOV30-3.55",
    "event_ticker": "KXAAAGASM-26NOV30",
    "market_type": "binary",
    "title": "Will average **gas prices** be above $3.55?",
    "yes_sub_title": "Above 3.55",
    "status": "active",
    "close_time": "2026-11-30T04:59:00Z",
    "yes_bid_dollars": "0.1000",
    "yes_ask_dollars": "0.1300",
    "no_bid_dollars": "0.8700",
    "no_ask_dollars": "0.9000",
    "last_price_dollars": "0.1300",
    "previous_price_dollars": "0.1400",
    "yes_bid_size_fp": "185.47",
    "yes_ask_size_fp": "5201.00",
    "volume_fp": "79237.43",
    "volume_24h_fp": "2324.37",
    "open_interest_fp": "27550.76",
    "result": "",
}

GOLF_SERIES = {
    "ticker": "KXPGAEAGLE",
    "title": "Player to Record an Eagle in Round",
    "category": "Sports",
    "categories": ["Sports"],
    "tags": ["Golf"],
    "frequency": "custom",
    "volume_fp": "542000.00",
    "settlement_sources": [{"name": "ESPN", "url": "https://espn.com"}],
}

GAS_SERIES = {
    "ticker": "KXAAAGASM",
    "title": "US gas price, monthly",
    "category": "Economics",
    "categories": ["Economics", "Commodities"],
    "tags": ["Oil and energy", "Oil & Gas"],
    "frequency": "monthly",
    "volume_fp": "1000.00",
    "settlement_sources": [{"name": "AAA", "url": "https://gasprices.aaa.com/"}],
}

CRYPTO_SERIES = {
    "ticker": "KXBTCHIT90K",
    "title": "Bitcoin above $90,000 by a date",
    "category": "Crypto",
    "categories": ["Crypto"],
    "tags": ["BTC"],
    "frequency": "custom",
    "volume_fp": "17464.00",
}

ELECTION_SERIES = {
    "ticker": "KXNEXTNATOSECGEN",
    "title": "Who will be the next Secretary General of NATO?",
    "category": "Elections",
    "categories": ["Elections"],
    "tags": ["International elections"],
    "frequency": "custom",
    "volume_fp": "500.00",
}

CULTURE_SERIES = {
    "ticker": "KXOSCARS",
    "title": "Oscars",
    "category": "Entertainment",
    "categories": ["Entertainment"],
    "tags": ["Oscars", "Movies"],
    "frequency": "annual",
    "volume_fp": "120000.00",
}


class FakeClient:
    """Minimal stand-in for RestClient used by collector tests (no network)."""

    def __init__(self, series, events, markets_by_series, settled=None, orderbooks=None):
        self._series = series
        self._events = events
        self._markets = markets_by_series
        self._settled = settled or {}
        self._orderbooks = orderbooks or {}
        self.request_count = 0
        self.errors: list[str] = []

    def exchange_status(self):
        self.request_count += 1
        return {"exchange_active": True, "trading_active": True}

    def series(self, **params):
        self.request_count += 1
        category = params.get("category")
        tags = params.get("tags")
        out = []
        for item in self._series:
            if category and category not in (item.get("categories") or [item.get("category")]):
                continue
            if tags and tags not in (item.get("tags") or []):
                continue
            out.append(item)
        return out

    def paginate(self, path, key, params=None, page_size=200, max_pages=25):
        self.request_count += 1
        params = params or {}
        if path == "/events":
            return self._events
        if path == "/markets":
            series = params.get("series_ticker")
            status = params.get("status", "open")
            if status == "settled":
                return self._settled.get(series, [])
            return self._markets.get(series, [])
        return []

    def orderbook(self, ticker, depth=None):
        self.request_count += 1
        return self._orderbooks.get(
            ticker,
            {
                "yes_dollars": [["0.5200", "100.00"], ["0.5500", "250.00"]],
                "no_dollars": [["0.4000", "50.00"], ["0.4300", "120.00"]],
            },
        )
