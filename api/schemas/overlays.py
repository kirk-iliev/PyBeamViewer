"""Projection overlay schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class OverlaySettings(BaseModel):
    h_enabled: Optional[bool] = None
    h_side: Optional[str] = None  # "bottom" | "top"
    v_enabled: Optional[bool] = None
    v_side: Optional[str] = None  # "left" | "right"
    scale: Optional[float] = Field(None, ge=0.05, le=0.50)
    show_full: Optional[bool] = None
    show_roi: Optional[bool] = None


class OverlayState(BaseModel):
    h_enabled: bool
    h_side: str
    v_enabled: bool
    v_side: str
    scale: float
    show_full: bool
    show_roi: bool
