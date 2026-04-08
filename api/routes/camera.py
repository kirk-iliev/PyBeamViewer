"""Camera setup endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.bridge import ApiBridge
from api.dependencies import get_bridge
from api.schemas.camera import CameraInfo, ExposureSet, GainSet, PrefixSelect
from api.schemas.common import AckResponse

router = APIRouter(prefix="/camera", tags=["Camera"])


@router.get("", response_model=CameraInfo)
def get_camera_info(bridge: ApiBridge = Depends(get_bridge)):
    """Get current camera configuration and PV names."""
    return bridge.get_camera_info()


@router.post("/prefix", response_model=AckResponse)
def select_prefix(body: PrefixSelect, bridge: ApiBridge = Depends(get_bridge)):
    """Switch to a different camera PV prefix."""
    try:
        bridge.select_prefix(body.prefix)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AckResponse(message=f"Switching to prefix {body.prefix!r}")


@router.post("/exposure", response_model=AckResponse)
def set_exposure(body: ExposureSet, bridge: ApiBridge = Depends(get_bridge)):
    """Set the camera exposure time (seconds)."""
    bridge.set_exposure(body.value)
    return AckResponse(message=f"Exposure set to {body.value}s")


@router.post("/gain", response_model=AckResponse)
def set_gain(body: GainSet, bridge: ApiBridge = Depends(get_bridge)):
    """Set the camera gain."""
    bridge.set_gain(body.value)
    return AckResponse(message=f"Gain set to {body.value}")
