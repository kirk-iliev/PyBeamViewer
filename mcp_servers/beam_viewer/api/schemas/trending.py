"""Trending panel schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TrendingConfig(BaseModel):
    visible: bool
    depth: int


class TrendingDepthSet(BaseModel):
    depth: int = Field(..., ge=50, le=2000, description="History depth in frames")


class TrendingHistory(BaseModel):
    count: int
    frame_number: list[float]
    sigma_x: list[float | None]
    sigma_y: list[float | None]
    centroid_x: list[float | None]
    centroid_y: list[float | None]
    roi_sigma_x: list[float | None]
    roi_sigma_y: list[float | None]
    drift_x: list[float | None]
    drift_y: list[float | None]
