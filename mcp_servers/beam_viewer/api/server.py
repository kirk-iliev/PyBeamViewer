"""FastAPI application factory for headless beam viewer.

Zero Qt imports.  The app is created via ``create_app(bridge)`` and can be
served directly by uvicorn.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .dependencies import get_bridge, init_bridge
from .routes import (
    analysis,
    background,
    beamspots,
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

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(bridge: Any, *, dispatcher: Optional[Any] = None) -> FastAPI:
    """Build and return the FastAPI application with all routes registered.

    Parameters
    ----------
    bridge : HeadlessBridge
        The bridge instance connecting the API to the headless controller.
    dispatcher : CallbackDispatcher, optional
        If provided, EVT_FRAME_READY events are wired to broadcast frames
        to all connected WebSocket clients.
    """
    init_bridge(bridge)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("Headless beam viewer API starting up")
        # Wire dispatcher → WebSocket broadcast inside the lifespan so we
        # have a guaranteed reference to the running event loop.
        _cleanup = _wire_ws_broadcast(bridge, dispatcher)
        yield
        if _cleanup:
            _cleanup()
        log.info("Headless beam viewer API shutting down")

    app = FastAPI(
        title="PyBeamViewer API (headless)",
        version="1.0.0",
        description="Programmatic access to the PyBeamViewer beam profile viewer — headless mode.",
        lifespan=lifespan,
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
    app.include_router(beamspots.router)
    app.include_router(roi.router)
    app.include_router(centroid.router)
    app.include_router(display.router)
    app.include_router(overlays.router)
    app.include_router(trending.router)
    app.include_router(frames.router)
    app.include_router(config.router)

    # Health check
    @app.get("/health", tags=["System"])
    def health(bridge=Depends(get_bridge)):
        info = bridge.get_streaming_status()
        connected = info["connected"]
        streaming = info["streaming"]
        frame_count = info["frame_count"]

        if connected and streaming:
            status = "ok"
            reason = None
        elif not connected:
            status = "degraded"
            reason = "EPICS disconnected"
        else:
            status = "degraded"
            reason = "streaming paused"

        result = {
            "status": status,
            "connected": connected,
            "streaming": streaming,
            "frame_count": frame_count,
            "ws_clients": ws_manager.connection_count,
        }
        if reason is not None:
            result["reason"] = reason
        return result

    # Redirect root to the web panel UI
    @app.get("/")
    async def root_redirect():
        return RedirectResponse(url="/panel/")

    # Mount static files for the web frontend panel
    if _STATIC_DIR.is_dir():
        app.mount("/panel", StaticFiles(directory=str(_STATIC_DIR), html=True), name="panel")

    return app


def _wire_ws_broadcast(bridge: Any, dispatcher: Optional[Any]) -> Optional[callable]:
    """Connect dispatcher EVT_FRAME_READY → ws_manager.broadcast.

    Called inside the lifespan so asyncio.get_running_loop() returns
    uvicorn's event loop.  Returns a cleanup callable (or None).
    """
    if dispatcher is None:
        return None

    from beam_viewer.core.headless_controller import EVT_FRAME_READY

    loop = asyncio.get_running_loop()

    def _on_frame_ready(_frame_state) -> None:
        if loop.is_closed():
            return
        payload = bridge.build_ws_frame_payload()
        if payload is not None:
            asyncio.run_coroutine_threadsafe(ws_manager.broadcast(payload), loop)

    dispatcher.register(EVT_FRAME_READY, _on_frame_ready)

    def _cleanup():
        try:
            dispatcher.unregister(EVT_FRAME_READY, _on_frame_ready)
        except (ValueError, KeyError):
            pass

    return _cleanup
