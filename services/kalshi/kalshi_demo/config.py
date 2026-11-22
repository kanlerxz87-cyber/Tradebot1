"""Fail-closed settings: only the officially documented demo hosts are accepted."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
from urllib.parse import urlparse

REST_URLS = frozenset({
    "https://external-api.demo.kalshi.co/trade-api/v2",
    "https://demo-api.kalshi.co/trade-api/v2",
})
WS_URLS = frozenset({
    "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
    "wss://demo-api.kalshi.co/trade-api/ws/v2",
})
DEFAULT_REST = "https://external-api.demo.kalshi.co/trade-api/v2"
DEFAULT_WS = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
TOPICS = ("gas", "elections", "culture", "crypto", "golf")


def positive_decimal(value: str, name: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a positive decimal") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name} must be a positive decimal")
    return result


@dataclass(frozen=True)
class Settings:
    rest_url: str = DEFAULT_REST
    ws_url: str = DEFAULT_WS
    api_key_id: str = ""
    private_key_path: str = ""
    operator_token: str = ""
    enable_demo_orders: bool = False
    paper_automation: bool = True
    poll_seconds: float = 30.0
    max_pages: int = 100
    max_order_dollars: Decimal = Decimal("10")
    max_session_dollars: Decimal = Decimal("100")
    db_path: str = "services/kalshi/data/observations.sqlite3"
    static_dir: str = "docs"
    allowed_origins: tuple[str, ...] = ("https://kanlerxz87-cyber.github.io",)
    read_interval_seconds: float = 0.5
    request_timeout: float = 8.0
    stale_seconds: int = 45

    def __post_init__(self):
        if self.rest_url not in REST_URLS or self.ws_url not in WS_URLS:
            raise ValueError("Only exact, officially documented Kalshi demo URLs are permitted")
        if bool(self.api_key_id) != bool(self.private_key_path):
            raise ValueError("API key ID and private key path must be provisioned together")
        if self.operator_token and len(self.operator_token) < 32:
            raise ValueError("Operator token must have at least 32 characters")
        if self.enable_demo_orders and not (self.api_key_id and self.operator_token):
            raise ValueError("Demo orders require server credentials and an operator token")
        if not 10 <= self.poll_seconds <= 3600 or not 1 <= self.max_pages <= 1000:
            raise ValueError("Poll interval or maximum page count is outside safe bounds")
        if self.read_interval_seconds < 0 or self.request_timeout <= 0:
            raise ValueError("Invalid request timing")
        if not self.max_order_dollars.is_finite() or self.max_order_dollars <= 0:
            raise ValueError("Order cap must be positive")
        if not self.max_session_dollars.is_finite() or self.max_session_dollars <= 0:
            raise ValueError("Cumulative cap must be positive")
        for origin in self.allowed_origins:
            parsed = urlparse(origin)
            if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                    or parsed.path or parsed.query or parsed.fragment or parsed.username):
                raise ValueError("Allowed origins must be exact http(s) origins, not wildcards")
        if self.private_key_path and Path(self.private_key_path).suffix.lower() not in {".pem", ".key"}:
            raise ValueError("Private key must be a server-side .pem or .key file")

    @classmethod
    def from_env(cls):
        return cls(
            rest_url=os.getenv("KALSHI_REST_URL", DEFAULT_REST).rstrip("/"),
            ws_url=os.getenv("KALSHI_WS_URL", DEFAULT_WS),
            api_key_id=os.getenv("KALSHI_API_KEY_ID", ""),
            private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH", ""),
            operator_token=os.getenv("KALSHI_OPERATOR_TOKEN", ""),
            enable_demo_orders=os.getenv("KALSHI_ENABLE_DEMO_ORDERS", "false").lower() == "true",
            paper_automation=os.getenv("KALSHI_PAPER_AUTOMATION", "true").lower() == "true",
            poll_seconds=float(os.getenv("KALSHI_POLL_SECONDS", "30")),
            max_pages=int(os.getenv("KALSHI_MAX_PAGES", "100")),
            max_order_dollars=positive_decimal(os.getenv("KALSHI_MAX_ORDER_DOLLARS", "10"), "order cap"),
            max_session_dollars=positive_decimal(os.getenv("KALSHI_MAX_SESSION_DOLLARS", "100"), "cumulative cap"),
            db_path=os.getenv("KALSHI_DB_PATH", "services/kalshi/data/observations.sqlite3"),
            static_dir=os.getenv("KALSHI_STATIC_DIR", "docs"),
            allowed_origins=tuple(x.strip() for x in os.getenv(
                "KALSHI_ALLOWED_ORIGINS", "https://kanlerxz87-cyber.github.io"
            ).split(",") if x.strip()),
        )
