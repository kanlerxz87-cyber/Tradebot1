"""Signed Kalshi demo API client (credentialed use).

Implements request signing per official docs:
  https://docs.kalshi.com/getting_started/api_keys
  - Headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP (ms, +/-30s),
    KALSHI-ACCESS-SIGNATURE
  - Pre-sign text: timestamp + HTTP method + path (NO query string)
  - Ed25519 signs directly; RSA uses RSA-PSS/SHA-256 (MGF1/SHA-256,
    salt length = digest length)

Demo base URL: https://external-api.demo.kalshi.co/trade-api/v2
  (https://docs.kalshi.com/getting_started/demo_env)

Requires: pip install requests cryptography
Credentials: your own demo API key ID + private key PEM (never commit them).
"""
import base64
import os
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DEMO_BASE = "https://external-api.demo.kalshi.co/trade-api/v2"


def load_private_key(path):
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def sign_text(private_key, text: str) -> str:
    msg = text.encode("utf-8")
    if isinstance(private_key, Ed25519PrivateKey):
        sig = private_key.sign(msg)
    else:
        sig = private_key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
    return base64.b64encode(sig).decode("utf-8")


class KalshiDemoClient:
    def __init__(self, key_id, private_key_path, base_url=DEMO_BASE):
        self.key_id = key_id
        self.private_key = load_private_key(private_key_path)
        self.base_url = base_url.rstrip("/")

    def _headers(self, method, path):
        ts = str(int(time.time() * 1000))
        path_no_query = path.split("?")[0]
        sig = sign_text(self.private_key, ts + method + path_no_query)
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "Content-Type": "application/json",
        }

    def request(self, method, path, params=None, body=None):
        url = self.base_url + path
        r = requests.request(method, url, params=params, json=body,
                             headers=self._headers(method, path), timeout=30)
        r.raise_for_status()
        return r.json()

    # Public (no auth needed, but signed client works too)
    def get_markets(self, status="open", limit=100, cursor=""):
        p = {"status": status, "limit": limit}
        if cursor:
            p["cursor"] = cursor
        return self.request("GET", "/markets", params=p)

    def get_orderbook(self, ticker, depth=10):
        return self.request("GET", f"/markets/{ticker}/orderbook",
                            params={"depth": depth})

    # Authenticated portfolio endpoints
    def get_balance(self):
        return self.request("GET", "/portfolio/balance")

    def get_positions(self):
        return self.request("GET", "/portfolio/positions")

    def get_fills(self, limit=100):
        return self.request("GET", "/portfolio/fills", params={"limit": limit})

    def place_order(self, ticker, side, count, price_cents, order_type="limit"):
        body = {"ticker": ticker, "side": side, "count": count,
                "price": price_cents, "type": order_type}
        return self.request("POST", "/portfolio/orders", body=body)


if __name__ == "__main__":
    key_id = os.environ.get("KALSHI_KEY_ID", "")
    key_path = os.environ.get("KALSHI_KEY_PATH", "kalshi.key")
    if not key_id or not os.path.exists(key_path):
        print("Set KALSHI_KEY_ID and KALSHI_KEY_PATH to your demo key files.")
        print("Generate a demo key at https://demo.kalshi.co/ -> Account Settings -> API Keys")
        raise SystemExit(1)
    c = KalshiDemoClient(key_id, key_path)
    print("Balance:", c.get_balance())
