"""Centroid and drift tracking schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CentroidReference(BaseModel):
    x: float
    y: float


class DriftData(BaseModel):
    has_reference: bool
    crosshair_enabled: bool
    reference: Optional[CentroidReference] = None
    live: Optional[CentroidReference] = None
    drift_x: Optional[float] = None
    drift_y: Optional[float] = None
    drift_x_um: Optional[float] = None
    drift_y_um: Optional[float] = None


class CrosshairSet(BaseModel):
    enabled: bool
