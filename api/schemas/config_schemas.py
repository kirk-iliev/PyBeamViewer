"""Configuration schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class CalibrationInfo(BaseModel):
    is_calibrated: bool
    um_per_pixel: float
    unit_label: str
    description: str


class PrefixInfo(BaseModel):
    name: str
    image_pv: str
    width_pv: str
    height_pv: str
    calibration: Optional[CalibrationInfo] = None


class ConfigOverview(BaseModel):
    active_prefix: str
    available_prefixes: list[str]
    epics: dict[str, Any]
    display: dict[str, Any]
