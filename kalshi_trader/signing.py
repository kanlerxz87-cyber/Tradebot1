"""Request signing for the Kalshi Trade API.

Verified implementation details (docs.kalshi.com):

* The signed message is ``timestamp + METHOD + path`` where ``path`` is the request path
  from the API root and **excludes** the query string
  (https://docs.kalshi.com/getting_started/api_environments — "Request Signing").
* ``timestamp`` is milliseconds since the Unix epoch, sent as a string in
  ``KALSHI-ACCESS-TIMESTAMP``.
* RSA keys are signed with **RSA-PSS / SHA-256** using a salt length equal to the digest
  length; Ed25519 keys sign the message directly
  (https://docs.kalshi.com/api-reference/portfolio/get-positions — securitySchemes).
* Headers: ``KALSHI-ACCESS-KEY``, ``KALSHI-ACCESS-SIGNATURE`` (base64), ``KALSHI-ACCESS-TIMESTAMP``.

This module is only needed for authenticated calls (demo account balance, positions and
orders). Public market-data calls do not need it
(https://docs.kalshi.com/getting_started/quick_start_market_data).
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from urllib.parse import urlparse

__all__ = [
    "SigningKey",
    "load_signing_key",
    "build_auth_headers",
    "SigningUnavailable",
]


class SigningUnavailable(RuntimeError):
    """Raised when signed requests are requested but no usable key is configured."""


class SigningKey:
    """A loaded private key that can produce Kalshi auth signatures."""

    def __init__(self, key_id: str, private_key) -> None:
        self.key_id = key_id
        self._key = private_key

    # -- signing ---------------------------------------------------------
    def sign_text(self, text: str) -> str:
        """Return the base64 signature for ``text``."""
        message = text.encode("utf-8")
        key = self._key
        try:  # Ed25519 keys sign the message directly.
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

            if isinstance(key, Ed25519PrivateKey):
                return base64.b64encode(key.sign(message)).decode("ascii")
        except ImportError:  # pragma: no cover - cryptography is a hard dependency
            raise SigningUnavailable("cryptography is required for signing")

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        signature = key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("ascii")

    # -- headers ---------------------------------------------------------
    def headers(self, method: str, full_url_or_path: str, timestamp_ms: str | None = None) -> dict[str, str]:
        """Build the three ``KALSHI-ACCESS-*`` headers for a request."""
        timestamp = timestamp_ms or str(int(time.time() * 1000))
        path = urlparse(full_url_or_path).path or full_url_or_path
        signed = f"{timestamp}{method.upper()}{path}"
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": self.sign_text(signed),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }


def load_signing_key(key_id: str, pem: str | None = None, pem_path: str | None = None) -> SigningKey:
    """Load an Ed25519 or RSA private key from a PEM string or file."""
    if not key_id:
        raise SigningUnavailable("KALSHI_API_KEY_ID is not set")
    if not pem and not pem_path:
        raise SigningUnavailable("KALSHI_PRIVATE_KEY or KALSHI_PRIVATE_KEY_PATH is not set")

    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:  # pragma: no cover
        raise SigningUnavailable("the 'cryptography' package is required for signed requests") from exc

    data = pem.encode("utf-8") if pem else Path(pem_path).read_bytes()
    key = serialization.load_pem_private_key(data, password=None)
    return SigningKey(key_id, key)
