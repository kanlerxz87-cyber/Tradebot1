import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

from kalshi_trader.signing import SigningKey, SigningUnavailable, load_signing_key


def _ed25519_pem() -> tuple[bytes, ed25519.Ed25519PrivateKey]:
    key = ed25519.Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem, key


def _rsa_pem() -> tuple[bytes, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem, key


def test_ed25519_headers_sign_timestamp_method_path():
    pem, key = _ed25519_pem()
    signing = load_signing_key("key-id", pem.decode())
    headers = signing.headers("GET", "https://demo-api.kalshi.co/trade-api/v2/portfolio/orders?limit=5", "1703123456789")

    assert headers["KALSHI-ACCESS-KEY"] == "key-id"
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1703123456789"
    signature = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
    # Query string must NOT be part of the signed text.
    key.public_key().verify(signature, b"1703123456789GET/trade-api/v2/portfolio/orders")


def test_rsa_pss_signature_verifies():
    pem, key = _rsa_pem()
    signing = SigningKey("k", key)
    signature = base64.b64decode(signing.sign_text("1703123456789POST/trade-api/v2/portfolio/events/orders"))
    key.public_key().verify(
        signature,
        b"1703123456789POST/trade-api/v2/portfolio/events/orders",
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_missing_credentials_raise():
    with pytest.raises(SigningUnavailable):
        load_signing_key("", "pem")
    with pytest.raises(SigningUnavailable):
        load_signing_key("key-id", None, None)


def test_timestamp_defaults_to_now(monkeypatch):
    pem, _ = _ed25519_pem()
    signing = load_signing_key("key-id", pem.decode())
    headers = signing.headers("GET", "/trade-api/v2/exchange/status")
    assert headers["KALSHI-ACCESS-TIMESTAMP"].isdigit()
    assert len(headers["KALSHI-ACCESS-TIMESTAMP"]) == 13
