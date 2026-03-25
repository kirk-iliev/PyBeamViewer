"""Integration tests — real config.json, real analysis pipeline.

Unlike unit tests (which mock config functions), these tests use the
actual config/config.json file on disk and run the full analysis pipeline
end-to-end with synthetic frames.  They verify that the real deployment
configuration is structurally valid and that the complete data path
(config → calibration → analysis → FitResult) works correctly.

Tests are marked ``integration`` — run them with:
    pytest tests/test_integration.py -v
or alongside the full suite:
    pytest tests/ -v
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.json"


def _require_real_config():
    """Skip the test if config.json doesn't exist (e.g., CI without it)."""
    if not _CONFIG_PATH.exists():
        pytest.skip(f"config.json not found at {_CONFIG_PATH}")


def _gaussian_frame(
    shape=(200, 200),
    center=(100, 100),
    sigma=15.0,
    amplitude=5000.0,
    offset=100.0,
) -> np.ndarray:
    rows, cols = shape
    y = np.arange(rows, dtype=np.float64)
    x = np.arange(cols, dtype=np.float64)
    X, Y = np.meshgrid(x, y)
    cx, cy = center
    frame = amplitude * np.exp(
        -0.5 * ((X - cx) ** 2 + (Y - cy) ** 2) / sigma ** 2
    ) + offset
    return frame.astype(np.uint16)


# ---------------------------------------------------------------------------
# Real config loading
# ---------------------------------------------------------------------------

class TestRealConfigLoading:
    """Tests that operate directly on the project's real config.json."""

    def test_config_file_exists(self):
        _require_real_config()
        assert _CONFIG_PATH.exists()

    def test_load_config_succeeds(self):
        _require_real_config()
        from config.config import load_config
        config = load_config()
        assert isinstance(config, dict)

    def test_active_prefix_is_valid(self):
        _require_real_config()
        from config.config import load_config, get_available_prefixes, get_active_prefix
        config = load_config()
        prefixes = get_available_prefixes()
        active = get_active_prefix()
        assert active in prefixes, (
            f"active_prefix {active!r} is not in pv_prefixes {prefixes}"
        )

    def test_all_prefixes_have_required_pv_keys(self):
        _require_real_config()
        from config.config import load_config
        config = load_config()
        required = {"image_pv", "width_pv", "height_pv"}
        for prefix, entry in config.get("pv_prefixes", {}).items():
            missing = required - set(entry.keys())
            assert not missing, (
                f"Prefix {prefix!r} is missing required PV keys: {missing}"
            )

    def test_epics_connection_has_host_and_port(self):
        _require_real_config()
        from config.config import get_epics_connection
        conn = get_epics_connection()
        assert "host" in conn
        assert "port" in conn
        assert isinstance(conn["port"], int)

    def test_display_settings_valid(self):
        _require_real_config()
        from config.config import get_display_settings
        display = get_display_settings()
        assert "colormap_name" in display
        assert "enable_fitting" in display
        assert isinstance(display.get("levels_interval", 30), int)

    def test_fallback_shapes_are_valid(self):
        _require_real_config()
        from config.config import load_config
        config = load_config()
        for prefix, entry in config.get("pv_prefixes", {}).items():
            fs = entry.get("fallback_shape")
            if fs is not None:
                assert len(fs) == 2, f"{prefix}: fallback_shape must have 2 elements"
                assert all(isinstance(v, int) and v > 0 for v in fs), (
                    f"{prefix}: fallback_shape values must be positive ints, got {fs}"
                )

    def test_calibration_methods_are_known(self):
        _require_real_config()
        from config.config import load_config
        valid = {"fixed", "pinhole", "none"}
        config = load_config()
        for prefix, entry in config.get("pv_prefixes", {}).items():
            cal = entry.get("calibration")
            if cal and isinstance(cal, dict):
                method = str(cal.get("method", "")).lower()
                assert method in valid, (
                    f"{prefix}: unknown calibration method {method!r}"
                )


# ---------------------------------------------------------------------------
# Calibration loading from real config
# ---------------------------------------------------------------------------

class TestRealCalibrationLoading:
    """End-to-end calibration load for each real prefix."""

    def test_load_calibration_for_all_prefixes(self):
        _require_real_config()
        from config.config import get_available_prefixes
        from analysis.calibration import load_calibration, Calibration
        for prefix in get_available_prefixes():
            cal = load_calibration(prefix)
            assert isinstance(cal, Calibration), (
                f"load_calibration({prefix!r}) did not return a Calibration"
            )
            assert cal.um_per_pixel > 0, (
                f"{prefix}: um_per_pixel must be positive, got {cal.um_per_pixel}"
            )

    def test_active_prefix_calibration_consistency(self):
        """If calibration is enabled, um_per_pixel must be physically plausible."""
        _require_real_config()
        from config.config import get_active_prefix
        from analysis.calibration import load_calibration
        prefix = get_active_prefix()
        cal = load_calibration(prefix)
        if cal.is_calibrated:
            # Physical sanity: µm/px at most ALS beamlines is roughly 0.1–100
            assert 0.01 < cal.um_per_pixel < 10000, (
                f"Suspicious um_per_pixel for {prefix!r}: {cal.um_per_pixel}"
            )
            assert cal.unit_label == "µm"


# ---------------------------------------------------------------------------
# Full end-to-end pipeline with real calibration
# ---------------------------------------------------------------------------

class TestEndToEndAnalysisPipeline:
    """Run the complete analysis pipeline (config → calibration → analyze_frame)."""

    def test_pipeline_with_active_prefix_calibration(self):
        """analyze_frame using the real calibration for the active camera."""
        _require_real_config()
        from config.config import get_active_prefix
        from analysis.calibration import load_calibration
        from analysis.analysis import analyze_frame

        prefix = get_active_prefix()
        cal = load_calibration(prefix)
        frame = _gaussian_frame()

        bp = analyze_frame(frame, do_fit=True, calibration=cal)

        assert bp.x_fit is not None
        assert bp.x_fit.success, "Gaussian fit failed on a clean synthetic frame"

        # Sigma should be close to 15 px
        assert bp.x_fit.sigma == pytest.approx(15.0, abs=2.0)

        if cal.is_calibrated:
            assert bp.x_fit.sigma_um is not None
            assert bp.x_fit.sigma_um == pytest.approx(
                15.0 * cal.um_per_pixel, rel=0.05
            )
            assert bp.x_fit.unit_label == "µm"
        else:
            assert bp.x_fit.sigma_um is None
            assert bp.x_fit.unit_label == "px"

    def test_pipeline_all_prefixes(self):
        """Pipeline must succeed for every configured prefix."""
        _require_real_config()
        from config.config import get_available_prefixes
        from analysis.calibration import load_calibration
        from analysis.analysis import analyze_frame

        frame = _gaussian_frame()
        for prefix in get_available_prefixes():
            cal = load_calibration(prefix)
            bp = analyze_frame(frame, do_fit=True, calibration=cal)
            assert bp.x_fit is not None, f"x_fit is None for prefix {prefix!r}"
            assert bp.x_fit.success, f"Fit failed for prefix {prefix!r}"

    def test_pipeline_do_fit_false(self):
        """do_fit=False must return projections but no fit results."""
        _require_real_config()
        from config.config import get_active_prefix
        from analysis.calibration import load_calibration
        from analysis.analysis import analyze_frame

        cal = load_calibration(get_active_prefix())
        frame = _gaussian_frame()
        bp = analyze_frame(frame, do_fit=False, calibration=cal)

        assert bp.x_fit is None
        assert bp.y_fit is None
        assert bp.x_projection is not None
        assert len(bp.x_projection) == frame.shape[1]

    def test_pipeline_with_roi_offsets(self):
        """ROI offset must shift the returned centroid by the correct amount."""
        _require_real_config()
        from config.config import get_active_prefix
        from analysis.calibration import load_calibration
        from analysis.analysis import analyze_frame

        cal = load_calibration(get_active_prefix())
        frame = _gaussian_frame()

        bp_base = analyze_frame(frame, do_fit=True, calibration=cal, x_offset=0)
        bp_offset = analyze_frame(frame, do_fit=True, calibration=cal, x_offset=50)

        assert bp_base.x_fit.success
        assert bp_offset.x_fit.success
        assert bp_offset.x_fit.centroid == pytest.approx(
            bp_base.x_fit.centroid + 50, abs=1.5
        )


# ---------------------------------------------------------------------------
# Config persistence round-trip (uses real config.json)
# ---------------------------------------------------------------------------

class TestRealConfigPersistence:
    """ROI save/load against the real config.json — cleans up after itself."""

    def test_roi_save_and_load_and_cleanup(self):
        """Save a test ROI, verify it loads, then remove it."""
        _require_real_config()
        from config.config import save_roi_for_prefix, get_roi_for_prefix

        # Use an unlikely prefix name to avoid clobbering real data
        test_prefix = "_PYTEST_INTEGRATION_"
        test_roi = (5, 10, 55, 60)

        try:
            save_roi_for_prefix(test_prefix, test_roi)
            loaded = get_roi_for_prefix(test_prefix)
            assert loaded == test_roi
        finally:
            # Always clean up — remove the test entry from config.json
            save_roi_for_prefix(test_prefix, None)
            assert get_roi_for_prefix(test_prefix) is None
