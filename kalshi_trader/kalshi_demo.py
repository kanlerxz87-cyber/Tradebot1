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

Order body and endpoint verified 2026-11-22 against

* ``POST /portfolio/events/orders`` — the V2 create-order endpoint
  (https://docs.kalshi.com/api-reference/orders/create-order-v2.md). Required body fields are
  ``ticker``, ``side``, ``count``, ``price``, ``time_in_force`` and
  ``self_trade_prevention_type``; ``count`` is a fixed-point string (2 dp) and ``price`` a
  fixed-point dollar string (up to 4 dp). A ``201`` means the order was **accepted**, not
  that it is resting, so ``remaining_count`` must be read from the response.
* ``side`` is the **book side**, not the outcome: ``bid`` ≡ yes, ``ask`` ≡ no, always
  (https://docs.kalshi.com/getting_started/order_direction.md). Buying NO is therefore
  ``side="ask"`` at a *no-leg* price, which is what :meth:`place_order` sends.
* The worked example in https://docs.kalshi.com/getting_started/quick_start_create_order
  sends ``side: "bid"`` with ``price: "0.0100"``.

:meth:`place_order` returns the exchange ``remaining_count``/``fill_count`` rather than
assuming a fill, because a resting order is not a position.
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
        # Snap to the whole-cent grid. Kalshi validates against the market's own price_ranges
        # grid (https://docs.kalshi.com/getting_started/fixed_point_migration); whole cents are
        # valid in every documented structure, so this is safe but conservative and is flagged.
        price = f"{max(0.01, min(0.99, round(limit_price * 100) / 100)):.4f}"
        # book_side, not outcome: bid == yes, ask == no (order_direction.md). The price sent is
        # the price of the book being bought, i.e. a no-leg price when buying NO.
        body_side = "bid" if side == "yes" else "ask"
        count_fp = f"{float(int(contracts)):.2f}"
        try:
            response = client.create_order(
                ticker=ticker,
                side=body_side,
                count=count_fp,
                price=price,
                client_order_id=client_order_id or str(uuid.uuid4()),
            )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return {"ok": False, "error": self.last_error}
        remaining = response.get("remaining_count") if isinstance(response, dict) else None
        filled = response.get("fill_count") if isinstance(response, dict) else None
        return {
            "ok": True,
            "order": response,
            "price": price,
            "side": body_side,
            "count": int(contracts),
            "fill_count": filled,
            "remaining_count": remaining,
            # A 201 is acceptance; only fill_count > 0 means the demo book actually holds it.
            "resting": remaining not in (None, "0.00", "0", 0),
        }
