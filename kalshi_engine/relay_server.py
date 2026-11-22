"""Optional localhost signed relay for connecting a real Kalshi Demo account to `/live/`.

Security boundary:
- Private keys NEVER enter GitHub Pages, repository files, or browser storage.
- Run this relay locally on your machine with your own Kalshi Demo credentials:
    export KALSHI_DEMO_KEY_ID="your-demo-key-id"
    export KALSHI_DEMO_KEY_PATH="/path/to/demo-private-key.pem"
    python3 -m kalshi_engine.relay_server --port 8787
- Exposes localhost-only endpoints for `/live/portfolio/`:
    GET  /api/demo/status    -> exchange status + demo balance + positions + fills
    POST /api/demo/order     -> submits V2 event order to POST /trade-api/v2/portfolio/events/orders
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from kalshi_engine.kalshi_v2_client import KalshiV2Client


def make_handler(client: KalshiV2Client):
    class RelayHandler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(200, {"ok": True})

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/api/demo/status"):
                try:
                    ex = client.get_exchange_status()
                    bal = client.get_balance()
                    pos = client.get_positions()
                    fills = client.get_fills(limit=50)
                    self._send(200, {"connected": True, "exchange": ex, "balance": bal, "positions": pos, "fills": fills})
                except Exception as exc:
                    self._send(502, {"connected": False, "error": str(exc)})
                return
            self._send(404, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/demo/order":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    req = json.loads(self.rfile.read(length).decode("utf-8"))
                    order = client.create_event_order(
                        ticker=req["ticker"],
                        outcome=req.get("side", "yes"),
                        action=req.get("action", "buy"),
                        count=req.get("contracts", 1),
                        price_dollars=req["price_dollars"],
                    )
                    self._send(201, {"ok": True, "order": order})
                except Exception as exc:
                    self._send(400, {"ok": False, "error": str(exc)})
                return
            self._send(404, {"error": "Not found"})

    return RelayHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="Local signed relay for Kalshi Demo API V2")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    client = KalshiV2Client.from_env()
    server = HTTPServer((args.host, args.port), make_handler(client))
    print(f"Kalshi Demo V2 local relay listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
