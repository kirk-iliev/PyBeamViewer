"""
calibration.py — Pixel-to-physical-units calibration.

Converts beam fit results (sigma, centroid) from pixel units to microns (µm)
at the source point, using the physics of the pinhole camera setup.

Calibration methods
-------------------
- ``"fixed"``   — a single µm/pixel factor (e.g. BL31 after physical alignment)
- ``"pinhole"`` — derived from known pinhole spacing, measured pixel spacing,
  and the imaging geometry (source→pinhole and pinhole→sensor distances)
- ``"none"``    — no calibration; values stay in pixel units

The pinhole formula is::

    µm_per_pixel_image  = pinhole_spacing_µm / measured_pinhole_spacing_px
    µm_per_pixel_source = µm_per_pixel_image × (d_source + d_sensor) / d_sensor

where *d_source* is the source-to-pinhole distance and *d_sensor* is the
pinhole-to-sensor distance (the ``(6.08 + 2.04) / 2.04`` factor seen in the
legacy MATLAB code for BL72).

Usage::

    cal = load_calibration("BL72")
    sigma_um = cal.pixel_to_um(sigma_px)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Calibration data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Calibration:
    """Immutable calibration for one camera axis (or both, if isotropic).

    Attributes
    ----------
    um_per_pixel : float
        Conversion factor at the source point.  ``1.0`` when uncalibrated.
    unit_label : str
        ``"µm"`` when calibrated, ``"px"`` otherwise.
    is_calibrated : bool
        Whether a real calibration is active.
    description : str
        Human-readable provenance note.
    """
    um_per_pixel: float = 1.0
    unit_label: str = "px"
    is_calibrated: bool = False
    description: str = "No calibration configured"

    def pixel_to_um(self, px_value: float) -> float:
        """Convert a value in pixels to calibrated units (µm or raw px)."""
        return px_value * self.um_per_pixel


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _calibration_from_fixed(cfg: Dict[str, Any]) -> Calibration:
    """Build a :class:`Calibration` from a ``"fixed"`` config block."""
    um_per_px = float(cfg["pixel_size_um"])
    desc = cfg.get("description", "Fixed calibration")
    return Calibration(
        um_per_pixel=um_per_px,
        unit_label="µm",
        is_calibrated=True,
        description=desc,
    )


def _calibration_from_pinhole(cfg: Dict[str, Any]) -> Calibration:
    """Build a :class:`Calibration` from a ``"pinhole"`` config block.

    Uses the pinhole camera geometry to convert from image-plane pixels
    to source-point µm.
    """
    spacing_um: float = float(cfg["pinhole_spacing_um"])
    spacing_px: float = float(cfg["measured_pinhole_spacing_px"])
    d_source: float = float(cfg["source_to_pinhole_mm"])
    d_sensor: float = float(cfg["pinhole_to_sensor_mm"])
    desc: str = cfg.get("description", "Pinhole calibration")

    if spacing_px <= 0 or d_sensor <= 0:
        return Calibration(description="Invalid pinhole calibration parameters")

    um_per_px_image = spacing_um / spacing_px
    magnification = (d_source + d_sensor) / d_sensor
    um_per_px_source = um_per_px_image * magnification

    return Calibration(
        um_per_pixel=um_per_px_source,
        unit_label="µm",
        is_calibrated=True,
        description=desc,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calibration_from_config(cal_cfg: Optional[Dict[str, Any]]) -> Calibration:
    """Create a :class:`Calibration` from a config dict (or ``None``).

    Called by :func:`load_calibration` — but can also be used directly for
    testing.
    """
    if cal_cfg is None:
        return Calibration()

    method = cal_cfg.get("method", "none").lower()
    if method == "fixed":
        return _calibration_from_fixed(cal_cfg)
    elif method == "pinhole":
        return _calibration_from_pinhole(cal_cfg)
    else:
        return Calibration()


def load_calibration(prefix: Optional[str] = None) -> Calibration:
    """Load the calibration for *prefix* from ``config.json``.

    Falls back gracefully to an uncalibrated identity if the prefix lacks a
    ``"calibration"`` block.
    """
    from config.config import get_pv_names
    pv_entry = get_pv_names(prefix)
    cal_cfg = pv_entry.get("calibration")
    return calibration_from_config(cal_cfg)
