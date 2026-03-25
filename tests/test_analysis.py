"""Tests for analysis.analysis — Gaussian fitting, projections, and pipeline."""

from __future__ import annotations

import math

import numpy as np
import pytest

from analysis.analysis import (
    BeamParameters,
    FitResult,
    _apply_calibration,
    _estimate_gaussian_params,
    _gauss1,
    analyze_frame,
    compute_projections,
    fit_gaussian_1d,
    gaussian_1d,
)
from analysis.calibration import Calibration


# ===================================================================
# gaussian_1d
# ===================================================================

class TestGaussian1D:
    """Tests for the standard 4-parameter Gaussian model."""

    def test_peak_at_centroid(self):
        x = np.array([5.0])
        val = gaussian_1d(x, amplitude=10.0, centroid=5.0, sigma=2.0, offset=3.0)
        assert val[0] == pytest.approx(13.0)  # amp + offset

    def test_symmetry(self):
        x = np.array([3.0, 7.0])
        vals = gaussian_1d(x, amplitude=10.0, centroid=5.0, sigma=2.0, offset=0.0)
        assert vals[0] == pytest.approx(vals[1])

    def test_offset(self):
        """Offset shifts the entire curve up."""
        x = np.linspace(0, 10, 50)
        y0 = gaussian_1d(x, 10.0, 5.0, 2.0, 0.0)
        y5 = gaussian_1d(x, 10.0, 5.0, 2.0, 5.0)
        np.testing.assert_allclose(y5 - y0, 5.0)

    def test_fwhm(self):
        """FWHM should be ≈ 2.3548 * sigma."""
        sigma = 3.0
        x = np.linspace(-20, 20, 10000)
        y = gaussian_1d(x, amplitude=1.0, centroid=0.0, sigma=sigma, offset=0.0)
        half_max = 0.5
        above = x[y >= half_max]
        fwhm = above[-1] - above[0]
        expected = 2.0 * math.sqrt(2.0 * math.log(2.0)) * sigma
        assert fwhm == pytest.approx(expected, rel=1e-3)


# ===================================================================
# _gauss1 (MATLAB convention)
# ===================================================================

class TestGauss1:
    """Tests for the 3-parameter MATLAB-style Gaussian model."""

    def test_peak_value(self):
        x = np.array([5.0])
        val = _gauss1(x, a=10.0, b=5.0, c=3.0)
        assert val[0] == pytest.approx(10.0)

    def test_sigma_relationship(self):
        """σ = |c| / √2.  At x = b ± σ, value should be a * exp(-0.5)."""
        a, b, c = 10.0, 5.0, 4.0
        sigma = abs(c) / math.sqrt(2.0)
        x = np.array([b + sigma])
        val = _gauss1(x, a, b, c)
        assert val[0] == pytest.approx(a * math.exp(-0.5), rel=1e-10)

    def test_symmetry(self):
        x = np.array([2.0, 8.0])
        vals = _gauss1(x, 10.0, 5.0, 3.0)
        assert vals[0] == pytest.approx(vals[1])


# ===================================================================
# _estimate_gaussian_params
# ===================================================================

class TestEstimateGaussianParams:
    """Tests for moment-based initial parameter estimation."""

    def test_clean_gaussian(self):
        sigma = 10.0
        x = np.arange(200, dtype=np.float64)
        y = 1000.0 * np.exp(-0.5 * ((x - 100.0) / sigma) ** 2) + 50.0
        amp, cen, sig, off = _estimate_gaussian_params(x, y)

        assert amp == pytest.approx(1000.0, rel=0.01)
        assert cen == pytest.approx(100.0, abs=2.0)
        assert sig == pytest.approx(sigma, rel=0.15)
        assert off == pytest.approx(50.0, abs=1.0)

    def test_flat_signal(self):
        """Flat signal should still return something (not crash)."""
        x = np.arange(100, dtype=np.float64)
        y = np.full(100, 10.0)
        amp, cen, sig, off = _estimate_gaussian_params(x, y)
        # amplitude should fallback to 1.0 since max(y_shifted) == 0
        assert amp == 1.0

    def test_narrow_peak(self):
        """Very narrow peak: estimator should still find the centroid."""
        x = np.arange(200, dtype=np.float64)
        y = np.zeros(200)
        y[100] = 1000.0
        amp, cen, sig, off = _estimate_gaussian_params(x, y)
        assert cen == pytest.approx(100.0, abs=1.0)
        assert sig > 0  # must be positive


# ===================================================================
# fit_gaussian_1d
# ===================================================================

class TestFitGaussian1D:
    """Tests for the 1-D Gaussian fitter."""

    def test_recovers_known_sigma(self):
        """Fit should recover σ within ~0.5 px on clean data."""
        true_sigma = 12.0
        x = np.arange(200, dtype=np.float64)
        y = 5000.0 * np.exp(-0.5 * ((x - 100.0) / true_sigma) ** 2) + 200.0
        result = fit_gaussian_1d(x, y)

        assert result.success
        assert result.sigma == pytest.approx(true_sigma, abs=0.5)
        assert result.centroid == pytest.approx(100.0, abs=0.5)

    def test_recovers_known_centroid(self):
        """Centroid recovery at a non-center position."""
        true_cen = 75.0
        x = np.arange(200, dtype=np.float64)
        y = 3000.0 * np.exp(-0.5 * ((x - true_cen) / 10.0) ** 2) + 100.0
        result = fit_gaussian_1d(x, y)

        assert result.success
        assert result.centroid == pytest.approx(true_cen, abs=0.5)

    def test_fitted_curve_length(self):
        """fitted_curve should have the same length as the input."""
        x = np.arange(150, dtype=np.float64)
        y = 1000.0 * np.exp(-0.5 * ((x - 75.0) / 8.0) ** 2) + 50.0
        result = fit_gaussian_1d(x, y)
        assert result.success
        assert len(result.fitted_curve) == len(x)

    def test_residual_is_small_on_clean(self):
        """Residual (RMSE) should be near zero on clean data."""
        x = np.arange(200, dtype=np.float64)
        y = 2000.0 * np.exp(-0.5 * ((x - 100.0) / 15.0) ** 2) + 100.0
        result = fit_gaussian_1d(x, y)
        assert result.success
        assert result.residual < 5.0  # effectively zero for clean data

    def test_flat_signal_fails(self):
        """A completely flat signal has no feature to fit."""
        x = np.arange(100, dtype=np.float64)
        y = np.full(100, 42.0)
        result = fit_gaussian_1d(x, y)
        assert not result.success
        assert np.isnan(result.sigma)

    def test_too_few_points_fails(self):
        """Fewer than 4 data points should fail gracefully."""
        x = np.array([1.0, 2.0, 3.0])
        y = np.array([10.0, 20.0, 10.0])
        result = fit_gaussian_1d(x, y)
        assert not result.success

    def test_single_hot_pixel_fails(self):
        """A single hot pixel (sub-pixel sigma) should be caught."""
        x = np.arange(200, dtype=np.float64)
        y = np.full(200, 100.0)
        y[100] = 10000.0
        result = fit_gaussian_1d(x, y)
        assert not result.success

    def test_noisy_data_still_converges(self):
        """Fit should still converge on moderately noisy data."""
        rng = np.random.default_rng(123)
        true_sigma = 15.0
        x = np.arange(300, dtype=np.float64)
        y_clean = 4000.0 * np.exp(-0.5 * ((x - 150.0) / true_sigma) ** 2) + 300.0
        y = y_clean + rng.normal(0, 50, size=len(x))
        result = fit_gaussian_1d(x, y)

        assert result.success
        assert result.sigma == pytest.approx(true_sigma, abs=2.0)

    def test_negative_c_gives_positive_sigma(self):
        """σ = |c|/√2, so even a negative c should produce positive sigma."""
        # Indirect: we just verify sigma is always positive on any successful fit.
        x = np.arange(200, dtype=np.float64)
        y = 3000.0 * np.exp(-0.5 * ((x - 100.0) / 10.0) ** 2) + 50.0
        result = fit_gaussian_1d(x, y)
        assert result.success
        assert result.sigma > 0


# ===================================================================
# compute_projections
# ===================================================================

class TestComputeProjections:
    """Tests for the projection (mean along axis) helper."""

    def test_shapes(self, gaussian_frame):
        x_proj, y_proj = compute_projections(gaussian_frame)
        rows, cols = gaussian_frame.shape
        assert x_proj.shape == (cols,)
        assert y_proj.shape == (rows,)

    def test_uniform_frame(self):
        """Projections of a uniform frame should all be the same value."""
        frame = np.full((50, 80), 42.0, dtype=np.float64)
        x_proj, y_proj = compute_projections(frame)
        np.testing.assert_allclose(x_proj, 42.0)
        np.testing.assert_allclose(y_proj, 42.0)

    def test_row_vector(self):
        """A single-row frame: x_proj = that row, y_proj = mean of row."""
        row = np.array([[10.0, 20.0, 30.0]])
        x_proj, y_proj = compute_projections(row)
        np.testing.assert_allclose(x_proj, [10.0, 20.0, 30.0])
        np.testing.assert_allclose(y_proj, [20.0])

    def test_column_vector(self):
        """A single-column frame: y_proj = that column, x_proj = mean of column."""
        col = np.array([[10.0], [20.0], [30.0]])
        x_proj, y_proj = compute_projections(col)
        np.testing.assert_allclose(x_proj, [20.0])
        np.testing.assert_allclose(y_proj, [10.0, 20.0, 30.0])

    def test_projection_peak_near_center(self, gaussian_frame):
        """For a centered Gaussian, projection peaks should be near center."""
        x_proj, y_proj = compute_projections(gaussian_frame)
        assert np.argmax(x_proj) == pytest.approx(100, abs=2)
        assert np.argmax(y_proj) == pytest.approx(100, abs=2)


# ===================================================================
# _apply_calibration
# ===================================================================

class TestApplyCalibration:
    """Tests for calibration application to FitResult."""

    def _make_fit(self, success: bool = True) -> FitResult:
        return FitResult(
            sigma=10.0,
            centroid=100.0,
            amplitude=5000.0,
            offset=100.0,
            fitted_curve=np.zeros(200),
            residual=1.0,
            success=success,
        )

    def test_calibrated(self, calibrated):
        fit = self._make_fit()
        result = _apply_calibration(fit, calibrated)
        assert result.sigma_um == pytest.approx(10.0 * 1.8852, rel=1e-4)
        assert result.centroid_um == pytest.approx(100.0 * 1.8852, rel=1e-4)
        assert result.unit_label == "µm"

    def test_uncalibrated_noop(self, uncalibrated):
        fit = self._make_fit()
        result = _apply_calibration(fit, uncalibrated)
        assert result.sigma_um is None
        assert result.unit_label == "px"

    def test_failed_fit_noop(self, calibrated):
        fit = self._make_fit(success=False)
        result = _apply_calibration(fit, calibrated)
        assert result.sigma_um is None


# ===================================================================
# analyze_frame (full pipeline)
# ===================================================================

class TestAnalyzeFrame:
    """Integration tests for the full analysis pipeline."""

    def test_fit_succeeds_on_gaussian(self, gaussian_frame):
        bp = analyze_frame(gaussian_frame, do_fit=True)
        assert isinstance(bp, BeamParameters)
        assert bp.x_fit is not None and bp.x_fit.success
        assert bp.y_fit is not None and bp.y_fit.success
        # Known sigma ≈ 12 px
        assert bp.x_fit.sigma == pytest.approx(12.0, abs=1.5)
        assert bp.y_fit.sigma == pytest.approx(12.0, abs=1.5)

    def test_do_fit_false(self, gaussian_frame):
        bp = analyze_frame(gaussian_frame, do_fit=False)
        assert bp.x_fit is None
        assert bp.y_fit is None
        assert len(bp.x_projection) == gaussian_frame.shape[1]

    def test_calibration_applied(self, gaussian_frame, calibrated):
        bp = analyze_frame(gaussian_frame, do_fit=True, calibration=calibrated)
        assert bp.x_fit.sigma_um is not None
        assert bp.x_fit.unit_label == "µm"

    def test_no_calibration_leaves_none(self, gaussian_frame):
        bp = analyze_frame(gaussian_frame, do_fit=True)
        assert bp.x_fit.sigma_um is None
        assert bp.x_fit.unit_label == "px"

    def test_roi_offset_shifts_centroid(self, gaussian_frame):
        """x_offset/y_offset should shift the centroid by the offset amount."""
        bp_no_offset = analyze_frame(gaussian_frame, do_fit=True, x_offset=0, y_offset=0)
        bp_offset = analyze_frame(gaussian_frame, do_fit=True, x_offset=50, y_offset=30)

        assert bp_offset.x_fit.centroid == pytest.approx(
            bp_no_offset.x_fit.centroid + 50, abs=1.0
        )
        assert bp_offset.y_fit.centroid == pytest.approx(
            bp_no_offset.y_fit.centroid + 30, abs=1.0
        )

    def test_flat_frame_fit_fails(self, flat_frame):
        bp = analyze_frame(flat_frame, do_fit=True)
        assert bp.x_fit is not None
        assert not bp.x_fit.success

    def test_projections_always_present(self, gaussian_frame):
        """Projections should be populated regardless of do_fit."""
        bp = analyze_frame(gaussian_frame, do_fit=False)
        assert bp.x_projection is not None
        assert bp.y_projection is not None
        assert len(bp.x_projection) == gaussian_frame.shape[1]
        assert len(bp.y_projection) == gaussian_frame.shape[0]
