"""FastAPI application factory and uvicorn server thread.

The API server runs in a daemon thread alongside the Qt event loop.
It uses its own asyncio event loop, completely independent of Qt.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .dependencies import get_bridge, init_bridge
from .routes import (
    analysis,
    background,
    camera,
    centroid,
    config,
    display,
    frames,
    overlays,
    roi,
    streaming,
    trending,
)
from .ws_manager import ws_manager

log = logging.getLogger(__name__)

# Module-level reference to the API event loop (set by the server thread).
_api_loop: asyncio.AbstractEventLoop | None = None


def get_api_loop() -> asyncio.AbstractEventLoop | None:
    """Return the asyncio event loop running in the API thread, or None."""
    return _api_loop


def create_app() -> FastAPI:
    """Build and return the FastAPI application with all routes registered."""
    app = FastAPI(
        title="PyBeamViewer API",
        version="1.0.0",
        description="Programmatic access to the PyBeamViewer beam profile viewer.",
    )

    # CORS: allow all origins for local development / beamline tools
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register all route modules
    app.include_router(camera.router)
    app.include_router(streaming.router)
    app.include_router(background.router)
    app.include_router(analysis.router)
    app.include_router(roi.router)
    app.include_router(centroid.router)
    app.include_router(display.router)
    app.include_router(overlays.router)
    app.include_router(trending.router)
    app.include_router(frames.router)
    app.include_router(config.router)

    @app.get("/health", tags=["System"])
    def health(bridge=Depends(get_bridge)):
        """Health check endpoint."""
        status = bridge.get_streaming_status()
        return {
            "status": "ok",
            "streaming": status["streaming"],
            "connected": status["connected"],
            "frame_count": status["frame_count"],
            "ws_clients": ws_manager.connection_count,
        }

    return app


def start_api_thread(
    bridge: Any,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> threading.Thread:
    """Start the FastAPI server in a daemon thread.

    Parameters
    ----------
    bridge : ApiBridge
        The bridge instance connecting the API to the Qt application.
    host : str
        Bind address for the server.
    port : int
        Port number for the server.

    Returns
    -------
    threading.Thread
        The running daemon thread.
    """
    init_bridge(bridge)
    ready = threading.Event()

    def _run() -> None:
        global _api_loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _api_loop = loop

        app = create_app()
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            loop="none",
            log_level="warning",
        )
        server = uvicorn.Server(config)

        # Signal that the loop is ready
        ready.set()

        loop.run_until_complete(server.serve())

    thread = threading.Thread(target=_run, name="api-server", daemon=True)
    thread.start()

    # Wait for the event loop to be running before returning
    ready.wait(timeout=5.0)
    log.info("API server starting on http://%s:%d", host, port)
    return thread


def schedule_ws_broadcast(payload: dict[str, Any]) -> None:
    """Schedule a WebSocket broadcast from any thread (e.g. Qt main thread).

    Uses ``call_soon_threadsafe`` to post to the API event loop.
    """
    loop = _api_loop
    if loop is None or loop.is_closed():
        return
    loop.call_soon_threadsafe(
        loop.create_task,
        ws_manager.broadcast(payload),
    )
