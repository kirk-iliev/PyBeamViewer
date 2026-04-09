"""Display settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..headless_bridge import HeadlessBridge
from ..dependencies import get_bridge
from ..schemas.common import AckResponse
from ..schemas.display import ColormapSet, ThemeInfo, VALID_COLORMAPS

router = APIRouter(prefix="/display", tags=["Display"])


@router.get("/theme", response_model=ThemeInfo)
def get_theme(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get the current UI theme."""
    return {"theme": bridge.get_theme()}


@router.post("/theme/toggle", response_model=AckResponse)
def toggle_theme(bridge: HeadlessBridge = Depends(get_bridge)):
    """Toggle between dark and light mode."""
    bridge.toggle_theme()
    return AckResponse(message="Theme toggled")


@router.get("/colormap")
def get_colormap(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get the current colormap name and available options."""
    return {
        "current": bridge.get_colormap(),
        "available": VALID_COLORMAPS,
    }


@router.post("/colormap", response_model=AckResponse)
def set_colormap(body: ColormapSet, bridge: HeadlessBridge = Depends(get_bridge)):
    """Set the image colormap."""
    try:
        bridge.set_colormap(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AckResponse(message=f"Colormap set to {body.name!r}")
