from kalshi_trader.swings import build_alert, detect

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

