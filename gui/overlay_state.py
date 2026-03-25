"""Projection overlay state dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverlayState:
    """Settings for projection overlays drawn on top of the image."""
    h_enabled: bool = False
    h_side: str = "bottom"    # "bottom" | "top"
    v_enabled: bool = False
    v_side: str = "left"      # "left" | "right"
    scale: float = 0.25       # 0.0 – 0.5, fraction of image dimension
    show_full: bool = True    # show overlays on the full-image pane
    show_roi: bool = True     # show overlays on the ROI pane

    def to_dict(self) -> dict:
        return {
            "h_enabled": self.h_enabled,
            "h_side": self.h_side,
            "v_enabled": self.v_enabled,
            "v_side": self.v_side,
            "scale": self.scale,
            "show_full": self.show_full,
            "show_roi": self.show_roi,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OverlayState":
        return cls(
            h_enabled=d.get("h_enabled", False),
            h_side=d.get("h_side", "bottom"),
            v_enabled=d.get("v_enabled", False),
            v_side=d.get("v_side", "left"),
            scale=d.get("scale", 0.25),
            show_full=d.get("show_full", True),
            show_roi=d.get("show_roi", True),
        )
