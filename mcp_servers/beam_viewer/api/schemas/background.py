"""Background subtraction schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BackgroundStatus(BaseModel):
    has_background: bool
    subtraction_enabled: bool


class BackgroundSubtractionSet(BaseModel):
    enabled: bool


class BackgroundLoadRequest(BaseModel):
    path: str = Field(..., description="Path to a saved .npy background file")


class SavedBackground(BaseModel):
    filename: str
    path: str


class BackgroundList(BaseModel):
    backgrounds: list[SavedBackground]
