"""No real credentials or live network are used by these tests."""

import base64
from dataclasses import replace

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
import httpx
import pytest

from services.kalshi.kalshi_demo.auth import Signer
from services.kalshi.kalshi_demo.client import KalshiClient, UpstreamError, public_path
from services.kalshi.kalshi_demo.config import Settings


@pytest.mark.parametrize("url", [
    "https://external-api.kalshi.com/trade-api/v2", "https://api.elections.kalshi.com/trade-api/v2",
    "https://localhost/trade-api/v2", "http://external-api.demo.kalshi.co/trade-api/v2",
    "https://external-api.demo.kalshi.co.evil.example/trade-api/v2",
    "https://external-api.demo.kalshi.co/trade-api/v2?x=1",
])
def test_non_demo_endpoints_are_rejected(url):
    with pytest.raises(ValueError):
        Settings(rest_url=url)


def test_keys_and_auth_fail_closed():
    with pytest.raises(ValueError):
        Settings(api_key_id="test")
    with pytest.raises(ValueError):
        Settings(enable_demo_orders=True)
    with pytest.raises(ValueError):
        Settings(operator_token="short")
    with pytest.raises(ValueError):
        Settings(allowed_origins=("*",))


@pytest.mark.parametrize("algorithm", ["rsa", "ed25519"])
def test_signing_uses_full_path_without_query(algorithm):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048) if algorithm == "rsa" else ed25519.Ed25519PrivateKey.generate()
    headers = Signer("test-key-not-real", private).headers("get", "/trade-api/v2/portfolio/balance?x=1", 1700000000123)
    expected = b"1700000000123GET/trade-api/v2/portfolio/balance"
    signature = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
    if algorithm == "rsa":
        private.public_key().verify(signature, expected,
                                    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
    else:
        private.public_key().verify(signature, expected)
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1700000000123"
    with pytest.raises(ValueError):
        Signer("test", private).headers("GET", "/portfolio/balance")


@pytest.mark.parametrize("path,allowed", [
    ("/events", True), ("/markets/TEST/orderbook", True), ("/series/TEST/markets/TEST/candlesticks", True),
    ("/portfolio/balance", False), ("/portfolio/events/orders", False),
    ("//evil.example/events", False), ("/markets/../../portfolio/balance", False),
    ("/events?x=1", False), ("/markets/http://evil.example", False),
])
def test_public_proxy_is_not_an_open_proxy(path, allowed):
    assert public_path(path) is allowed


async def test_pagination_all_pages_and_no_secret_headers(settings):
    calls = []
    def handler(request):
        calls.append(request)
        assert "KALSHI-ACCESS-KEY" not in request.headers
        if "cursor" not in request.url.params:
            return httpx.Response(200, json={"events": [{"event_ticker": "TEST-1"}], "cursor": "next"})
        return httpx.Response(200, json={"events": [{"event_ticker": "TEST-2"}], "cursor": ""})
    client = KalshiClient(settings, transport=httpx.MockTransport(handler))
    result = await client.pages("/events", "events")
    assert result.complete and len(result.rows) == 2 and result.pages == 2
    assert calls[1].url.params["cursor"] == "next"
    await client.close()


async def test_cursor_loop_is_flagged_not_exhaustive(settings):
    client = KalshiClient(settings, transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"events": [{"event_ticker": "TEST"}], "cursor": "same"})))
    result = await client.pages("/events", "events")
    assert not result.complete and result.error == "repeated_or_invalid_cursor"
    await client.close()


async def test_page_limit_and_missing_result_are_flagged(settings):
    client = KalshiClient(replace(settings, max_pages=1), transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"events": [], "cursor": "more"})))
    assert (await client.pages("/events", "events")).error == "page_limit_reached"
    await client.close()
    client = KalshiClient(settings, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"cursor": ""})))
    assert (await client.pages("/events", "events")).error == "missing_or_invalid_result_array"
    await client.close()


async def test_write_timeout_is_ambiguous_and_never_retried(settings):
    attempts = []
    def timeout(request):
        attempts.append(request)
        raise httpx.ReadTimeout("synthetic", request=request)
    signer = Signer("test-only", ed25519.Ed25519PrivateKey.generate())
    client = KalshiClient(settings, signer, httpx.MockTransport(timeout))
    with pytest.raises(UpstreamError) as info:
        await client.request("POST", "/portfolio/events/orders", body={"synthetic": True}, authenticated=True)
    assert info.value.ambiguous and len(attempts) == 1
    await client.close()


async def test_redirect_does_not_forward_credentials(settings):
    attempts = []
    def redirect(request):
        attempts.append(request)
        return httpx.Response(302, headers={"location": "https://example.com/steal"})
    client = KalshiClient(settings, Signer("test-only", ed25519.Ed25519PrivateKey.generate()), httpx.MockTransport(redirect))
    with pytest.raises(UpstreamError):
        await client.get("/portfolio/balance", authenticated=True)
    assert len(attempts) == 1
    await client.close()


async def test_read_retry_is_bounded_and_missing_auth_does_not_make_request(settings, monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr("services.kalshi.kalshi_demo.client.asyncio.sleep", no_sleep)
    attempts = []
    def fail(request):
        attempts.append(request)
        return httpx.Response(429, headers={"retry-after": "0"})
    client = KalshiClient(settings, transport=httpx.MockTransport(fail))
    with pytest.raises(UpstreamError):
        await client.get("/events")
    assert len(attempts) == 3
    with pytest.raises(UpstreamError) as info:
        await client.get("/portfolio/balance", authenticated=True)
    assert info.value.code == "demo_credentials_not_configured" and len(attempts) == 3
    await client.close()
