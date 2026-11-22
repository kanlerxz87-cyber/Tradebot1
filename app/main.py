"""FastAPI service: JSON API + the live dashboard UI.

Run it:

    KALSHI_ENV=demo uvicorn app.main:app --host 0.0.0.0 --port 8000

Routes
------
    GET  /                     dashboard (HTML)
    GET  /api/health           liveness + configuration summary (no secrets)
    GET  /api/state            one-shot snapshot of everything the dashboard shows
    GET  /api/markets          tracked markets for a topic
    GET  /api/market/{ticker}  ticks + orderbook + alerts for one market
    GET  /api/alerts           all-events chat feed (JSON)
    GET  /api/alerts/selective high-ROI chat feed (JSON)
    GET  /api/portfolio        simulated portfolios per strategy
    GET  /api/analytics        trades grouped by category / topic / side
    GET  /api/resolutions      resolved markets and how they resolved
    GET  /api/verification     the verified-facts registry (data/verification.json)
    POST /api/refresh          force a market-universe refresh

The HTTP layer never invents data: when the engine has not produced a value the
field is null and the UI renders it as "unverified" or "--".
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from .collector import Collector
from .config import load_settings
from .kalshi_api import KalshiAPI, KalshiAPIError
from .storage import Store
from .topics import TOPIC_META, TOPIC_ORDER

log = logging.getLogger("kalshi.app")

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
ROOT = HERE.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    store = Store(settings.db_path)
    api = KalshiAPI(settings)
    await api.__aenter__()
    collector = Collector(settings, store, api=api)
    app.state.settings = settings
    app.state.store = store
    app.state.collector = collector
    app.state.started = False
    if not settings.has_credentials and settings.environment == "demo":
        log.info("No Kalshi credentials: market data only, no orders, no websocket.")
    try:
        yield
    finally:
        await collector.stop()
        await api.__aexit__(None, None, None)
        store.close()


app = FastAPI(title="Kalshi Live Dashboard", version="1.0.0", lifespan=lifespan)


def _collector(request: Request) -> Collector:
    return request.app.state.collector


async def _ensure_started(request: Request) -> Collector:
    collector = _collector(request)
    if not collector.status["running"]:
        await collector.start(own_api=False)
        # First refresh is awaited so the first page paint has content.
        try:
            await collector.refresh_universe()
            collector._last_universe = __import__("time").time()
        except Exception as exc:
            collector.status["last_error"] = f"initial refresh: {exc}"
    return collector


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/health")
async def health(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "ok": True,
        "settings": settings.as_public_dict(),
        "verification_loaded": (ROOT / "data" / "verification.json").exists(),
    }


@app.get("/api/config")
async def config(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        **settings.as_public_dict(),
        "topics": [{"key": k, **TOPIC_META[k]} for k in TOPIC_ORDER],
        "alert_rule": "Alert when |price change| >= $0.10 within the rolling window.",
    }


@app.get("/api/state")
async def state(request: Request, topic: str = Query("all"), limit: int = Query(60, ge=1, le=500)) -> dict:
    collector = await _ensure_started(request)
    payload = collector.dashboard_state(topic=None if topic == "all" else topic, limit=limit)
    payload["topic_meta"] = {k: TOPIC_META[k] for k in TOPIC_ORDER}
    return payload


@app.get("/api/markets")
async def markets(request: Request, topic: str = Query("all"), limit: int = Query(80, ge=1, le=500)) -> dict:
    collector = await _ensure_started(request)
    return {"markets": collector._market_rows(topic=None if topic == "all" else topic, limit=limit),
            "topic": topic}


@app.get("/api/market/{ticker}")
async def market_detail(request: Request, ticker: str,
                        range_seconds: int = Query(3600, ge=10, le=7 * 86400)) -> dict:
    collector = await _ensure_started(request)
    detail = collector.market_detail(ticker.upper(), range_seconds=range_seconds)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")
    return detail


@app.get("/api/alerts")
async def alerts(request: Request, since_id: int = Query(0, ge=0),
                 limit: int = Query(60, ge=1, le=500), topic: str = Query("all")) -> dict:
    store: Store = request.app.state.store
    rows = store.list_alerts(since_id=since_id, limit=limit,
                             topic=None if topic == "all" else topic, selective=None)
    return {"alerts": list(reversed(rows)), "since_id": since_id,
            "rule": ">= $0.10 move in either direction"}


@app.get("/api/alerts/selective")
async def alerts_selective(request: Request, since_id: int = Query(0, ge=0),
                           limit: int = Query(60, ge=1, le=500)) -> dict:
    store: Store = app_store(request)
    rows = store.list_alerts(since_id=since_id, limit=limit, selective=True)
    settings = request.app.state.settings
    return {"alerts": list(reversed(rows)), "since_id": since_id,
            "min_score": str(settings.selective_min_score),
            "note": "Ranked by a heuristic trade-quality score, not a probability of profit."}


def app_store(request: Request) -> Store:
    return request.app.state.store


@app.get("/api/portfolio")
async def portfolio(request: Request) -> dict:
    collector = await _ensure_started(request)
    return collector.sim.portfolio_summary()


@app.get("/api/analytics")
async def analytics(request: Request) -> dict:
    collector = await _ensure_started(request)
    payload = collector.sim.category_analytics()
    payload["alert_stats"] = request.app.state.store.alert_stats()
    return payload


@app.get("/api/resolutions")
async def resolutions(request: Request, topic: str = Query("all"), limit: int = Query(200, ge=1, le=1000)) -> dict:
    store: Store = request.app.state.store
    return {"resolutions": store.list_resolutions(topic=None if topic == "all" else topic, limit=limit)}


@app.get("/api/verification")
async def verification() -> dict:
    path = ROOT / "data" / "verification.json"
    if not path.exists():
        raise HTTPException(status_code=404,
                            detail="data/verification.json not generated yet; run python -m engine.build_site_data")
    return json.loads(path.read_text())


@app.post("/api/refresh")
async def refresh(request: Request) -> dict:
    collector = await _ensure_started(request)
    try:
        result = await collector.refresh_universe()
    except KalshiAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return result


@app.get("/api/charts/{ticker}")
async def chart_series(request: Request, ticker: str, range_seconds: int = Query(3600, ge=10, le=7 * 86400)) -> dict:
    """Time series shaped for a simple x=time, y=price chart."""
    collector = await _ensure_started(request)
    ticks = request.app.state.store.ticks(ticker.upper(), since_ts=__import__("time").time() - range_seconds,
                                          limit=20000)
    points = []
    for row in ticks:
        bid = row.get("yes_bid")
        ask = row.get("yes_ask")
        price = None
        try:
            bid_f = float(bid) if bid not in (None, "") else None
            ask_f = float(ask) if ask not in (None, "") else None
            if bid_f and ask_f and 0 < bid_f <= ask_f < 1:
                price = (bid_f + ask_f) / 2
            elif row.get("last_price") not in (None, ""):
                price = float(row["last_price"])
            elif bid_f:
                price = bid_f
        except (TypeError, ValueError):
            price = None
        if price is None:
            continue
        points.append({"t": row["ts"], "p": round(price, 4)})
    return {"ticker": ticker.upper(), "points": points, "range_seconds": range_seconds,
            "note": "Mid of best YES bid and implied YES ask; falls back to last traded price."}


@app.exception_handler(KalshiAPIError)
async def kalshi_error_handler(request: Request, exc: KalshiAPIError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"error": "kalshi_upstream", "detail": str(exc),
                                                  "status": exc.status, "code": exc.code})


if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
