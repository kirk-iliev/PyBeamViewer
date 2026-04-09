"""Frame data and projection schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class FrameMetadata(BaseModel):
    frame_number: int
    fps: float
    height: int
    width: int
    dtype: str


class ProjectionData(BaseModel):
    x_projection: list[float]
    y_projection: list[float]


class FrameData(BaseModel):
    metadata: FrameMetadata
    image_b64_png: str  # Base64-encoded PNG


class RoiFrameData(BaseModel):
    active: bool
    metadata: Optional[FrameMetadata] = None
    image_b64_png: Optional[str] = None
    projections: Optional[ProjectionData] = None
    fit: Optional[dict] = None
