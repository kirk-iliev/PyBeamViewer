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


def _gauss1(x: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
    """MATLAB ``gauss1`` model: a · exp(−((x − b) / c)²).

    Relation to standard Gaussian: σ = |c| / √2.
    Used internally by :func:`fit_gaussian_1d` to match the MATLAB
    ``beam_fit_gaussian`` fitting convention exactly.
    """
    return a * np.exp(-((x - b) / c) ** 2)


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
# Gaussian fit
# ---------------------------------------------------------------------------

def fit_gaussian_1d(x_data: np.ndarray, y_data: np.ndarray) -> FitResult:
    """Fit a 1-D Gaussian to *x_data*, *y_data*.

    Mirrors the MATLAB ``beam_fit_gaussian`` pipeline exactly:

    1. **Fixed offset** — ``Offsethat = min(y)``, subtracted before fitting
       and *not* a free parameter.  This matches MATLAB's pre-subtraction
       convention rather than floating the baseline in the optimizer.
    2. **Quarter-max threshold** — only pixels where
       ``y_shifted > peak / 4`` are passed to the optimizer
       (``x_reduced = find(y > ymax/4)`` in MATLAB).  This restricts the
       fit to the Gaussian *core*, excluding scatter / diffraction tails
       that are not part of the true beam distribution.
    3. **3-parameter ``gauss1`` model** — ``a · exp(−((x−b)/c)²)`` fitted
       on the thresholded data only, matching MATLAB's ``fit(..., 'gauss1')``.
    4. **Sigma extraction** — ``σ = |c| / √2`` (MATLAB: ``f.c1/sqrt(2)``).
    5. **Full-range curve** — the fitted curve is evaluated over the
       *complete* x range with the fixed offset restored, for display.

    Returns a :class:`FitResult` with ``success=True`` on a good fit, or
    ``success=False`` with NaN-filled fields on failure.
    """
    try:
        x = np.asarray(x_data, dtype=np.float64).ravel()
        y = np.asarray(y_data, dtype=np.float64).ravel()

        if len(x) < 4 or len(y) < 4:
            raise ValueError("Not enough data points for Gaussian fit")

        # --- Step 1: fixed offset (MATLAB: Offsethat = min(y)) -------------
        offset = float(np.min(y))
        y_shifted = y - offset
        ymax = float(np.max(y_shifted))

        if ymax <= 0:
            raise ValueError("Flat signal — no feature to fit")

        # --- Step 2: quarter-max threshold ----------------------------------
        # MATLAB: x_reduced = find(y > ymax/4)
        mask = y_shifted > ymax / 4.0
        n_core = int(mask.sum())
        if n_core < 4:
            raise ValueError(
                f"Only {n_core} points above quarter-max threshold — "
                "signal too narrow or noisy"
            )

        x_core = x[mask]
        y_core = y_shifted[mask]

        # --- Initial parameter estimates (on core data) --------------------
        amp0 = ymax

        # Intensity-weighted centroid from core points
        total = float(np.sum(y_core))
        cen0 = (
            float(np.sum(x_core * y_core) / total)
            if total > 0
            else float(x_core[len(x_core) // 2])
        )

        # FWHM-based sigma from the full shifted signal (not just the core)
        half_max = ymax / 2.0
        above_half = np.where(y_shifted >= half_max)[0]
        if len(above_half) >= 2:
            fwhm = float(x[above_half[-1]] - x[above_half[0]])
            sig0 = fwhm / (2.0 * np.sqrt(2.0 * np.log(2.0)))
        else:
            sig0 = float((x_core[-1] - x_core[0]) / 2.0)
        if sig0 <= 0:
            sig0 = 1.0

        # Guard: sub-pixel sigma estimate → hot-pixel / δ-spike
        if sig0 < 1.0:
            raise ValueError(
                f"Estimated sigma ({sig0:.3f} px) is sub-pixel — "
                "likely a hot-pixel spike; skipping fit"
            )

        # Convert to gauss1 c parameter: c = σ · √2
        c0 = sig0 * np.sqrt(2.0)

        # --- Step 3: 3-parameter gauss1 fit on core data -------------------
        # MATLAB: f = fit(x(x_reduced), y(x_reduced), 'gauss1')
        popt, _ = curve_fit(
            _gauss1,
            x_core,
            y_core,
            p0=[amp0, cen0, c0],
            maxfev=2000,
        )
        a_fit, b_fit, c_fit = popt

        # --- Step 4: extract sigma (MATLAB: Sigmahat = f.c1/sqrt(2)) -------
        sigma = abs(c_fit) / np.sqrt(2.0)

        # --- Step 5: reconstruct full curve with offset restored -----------
        # MATLAB: yhat = f.a1 * exp(-((x-f.b1)/f.c1)^2) + Offsethat
        fitted = _gauss1(x, a_fit, b_fit, c_fit) + offset
        residual = float(np.sqrt(np.mean((y - fitted) ** 2)))

        return FitResult(
            sigma=sigma,
            centroid=b_fit,
            amplitude=a_fit,
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
