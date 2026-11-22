"""Same-origin UI + public feed; private account access requires a separate operator token."""

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import hmac
import json
from pathlib import Path
import re
import time
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .auth import Signer
from .client import KalshiClient, PUBLIC_QUERY_KEYS, TICKER_PATTERN, UpstreamError, public_path
from .config import Settings, TOPICS
from .domain import BookError, group_events
from .orders import OrderIntent, submit_order
from .runtime import Runtime, now_ms
from .store import Store


def create_app(settings: Settings | None = None, *, runtime: Runtime | None = None,
               run_background: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application):
        nonlocal runtime
        if runtime is None:
            signer = Signer.from_file(settings.api_key_id, settings.private_key_path) if settings.api_key_id else None
            runtime = Runtime(settings, KalshiClient(settings, signer), Store(settings.db_path))
        application.state.runtime = runtime
        if run_background:
            await runtime.start()
        yield
        await runtime.stop()

    application = FastAPI(title="Tradebot1 — demo-only research service", version="1.0.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type"],
    )
    requests_by_peer: dict[str, deque] = defaultdict(deque)
    proxy_cache: dict[str, tuple[float, dict]] = {}
    proxy_semaphore = asyncio.Semaphore(4)

    def get_runtime(request: Request) -> Runtime:
        return request.app.state.runtime

    async def operator(request: Request):
        expected = settings.operator_token
        if not expected:
            raise HTTPException(503, "operator_access_not_configured")
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied.encode(), f"Bearer {expected}".encode()):
            raise HTTPException(401, "operator_authorization_required", headers={"WWW-Authenticate": "Bearer"})

    def valid_ticker(ticker: str) -> str:
        if not re.fullmatch(TICKER_PATTERN, ticker):
            raise HTTPException(422, "invalid_ticker")
        return ticker

    @application.middleware("http")
    async def security(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            peer = request.client.host if request.client else "unknown"
            stamp = time.monotonic()
            recent = requests_by_peer[peer]
            while recent and stamp - recent[0] >= 60:
                recent.popleft()
            if len(recent) >= 240:
                return JSONResponse({"error": "service_rate_limit"}, status_code=429,
                                    headers={"Retry-After": "60", "Cache-Control": "no-store"})
            recent.append(stamp)
            if len(requests_by_peer) > 10_000:
                requests_by_peer.clear()
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(UpstreamError)
    async def upstream_error(request: Request, exc: UpstreamError):
        status = exc.status if 400 <= exc.status < 600 else 502
        return JSONResponse({"error": exc.code, "unverified": True, "ambiguous": exc.ambiguous}, status_code=status)

    @application.exception_handler(BookError)
    async def book_error(request: Request, exc: BookError):
        return JSONResponse({"error": "book_invalid_resnapshot_required", "unverified": True}, status_code=502)

    @application.get("/api/health")
    async def health(service: Runtime = Depends(get_runtime)):
        return service.health()

    @application.get("/api/snapshot")
    async def snapshot(service: Runtime = Depends(get_runtime)):
        return service.snapshot()

    @application.get("/api/events")
    async def events(topic: str | None = None, service: Runtime = Depends(get_runtime)):
        if topic is not None and topic not in TOPICS:
            raise HTTPException(422, "unsupported_topic")
        rows = group_events(list(service.events.values()), service.markets)
        return {"events": [row for row in rows if topic is None or row["topic"] == topic],
                "coverage": {"discovery_complete": service.state["discovery_complete"]}}

    @application.get("/api/alerts")
    async def alerts(selected: bool = False, limit: int = Query(100, ge=1, le=1000),
                     service: Runtime = Depends(get_runtime)):
        return {"alerts": service.store.alerts(selected, limit)}

    @application.get("/api/markets/{ticker}/history")
    async def history(ticker: str, window: Literal["seconds", "minutes", "hours"] = "minutes",
                      service: Runtime = Depends(get_runtime)):
        valid_ticker(ticker)
        if ticker not in service.markets:
            raise HTTPException(404, "untracked_market")
        duration = {"seconds": 60_000, "minutes": 3_600_000, "hours": 86_400_000}[window]
        points = service.store.history(ticker, now_ms() - duration)
        return {"ticker": ticker, "points": points, "window": window, "window_ms": duration,
                "point_limit": 10_000, "possibly_truncated": len(points) == 10_000,
                "interpolated": False, "source_url": service.markets[ticker]["source_url"]}

    @application.get("/api/markets/{ticker}/orderbook")
    async def orderbook(ticker: str, service: Runtime = Depends(get_runtime)):
        valid_ticker(ticker)
        return (await service.get_book(ticker)).as_dict(now_ms())

    @application.get("/api/paper")
    async def paper(service: Runtime = Depends(get_runtime)):
        return service.paper.summary(service.markets, now_ms())

    @application.get("/api/verification")
    async def verification():
        path = Path(__file__).resolve().parent.parent / "verification.json"
        return json.loads(path.read_text())

    @application.get("/api/stream")
    async def stream(request: Request, service: Runtime = Depends(get_runtime)):
        if len(service.listeners) >= 50:
            raise HTTPException(429, "too_many_stream_clients")

        async def generate():
            queue = asyncio.Queue(maxsize=1)
            service.listeners.add(queue)
            try:
                yield "event: snapshot\ndata: " + json.dumps(service.snapshot(), separators=(",", ":")) + "\n\n"
                while not await request.is_disconnected():
                    try:
                        await asyncio.wait_for(queue.get(), timeout=15)
                        # Coalesce bursts: each update is an authoritative full public snapshot.
                        await asyncio.sleep(0.15)
                        yield "event: update\ndata: " + json.dumps(service.snapshot(), separators=(",", ":")) + "\n\n"
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
            finally:
                service.listeners.discard(queue)

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @application.get("/api/kalshi/{path:path}")
    async def proxy(path: str, request: Request, service: Runtime = Depends(get_runtime)):
        upstream_path = "/" + path
        if not public_path(upstream_path) or ".." in upstream_path:
            raise HTTPException(404, "path_not_allowed")
        query = dict(request.query_params)
        if any(key not in PUBLIC_QUERY_KEYS for key in query) or len(str(request.query_params)) > 4000:
            raise HTTPException(422, "query_not_allowed")
        cache_key = upstream_path + "?" + str(sorted(query.items()))
        cached = proxy_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 5:
            return JSONResponse(cached[1], headers={"X-Data-Mode": "demo-rest-cache", "X-Cache-Max-Age": "5"})
        async with proxy_semaphore:
            data = await service.client.get(upstream_path, query)
        if len(proxy_cache) >= 200:
            proxy_cache.pop(next(iter(proxy_cache)))
        proxy_cache[cache_key] = (time.monotonic(), data)
        return JSONResponse(data, headers={"X-Data-Mode": "demo-rest-observation"})

    @application.get("/api/portfolio", dependencies=[Depends(operator)])
    async def portfolio(service: Runtime = Depends(get_runtime)):
        return await service.portfolio()

    @application.get("/api/orders/journal", dependencies=[Depends(operator)])
    async def journal(service: Runtime = Depends(get_runtime)):
        return {"orders": service.store.journal(), "environment": "demo"}

    @application.post("/api/orders", dependencies=[Depends(operator)])
    async def order(intent: OrderIntent, service: Runtime = Depends(get_runtime)):
        return await submit_order(service, intent)

    @application.delete("/api/orders/{order_id}", dependencies=[Depends(operator)])
    async def cancel(order_id: str, ticker: str, service: Runtime = Depends(get_runtime)):
        valid_ticker(ticker)
        if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", order_id):
            raise HTTPException(422, "invalid_order_id")
        if not service.client.signer:
            raise HTTPException(503, "demo_credentials_not_configured")
        # Cancels remain available after kill; they reduce outstanding activity.
        result = await service.client.request("DELETE", f"/portfolio/events/orders/{order_id}",
                                              params={"market_ticker": ticker, "exchange_index": -1},
                                              authenticated=True)
        service._portfolio_cache = None
        return {"response": result, "environment": "demo",
                "source_url": "https://docs.kalshi.com/api-reference/orders/cancel-order-v2"}

    @application.post("/api/controls/kill", dependencies=[Depends(operator)])
    async def kill(service: Runtime = Depends(get_runtime)):
        service.kill_switch = True
        return {"new_demo_orders": "disabled", "note": "An in-flight request may already have been accepted. Reconcile the journal."}

    static = Path(settings.static_dir)
    if static.is_dir():
        application.mount("/", StaticFiles(directory=static, html=True), name="dashboard")
    else:
        @application.get("/")
        async def pending_static():
            return {"service": "Tradebot1 demo-only adapter", "dashboard": "static integration pending", "health": "/api/health"}

    return application


app = create_app()
