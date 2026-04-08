"""Trending panel endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.bridge import ApiBridge
from api.dependencies import get_bridge
from api.schemas.common import AckResponse
from api.schemas.trending import TrendingConfig, TrendingDepthSet, TrendingHistory, TrendingVisibleSet

router = APIRouter(prefix="/trending", tags=["Trending"])


@router.get("", response_model=TrendingConfig)
def get_trending_config(bridge: ApiBridge = Depends(get_bridge)):
    """Get trending panel configuration."""
    return bridge.get_trending_config()


@router.post("/visible", response_model=AckResponse)
def set_trending_visible(body: TrendingVisibleSet, bridge: ApiBridge = Depends(get_bridge)):
    """Show or hide the trending panel."""
    bridge.set_trending_visible(body.visible)
    action = "shown" if body.visible else "hidden"
    return AckResponse(message=f"Trending panel {action}")


@router.post("/depth", response_model=AckResponse)
def set_trending_depth(body: TrendingDepthSet, bridge: ApiBridge = Depends(get_bridge)):
    """Set the trending history depth (number of frames)."""
    bridge.set_trending_depth(body.depth)
    return AckResponse(message=f"Trending depth set to {body.depth} frames")


@router.get("/history", response_model=TrendingHistory)
def get_trending_history(bridge: ApiBridge = Depends(get_bridge)):
    """Get the trending history data."""
    return bridge.get_trending_history()
