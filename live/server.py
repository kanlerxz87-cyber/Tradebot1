#!/usr/bin/env python3
"""Live desk server — Python standard library only.

    python3 live/server.py --port 8000            # 0.0.0.0:8000, auto mode
    python3 live/server.py --mode live            # poll the demo REST API instead
    python3 live/server.py --interval 1.0         # tick cadence, seconds

Routes
------
``GET /``                     the dashboard (static files under ``live/static``)
``GET /api/meta``             mode, disclosure, threshold, strategies, sources
``GET /api/state``            topics -> events -> markets, alerts, portfolio, resolution watch
``GET /api/series``           ``?ticker=``&``seconds=`` price history for the chart
``GET /api/book``             ``?ticker=`` bid/ask ladder with resting contracts per price
``GET /api/stream``           Server-Sent Events: one ``tick`` message per interval
``GET /api/health``           liveness

Why SSE rather than WebSocket
-----------------------------
The browser needs a push channel; the standard library cannot speak WebSocket, and adding a
third-party dependency would mean this file could not run on a bare machine. Server-Sent
Events are one HTTP response and are supported by every current browser. Kalshi's own
WebSocket channel (``wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2``) is the right
transport for production and is documented in ``/api/meta`` and ``live/README.md``; this
process never claims to use it.

Nothing here can place an order. Only public market-data routes are called.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from desk import Desk, THRESHOLD, DOCS

STATIC = Path(__file__).resolve().parent / "static"
ALLOWED_RANGES = {30, 60, 300, 900, 3600, 14400}


class Hub:
    """Fan-out of tick payloads to every connected SSE client."""

    def __init__(self, desk: Desk) -> None:
        self.desk = desk
        self.subscribers: set[queue.Queue] = set()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="desk-ticker", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        while not self.stop.is_set():
            started = time.time()
            try:
                payload = self.desk.tick()
            except Exception as exc:  # noqa: BLE001 - a bad tick must not kill the process
                payload = {"ts": time.time(), "error": f"{type(exc).__name__}: {exc}", "updates": []}
            message = json.dumps({"type": "tick", **payload})
            with self.lock:
                dead = []
                for q in self.subscribers:
                    try:
                        q.put_nowait(message)
                    except queue.Full:
                        dead.append(q)
                for q in dead:
                    self.subscribers.discard(q)
            elapsed = time.time() - started
            self.stop.wait(max(0.05, self.desk.interval - elapsed))

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=120)
        with self.lock:
            self.subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            self.subscribers.discard(q)


class Handler(BaseHTTPRequestHandler):
    server_version = "DeskHTTP/1.0"
    protocol_version = "HTTP/1.1"
    desk: Desk
    hub: Hub

    # -- plumbing --------------------------------------------------------- #

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter logs, one line per request
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-store")

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._json({"error": "not found", "path": str(path)}, 404)
            return
        body = path.read_bytes()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json",
            ".svg": "image/svg+xml",
        }.get(path.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        # A preview frame must be embeddable; never send a framing denial.
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        route = parsed.path

        if route in ("/", "/index.html"):
            self._file(STATIC / "index.html")
            return
        if route == "/api/health":
            self._json({"ok": True, "mode": self.desk.mode, "ticks": self.desk.ticks,
                        "at": self.desk.meta()["lastTickAt"]})
            return
        if route == "/api/meta":
            self._json(self.desk.meta())
            return
        if route == "/api/state":
            self._json(self.desk.state())
            return
        if route == "/api/series":
            ticker = (query.get("ticker") or [""])[0]
            try:
                seconds = int((query.get("seconds") or ["900"])[0])
            except ValueError:
                seconds = 900
            seconds = min(seconds, max(ALLOWED_RANGES))
            self._json(self.desk.series(ticker, seconds))
            return
        if route == "/api/book":
            ticker = (query.get("ticker") or [""])[0]
            self._json(self.desk.book(ticker))
            return
        if route == "/api/stream":
            self._stream()
            return
        if route.startswith("/static/"):
            self._file(STATIC / route[len("/static/"):])
            return
        if route.startswith("/api/"):
            self._json({"error": "unknown endpoint", "docs": "/api/meta"}, 404)
            return
        # Static asset fallback (app.js, style.css, favicon).
        candidate = (STATIC / route.lstrip("/")).resolve()
        if STATIC in candidate.parents:
            self._file(candidate)
            return
        self._json({"error": "not found", "path": route}, 404)

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()
        q = self.hub.subscribe()
        try:
            first = json.dumps({"type": "hello", "mode": self.desk.mode, "threshold": THRESHOLD,
                                "at": self.desk.meta()["lastTickAt"]})
            self.wfile.write(f"event: hello\ndata: {first}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    message = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(f"data: {message}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.hub.unsubscribe(q)


def build(host: str, port: int, mode: str, interval: float) -> ThreadingHTTPServer:
    desk = Desk(mode=mode, interval=interval)
    hub = Hub(desk)
    handler = type("BoundHandler", (Handler,), {"desk": desk, "hub": hub})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    hub.start()
    # Prime one tick so /api/state and the chart have a second point immediately.
    desk.tick()
    return httpd


def main() -> None:
    parser = argparse.ArgumentParser(description="Kalshi live desk (stdlib only)")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--mode", choices=("auto", "simulated", "live"), default="auto",
                        help="auto tries live once, then falls back to the labelled simulation")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between ticks")
    args = parser.parse_args()
    httpd = build(args.host, args.port, args.mode, args.interval)
    desk = httpd.RequestHandlerClass.desk
    meta = desk.meta()
    print(f"live desk  mode={meta['mode']}  markets={meta['snapshot']['markets']}  "
          f"source={meta['snapshot']['source']}", flush=True)
    print(f"listening  http://{args.host}:{httpd.server_address[1]}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopping", flush=True)
    finally:
        desk.lock = threading.RLock()
        httpd.server_close()


if __name__ == "__main__":
    main()
