"""Streaming control endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..headless_bridge import HeadlessBridge
from ..dependencies import get_bridge
from ..schemas.common import AckResponse
from ..schemas.streaming import StreamingSet, StreamingStatus

router = APIRouter(prefix="/streaming", tags=["Streaming"])


@router.get("", response_model=StreamingStatus)
def get_streaming_status(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get current streaming status."""
    return bridge.get_streaming_status()


@router.post("", response_model=AckResponse)
def set_streaming(body: StreamingSet, bridge: HeadlessBridge = Depends(get_bridge)):
    """Start or pause frame streaming."""
    bridge.set_streaming(body.streaming)
    action = "resumed" if body.streaming else "paused"
    return AckResponse(message=f"Streaming {action}")
