"""Same-origin static server + authenticated Kalshi Demo V2 relay (`/api/demo/*`).

Why this server exists:
  1. Kalshi's signed headers (`KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`,
     `KALSHI-ACCESS-TIMESTAMP`) are omitted from browser CORS preflight
     `Access-Control-Allow-Headers` on `external-api.demo.kalshi.co`, and private
     RSA-PSS / Ed25519 keys must never be shipped to client-side JavaScript.
  2. Browser-facing code must never call `127.0.0.1` or `localhost` directly; instead,
     `demo-desk` calls relative same-origin endpoints (`/api/demo/status` and
     `/api/demo/order`).
  3. Binding to `0.0.0.0` lets this server host the static repository pages AND the
     `/api/demo/*` endpoints on a single origin (works identically locally or behind a
     cloud preview proxy). When `KALSHI_DEMO_KEY_ID` is absent, `/api/demo/status`
     reports `connected: false` cleanly so the UI continues in verified paper mode.

Usage:
    python3 -m kalshi_engine.relay_server --host 0.0.0.0 --port 8787
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .kalshi_v2_client import KalshiV2Client

REPO_ROOT = Path(__file__).resolve().parent.parent


def _try_load_client() -> tuple[Optional[KalshiV2Client], Optional[str]]:
    if not os.environ.get("KALSHI_DEMO_KEY_ID"):
        return None, (
            "KALSHI_DEMO_KEY_ID / KALSHI_DEMO_KEY_PATH not configured in server environment; "
            "running in verified paper simulation + public Demo REST mode."
        )
    try:
        return KalshiV2Client.from_env(), None
    except Exception as exc:  # pragma: no cover - defensive env diagnostics
        return None, str(exc)


class DemoRelayHandler(SimpleHTTPRequestHandler):
    client: Optional[KalshiV2Client] = None
    client_error: Optional[str] = None
    static_root: Path = REPO_ROOT

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.static_root), **kwargs)

    def end_headers(self) -> None:
        # Allow embedding in preview iframes and cross-origin reads without host rejections.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def _send_json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/demo/status":
            if self.client is None:
                self._send_json(
                    200,
                    {
                        "connected": False,
                        "mode": "public_demo_plus_paper",
                        "reason": self.client_error or "Demo API key not configured.",
                        "docs_url": "https://docs.kalshi.com/getting_started/api_keys",
                    },
                )
                return
            try:
                ex = self.client.get_exchange_status()
                bal = self.client.get_balance()
                pos = self.client.get_positions()
                orders = self.client.get_orders()
                fills = self.client.get_fills(limit=25)
                self._send_json(
                    200,
                    {
                        "connected": True,
                        "mode": "authenticated_demo_v2",
                        "exchange_status": ex,
                        "balance": bal,
                        "positions": pos,
                        "orders": orders,
                        "fills": fills,
                    },
                )
            except Exception as exc:
                self._send_json(502, {"connected": False, "error": str(exc)})
            return

        # Serve static workspace files (root landing, /demo-desk/, /docs/, /terminal/, etc.)
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/demo/order":
            self._send_json(404, {"error": "Unknown POST endpoint"})
            return
        if self.client is None:
            self._send_json(
                503,
                {
                    "connected": False,
                    "error": self.client_error or "KALSHI_DEMO_KEY_ID not configured on relay server.",
                    "docs_url": "https://docs.kalshi.com/getting_started/quick_start_create_order",
                },
            )
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        try:
            resp = self.client.create_event_order(
                ticker=str(body["ticker"]),
                yes_or_no=str(body.get("side", "yes")),
                buy_or_sell=str(body.get("action", "buy")),
                contracts=body.get("count", 1),
                price_dollars=body["price_dollars"],
                time_in_force=str(body.get("time_in_force", "good_till_canceled")),
            )
            self._send_json(201, {"ok": True, "response": resp})
        except Exception as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})


def create_server(host: str = "0.0.0.0", port: int = 8787) -> ThreadingHTTPServer:
    client, err = _try_load_client()
    DemoRelayHandler.client = client
    DemoRelayHandler.client_error = err
    DemoRelayHandler.static_root = REPO_ROOT
    return ThreadingHTTPServer((host, port), DemoRelayHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Same-origin static server + Kalshi Demo V2 relay")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    srv = create_server(args.host, args.port)
    mode = "authenticated Demo V2" if DemoRelayHandler.client else "public Demo + paper simulation"
    print(f"Serving Tradebot1 + Kalshi Demo V2 relay ({mode}) at http://{args.host}:{args.port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
