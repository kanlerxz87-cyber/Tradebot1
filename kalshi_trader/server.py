"""Local live server: same site, plus seconds-level refresh and a WebSocket push.

Run with ``python -m kalshi_trader.cli serve``. The static site under ``docs/`` is served at
``/`` so the dashboard, the topic pages and the JSON data all work exactly as they do on
GitHub Pages — the only difference is that this process can also collect fresh data.

Endpoints
---------
``GET /api/status``              health, cadence, data source, last cycle metadata
``GET /api/latest``              the latest cycle payload
``GET /api/history``             all recorded price series
``GET /api/history/{ticker}``    one series
``GET /api/orderbook/{ticker}``  live orderbook (best effort; needs egress to Kalshi)
``POST /api/collect``            force a cycle now
``WS  /ws``                      pushes ``{"type": "tick", "payload": latest}``

CORS is fully open so the page can be embedded in a preview frame.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from . import store
from .client import public_client
from .collector import run_cycle
from .config import Settings
from .marketdata import normalize_orderbook

log = logging.getLogger(__name__)


def create_app(settings: Settings, *, interval: int = 30, live: bool = True):
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("pip install -r requirements.txt (fastapi + uvicorn are required)") from exc

    app = FastAPI(title="Kalshi Trader dashboard", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    state: dict[str, Any] = {
        "last_cycle": store.read_json(settings.data_dir / "latest.json", {}) or {},
        "last_run_ts": 0,
        "last_error": None,
        "clients": set(),
        "interval": interval,
        "live": live,
        "cycles": 0,
    }

    async def broadcast(payload: dict[str, Any]) -> None:
        dead = []
        message = json.dumps({"type": "tick", "payload": payload})
        for ws in list(state["clients"]):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            state["clients"].discard(ws)

    async def cycle_loop() -> None:
        while True:
            started = time.time()
            try:
                payload = await asyncio.to_thread(run_cycle, settings, samples=2)
                state["last_cycle"] = payload
                state["last_run_ts"] = int(started)
                state["cycles"] += 1
                state["last_error"] = None
                await broadcast(payload)
            except Exception as exc:  # keep the server alive
                state["last_error"] = f"{type(exc).__name__}: {exc}"
                log.exception("cycle failed")
            await asyncio.sleep(max(5, interval))

    @app.on_event("startup")
    async def _startup() -> None:  # pragma: no cover - exercised at runtime
        if live:
            asyncio.create_task(cycle_loop())

    # ------------------------------------------------------------------ api
    @app.get("/api/status")
    async def api_status() -> JSONResponse:
        latest = state["last_cycle"] or {}
        return JSONResponse(
            {
                "ok": True,
                "live_collection": live,
                "interval_seconds": interval,
                "cycles_completed": state["cycles"],
                "last_run_ts": state["last_run_ts"],
                "last_error": state["last_error"],
                "generated_at": latest.get("generated_at"),
                "markets": latest.get("market_count"),
                "alerts": len(latest.get("alerts") or []),
                "data_env": settings.data_env,
                "rest_base": settings.rest_base,
            }
        )

    @app.get("/api/latest")
    async def api_latest() -> JSONResponse:
        return JSONResponse(state["last_cycle"] or store.read_json(settings.data_dir / "latest.json", {}))

    @app.get("/api/history")
    async def api_history() -> JSONResponse:
        return JSONResponse(store.read_json(settings.data_dir / "history.json", {}))

    @app.get("/api/history/{ticker}")
    async def api_history_one(ticker: str) -> JSONResponse:
        payload = store.read_json(settings.data_dir / "history.json", {}) or {}
        return JSONResponse({"ticker": ticker, "points": (payload.get("series") or {}).get(ticker, [])})

    @app.get("/api/orderbook/{ticker}")
    async def api_orderbook(ticker: str) -> JSONResponse:
        client = public_client(settings)
        try:
            raw = await asyncio.to_thread(client.orderbook, ticker, 12)
            return JSONResponse({"ticker": ticker, "orderbook": normalize_orderbook(raw), "ok": True})
        except Exception as exc:
            return JSONResponse(
                {"ticker": ticker, "ok": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=502
            )

    @app.post("/api/collect")
    async def api_collect() -> JSONResponse:
        payload = await asyncio.to_thread(run_cycle, settings, samples=1)
        state["last_cycle"] = payload
        state["last_run_ts"] = int(time.time())
        await broadcast(payload)
        return JSONResponse({"ok": True, "generated_at": payload.get("generated_at")})

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        state["clients"].add(websocket)
        try:
            if state["last_cycle"]:
                await websocket.send_text(json.dumps({"type": "tick", "payload": state["last_cycle"]}))
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            state["clients"].discard(websocket)

    # --------------------------------------------------------------- static
    site_dir = Path(settings.site_dir)
    if site_dir.exists():
        app.mount("/", StaticFiles(directory=str(site_dir), html=True), name="site")

    return app
