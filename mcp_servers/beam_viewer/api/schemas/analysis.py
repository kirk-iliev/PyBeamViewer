"""Analysis and fit result schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class FitResultSchema(BaseModel):
    success: bool
    sigma: Optional[float] = None
    sigma_um: Optional[float] = None
    centroid: Optional[float] = None
    centroid_um: Optional[float] = None
    amplitude: Optional[float] = None
    offset: Optional[float] = None
    residual: Optional[float] = None
    unit_label: str = "px"


class AnalysisStatus(BaseModel):
    fit_full_enabled: bool
    fit_roi_enabled: bool
    x_fit: Optional[FitResultSchema] = None
    y_fit: Optional[FitResultSchema] = None


class FitFullSet(BaseModel):
    enabled: bool


class FitRoiSet(BaseModel):
    enabled: bool
