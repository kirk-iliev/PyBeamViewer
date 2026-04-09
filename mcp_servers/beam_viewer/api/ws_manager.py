"""WebSocket connection manager for real-time frame streaming."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and broadcasts frame data."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        log.info("WebSocket client connected (%d total)", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        log.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Send a JSON payload to all connected clients concurrently.

        Uses ``asyncio.gather`` so a slow client cannot block others.
        Each send is wrapped in a 1-second timeout; connections that fail
        or time out are evicted.
        """
        async with self._lock:
            if not self._connections:
                return
            results = await asyncio.gather(
                *(
                    asyncio.wait_for(ws.send_json(payload), timeout=1.0)
                    for ws in self._connections
                ),
                return_exceptions=True,
            )
            dead = [
                ws
                for ws, result in zip(self._connections, results)
                if isinstance(result, BaseException)
            ]
            for ws in dead:
                self._connections.remove(ws)
                log.debug("Evicted WebSocket client after failed send")

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Module-level singleton
ws_manager = WebSocketManager()
