from urllib.parse import quote_plus

from kalshi_trader.swings import CONTEXT_NOTE, build_alert, context_links, detect

BASE = {"ticker": "T-1", "topic": "crypto", "title": "Test", "price": 0.60}


def test_exactly_ten_cents_fires():
    alert = build_alert(BASE, 0.55, 0.65, 1700000000)
    assert alert is not None
    assert alert["direction"] == "up"
    assert alert["delta"] == 0.1
    assert alert["abs_delta"] == 0.1


def test_nine_cents_does_not_fire():
    assert build_alert(BASE, 0.55, 0.64, 1700000000) is None


def test_down_move_and_pct():
    alert = build_alert(BASE, 0.80, 0.65, 1700000000)
    assert alert["direction"] == "down"
    assert alert["delta"] == -0.15
    assert alert["pct_change"] == -18.75


def test_alert_id_is_stable():
    first = build_alert(BASE, 0.55, 0.65, 1700000000)["id"]
    second = build_alert(BASE, 0.55, 0.65, 1700000000)["id"]
    assert first == second
    assert len(first) == 12


def test_detect_uses_previous_price_state():
    markets = [
        dict(BASE, ticker="T-1", mid=0.70, yes_bid=0.69, yes_ask=0.71),
        dict(BASE, ticker="T-2", mid=0.50),
    ]
    alerts = detect(markets, {"T-1": [0.55], "T-2": [0.40]}, 1700000000)
    assert [a["ticker"] for a in alerts] == ["T-1", "T-2"]  # sorted by size, equal here → stable
    assert len(alerts) == 2


def test_detect_skips_markets_without_baseline():
    markets = [dict(BASE, ticker="T-9", mid=0.9)]
    assert detect(markets, {}, 1700000000) == []


def test_context_links_are_labelled_searches_not_attributions():
    market = dict(
        BASE,
        title="Will CPI come in above 3.0%?",
        api_url="https://external-api.kalshi.com/trade-api/v2/markets/T-1",
        series_page_url="https://kalshi.com/markets/kxcpi",
    )
    links = context_links(market)
    assert [l["kind"] for l in links] == ["record", "record", "search", "search"]
    search = [l for l in links if l["kind"] == "search"]
    assert all(l["url"].startswith("https://") for l in search)
    # The query is the market's own title, URL-encoded, and nothing else is invented.
    expected = quote_plus("Will CPI come in above 3.0%?")
    assert search[0]["url"].endswith(expected)
    assert search[1]["url"].endswith(expected)


def test_context_links_have_no_search_without_a_title():
    links = context_links({"api_url": "https://external-api.kalshi.com/trade-api/v2/markets/T-1"})
    assert [l["kind"] for l in links] == ["record"]


def test_alert_carries_context_links_and_a_disclaimer():
    alert = build_alert(dict(BASE, title="Test market"), 0.40, 0.55, 1700000000)
    assert alert["context_note"] == CONTEXT_NOTE
    assert "not evidence" in alert["context_note"]
    assert any(l["kind"] == "search" for l in alert["context_links"])
