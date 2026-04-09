"""Trending panel schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TrendingConfig(BaseModel):
    visible: bool
    depth: int


class TrendingDepthSet(BaseModel):
    depth: int = Field(..., ge=50, le=2000, description="History depth in frames")


class TrendingVisibleSet(BaseModel):
    visible: bool


class TrendingHistory(BaseModel):
    count: int
    frame_number: list[float]
    sigma_x: list[float]
    sigma_y: list[float]
    centroid_x: list[float]
    centroid_y: list[float]
    roi_sigma_x: list[float]
    roi_sigma_y: list[float]
    drift_x: list[float]
    drift_y: list[float]
