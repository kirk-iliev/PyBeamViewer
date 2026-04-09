"""Frame data endpoints and WebSocket streaming."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ..headless_bridge import HeadlessBridge
from ..dependencies import get_bridge
from ..schemas.frames import FrameData, FrameMetadata, ProjectionData, RoiFrameData
from ..ws_manager import ws_manager

log = logging.getLogger(__name__)

router = APIRouter(prefix="/frames", tags=["Frames"])


@router.get("/metadata", response_model=FrameMetadata)
def get_frame_metadata(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get metadata for the current frame (number, FPS, dimensions)."""
    return bridge.get_frame_metadata()


@router.get("/current", response_model=FrameData)
def get_current_frame(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get the current frame as a base64-encoded PNG with metadata."""
    metadata = bridge.get_frame_metadata()
    image_b64 = bridge.get_frame_png_b64()
    return {"metadata": metadata, "image_b64_png": image_b64}


@router.get("/projections", response_model=ProjectionData)
def get_projections(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get the current full-image X and Y projections."""
    return bridge.get_projections()


@router.get("/roi", response_model=RoiFrameData)
def get_roi_frame(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get the ROI crop frame data including image and projections."""
    return bridge.get_roi_frame_data()


@router.websocket("/ws/stream")
async def stream_frames(websocket: WebSocket, bridge: HeadlessBridge = Depends(get_bridge)):
    """WebSocket endpoint for real-time frame streaming.

    Pushes complete frame payloads (image, analysis, ROI, drift) to
    connected clients whenever a new frame is processed.
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep the connection alive; handle client messages (ping/config)
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Client can send "ping" to keep alive
                if msg == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Send keepalive
                try:
                    await websocket.send_json({"type": "keepalive"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.debug("WebSocket error: %s", exc)
    finally:
        await ws_manager.disconnect(websocket)
