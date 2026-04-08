"""Camera-related Pydantic schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CameraInfo(BaseModel):
    active_prefix: str
    host: str
    port: int
    image_pv: str
    width_pv: str
    height_pv: str
    exposure_pv: str
    exposure_rbv_pv: str
    gain_pv: str
    gain_rbv_pv: str
    fallback_shape: Optional[list[int]] = None


class ExposureSet(BaseModel):
    value: float = Field(..., gt=0, le=30.0, description="Exposure time in seconds")


class GainSet(BaseModel):
    value: int = Field(..., ge=0, le=40, description="Gain value")


class PrefixSelect(BaseModel):
    prefix: str = Field(..., description="Camera PV prefix (e.g. 'BL31', 'BL72')")
