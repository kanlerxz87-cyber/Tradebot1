"""Signing tests, checked against Kalshi's documented pre-sign text.

Sources:
* https://docs.kalshi.com/getting_started/api_keys  (timestamp + METHOD + path,
  query stripped, Ed25519 or RSA-PSS/SHA-256, 30 second tolerance)
* https://docs.kalshi.com/getting_started/api_environments  (path is
  `/trade-api/v2/...` on every host; websocket signs `/trade-api/ws/v2`)
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

from app.auth import KalshiSigner, signing_path


def _signer_ed25519():
    key = ed25519.Ed25519PrivateKey.generate()
    return KalshiSigner(key_id="key-1", private_key=key), key.public_key()


def _signer_rsa():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return KalshiSigner(key_id="key-2", private_key=key), key.public_key()


def test_query_string_is_stripped_from_the_signed_path():
    assert signing_path("/trade-api/v2/portfolio/orders?limit=5") == "/trade-api/v2/portfolio/orders"
    assert signing_path("https://external-api.demo.kalshi.co/trade-api/v2/markets?status=open") \
        == "/trade-api/v2/markets"
    assert signing_path("https://demo-api.kalshi.co/trade-api/ws/v2") == "/trade-api/ws/v2"


def test_websocket_signing_path_has_no_v2_prefix():
    # Documented: sign timestamp + "GET" + "/trade-api/ws/v2"
    assert signing_path("/trade-api/ws/v2") == "/trade-api/ws/v2"


def test_ed25519_signature_verifies_over_timestamp_method_path():
    signer, public = _signer_ed25519()
    headers = signer.headers("GET", "/trade-api/v2/portfolio/balance", timestamp_ms=1700000000000)
    assert headers["KALSHI-ACCESS-KEY"] == "key-1"
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1700000000000"
    message = b"1700000000000GET/trade-api/v2/portfolio/balance"
    public.verify(base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]), message)


def test_rsa_uses_pss_with_digest_length_salt():
    signer, public = _signer_rsa()
    headers = signer.headers("POST", "/trade-api/v2/portfolio/events/orders", timestamp_ms=1700000000000)
    message = b"1700000000000POST/trade-api/v2/portfolio/events/orders"
    public.verify(
        base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]),
        message,
        padding.PSS(mgf=padding.MGF1(__import__("cryptography.hazmat.primitives.hashes",
                                                fromlist=["SHA256"]).SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        __import__("cryptography.hazmat.primitives.hashes",
                   fromlist=["SHA256"]).SHA256(),
    )


def test_key_type_is_detected_from_the_parsed_key():
    assert _signer_ed25519()[0].key_type == "ed25519"
    assert _signer_rsa()[0].key_type == "rsa"


def test_pem_loading_round_trip(tmp_path):
    key = ed25519.Ed25519PrivateKey.generate()
    path = tmp_path / "k.key"
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    signer = KalshiSigner.from_pem_file("kid", path)
    assert signer.key_type == "ed25519"
    assert "KALSHI-ACCESS-SIGNATURE" in signer.headers("GET", "/trade-api/v2/exchange/status")
