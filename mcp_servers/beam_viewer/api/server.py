"""FastAPI application factory for headless beam viewer.

Zero Qt imports.  The app is created via ``create_app(bridge)`` and can be
served directly by uvicorn.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(bridge: Any) -> FastAPI:
    """Build and return the FastAPI application with all routes registered.

    Parameters
    ----------
    bridge : HeadlessBridge
        The bridge instance connecting the API to the headless controller.
    """
    init_bridge(bridge)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("Headless beam viewer API starting up")
        yield
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
        status = bridge.get_streaming_status()
        return {
            "status": "ok",
            "streaming": status["streaming"],
            "connected": status["connected"],
            "frame_count": status["frame_count"],
            "ws_clients": ws_manager.connection_count,
        }

    # Mount static files for the web frontend panel
    if _STATIC_DIR.is_dir():
        app.mount("/panel", StaticFiles(directory=str(_STATIC_DIR), html=True), name="panel")

    return app
