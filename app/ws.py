"""Authenticated WebSocket client for live ticks and market resolution events.

Source: https://docs.kalshi.com/getting_started/quick_start_websockets

Verified details implemented here:

* Connect to `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` (demo) or
  `wss://external-api-ws.kalshi.com/trade-api/ws/v2` (production).
* The handshake is authenticated with the same three headers as REST, signing
  `timestamp + "GET" + "/trade-api/ws/v2"` -- note this path has **no**
  `/trade-api/v2` prefix and no query string.
* Subscribe with `{"id": n, "cmd": "subscribe", "params": {"channels": [...],
  "market_tickers": [...]}}`.
* `ticker` messages carry `price_dollars`, `yes_bid_dollars`, `yes_ask_dollars`,
  `ts_ms`; they are conflated to one flush per second.
  (https://docs.kalshi.com/websockets/market-ticker)
* `market_lifecycle_v2` messages carry `result`, `determination_ts` and
  `settlement_value` when a market resolves.
  (https://docs.kalshi.com/websockets/market-and-event-lifecycle)
* A rejected handshake returns HTTP 429 for rate/connection limits, so we
  reconnect with exponential backoff instead of looping.

If no API key is configured, the collector simply stays on REST polling; the
dashboard then says "WebSocket: not connected (no credentials)".
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from typing import Awaitable, Callable

import websockets

from .auth import KalshiSigner
from .config import WS_SIGN_PATH, Settings

log = logging.getLogger("kalshi.ws")

PUBLIC_CHANNELS = ("ticker", "trade", "market_lifecycle_v2")


class KalshiWebSocket:
    def __init__(self, settings: Settings, signer: KalshiSigner | None,
                 on_message: Callable[[dict], Awaitable[None]]):
        self.settings = settings
        self.signer = signer
        self.on_message = on_message
        self.connected = False
        self.last_error: str | None = None
        self.messages = 0
        self._market_tickers: list[str] = []
        self._stop = asyncio.Event()
        # websockets >= 15 reads HTTP(S)_PROXY from the environment by default.
        proxy = os.environ.get("KALSHI_WS_PROXY")
        self._proxy: str | None = proxy if proxy else None

    async def run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                await self._connect_and_listen()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("websocket error: %s", self.last_error)
                await asyncio.sleep(delay + random.random() * 0.5)
                delay = min(delay * 2, 30.0)

    def stop(self) -> None:
        self._stop.set()

    def update_markets(self, tickers: list[str]) -> None:
        """Replace the subscription list; reconnect applies it on next cycle."""
        self._market_tickers = list(dict.fromkeys(tickers))[:800]

    async def _connect_and_listen(self) -> None:
        if self.signer is None:
            await asyncio.sleep(5)
            raise RuntimeError("no credentials for authenticated websocket")
        headers = self.signer.headers("GET", WS_SIGN_PATH)
        async with websockets.connect(
            self.settings.ws_url,
            additional_headers=headers,
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
            max_size=8 * 1024 * 1024,
            proxy=self._proxy,
        ) as ws:
            self.connected = True
            self.last_error = None
            channels = ["ticker", "market_lifecycle_v2"]
            params: dict = {"channels": channels}
            if self._market_tickers:
                params["market_tickers"] = self._market_tickers
            await ws.send(json.dumps({"id": 1, "cmd": "subscribe", "params": params}))
            async for raw in ws:
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self.messages += 1
                msg_type = message.get("type")
                if msg_type == "error":
                    self.last_error = str(message.get("msg"))
                    log.warning("websocket channel error: %s", self.last_error)
                    continue
                if msg_type in ("subscribed", "ok"):
                    continue
                await self.on_message(message)
        self.connected = False
