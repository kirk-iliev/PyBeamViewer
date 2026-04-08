"""ROI (Region of Interest) endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.bridge import ApiBridge
from api.dependencies import get_bridge
from api.schemas.common import AckResponse
from api.schemas.roi import RoiSpec, RoiState

router = APIRouter(prefix="/roi", tags=["ROI"])


@router.get("", response_model=RoiState)
def get_roi(bridge: ApiBridge = Depends(get_bridge)):
    """Get the current ROI selection."""
    return bridge.get_roi()


@router.post("", response_model=AckResponse)
def set_roi(body: RoiSpec, bridge: ApiBridge = Depends(get_bridge)):
    """Set the ROI rectangle (x0, y0, x1, y1) in pixel coordinates."""
    if body.x1 <= body.x0 or body.y1 <= body.y0:
        raise HTTPException(
            status_code=400,
            detail="Invalid ROI: x1 must be > x0 and y1 must be > y0",
        )
    bridge.set_roi(body.x0, body.y0, body.x1, body.y1)
    return AckResponse(
        message=f"ROI set to ({body.x0}, {body.y0}) - ({body.x1}, {body.y1})"
    )


@router.delete("", response_model=AckResponse)
def clear_roi(bridge: ApiBridge = Depends(get_bridge)):
    """Clear the current ROI selection."""
    bridge.clear_roi()
    return AckResponse(message="ROI cleared")


@router.post("/center", response_model=AckResponse)
def center_roi(bridge: ApiBridge = Depends(get_bridge)):
    """Re-center the ROI as a square around the intensity centroid."""
    roi = bridge.get_roi()
    if not roi["active"]:
        raise HTTPException(status_code=400, detail="No active ROI to center")
    bridge.center_roi()
    return AckResponse(message="ROI centered on intensity centroid")
