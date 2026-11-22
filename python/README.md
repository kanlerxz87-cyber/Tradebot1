# Python tools (credentialed demo use)

## `kalshi_client.py` — signed Kalshi demo client
Implements request signing exactly per official docs:
https://docs.kalshi.com/getting_started/api_keys
(headers `KALSHI-ACCESS-KEY/-TIMESTAMP/-SIGNATURE`; sign
`timestamp + method + path` without query string; Ed25519 or RSA-PSS/SHA-256;
timestamp within 30 s).

Setup:
1. Create a demo account at https://demo.kalshi.co/ (mock funds).
2. Account Settings → API Keys → Create New API Key. Save the Key ID and
   private key PEM immediately (shown once).
3. `pip install requests cryptography`
4. `export KALSHI_KEY_ID=... KALSHI_KEY_PATH=kalshi.key`
5. `python3 kalshi_client.py` → prints demo balance.

Never commit your private key. Demo keys only work on demo endpoints
(https://docs.kalshi.com/getting_started/api_environments).

## `simulator.py` — paper-trading engine
Mirrors the browser simulator (`site/assets/app.js`). Pure stdlib.
Run tests: `python3 python/test_simulator.py` or `python3 -m pytest python/ -q`
