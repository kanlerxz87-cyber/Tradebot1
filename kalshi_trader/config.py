"""Runtime configuration.

Every endpoint below is taken from the official documentation
(https://docs.kalshi.com/getting_started/api_environments) — see
``docs/data/sources.json`` for the machine-readable citation list.

Design decision (flagged on the Flagged for Review page):
* Market data is read from the **production** public endpoints. They require no API key,
  which means the dashboard can run fully autonomously, and they carry real volume and
  real prices. The demo environment is a sandbox whose prices Kalshi explicitly warns may
  not reflect real markets.
* Order execution defaults to the internal **paper** ledger, because a Kalshi demo account
  (and its API key) cannot be created from inside this repository. If demo credentials are
  supplied as environment variables / GitHub secrets the demo adapter activates on its own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROD_REST = "https://external-api.kalshi.com/trade-api/v2"
PROD_REST_SHARED = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_REST = "https://external-api.demo.kalshi.co/trade-api/v2"
DEMO_REST_SHARED = "https://demo-api.kalshi.co/trade-api/v2"

PROD_WS = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
DEMO_WS = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "app_data"

#: A swing alert fires when the contract price moves at least this many dollars.
SWING_THRESHOLD = 0.10


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """All tunables in one place. Everything is overridable by environment variable."""

    # --- data source -------------------------------------------------------
    data_env: str = field(default_factory=lambda: _env("KALSHI_DATA_ENV", "prod").lower())
    # --- execution ---------------------------------------------------------
    execution_mode: str = field(default_factory=lambda: _env("KALSHI_EXECUTION", "paper").lower())
    # --- credentials (optional; only needed for demo execution) ------------
    key_id: str = field(default_factory=lambda: _env("KALSHI_API_KEY_ID"))
    private_key_pem: str = field(default_factory=lambda: _env("KALSHI_PRIVATE_KEY"))
    private_key_path: str = field(default_factory=lambda: _env("KALSHI_PRIVATE_KEY_PATH"))

    # --- polling -----------------------------------------------------------
    request_interval_s: float = field(default_factory=lambda: _env_float("KALSHI_REQUEST_INTERVAL", 0.12))
    timeout_s: float = field(default_factory=lambda: _env_float("KALSHI_HTTP_TIMEOUT", 25.0))
    max_retries: int = field(default_factory=lambda: _env_int("KALSHI_MAX_RETRIES", 4))
    cycle_samples: int = field(default_factory=lambda: _env_int("KALSHI_CYCLE_SAMPLES", 2))
    sample_gap_s: float = field(default_factory=lambda: _env_float("KALSHI_SAMPLE_GAP", 20.0))

    # --- book / model limits ----------------------------------------------
    max_markets_per_topic: int = field(default_factory=lambda: _env_int("KALSHI_MAX_MARKETS_PER_TOPIC", 60))
    history_points: int = field(default_factory=lambda: _env_int("KALSHI_HISTORY_POINTS", 240))
    history_markets: int = field(default_factory=lambda: _env_int("KALSHI_HISTORY_MARKETS", 60))
    max_alerts: int = field(default_factory=lambda: _env_int("KALSHI_MAX_ALERTS", 400))
    max_trades: int = field(default_factory=lambda: _env_int("KALSHI_MAX_TRADES", 400))

    # --- paper trading -----------------------------------------------------
    bankroll: float = field(default_factory=lambda: _env_float("KALSHI_PAPER_BANKROLL", 1000.0))
    risk_per_trade: float = field(default_factory=lambda: _env_float("KALSHI_RISK_PER_TRADE", 0.02))
    max_open_positions: int = field(default_factory=lambda: _env_int("KALSHI_MAX_POSITIONS", 12))
    fee_model: str = field(default_factory=lambda: _env("KALSHI_FEE_MODEL", "quadratic").lower())

    # --- paths -------------------------------------------------------------
    repo_root: Path = REPO_ROOT
    site_dir: Path = REPO_ROOT / "docs" / "desk"
    data_dir: Path = REPO_ROOT / "docs" / "desk" / "data"
    state_dir: Path = REPO_ROOT / "app_data"
    paper_ledger: Path = REPO_ROOT / "app_data" / "paper_ledger.json"

    # ---------------------------------------------------------------------
    @property
    def rest_base(self) -> str:
        return DEMO_REST if self.data_env == "demo" else PROD_REST

    @property
    def ws_url(self) -> str:
        return DEMO_WS if self.data_env == "demo" else PROD_WS

    @property
    def demo_rest_base(self) -> str:
        return DEMO_REST

    @property
    def demo_ws_url(self) -> str:
        return DEMO_WS

    def has_credentials(self) -> bool:
        return bool(self.key_id) and bool(self.private_key_pem or self.private_key_path)

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.state_dir):
            path.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
