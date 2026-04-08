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
        """Send a JSON payload to all connected clients.

        Disconnected clients are silently removed.
        """
        async with self._lock:
            if not self._connections:
                return
            dead: list[WebSocket] = []
            for ws in self._connections:
                try:
                    await ws.send_json(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.remove(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Module-level singleton
ws_manager = WebSocketManager()
