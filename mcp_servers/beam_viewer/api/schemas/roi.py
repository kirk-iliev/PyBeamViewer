"""ROI (Region of Interest) schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RoiSpec(BaseModel):
    x0: int = Field(..., ge=0, description="Left edge in pixels")
    y0: int = Field(..., ge=0, description="Top edge in pixels")
    x1: int = Field(..., ge=0, description="Right edge in pixels")
    y1: int = Field(..., ge=0, description="Bottom edge in pixels")


class RoiState(BaseModel):
    active: bool
    roi: Optional[RoiSpec] = None
