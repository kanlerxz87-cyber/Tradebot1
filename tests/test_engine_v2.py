"""Regression tests for Engine V2 signing, order-direction price scale,
per-series fee multipliers, non-retry on POST writes, and scalar settlement.

Official sources verified:
- Request signing (`/trade-api/v2/...` without query string):
  https://docs.kalshi.com/getting_started/api_keys
  https://docs.kalshi.com/getting_started/api_environments
- Order V2 unified YES price scale (`bid` at P_yes; `ask` at `1 - P_no`):
  https://docs.kalshi.com/api-reference/orders/create-order-v2
  https://docs.kalshi.com/getting_started/order_direction
- Per-series fee multiplier (`fee_multiplier` / Non-Standard Fees PDF):
  https://kalshi.com/docs/kalshi-fee-schedule.pdf
  https://docs.kalshi.com/api-reference/market/get-series
- Market lifecycle & settlement (`yes`, `no`, `scalar` with `settlement_value_dollars`):
  https://docs.kalshi.com/getting_started/market_lifecycle
  https://docs.kalshi.com/getting_started/market_settlement
"""

from __future__ import annotations

import base64
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.config import Settings
from app.kalshi_api import KalshiAPI, KalshiAPIError
from app.money import fee_dollars, series_fee_multiplier
from app.simulator import BUY, NO, YES, Decision, MarketContext, Simulator, spec_by_key
from app.storage import Store


@pytest.mark.asyncio
async def test_kalshi_api_signs_full_trade_api_v2_path_and_never_retries_post(tmp_path):
    key = ed25519.Ed25519PrivateKey.generate()
    pub = key.public_key()
    key_path = tmp_path / "demo.key"
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        if request.method == "POST":
            return httpx.Response(503, json={"error": {"code": "service_unavailable"}})
        return httpx.Response(200, json={"balance": 100000, "portfolio_value": 0})

    settings = Settings(
        environment="demo",
        api_key_id="demo-key-1",
        private_key_path=str(key_path),
    )

    transport = httpx.MockTransport(handler)
    async with KalshiAPI(settings, transport=transport, max_retries=3) as api:
        bal = await api.balance()
        assert bal["balance"] == 100000
        req = seen_requests[0]
        ts = req.headers["KALSHI-ACCESS-TIMESTAMP"]
        sig = base64.b64decode(req.headers["KALSHI-ACCESS-SIGNATURE"])
        # Must sign /trade-api/v2/portfolio/balance, NEVER /portfolio/balance
        expected_msg = f"{ts}GET/trade-api/v2/portfolio/balance".encode()
        pub.verify(sig, expected_msg)

        # POST order write must NOT retry on 503 (prevent duplicate submissions)
        with pytest.raises(KalshiAPIError) as exc_info:
            await api.create_order({"ticker": "KXAAAGASM-26NOV30-3.50", "side": "bid"})
        assert exc_info.value.status == 503
        post_calls = [r for r in seen_requests if r.method == "POST"]
        assert len(post_calls) == 1
        post_req = post_calls[0]
        post_ts = post_req.headers["KALSHI-ACCESS-TIMESTAMP"]
        post_sig = base64.b64decode(post_req.headers["KALSHI-ACCESS-SIGNATURE"])
        pub.verify(post_sig, f"{post_ts}POST/trade-api/v2/portfolio/events/orders".encode())


@pytest.mark.asyncio
async def test_demo_order_converts_no_buy_price_to_unified_yes_scale(tmp_path):
    sent_payloads: list[dict] = []

    class DummyAPI:
        async def create_order(self, payload: dict) -> dict:
            sent_payloads.append(payload)
            return {"order": {"order_id": f"ord-{len(sent_payloads)}", "remaining_count": "0.00"}}

    settings = Settings(
        environment="demo",
        enable_live_orders=True,
        db_path=str(tmp_path / "sim.sqlite"),
    )
    store = Store(settings.db_path)
    sim = Simulator(store, settings, api=DummyAPI())
    spec = spec_by_key("baseline_control")
    assert spec is not None

    ctx_yes = MarketContext(
        ticker="KXAAAGASM-26NOV30-3.50",
        event_ticker="KXAAAGASM-26NOV30",
        topic="gas",
        title="US gas above $3.50",
        best_bid=Decimal("0.40"),
        best_ask=Decimal("0.42"),
        two_sided=True,
    )
    dec_yes = Decision(action=BUY, side=YES, contracts=Decimal("5"), price=Decimal("0.42"), reason="buy yes")
    res_yes = await sim.execute(spec, dec_yes, alert={"delta": "0.12"}, ctx=ctx_yes, mode="demo")
    assert res_yes["status"] == "filled"
    assert sent_payloads[0]["side"] == "bid"
    assert sent_payloads[0]["price"] == "0.4200"

    ctx_no = MarketContext(
        ticker="KXPGATOUR-THRC26-MPEN",
        event_ticker="KXPGATOUR-THRC26",
        topic="golf",
        title="PGA winner",
        best_bid=Decimal("0.28"),
        best_ask=Decimal("0.31"),
        two_sided=True,
    )
    dec_no = Decision(action=BUY, side=NO, contracts=Decimal("4"), price=Decimal("0.31"), reason="buy no")
    res_no = await sim.execute(spec, dec_no, alert={"delta": "-0.11"}, ctx=ctx_no, mode="demo")
    assert res_no["status"] == "filled"
    # Buying NO at $0.31 must map to side="ask" on unified YES grid at $1.00 - $0.31 = $0.6900
    assert sent_payloads[1]["side"] == "ask"
    assert sent_payloads[1]["price"] == "0.6900"
    store.close()


def test_series_fee_multiplier_honors_api_override_and_published_schedule():
    # KXBTCY is 0 / 0 in the published PDF Non-Standard Fees table
    assert series_fee_multiplier("KXBTCY-27JAN0100-B100000") == Decimal("0")
    assert fee_dollars(
        Decimal("0.50"),
        Decimal("10"),
        series_multiplier=series_fee_multiplier("KXBTCY-27JAN0100-B100000"),
    ) == Decimal("0")

    # Explicit API fee_multiplier (e.g. Demo returning 1 on KXBTCY) overrides static table
    assert series_fee_multiplier("KXBTCY-27JAN0100-B100000", api_fee_multiplier="1") == Decimal("1")
    assert fee_dollars(
        Decimal("0.50"),
        Decimal("100"),
        series_multiplier=series_fee_multiplier("KXBTCY-27JAN0100-B100000", api_fee_multiplier="1"),
    ) == Decimal("1.75")

    # Standard series KXAAAGASM is 1 / 1
    assert series_fee_multiplier("KXAAAGASM-26NOV30-3.50") == Decimal("1")


@pytest.mark.asyncio
async def test_scalar_settlement_credits_proportional_payout_with_zero_fee(tmp_path):
    settings = Settings(db_path=str(tmp_path / "scalar.sqlite"))
    store = Store(settings.db_path)
    sim = Simulator(store, settings)
    spec = spec_by_key("baseline_control")
    assert spec is not None

    ctx = MarketContext(
        ticker="KXXISUCCESSOR-45JAN01",
        event_ticker="KXXISUCCESSOR",
        topic="elections",
        title="Scalar settlement test",
        best_bid=Decimal("0.38"),
        best_ask=Decimal("0.40"),
        two_sided=True,
    )
    dec = Decision(action=BUY, side=YES, contracts=Decimal("10"), price=Decimal("0.40"), reason="entry")
    opened = await sim.execute(spec, dec, alert={"delta": "0.10"}, ctx=ctx, mode="paper")
    assert opened["status"] == "filled"

    actions = await sim.settle_resolutions(
        [{"ticker": "KXXISUCCESSOR-45JAN01", "result": "scalar", "settlement_value": "0.5000"}]
    )
    assert len(actions) == 1
    assert actions[0]["status"] == "settled"
    assert actions[0]["proceeds"] == "5.0000"
    assert actions[0]["fee"] == "0"
    store.close()
