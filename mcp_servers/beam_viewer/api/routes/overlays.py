"""Projection overlay endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..headless_bridge import HeadlessBridge
from ..dependencies import get_bridge
from ..schemas.common import AckResponse
from ..schemas.overlays import OverlaySettings
from ..schemas.overlays import OverlayState as OverlayStateSchema

router = APIRouter(prefix="/overlays", tags=["Overlays"])


@router.get("", response_model=OverlayStateSchema)
def get_overlays(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get current projection overlay settings."""
    return bridge.get_overlay_settings()


@router.post("", response_model=AckResponse)
def set_overlays(body: OverlaySettings, bridge: HeadlessBridge = Depends(get_bridge)):
    """Update projection overlay settings (partial update supported)."""
    valid_sides_h = {"bottom", "top"}
    valid_sides_v = {"left", "right"}

    if body.h_side is not None and body.h_side not in valid_sides_h:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid h_side: {body.h_side!r}. Must be one of {valid_sides_h}",
        )
    if body.v_side is not None and body.v_side not in valid_sides_v:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid v_side: {body.v_side!r}. Must be one of {valid_sides_v}",
        )

    settings = body.model_dump(exclude_none=True)
    bridge.set_overlay_settings(settings)
    return AckResponse(message="Overlay settings updated")
