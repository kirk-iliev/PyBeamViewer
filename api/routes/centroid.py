"""Centroid reference and drift tracking endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.bridge import ApiBridge
from api.dependencies import get_bridge
from api.schemas.centroid import CrosshairSet, DriftData
from api.schemas.common import AckResponse

router = APIRouter(prefix="/centroid", tags=["Centroid"])


@router.get("", response_model=DriftData)
def get_drift(bridge: ApiBridge = Depends(get_bridge)):
    """Get centroid reference, live position, and drift values."""
    return bridge.get_drift()


@router.post("/crosshair", response_model=AckResponse)
def set_crosshair(body: CrosshairSet, bridge: ApiBridge = Depends(get_bridge)):
    """Enable or disable the centroid crosshair overlay."""
    bridge.set_crosshair(body.enabled)
    action = "enabled" if body.enabled else "disabled"
    return AckResponse(message=f"Centroid crosshair {action}")
