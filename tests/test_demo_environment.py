import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from kalshi_trader.config import DEMO_REST, Settings
from kalshi_trader.paper import PaperLedger

ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location("tradebot_site_builder", ROOT / "tools" / "build_site.py")
SITE = module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(SITE)


@pytest.mark.parametrize(
    "root",
    [
        "https://external-api.demo.kalshi.co/trade-api/v2",
        "https://demo-api.kalshi.co/trade-api/v2/",
    ],
)
def test_site_builder_accepts_only_explicit_official_demo_snapshot(root):
    assert SITE.is_demo_snapshot({"data_env": "demo", "rest_base": root})


@pytest.mark.parametrize(
    "snapshot",
    [
        {"data_env": "prod", "rest_base": "https://external-api.kalshi.com/trade-api/v2"},
        {"data_env": "demo", "rest_base": "https://external-api.kalshi.com/trade-api/v2"},
        {"data_env": "demo", "rest_base": "https://external-api.demo.kalshi.co.evil.invalid/trade-api/v2"},
        {"data_env": "demo"},
        None,
    ],
)
def test_site_builder_rejects_production_unknown_and_unlabelled_snapshots(snapshot):
    assert not SITE.is_demo_snapshot(snapshot)


def test_static_generators_withhold_production_markets_and_portfolio():
    production = {
        "data_env": "prod",
        "rest_base": "https://external-api.kalshi.com/trade-api/v2",
        "generated_at": "2026-11-27T12:00:00Z",
        "topics": {
            "crypto": {
                "markets": [{"ticker": "PROD-ONLY-TICKER", "title": "PROD-ONLY-TITLE", "api_url": "https://external-api.kalshi.com/market"}],
                "events": [{"event_ticker": "PROD-EVENT", "title": "PROD-ONLY-EVENT"}],
                "markets_count": 1,
                "series_count": 1,
                "notional_24h_est": 12345,
                "open_interest": 10,
            }
        },
    }
    index = SITE.build_index_static(production)
    topic = SITE.build_topic_page("crypto", production, {"series": {"PROD-SERIES": {"ticker": "PROD-SERIES", "topic": "crypto"}}})
    portfolio = SITE.build_portfolio_static({"headline": {"equity": 9876.54}}, production)
    for html in (index, topic, portfolio):
        assert "PROD-ONLY" not in html
        assert "PROD-EVENT" not in html
        assert "9876.54" not in html
        assert "Demo data withheld" in html or "Paper history withheld" in html


def test_demo_ui_environment_helper_rejects_production_override():
    helper_path = ROOT / "docs" / "desk" / "assets" / "js" / "environment.cjs"
    # Load this standalone, dependency-free helper in Node so the same logic is tested
    # that the browser uses before any live REST request is made.
    import subprocess

    result = subprocess.run(
        [
            "node",
            "-e",
            "const e=require(process.argv[1]);"
            "if(!e.isDemoSnapshot({data_env:'demo',rest_base:e.PRIMARY}))process.exit(1);"
            "if(e.restBase('https://external-api.kalshi.com/trade-api/v2')!==null)process.exit(2);"
            "if(e.restBase('https://external-api.demo.kalshi.co.evil.invalid/trade-api/v2')!==null)process.exit(3);"
            "if(e.restBase()!==e.PRIMARY)process.exit(4);",
            str(helper_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_collection_defaults_to_official_demo_and_rejects_unknown_environment(monkeypatch):
    monkeypatch.delenv("KALSHI_DATA_ENV", raising=False)
    settings = Settings()
    assert settings.data_env == "demo"
    assert settings.rest_base == DEMO_REST
    with pytest.raises(ValueError, match="exactly 'demo' or 'prod'"):
        Settings(data_env="staging")


def test_legacy_or_other_environment_paper_ledger_is_never_reused(tmp_path):
    settings = Settings(data_dir=tmp_path, state_dir=tmp_path, paper_ledger=tmp_path / "ledger.json")
    settings.paper_ledger.write_text(
        json.dumps({
            "version": 1,
            "data_env": "prod",
            "cash": 1.0,
            "positions": {"prod-position": {"ticker": "PROD-TICKER"}},
            "trades": [],
            "equity": [],
            "rejected": [],
            "counters": {"trade_seq": 1},
        }),
        encoding="utf-8",
    )
    ledger = PaperLedger.load(settings)
    assert ledger.state["data_env"] == "demo"
    assert ledger.positions == {}
    assert ledger.cash == 1000.0


def test_collector_resets_prior_environment_histories_alerts_and_resolutions(tmp_path):
    from kalshi_trader.collector import run_cycle
    from tests.test_collector import _client, _settings

    settings = _settings(tmp_path)
    (tmp_path / "latest.json").write_text(json.dumps({
        "data_env": "prod",
        "rest_base": "https://external-api.kalshi.com/trade-api/v2",
    }), encoding="utf-8")
    (tmp_path / "history.json").write_text(json.dumps({"series": {"OLD": [[1, 0.25]]}}), encoding="utf-8")
    (tmp_path / "meta.json").write_text(json.dumps({"last_prices": {"OLD": [0.25]}}), encoding="utf-8")
    (tmp_path / "alerts.json").write_text(json.dumps({"items": [{"id": "prod-alert", "marketTicker": "OLD"}]}), encoding="utf-8")
    (tmp_path / "resolved.json").write_text(json.dumps({"items": [{"ticker": "PROD-RESOLVED", "result": "yes"}]}), encoding="utf-8")

    latest = run_cycle(settings, client=_client(), now=1_795_000_000, samples=1)

    assert latest["data_env"] == "demo"
    assert latest["rest_base"] == DEMO_REST
    assert any("environment changed" in error.lower() for error in latest["errors"])
    assert all(alert.get("id") != "prod-alert" for alert in latest["alerts"])
    assert all(row.get("ticker") != "PROD-RESOLVED" for row in latest["resolved"])
    history = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert "OLD" not in history["series"]
    saved = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert saved["data_env"] == "demo"


def test_published_non_demo_snapshot_and_browser_routes_are_fail_closed():
    latest = json.loads((ROOT / "docs/desk/data/latest.json").read_text(encoding="utf-8"))
    assert not SITE.is_demo_snapshot(latest)
    assert latest["data_env"] == "unverified"
    for rel in [
        "docs/desk/index.html",
        "docs/desk/topics/crypto.html",
        "docs/desk/topics/gas-prices.html",
    ]:
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert "Demo data withheld" in html
        assert "KXBTCD-26NOV2717-T59999.99" not in html
    portfolio = (ROOT / "docs/desk/portfolio.html").read_text(encoding="utf-8")
    assert "Paper history withheld" in portfolio

    app = (ROOT / "docs/desk/assets/js/app.js").read_text(encoding="utf-8")
    assert "external-api.kalshi.com/trade-api/v2" not in app
    assert "isDemoSnapshot(state.latest)" in app
    assert "isDemoSnapshot(status)" in app
    assert "isDemoSnapshot(msg.payload)" in app
    assert 'KALSHI_DATA_ENV: demo' in (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")


def test_demo_paper_ledger_is_empty_after_clearing_old_production_positions():
    state = json.loads((ROOT / "app_data/paper_ledger.json").read_text(encoding="utf-8"))
    assert state["data_env"] == "demo"
    assert state["positions"] == {}
    assert state["trades"] == []
