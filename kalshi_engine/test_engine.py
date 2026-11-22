"""Offline unit tests for `kalshi_engine` (V2 signing, orderbook math, 5-topic filter, alerts, strategies, fees)."""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kalshi_engine.kalshi_v2_client import (
    DEMO_REST_PRIMARY,
    DEMO_WS_PRIMARY,
    KalshiV2Client,
    build_presign_message,
    build_v2_event_order_payload,
    canonical_sign_path,
    sign_kalshi_message,
    summarize_orderbook,
)
from kalshi_engine.simulator import (
    CustomStrategyRule,
    StrategyPortfolioEngine,
    classify_topic,
    compute_kalshi_fee,
)


def test_canonical_sign_path_includes_trade_api_v2():
    # Regression test for R1 (python/kalshi_client.py omitted /trade-api/v2)
    path = canonical_sign_path(DEMO_REST_PRIMARY, "/portfolio/balance?subaccount=0")
    assert path == "/trade-api/v2/portfolio/balance"
    msg = build_presign_message("1795329000000", "get", path)
    assert msg == "1795329000000GET/trade-api/v2/portfolio/balance"


def test_ed25519_and_rsa_pss_signing_and_ws_headers():
    import subprocess

    ed_pem = subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ed25519"],
        capture_output=True,
        check=True,
    ).stdout
    rsa_pem = subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048"],
        capture_output=True,
        check=True,
    ).stdout

    client_ed = KalshiV2Client(key_id="demo-ed-key", private_key=ed_pem, base_url=DEMO_REST_PRIMARY, ws_url=DEMO_WS_PRIMARY)
    hdrs = client_ed.auth_headers("POST", "/portfolio/events/orders?foo=1", timestamp_ms="1795329000123")
    assert hdrs["KALSHI-ACCESS-KEY"] == "demo-ed-key"
    assert hdrs["KALSHI-ACCESS-TIMESTAMP"] == "1795329000123"
    assert len(hdrs["KALSHI-ACCESS-SIGNATURE"]) == 88  # 64-byte Ed25519 signature base64-encoded

    ws_hdrs = client_ed.ws_auth_headers(timestamp_ms="1795329000999")
    assert ws_hdrs["KALSHI-ACCESS-TIMESTAMP"] == "1795329000999"

    sig_rsa = sign_kalshi_message(rsa_pem, "1795329000123GET/trade-api/v2/portfolio/balance")
    assert len(sig_rsa) == 344  # 256-byte RSA-2048 signature base64-encoded

    sub = json.loads(KalshiV2Client.build_ws_subscribe(1, ["ticker", "orderbook_delta"], ["KXDEMOFUTHOURLY-26NOV22H08-UP"]))
    assert sub["cmd"] == "subscribe" and "ticker" in sub["params"]["channels"]


def test_v2_event_order_payload_shape():
    # Regression test for R2 (legacy /portfolio/orders removed -> V2 /portfolio/events/orders)
    buy_yes = build_v2_event_order_payload("KXPRESPERSON-28-GNEWS", "yes", "buy", 10, "0.0780", client_order_id="cid-1")
    assert buy_yes == {
        "ticker": "KXPRESPERSON-28-GNEWS",
        "side": "bid",
        "count": "10",
        "price": "0.0780",
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "taker_at_cross",
        "client_order_id": "cid-1",
    }
    buy_no = build_v2_event_order_payload("KXPRESPERSON-28-GNEWS", "no", "buy", 5, "0.9200", client_order_id="cid-2")
    assert buy_no["side"] == "ask" and buy_no["price"] == "0.0800"


def test_reciprocal_orderbook_math_and_no_truncation():
    # Verified against live KXPRESPERSON-28-GNEWS orderbook & R5 regression
    raw = {
        "orderbook_fp": {
            "yes_dollars": [["0.0010", "160.00"], ["0.0760", "4385.96"], ["0.0770", "4329.00"]],
            "no_dollars": [["0.9200", "4166.66"], ["0.9210", "4219.40"], ["0.9220", "481.97"], ["0.9230", "100.00"]],
        }
    }
    summary = summarize_orderbook(raw)
    assert summary["best_yes_bid"] == 0.0770
    assert summary["best_yes_ask"] == 0.0770  # 1.0000 - 0.9230
    assert summary["yes_spread"] == 0.0
    assert len(summary["no_bids"]) == 4  # never truncated when longer than yes_dollars!


def test_strict_five_topics_no_substring_false_positives():
    # Regression test for R6 ("OpenAI" != Golf, "resolve" != Crypto, "soil" != Gas, "sportsbook" != Culture)
    assert classify_topic({"title": "Will OpenAI release GPT-6 this year?", "category": "Science and Technology"}) is None
    assert classify_topic({"title": "Will Congress resolve the budget dispute?", "category": "Politics"}) is None
    assert classify_topic({"title": "US soil moisture index in July", "category": "Climate"}) is None
    assert classify_topic({"title": "NBA Sixth Man of the Year", "category": "Sports"}) is None

    assert classify_topic({"ticker": "KXAAAGASMINTX-26DEC31-2.10", "title": "Texas gas prices below $2.10"}) == "Gas Prices"
    assert classify_topic({"ticker": "KXPRESPERSON-28-GNEWS", "category": "Elections", "title": "Who will win the next presidential election?"}) == "Elections"
    assert classify_topic({"ticker": "KXPERFORMBONDSONG-35-DUA", "category": "Entertainment", "title": "Next James Bond Song"}) == "Culture"
    assert classify_topic({"ticker": "KXDEMOFUTHOURLY-26NOV22H08-UP", "category": "Test", "title": "Demo BTC at or above 59023.8 USD"}) == "Crypto"
    assert classify_topic({"ticker": "KXPGATOUR-THRC26-CBEZ", "category": "Sports", "title": "The RSM Classic: Bezuidenhout wins"}) == "Golf"


def test_alerts_all_five_strategies_custom_rules_fees_and_scalar_settlement():
    eng = StrategyPortfolioEngine(starting_bankroll=1000.0, contracts_per_signal=10)
    eng.custom_rules.append(
        CustomStrategyRule(
            name="crypto_dip_buyer",
            trade_type="custom_dip",
            topic_filter="Crypto",
            min_abs_swing=0.20,
            price_min=0.20,
            price_max=0.50,
            direction="always_yes",
            contracts=5,
        )
    )

    m0 = {
        "ticker": "KXDEMOFUTHOURLY-26NOV22H08-UP",
        "event_ticker": "KXDEMOFUTHOURLY-26NOV22H08",
        "title": "Demo BTC at or above 59023.8 USD",
        "status": "active",
        "last_price_dollars": "0.5500",
        "yes_bid_dollars": "0.5300",
        "yes_ask_dollars": "0.5700",
        "volume_fp": "1300.00",
        "volume_24h_fp": "735.00",
        "open_interest_fp": "90.00",
    }
    assert eng.observe_market(m0, "Crypto", "2026-11-22T07:09:12Z", "https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDEMOFUTHOURLY-26NOV22H08-UP") is None

    # +$0.10 jump (0.55 -> 0.65): triggers momentum, mean_reversion, spread_capture, AND favorite_follow!
    m1 = {**m0, "last_price_dollars": "0.6500", "yes_bid_dollars": "0.6300", "yes_ask_dollars": "0.6600"}
    a1 = eng.observe_market(m1, "Crypto", "2026-11-22T07:09:17Z", "https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDEMOFUTHOURLY-26NOV22H08-UP")
    assert a1 is not None and abs(a1.delta - 0.10) < 1e-6 and a1.high_roi is True
    strats_triggered = {t.strategy for t in eng.trades}
    assert {"momentum", "mean_reversion", "spread_capture", "favorite_follow"}.issubset(strats_triggered)

    # -$0.30 drop (0.65 -> 0.35): triggers longshot_value AND custom rule `crypto_dip_buyer`!
    m2 = {**m0, "last_price_dollars": "0.3500", "yes_bid_dollars": "0.3300", "yes_ask_dollars": "0.3700"}
    a2 = eng.observe_market(m2, "Crypto", "2026-11-22T07:09:22Z", "https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDEMOFUTHOURLY-26NOV22H08-UP")
    assert a2 is not None and abs(a2.delta + 0.30) < 1e-6
    strats_triggered = {t.strategy for t in eng.trades}
    assert "longshot_value" in strats_triggered and "crypto_dip_buyer" in strats_triggered

    # Settle YES and verify category analytics
    settled = eng.settle_market("KXDEMOFUTHOURLY-26NOV22H08-UP", "yes")
    assert len(settled) == len(eng.trades)
    cats = eng.analytics_by_category()
    assert cats["Crypto | longshot_value | longshot"]["realized_pnl"] > 0

    # Test scalar settlement (KXXISUCCESSOR-45JAN01-DXUE settled at $0.50)
    ms = {"ticker": "KXXISUCCESSOR-45JAN01-DXUE", "event_ticker": "KXXISUCCESSOR-45JAN01", "title": "Leader", "status": "active", "last_price_dollars": "0.7000"}
    ts = eng.execute_trade(ms, "Elections", "yes", 10, "manual_ticket", "manual", "2026-11-22T07:10:00Z", price_override=0.40)
    assert ts is not None
    eng.settle_market("KXXISUCCESSOR-45JAN01-DXUE", "scalar", settlement_value_dollars=0.50)
    assert ts.status == "finalized" and ts.payout == 5.0

    # Fee rounding accumulator sanity check
    fee1, acc1 = compute_kalshi_fee(0.55, 1, target_precision="0.01")
    assert fee1 >= Decimal("0") and acc1 >= Decimal("0")


if __name__ == "__main__":
    test_canonical_sign_path_includes_trade_api_v2()
    test_ed25519_and_rsa_pss_signing_and_ws_headers()
    test_v2_event_order_payload_shape()
    test_reciprocal_orderbook_math_and_no_truncation()
    test_strict_five_topics_no_substring_false_positives()
    test_alerts_all_five_strategies_custom_rules_fees_and_scalar_settlement()
    print("All kalshi_engine tests passed.")
