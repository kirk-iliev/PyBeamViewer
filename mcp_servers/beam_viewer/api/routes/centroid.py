"""Centroid reference and drift tracking endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..headless_bridge import HeadlessBridge
from ..dependencies import get_bridge
from ..schemas.centroid import CentroidReferenceSet, CrosshairSet, DriftData
from ..schemas.common import AckResponse

router = APIRouter(prefix="/centroid", tags=["Centroid"])


@router.get("", response_model=DriftData)
def get_drift(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get centroid reference, live position, and drift values."""
    return bridge.get_drift()


@router.post("/crosshair", response_model=AckResponse)
def set_crosshair(body: CrosshairSet, bridge: HeadlessBridge = Depends(get_bridge)):
    """Enable or disable the centroid crosshair overlay."""
    bridge.set_crosshair(body.enabled)
    action = "enabled" if body.enabled else "disabled"
    return AckResponse(message=f"Centroid crosshair {action}")


@router.post("/reference", response_model=AckResponse)
def set_centroid_reference(
    body: CentroidReferenceSet,
    bridge: HeadlessBridge = Depends(get_bridge),
):
    """Set the centroid reference to a fixed full-frame pixel coordinate.

    Drift values returned by ``GET /centroid`` are computed as
    ``live - reference`` once the reference is set.
    """
    bridge.set_centroid_reference(body.x, body.y)
    return AckResponse(
        message=f"Centroid reference set to ({body.x:.2f}, {body.y:.2f})"
    )


@router.delete("/reference", response_model=AckResponse)
def clear_centroid_reference(bridge: HeadlessBridge = Depends(get_bridge)):
    """Clear the centroid reference for the active camera."""
    bridge.clear_centroid_reference()
    return AckResponse(message="Centroid reference cleared")
