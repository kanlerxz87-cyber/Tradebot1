"""Request signing for the Kalshi Trade API.

Source: https://docs.kalshi.com/getting_started/api_keys

Verified rules implemented here:

1. Headers are `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`,
   `KALSHI-ACCESS-TIMESTAMP` (milliseconds).
2. Pre-sign text is `timestamp + METHOD + path`, where the path is the **full
   path from the API root without query parameters**
   (e.g. `/trade-api/v2/portfolio/orders`).
3. Ed25519 keys sign the bytes directly; RSA keys use RSA-PSS with SHA-256,
   MGF1(SHA-256) and salt length equal to the digest length.
4. The timestamp must be within **30 seconds** of Kalshi's clock or the request
   fails with 401 `header_timestamp_expired`.
5. The same pre-sign text is used for the WebSocket handshake, with path
   `/trade-api/ws/v2`.

The private key never leaves the machine and is never logged.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

CLOCK_SKEW_LIMIT_SECONDS = 30


class AuthError(RuntimeError):
    pass


def signing_path(url_or_path: str) -> str:
    """Return the path used in the pre-sign text: full path, no query string."""
    parts = urlsplit(url_or_path)
    path = parts.path if parts.scheme or parts.netloc else url_or_path
    return path.split("?")[0]


@dataclass
class KalshiSigner:
    key_id: str
    private_key: object

    @classmethod
    def from_pem_file(cls, key_id: str, path: str | Path) -> "KalshiSigner":
        raw = Path(path).read_bytes()
        try:
            key = serialization.load_pem_private_key(raw, password=None)
        except Exception as exc:  # pragma: no cover - config error path
            raise AuthError(f"Could not load private key from {path}: {exc}") from exc
        if not isinstance(key, (ed25519.Ed25519PrivateKey, rsa.RSAPrivateKey)):
            raise AuthError("Kalshi API keys must be Ed25519 or RSA private keys")
        return cls(key_id=key_id, private_key=key)

    @property
    def key_type(self) -> str:
        return "ed25519" if isinstance(self.private_key, ed25519.Ed25519PrivateKey) else "rsa"

    def sign_bytes(self, message: bytes) -> bytes:
        if isinstance(self.private_key, ed25519.Ed25519PrivateKey):
            return self.private_key.sign(message)
        return self.private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )

    def headers(self, method: str, url_or_path: str, timestamp_ms: int | None = None) -> dict[str, str]:
        ts = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
        message = f"{ts}{method.upper()}{signing_path(url_or_path)}".encode()
        signature = base64.b64encode(self.sign_bytes(message)).decode()
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }


def generate_keypair(key_type: str = "ed25519", out_dir: str | Path = "data/secrets") -> dict:
    """Create a local keypair for registering at kalshi.com/account/profile.

    Mirrors the documented `openssl genpkey` workflow, but in pure Python. The
    private key is written with 0600 permissions and must stay out of git.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if key_type.lower() == "rsa":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    else:
        key = ed25519.Ed25519PrivateKey.generate()
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_path = out / f"kalshi_{key_type}.key"
    pub_path = out / f"kalshi_{key_type}.pub"
    key_path.write_bytes(priv_pem)
    key_path.chmod(0o600)
    pub_path.write_bytes(pub_pem)
    return {"private_key_path": str(key_path), "public_key_path": str(pub_path), "key_type": key_type}
