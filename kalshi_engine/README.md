# `kalshi_engine` — V2 Kalshi Demo Client, Strategy Simulator & Local Relay

Verified line-by-line against official Kalshi API documentation (checked 2026-11-22):
- [API Environments & Endpoints](https://docs.kalshi.com/getting_started/api_environments.md)
- [API Keys & Request Signing](https://docs.kalshi.com/getting_started/api_keys.md)
- [Create Order (V2) — `/portfolio/events/orders`](https://docs.kalshi.com/api-reference/orders/create-order-v2.md)
- [Orderbook Responses (Reciprocal Bid/Ask Math)](https://docs.kalshi.com/getting_started/orderbook_responses.md)
- [Market Lifecycle (`active` → `finalized`)](https://docs.kalshi.com/getting_started/market_lifecycle.md)
- [Fee Rounding & Accumulator](https://docs.kalshi.com/getting_started/fee_rounding.md)

## Run Offline Unit Tests

```bash
python3 kalshi_engine/test_engine.py
```

## Optional: Connect Your Authenticated Kalshi Demo Account Locally

Never place API keys or private PEM files into GitHub Pages or git. To execute real orders and read your live Demo Account balance/fills from the `/live/` dashboard:

1. Generate a Demo API key (Ed25519 recommended, or RSA-2048) at `https://demo.kalshi.co/` → **Account Settings → API Keys**.
2. Install `cryptography` locally (`pip install cryptography`) and start the local relay:
   ```bash
   export KALSHI_DEMO_KEY_ID="your-demo-key-id"
   export KALSHI_DEMO_KEY_PATH="/path/to/demo.key"
   python3 -m kalshi_engine.relay_server --port 8787
   ```
3. On `/live/portfolio/`, enter `http://127.0.0.1:8787` in **Local Demo Account Relay** to view live Demo Account balance, positions, fills, and route V2 orders (`POST /trade-api/v2/portfolio/events/orders`).
