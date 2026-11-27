"""Same-origin static server + signed V2 relay for Kalshi Demo API (`/demo-desk/` & `/live/`).

Security boundary:
- Private keys NEVER enter GitHub Pages, repository files, or browser storage.
- Serves static workspace pages cleanly alongside relative `/api/demo/*` endpoints
  so browser code never needs hardcoded `localhost` / `127.0.0.1` URLs:
    GET  /api/demo/status     -> public Demo exchange status + authenticated Demo account if keys set
    GET  /api/demo/public?... -> read-only proxy for allowlisted public Kalshi Demo V2 paths
    POST /api/demo/order      -> submits V2 event order to POST /trade-api/v2/portfolio/events/orders
- Dotfiles (`.git`, `.env`) and key files (`*.pem`, `*.key`) are strictly blocked from static serving.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from kalshi_engine.kalshi_v2_client import KalshiV2Client

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWED_PUBLIC_PREFIXES = ("/exchange/status", "/series", "/events", "/markets")


def _is_blocked_static_path(url_path: str) -> bool:
    clean = urllib.parse.unquote(url_path.split("?", 1)[0])
    parts = [p for p in clean.split("/") if p]
    for part in parts:
        if part.startswith(".") or part.endswith((".pem", ".key", ".p8", ".env")):
            return True
    return False


def make_handler(client: KalshiV2Client, static_dir: Path = REPO_ROOT):
    class RelayHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(static_dir), **kwargs)

        def log_message(self, fmt: str, *args: Any) -> None:  # quiet clean logs
            super().log_message(fmt, *args)

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send_json(200, {"ok": True})

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlsplit(self.path)
            route = parsed.path

            if route == "/api/demo/status":
                has_creds = bool(client.key_id and client.private_key is not None)
                exchange_data: dict[str, Any] | None = None
                exchange_err: str | None = None
                try:
                    exchange_data = client.get_exchange_status()
                except Exception as exc:
                    exchange_err = str(exc)

                if not has_creds:
                    self._send_json(
                        200,
                        {
                            "ok": exchange_data is not None,
                            "connected": False,
                            "authenticated": False,
                            "mode": "public_relay_no_demo_key",
                            "exchange": exchange_data,
                            "exchange_error": exchange_err,
                            "auth_note": (
                                "Unauthenticated public relay active. Set KALSHI_DEMO_KEY_ID and "
                                "KALSHI_DEMO_KEY_PATH locally to query /portfolio/balance, /portfolio/fills, "
                                "and submit live V2 Demo orders."
                            ),
                            "docs_url": "https://docs.kalshi.com/getting_started/api_keys",
                        },
                    )
                    return

                try:
                    bal = client.get_balance()
                    pos = client.get_positions()
                    fills = client.get_fills(limit=50)
                    self._send_json(
                        200,
                        {
                            "ok": True,
                            "connected": True,
                            "authenticated": True,
                            "mode": "authenticated_demo_account",
                            "exchange": exchange_data,
                            "balance": bal,
                            "positions": pos,
                            "fills": fills,
                        },
                    )
                except Exception as exc:
                    self._send_json(
                        502,
                        {
                            "ok": False,
                            "connected": False,
                            "authenticated": False,
                            "exchange": exchange_data,
                            "error": str(exc),
                        },
                    )
                return

            if route == "/api/demo/public":
                qs = urllib.parse.parse_qs(parsed.query)
                endpoint = (qs.get("endpoint") or [""])[0].strip()
                ep_parts = urllib.parse.urlsplit(endpoint)
                ep_path = "/" + ep_parts.path.lstrip("/")
                if not any(ep_path == p or ep_path.startswith(p + "/") for p in ALLOWED_PUBLIC_PREFIXES):
                    self._send_json(400, {"ok": False, "error": f"Disallowed public endpoint: {ep_path!r}"})
                    return
                ep_params = dict(urllib.parse.parse_qsl(ep_parts.query, keep_blank_values=False))
                try:
                    data = client.request("GET", ep_path, params=ep_params, authenticated=False)
                    self._send_json(200, {"ok": True, "endpoint": ep_path, "data": data})
                except Exception as exc:
                    self._send_json(502, {"ok": False, "endpoint": ep_path, "error": str(exc)})
                return

            if _is_blocked_static_path(route):
                self._send_json(403, {"error": "Forbidden path"})
                return

            super().do_GET()

        def do_HEAD(self) -> None:  # noqa: N802
            if _is_blocked_static_path(self.path):
                self.send_error(403, "Forbidden path")
                return
            super().do_HEAD()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/api/demo/order":
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
                    self._send_json(201, {"ok": True, "order": order})
                except Exception as exc:
                    self._send_json(400, {"ok": False, "error": str(exc)})
                return
            self._send_json(404, {"error": "Not found"})

    return functools.partial(RelayHandler)


def create_relay_server(
    host: str = "0.0.0.0",
    port: int = 8787,
    client: KalshiV2Client | None = None,
    static_dir: Path = REPO_ROOT,
) -> ThreadingHTTPServer:
    active_client = client or KalshiV2Client.from_env()
    return ThreadingHTTPServer((host, port), make_handler(active_client, static_dir=static_dir))


create_server = create_relay_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Same-origin static server + signed V2 relay for Kalshi Demo API")
    parser.add_argument("--host", default=os.environ.get("KALSHI_RELAY_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("KALSHI_RELAY_PORT", "8787")))
    args = parser.parse_args()
    server = create_relay_server(host=args.host, port=args.port)
    print(f"Kalshi Demo V2 server & relay listening on http://{args.host}:{args.port}/demo-desk/")
    server.serve_forever()


if __name__ == "__main__":
    main()
