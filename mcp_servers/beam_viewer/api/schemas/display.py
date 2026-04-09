"""Display settings schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

VALID_COLORMAPS = ["hot", "viridis", "inferno", "plasma", "magma", "cividis", "gray"]


class ColormapSet(BaseModel):
    name: str = Field(..., description="Colormap name")


class ThemeInfo(BaseModel):
    theme: str  # "dark" or "light"
