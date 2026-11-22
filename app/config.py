"""Runtime configuration, read from environment variables only.

No secrets are ever written to disk by this project. The API key ID and the
path to the private key PEM come from the environment; the key file stays
outside the repository.

Verified endpoints (source: https://docs.kalshi.com/getting_started/api_environments):

    Environment | REST                                          | WebSocket
    ------------|-----------------------------------------------|-------------------------------------------
    production  | https://external-api.kalshi.com/trade-api/v2  | wss://external-api-ws.kalshi.com/trade-api/ws/v2
    demo        | https://external-api.demo.kalshi.co/trade-api/v2 | wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2

The legacy hosts (`api.elections.kalshi.com`, `demo-api.kalshi.co`) are
"also supported" per the same page; we default to the recommended ones.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Mapping

REST_HOSTS = {
    "production": "https://external-api.kalshi.com/trade-api/v2",
    "demo": "https://external-api.demo.kalshi.co/trade-api/v2",
}
WS_HOSTS = {
    "production": "wss://external-api-ws.kalshi.com/trade-api/ws/v2",
    "demo": "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
}
# Signing path is identical on every host and excludes the query string.
# Source: https://docs.kalshi.com/getting_started/api_environments (Request Signing)
WS_SIGN_PATH = "/trade-api/ws/v2"


def _dec(value: str | float | int | None, default: Decimal) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except Exception:  # pragma: no cover - defensive
        return default


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable settings snapshot."""

    environment: str = "demo"
    rest_base: str = REST_HOSTS["demo"]
    ws_url: str = WS_HOSTS["demo"]

    api_key_id: str | None = None
    private_key_path: str | None = None

    # Alerting: the product requirement is a swing of at least $0.10 in either
    # direction. Prices are in dollars, so 0.10 == 10 cents.
    swing_threshold: Decimal = Decimal("0.10")
    # Compare against a rolling window as well as the previous tick.
    swing_window_seconds: int = 60
    alert_cooldown_seconds: int = 30
    # Score below which an alert stays out of the "high ROI" feed.
    selective_min_score: Decimal = Decimal("0.55")

    # Simulator
    starting_cash: Decimal = Decimal("10000.00")
    max_position_per_market: Decimal = Decimal("500.00")
    max_contracts_per_order: Decimal = Decimal("100")
    max_portfolio_gross: Decimal = Decimal("5000.00")
    taker_fee_multiplier: Decimal = Decimal("0.07")
    maker_fee_multiplier: Decimal = Decimal("0.0175")
    fee_rounding: str = "cent"          # "cent" (published table) or "micro" (6dp)

    # Live execution is opt-in and demo-only by default.
    enable_live_orders: bool = False
    live_orders_allowed_envs: tuple[str, ...] = ("demo",)

    # Polling (REST). WebSocket is preferred when a key is present.
    poll_seconds: int = 3
    market_page_limit: int = 200
    max_tracked_markets: int = 250

    db_path: str = "data/state/kalshi.sqlite3"
    news_lookback_hours: int = 2
    extra: Mapping[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ utils
    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key_id and self.private_key_path)

    @property
    def live_orders_enabled(self) -> bool:
        return self.enable_live_orders and self.environment in self.live_orders_allowed_envs

    def with_overrides(self, **kwargs) -> "Settings":
        return replace(self, **kwargs)

    def as_public_dict(self) -> dict:
        """Safe-to-serve view. Never includes key material."""
        return {
            "environment": self.environment,
            "rest_base": self.rest_base,
            "ws_url": self.ws_url,
            "has_credentials": self.has_credentials,
            "live_orders_enabled": self.live_orders_enabled,
            "swing_threshold": str(self.swing_threshold),
            "swing_window_seconds": self.swing_window_seconds,
            "starting_cash": str(self.starting_cash),
            "fee_rounding": self.fee_rounding,
        }


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    environment = (env.get("KALSHI_ENV") or "demo").strip().lower()
    if environment not in REST_HOSTS:
        environment = "demo"
    return Settings(
        environment=environment,
        rest_base=env.get("KALSHI_REST_BASE") or REST_HOSTS[environment],
        ws_url=env.get("KALSHI_WS_URL") or WS_HOSTS[environment],
        api_key_id=(env.get("KALSHI_API_KEY_ID") or "").strip() or None,
        private_key_path=(env.get("KALSHI_PRIVATE_KEY_PATH") or "").strip() or None,
        swing_threshold=_dec(env.get("KALSHI_SWING_THRESHOLD"), Decimal("0.10")),
        swing_window_seconds=int(env.get("KALSHI_SWING_WINDOW_SECONDS") or 60),
        alert_cooldown_seconds=int(env.get("KALSHI_ALERT_COOLDOWN_SECONDS") or 30),
        selective_min_score=_dec(env.get("KALSHI_SELECTIVE_MIN_SCORE"), Decimal("0.55")),
        starting_cash=_dec(env.get("KALSHI_STARTING_CASH"), Decimal("10000.00")),
        max_position_per_market=_dec(env.get("KALSHI_MAX_POSITION"), Decimal("500.00")),
        max_contracts_per_order=_dec(env.get("KALSHI_MAX_CONTRACTS"), Decimal("100")),
        taker_fee_multiplier=_dec(env.get("KALSHI_TAKER_FEE_MULT"), Decimal("0.07")),
        maker_fee_multiplier=_dec(env.get("KALSHI_MAKER_FEE_MULT"), Decimal("0.0175")),
        fee_rounding=(env.get("KALSHI_FEE_ROUNDING") or "cent").strip().lower(),
        enable_live_orders=_bool(env.get("KALSHI_ENABLE_LIVE_ORDERS")),
        poll_seconds=int(env.get("KALSHI_POLL_SECONDS") or 3),
        market_page_limit=int(env.get("KALSHI_PAGE_LIMIT") or 200),
        max_tracked_markets=int(env.get("KALSHI_MAX_MARKETS") or 250),
        db_path=env.get("KALSHI_DB_PATH") or "data/state/kalshi.sqlite3",
        news_lookback_hours=int(env.get("KALSHI_NEWS_LOOKBACK_HOURS") or 2),
    )
