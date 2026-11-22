"""Catalyst links must be sourced or clearly labelled as searches — never asserted causes."""

from kalshi_trader import catalysts

MARKET = {
    "ticker": "KXAAAGASW-26NOV23-3.6300",
    "topic": "gas",
    "title": "Will average **gas prices** be above $3.6300?",
    "yes_sub_title": "Above 3.6300",
    "series_ticker": "KXAAAGASW",
    "series_page_url": "https://kalshi.com/markets/kxaaagasw",
    "api_url": "https://external-api.kalshi.com/trade-api/v2/markets/KXAAAGASW-26NOV23-3.6300",
    "rules_primary": "If average regular gas prices for United States are strictly greater than $3.6300 on Nov 23, 2026 according to AAA, then the market resolves to Yes.",
}

SERIES_META = {
    "KXAAAGASW": {
        "ticker": "KXAAAGASW",
        "contract_terms_url": "https://kalshi.com/terms/kxaaagasw",
        "settlement_sources": [{"name": "AAA", "url": "https://gasprices.aaa.com/"}],
    }
}


def test_keywords_drop_numbers_stopwords_and_tickers():
    words = catalysts.keywords(MARKET)
    assert "gas" in words and "prices" in words
    assert "3.6300" not in words
    assert "above" not in words
    assert all(w.isalpha() or "-" in w for w in words)


def test_official_links_come_only_from_api_fields():
    market = {**MARKET, "series_ticker": "KXAAAGASW"}
    links = catalysts.official_links(market, {**SERIES_META["KXAAAGASW"]})
    urls = [item["url"] for item in links]
    assert "https://kalshi.com/markets/kxaaagasw" in urls
    assert "https://kalshi.com/terms/kxaaagasw" in urls
    assert "https://gasprices.aaa.com/" in urls
    assert all(item["kind"] == "official" and item["verified"] is True for item in links)
    # nothing is duplicated
    assert len(urls) == len(set(urls))


def test_search_links_are_never_marked_verified_and_are_time_boxed():
    links = catalysts.search_links(
        MARKET, iso="2026-11-22T07:14:46Z", series_meta=SERIES_META["KXAAAGASW"]
    )
    assert links, "at least one search candidate is expected"
    assert all(item["kind"] == "search" and item["verified"] is False for item in links)
    dated = [item for item in links if item["label"].startswith("News on 2026-11-22")]
    assert dated, "a move with a timestamp must get a date-restricted search"
    assert "cd_min%3A11%2F22%2F2026" in dated[0]["url"] or "cd_min:11/22/2026" in dated[0]["url"]
    assert any("gasprices.aaa.com" in item["url"] for item in links)


def test_no_series_metadata_still_yields_official_market_links():
    links = catalysts.for_market(MARKET, None, iso="2026-11-22T00:00:00Z")
    assert links["official"], "market-level links need no series metadata"
    assert all(item["verified"] is True for item in links["official"])


def test_empty_contract_yields_no_fabricated_query():
    out = catalysts.for_market({"ticker": "X-1", "title": ""}, None)
    assert out["official"] == [] and out["search"] == []


def test_alert_carries_catalysts():
    from kalshi_trader.swings import build_alert

    alert = build_alert(
        {**MARKET, "price": 0.5, "yes_bid": 0.49, "yes_ask": 0.51},
        0.40,
        0.55,
        1_790_000_000,
        series_meta=SERIES_META["KXAAAGASW"],
    )
    assert alert["catalysts"]["official"], "official contract links must ride along with the alert"
    assert all(item["verified"] is False for item in alert["catalysts"]["search"])


def test_sub_ten_cent_moves_still_produce_no_alert():
    from kalshi_trader.swings import build_alert

    assert build_alert({**MARKET, "price": 0.5}, 0.40, 0.49, 1_790_000_000) is None
    assert build_alert({**MARKET, "price": 0.5}, 0.40, 0.50, 1_790_000_000) is not None
