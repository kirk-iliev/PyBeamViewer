"""
analysis.py — Beam analysis and fitting functions.

Provides Gaussian fitting, projection computation, and beam-parameter
extraction.  Based on the MATLAB beamviewer's ``beam_fit_gaussian`` and
``updategraphics`` routines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from analysis.calibration import Calibration

import numpy as np
from scipy.optimize import curve_fit


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FitResult:
    """Result of a 1-D Gaussian fit.

    Raw pixel values (``sigma``, ``centroid``) are always present.
    Calibrated values (``sigma_um``, ``centroid_um``) are populated when
    a :class:`~analysis.calibration.Calibration` is applied.
    """
    sigma: float
    centroid: float
    amplitude: float
    offset: float
    fitted_curve: np.ndarray
    residual: float
    success: bool
    # Calibrated fields — None when uncalibrated
    sigma_um: Optional[float] = None
    centroid_um: Optional[float] = None
    unit_label: str = "px"


@dataclass(frozen=True)
class BeamParameters:
    """Complete analysis results for a single frame."""
    x_projection: np.ndarray
    y_projection: np.ndarray
    x_fit: Optional[FitResult] = None
    y_fit: Optional[FitResult] = None


# ---------------------------------------------------------------------------
# 1-D Gaussian model
# ---------------------------------------------------------------------------

def gaussian_1d(
    x: np.ndarray,
    amplitude: float,
    centroid: float,
    sigma: float,
    offset: float,
) -> np.ndarray:
    """Evaluate  A · exp(−(x − μ)² / 2σ²) + offset."""
    return amplitude * np.exp(-0.5 * ((x - centroid) / sigma) ** 2) + offset


# ---------------------------------------------------------------------------
# Initial-parameter estimation
# ---------------------------------------------------------------------------

def _estimate_gaussian_params(
    x: np.ndarray,
    y: np.ndarray,
) -> Tuple[float, float, float, float]:
    """Quick moment-based initial guesses: (amplitude, centroid, sigma, offset)."""
    offset = float(np.min(y))
    y_shifted = y - offset
    amplitude = float(np.max(y_shifted))
    if amplitude <= 0:
        amplitude = 1.0

    # Centre of mass → centroid
    total = np.sum(y_shifted)
    if total > 0:
        centroid = float(np.sum(x * y_shifted) / total)
    else:
        centroid = float(x[len(x) // 2])

    # FWHM → sigma
    half_max = amplitude / 2.0
    above_half = np.where(y_shifted >= half_max)[0]
    if len(above_half) >= 2:
        fwhm = float(x[above_half[-1]] - x[above_half[0]])
        sigma = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    else:
        sigma = float((x[-1] - x[0]) / 4.0)
    if sigma <= 0:
        sigma = 1.0

    return amplitude, centroid, sigma, offset


# ---------------------------------------------------------------------------
# Gaussian fit (mirrors MATLAB beam_fit_gaussian)
# ---------------------------------------------------------------------------

def fit_gaussian_1d(x_data: np.ndarray, y_data: np.ndarray) -> FitResult:
    """Fit a 1-D Gaussian to *x_data*, *y_data*.

    Returns a :class:`FitResult` with ``success=True`` on a good fit, or
    ``success=False`` with NaN-filled fields on failure.
    """
    try:
        x = np.asarray(x_data, dtype=np.float64).ravel()
        y = np.asarray(y_data, dtype=np.float64).ravel()

        if len(x) < 4 or len(y) < 4:
            raise ValueError("Not enough data points for Gaussian fit")

        amp0, cen0, sig0, off0 = _estimate_gaussian_params(x, y)

        # Guard: flat signal — nothing to fit.
        y_range = float(np.max(y) - np.min(y))
        if y_range == 0:
            raise ValueError("Flat signal — no feature to fit")

        # Guard: near-delta spike (hot pixel).  When the estimated sigma is
        # sub-pixel (< 1.0) the projection is essentially a δ-function;
        # curve_fit will spin through thousands of evaluations trying to
        # shrink sigma to zero against a hard lower bound and never converge
        # cleanly.  Bail out immediately in this case.
        if sig0 < 1.0:
            raise ValueError(
                f"Estimated sigma ({sig0:.3f} px) is sub-pixel — "
                "likely a hot-pixel spike; skipping fit"
            )

        x_range = float(x[-1] - x[0]) if len(x) > 1 else 1.0
        bounds = (
            [0.0, float(x[0]) - x_range, 1e-6, -np.inf],
            [np.inf, float(x[-1]) + x_range, x_range, np.inf],
        )

        popt, _ = curve_fit(
            gaussian_1d,
            x,
            y,
            p0=[amp0, cen0, sig0, off0],
            bounds=bounds,
            maxfev=2000,
        )

        amplitude, centroid, sigma, offset = popt
        fitted = gaussian_1d(x, *popt)
        residual = float(np.sqrt(np.mean((y - fitted) ** 2)))

        return FitResult(
            sigma=abs(sigma),
            centroid=centroid,
            amplitude=amplitude,
            offset=offset,
            fitted_curve=fitted,
            residual=residual,
            success=True,
        )

    except Exception:
        n = len(x_data) if hasattr(x_data, '__len__') else 0
        return FitResult(
            sigma=np.nan,
            centroid=np.nan,
            amplitude=np.nan,
            offset=np.nan,
            fitted_curve=np.full(n, np.nan, dtype=np.float64),
            residual=np.nan,
            success=False,
        )


# ---------------------------------------------------------------------------
# Projection helpers
# ---------------------------------------------------------------------------

def compute_projections(frame: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return (x_projection, y_projection) — mean along each axis.

    * x_projection: mean along rows   → 1-D array of length ``frame.shape[1]``
    * y_projection: mean along columns → 1-D array of length ``frame.shape[0]``
    """
    x_projection = np.mean(frame, axis=0)
    y_projection = np.mean(frame, axis=1)
    return x_projection, y_projection


# ---------------------------------------------------------------------------
# Full-frame analysis pipeline
# ---------------------------------------------------------------------------

def _apply_calibration(
    fit: FitResult,
    calibration: "Calibration",
) -> FitResult:
    """Return a new :class:`FitResult` with calibrated µm fields populated."""
    if not fit.success or not calibration.is_calibrated:
        return fit
    from dataclasses import replace
    return replace(
        fit,
        sigma_um=calibration.pixel_to_um(fit.sigma),
        centroid_um=calibration.pixel_to_um(fit.centroid),
        unit_label=calibration.unit_label,
    )


def analyze_frame(
    frame: np.ndarray,
    *,
    do_fit: bool = True,
    calibration: Optional["Calibration"] = None,
) -> BeamParameters:
    """Run the full analysis pipeline on a single frame.

    1. Compute X / Y projections
    2. Optionally fit each projection to a Gaussian
    3. If *calibration* is provided, apply µm conversion to fit results

    Returns a :class:`BeamParameters` snapshot.
    """
    x_proj, y_proj = compute_projections(frame)

    x_fit: Optional[FitResult] = None
    y_fit: Optional[FitResult] = None

    if do_fit:
        x_axis = np.arange(frame.shape[1], dtype=np.float64)
        y_axis = np.arange(frame.shape[0], dtype=np.float64)
        x_fit = fit_gaussian_1d(x_axis, x_proj)
        y_fit = fit_gaussian_1d(y_axis, y_proj)

        if calibration is not None:
            x_fit = _apply_calibration(x_fit, calibration)
            y_fit = _apply_calibration(y_fit, calibration)

    return BeamParameters(
        x_projection=x_proj,
        y_projection=y_proj,
        x_fit=x_fit,
        y_fit=y_fit,
    )
