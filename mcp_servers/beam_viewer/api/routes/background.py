"""Background subtraction endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..headless_bridge import HeadlessBridge
from ..dependencies import get_bridge
from ..schemas.background import (
    BackgroundList,
    BackgroundLoadRequest,
    BackgroundStatus,
    BackgroundSubtractionSet,
)
from ..schemas.common import AckResponse

router = APIRouter(prefix="/background", tags=["Background"])


@router.get("", response_model=BackgroundStatus)
def get_background_status(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get background subtraction status."""
    return bridge.get_background_status()


@router.post("/acquire", response_model=AckResponse)
def acquire_background(bridge: HeadlessBridge = Depends(get_bridge)):
    """Capture the next incoming frame as the background reference."""
    bridge.acquire_background()
    return AckResponse(message="Background acquisition requested — will capture on next frame")


@router.post("/subtraction", response_model=AckResponse)
def set_subtraction(body: BackgroundSubtractionSet, bridge: HeadlessBridge = Depends(get_bridge)):
    """Enable or disable background subtraction."""
    status = bridge.get_background_status()
    if body.enabled and not status["has_background"]:
        raise HTTPException(
            status_code=400,
            detail="Cannot enable subtraction — no background frame acquired",
        )
    bridge.set_background_subtraction(body.enabled)
    action = "enabled" if body.enabled else "disabled"
    return AckResponse(message=f"Background subtraction {action}")


@router.post("/save", response_model=AckResponse)
def save_background(bridge: HeadlessBridge = Depends(get_bridge)):
    """Save the current in-memory background to a timestamped .npy file."""
    status = bridge.get_background_status()
    if not status["has_background"]:
        raise HTTPException(status_code=400, detail="No background to save")
    bridge.save_background()
    return AckResponse(message="Background saved")


@router.post("/load", response_model=AckResponse)
def load_background(body: BackgroundLoadRequest, bridge: HeadlessBridge = Depends(get_bridge)):
    """Load a previously saved background from a .npy file."""
    try:
        bridge.load_background(body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AckResponse(message="Loading background")


@router.get("/list", response_model=BackgroundList)
def list_backgrounds(bridge: HeadlessBridge = Depends(get_bridge)):
    """List all saved background files for the active camera prefix."""
    return {"backgrounds": bridge.list_backgrounds()}
