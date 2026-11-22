"""Signing follows the official authenticated-request guide (2026-11-22)."""

import base64
from pathlib import Path
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa


class Signer:
    def __init__(self, key_id: str, private_key):
        if not isinstance(private_key, (rsa.RSAPrivateKey, ed25519.Ed25519PrivateKey)):
            raise ValueError("Only RSA and Ed25519 keys are supported by this adapter")
        self.key_id = key_id
        self._key = private_key

    @classmethod
    def from_file(cls, key_id: str, path: str):
        # Never print PEM data, request signatures, or the API key ID.
        private_key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        return cls(key_id, private_key)

    def headers(self, method: str, path: str, timestamp_ms: int | None = None) -> dict[str, str]:
        timestamp = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
        # Full path from host root; query parameters are never signed.
        clean_path = urlsplit(path).path
        if not clean_path.startswith("/trade-api/"):
            raise ValueError("Signing requires the full /trade-api/ path")
        message = f"{timestamp}{method.upper()}{clean_path}".encode()
        if isinstance(self._key, ed25519.Ed25519PrivateKey):
            signature = self._key.sign(message)
        else:
            signature = self._key.sign(
                message,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        }
