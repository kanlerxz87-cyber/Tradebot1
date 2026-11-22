"""Route-level tests for anonymous/private separation and project-relative serving."""

from dataclasses import replace
import json

from fastapi.testclient import TestClient
import httpx
import pytest

from services.kalshi.kalshi_demo.client import KalshiClient
from services.kalshi.kalshi_demo.runtime import Runtime
from services.kalshi.kalshi_demo.server import create_app


@pytest.fixture
def app_factory(settings, store):
    def create(token="", handler=None):
        configured = replace(settings, operator_token=token)
        client = KalshiClient(configured, transport=httpx.MockTransport(
            handler or (lambda request: httpx.Response(200, json={"events": [], "cursor": ""}))))
        runtime = Runtime(configured, client, store)
        return create_app(configured, runtime=runtime, run_background=False), runtime
    return create


def test_health_is_honest_and_private_routes_disabled(app_factory):
    app, runtime = app_factory()
    with TestClient(app, base_url="https://8000-example.e2b.app") as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        health = response.json()
        assert health["credentials_configured"] is False
        assert health["demo_order_execution"] == "disabled"
        assert health["data_stale"]
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/portfolio").status_code == 503
        assert client.get("/api/snapshot").json()["markets"] == []
        assert client.get("/api/verification").status_code == 200


def test_operator_auth_cannot_be_bypassed_or_leaked(app_factory):
    token = "synthetic-operator-" + "x" * 32
    app, runtime = app_factory(token)
    runtime.store.put("private_portfolio", "latest", {"secret": "PRIVATE-SENTINEL"})
    with TestClient(app) as client:
        assert client.get("/api/portfolio").status_code == 401
        assert client.get("/api/portfolio?token=" + token).status_code == 401
        assert client.get("/api/portfolio", headers={"Authorization": "Bearer wrong"}).status_code == 401
        response = client.get("/api/portfolio", headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200
        assert response.json()["status"] == "credentials_required"
        public = client.get("/api/snapshot").text
        assert token not in public and "PRIVATE-SENTINEL" not in public
        assert client.post("/api/controls/kill").status_code == 401
        assert client.post("/api/controls/kill", headers={"Authorization": "Bearer " + token}).json()["new_demo_orders"] == "disabled"
        assert runtime.kill_switch


def test_proxy_accepts_only_public_gets_and_allowed_queries(app_factory):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"events": [], "cursor": ""})
    app, runtime = app_factory(handler=handler)
    with TestClient(app) as client:
        assert client.get("/api/kalshi/events?limit=20").status_code == 200
        assert client.get("/api/kalshi/events?limit=20").headers["x-data-mode"] == "demo-rest-cache"
        assert len(requests) == 1
        assert requests[0].url.host == "external-api.demo.kalshi.co"
        assert "authorization" not in requests[0].headers
        assert client.get("/api/kalshi/portfolio/balance").status_code == 404
        assert client.get("/api/kalshi/https://example.com").status_code == 404
        assert client.get("/api/kalshi/events?secret_key=no").status_code == 422
        assert client.post("/api/kalshi/events").status_code in {404, 405}


def test_cors_is_exact_no_arbitrary_credential_sharing(app_factory):
    app, runtime = app_factory()
    with TestClient(app) as client:
        allowed = client.get("/api/health", headers={"Origin": "https://kanlerxz87-cyber.github.io"})
        assert allowed.headers["access-control-allow-origin"] == "https://kanlerxz87-cyber.github.io"
        denied = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in denied.headers
        assert "access-control-allow-credentials" not in allowed.headers


def test_market_history_windows_and_topic_validation(app_factory, raw_market):
    app, runtime = app_factory()
    runtime.ingest_market(raw_market, "crypto")
    with TestClient(app) as client:
        for window, milliseconds in [("seconds", 60_000), ("minutes", 3_600_000), ("hours", 86_400_000)]:
            response = client.get(f"/api/markets/{raw_market['ticker']}/history?window={window}")
            assert response.status_code == 200
            assert response.json()["window_ms"] == milliseconds
            assert response.json()["interpolated"] is False
        assert client.get(f"/api/markets/{raw_market['ticker']}/history?window=years").status_code == 422
        assert client.get("/api/events?topic=baseball").status_code == 422
        assert client.get("/api/alerts?limit=-1").status_code == 422
        assert client.get("/api/alerts?selected=true").json()["alerts"] == []
        assert "PRIVATE" not in json.dumps(client.get("/api/snapshot").json())
