"""Optional adapter for a real Kalshi **demo** account.

Status in this repository: **not connected**, because a demo account and its API key can only
be created by a person (https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account).
Nothing here invents account data: when credentials are absent every consumer of this module
receives ``{"connected": False, "reason": ...}`` and the site renders that verbatim.

To activate, set these repository secrets / environment variables:

* ``KALSHI_API_KEY_ID``      — the demo API key id
* ``KALSHI_PRIVATE_KEY``     — the demo private key PEM (multiline, RSA or Ed25519)

Then set ``KALSHI_EXECUTION=demo``. The next scheduled cycle will read the demo balance and
positions and mirror new simulated entries as real demo orders.

Order body and endpoint verified against
https://docs.kalshi.com/getting_started/quick_start_create_order
(``POST /portfolio/events/orders``).
"""

from __future__ import annotations

import uuid
from typing import Any

from .client import RestClient, demo_client
from .config import Settings
from .portfolio import demo_account_summary

REQUIRED_ENV = ("KALSHI_API_KEY_ID", "KALSHI_PRIVATE_KEY")
HELP_URL = "https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account"


class DemoAccount:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: RestClient | None = None
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        return self.settings.has_credentials()

    @property
    def client(self) -> RestClient | None:
        if not self.configured:
            return None
        if self._client is None:
            self._client = demo_client(self.settings)
        return self._client

    # ------------------------------------------------------------------ reads
    def status(self) -> dict[str, Any]:
        if not self.configured:
            return {
                "connected": False,
                "reason": "Demo API credentials are not configured for this deployment.",
                "required_env": list(REQUIRED_ENV),
                "api_base": self.settings.demo_rest_base,
                "setup_url": HELP_URL,
                "note": (
                    "A Kalshi demo account and its API key can only be created by the account holder, "
                    "so this session could not create one. Paper trading runs autonomously regardless."
                ),
            }
        return {
            "connected": True,
            "api_base": self.settings.demo_rest_base,
            "execution_mode": self.settings.execution_mode,
        }

    def snapshot(self) -> dict[str, Any]:
        client = self.client
        if client is None:
            return {"connected": False, "summary": demo_account_summary(None, None), "status": self.status()}
        try:
            balance = client.balance()
        except Exception as exc:  # network or auth failure must not break the cycle
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {
                "connected": False,
                "reason": self.last_error,
                "summary": demo_account_summary(None, None),
                "status": self.status(),
            }
        try:
            positions = client.positions()
        except Exception as exc:
            self.last_error = f"positions: {type(exc).__name__}: {exc}"
            positions = []
        return {
            "connected": True,
            "balance": balance,
            "positions": positions,
            "summary": demo_account_summary(balance, positions),
            "updated_iso": None,
        }

    # ----------------------------------------------------------------- writes
    def place_order(
        self,
        ticker: str,
        side: str,
        contracts: int,
        limit_price: float,
        *,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a limit order to the demo exchange. Prices are snapped to the cent grid."""
        client = self.client
        if client is None:
            return {"ok": False, "error": "not_configured"}
        price = f"{max(0.01, min(0.99, round(limit_price * 100) / 100)):.4f}"
        body_side = "bid" if side == "yes" else "ask"
        try:
            response = client.create_order(
                ticker=ticker,
                side=body_side,
                count=str(int(contracts)),
                price=price,
                client_order_id=client_order_id or str(uuid.uuid4()),
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {"ok": False, "error": self.last_error}
        return {"ok": True, "order": response, "price": price, "side": body_side, "count": int(contracts)}
