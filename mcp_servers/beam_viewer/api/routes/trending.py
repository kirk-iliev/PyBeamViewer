"""Trending panel endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..headless_bridge import HeadlessBridge
from ..dependencies import get_bridge
from ..schemas.common import AckResponse
from ..schemas.trending import TrendingConfig, TrendingDepthSet, TrendingHistory

router = APIRouter(prefix="/trending", tags=["Trending"])


@router.get("", response_model=TrendingConfig)
def get_trending_config(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get trending panel configuration."""
    return bridge.get_trending_config()


@router.post("/depth", response_model=AckResponse)
def set_trending_depth(body: TrendingDepthSet, bridge: HeadlessBridge = Depends(get_bridge)):
    """Set the trending history depth (number of frames)."""
    bridge.set_trending_depth(body.depth)
    return AckResponse(message=f"Trending depth set to {body.depth} frames")


@router.get("/history", response_model=TrendingHistory)
def get_trending_history(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get the trending history data."""
    return bridge.get_trending_history()
