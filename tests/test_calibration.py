"""Tests for the calibration module."""

import math
import numpy as np
import pytest

from analysis.calibration import Calibration, calibration_from_config, _calibration_from_pinhole


# ---------------------------------------------------------------------------
# Calibration dataclass
# ---------------------------------------------------------------------------

class TestCalibration:
    def test_uncalibrated_default(self):
        cal = Calibration()
        assert cal.um_per_pixel == 1.0
        assert cal.unit_label == "px"
        assert not cal.is_calibrated
        # pixel_to_um should return the pixel value unchanged
        assert cal.pixel_to_um(5.0) == 5.0

    def test_fixed_calibration(self):
        cal = Calibration(um_per_pixel=1.8852, unit_label="µm", is_calibrated=True)
        assert cal.is_calibrated
        assert cal.unit_label == "µm"
        assert cal.pixel_to_um(10.0) == pytest.approx(18.852, rel=1e-4)


# ---------------------------------------------------------------------------
# Config-based factory
# ---------------------------------------------------------------------------

class TestCalibrationFromConfig:
    def test_none_config(self):
        cal = calibration_from_config(None)
        assert not cal.is_calibrated
        assert cal.um_per_pixel == 1.0

    def test_method_none(self):
        cal = calibration_from_config({"method": "none"})
        assert not cal.is_calibrated

    def test_fixed_method(self):
        cal = calibration_from_config({
            "method": "fixed",
            "pixel_size_um": 1.8852,
            "description": "BL31 test",
        })
        assert cal.is_calibrated
        assert cal.um_per_pixel == 1.8852
        assert cal.unit_label == "µm"
        assert "BL31" in cal.description

    def test_pinhole_method_matches_matlab(self):
        """Cross-check with the legacy MATLAB BL72 calculation.

        MATLAB code (beamviewer.m lines 576-581):
            dis_vec(at zoom 10000) = 274.7778 px for 1000 µm spacing
            um_per_px_image = 1000 / 274.7778
            um_per_px_image *= (6.08 + 2.04) / 6.08   (image-plane to phosor)
            um_per_px_source = um_per_px_image * 6.08 / 2.04  (phosor to source)

        The combined formula simplifies to:
            um_per_px = (1000 / 274.7778) * (6.08 + 2.04) / 2.04
        """
        cal = calibration_from_config({
            "method": "pinhole",
            "pinhole_spacing_um": 1000.0,
            "source_to_pinhole_mm": 6.08,
            "pinhole_to_sensor_mm": 2.04,
            "measured_pinhole_spacing_px": 274.7778,
            "description": "BL72 test",
        })
        assert cal.is_calibrated

        # Expected: (1000 / 274.7778) * (6.08 + 2.04) / 2.04
        expected_um_per_px = (1000.0 / 274.7778) * (6.08 + 2.04) / 2.04
        assert cal.um_per_pixel == pytest.approx(expected_um_per_px, rel=1e-6)

        # Sanity: should be roughly 14.5 µm/px at source
        assert 14.0 < cal.um_per_pixel < 15.0

    def test_pinhole_invalid_spacing(self):
        """Zero or negative pixel spacing should yield uncalibrated."""
        cal = calibration_from_config({
            "method": "pinhole",
            "pinhole_spacing_um": 1000.0,
            "source_to_pinhole_mm": 6.08,
            "pinhole_to_sensor_mm": 2.04,
            "measured_pinhole_spacing_px": 0.0,
        })
        assert not cal.is_calibrated

    def test_unknown_method(self):
        cal = calibration_from_config({"method": "unknown_method"})
        assert not cal.is_calibrated


# ---------------------------------------------------------------------------
# FitResult with calibration
# ---------------------------------------------------------------------------

class TestFitResultCalibration:
    def test_analyze_frame_with_calibration(self):
        """Full pipeline: generate a Gaussian frame, fit it, apply calibration."""
        from analysis.analysis import analyze_frame

        # Create a 100×100 frame with a Gaussian bump
        x = np.arange(100, dtype=np.float64)
        y = np.arange(100, dtype=np.float64)
        X, Y = np.meshgrid(x, y)
        sigma_px = 8.0
        frame = 1000.0 * np.exp(
            -0.5 * ((X - 50) ** 2 + (Y - 50) ** 2) / sigma_px ** 2
        )

        cal = Calibration(um_per_pixel=1.8852, unit_label="µm", is_calibrated=True)
        bp = analyze_frame(frame.astype(np.uint16), do_fit=True, calibration=cal)

        # X fit should succeed with calibrated values
        assert bp.x_fit is not None
        assert bp.x_fit.success
        assert bp.x_fit.sigma == pytest.approx(sigma_px, abs=1.0)
        assert bp.x_fit.sigma_um is not None
        assert bp.x_fit.sigma_um == pytest.approx(sigma_px * 1.8852, abs=2.0)
        assert bp.x_fit.unit_label == "µm"

    def test_analyze_frame_without_calibration(self):
        """Without calibration, sigma_um should be None."""
        from analysis.analysis import analyze_frame

        x = np.arange(100, dtype=np.float64)
        y = np.arange(100, dtype=np.float64)
        X, Y = np.meshgrid(x, y)
        frame = 1000.0 * np.exp(-0.5 * ((X - 50) ** 2 + (Y - 50) ** 2) / 64)

        bp = analyze_frame(frame.astype(np.uint16), do_fit=True)
        assert bp.x_fit is not None
        assert bp.x_fit.success
        assert bp.x_fit.sigma_um is None
        assert bp.x_fit.unit_label == "px"
