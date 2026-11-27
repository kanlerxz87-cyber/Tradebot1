# `kalshi_engine` — V2 Kalshi Demo Client, Strategy Simulator & Same-Origin Relay

Verified line-by-line against official Kalshi API documentation (re-verified `2026-11-27` UTC):
- [API Environments & Endpoints](https://docs.kalshi.com/getting_started/api_environments) (`external-api.demo.kalshi.co`, `demo-api.kalshi.co`, `external-api-ws.demo.kalshi.co`, `demo-api.kalshi.co`, `user-ws.demo.kalshi.co`)
- [API Keys & Request Signing](https://docs.kalshi.com/getting_started/api_keys) (`timestamp + METHOD + /trade-api/v2/...` without query string)
- [Create Order (V2) — `/portfolio/events/orders`](https://docs.kalshi.com/api-reference/orders/create-order-v2)
- [Orderbook Responses (Reciprocal Bid/Ask & VWAP Depth Math)](https://docs.kalshi.com/getting_started/orderbook_responses)
- [Market Lifecycle (`active` → `finalized`, `yes` / `no` / `scalar`)](https://docs.kalshi.com/getting_started/market_lifecycle)
- [Fee Rounding, 6dp `ceil`, Accumulator & Per-Series `fee_multiplier`](https://docs.kalshi.com/getting_started/fee_rounding)

## Run Offline Unit Tests

```bash
python3 kalshi_engine/test_engine.py
```

## Optional: Same-Origin Static Preview + Signed Kalshi Demo Account Relay

Never place API keys or private PEM files into GitHub Pages or git. To serve `/demo-desk/` on the same origin as `/api/demo/*` (eliminating cross-origin / `localhost` browser hardcoding) and optionally connect your authenticated Kalshi Demo account:

1. Generate a Demo API key (Ed25519 recommended, or RSA-2048) at `https://demo.kalshi.co/` → **Account Settings → API Keys**.
2. Install `cryptography` (`pip install cryptography`) and start the relay (binds `0.0.0.0:8787` by default):
   ```bash
   export KALSHI_DEMO_KEY_ID="your-demo-key-id"
   export KALSHI_DEMO_KEY_PATH="/path/to/demo.key"
   python3 -m kalshi_engine.relay_server --port 8787
   ```
3. Open `/demo-desk/` or `/demo-desk/portfolio/` on that server: relative `/api/demo/status` and `/api/demo/order` routes automatically surface live Demo Account balance, positions, fills, and submit signed V2 event orders (`POST /trade-api/v2/portfolio/events/orders`). Without credentials, the server safely runs in public read-only mode.
