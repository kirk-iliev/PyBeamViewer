"""Tests for ApiBridge — the core adapter between FastAPI and Qt.

Uses mock objects for state, controller, and window to test bridge
logic without requiring a running Qt application.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from api.bridge import ApiBridge, _nan_to_none, _ndarray_to_list, _frame_to_png_b64


# ---------------------------------------------------------------------------
# Fixtures — build minimal mock objects that mimic the real Qt types
# ---------------------------------------------------------------------------

def _make_mock_state():
    """Create a mock AppState with realistic attributes."""
    state = MagicMock()
    state.host = "127.0.0.1"
    state.port = 15064
    state.image_pv = "TEST:image1:ArrayData"
    state.width_pv = "TEST:image1:ArraySize0_RBV"
    state.height_pv = "TEST:image1:ArraySize1_RBV"
    state.exposure_pv = "TEST:cam1:AcquireTime"
    state.exposure_rbv_pv = "TEST:cam1:AcquireTime_RBV"
    state.gain_pv = "TEST:cam1:Gain"
    state.gain_rbv_pv = "TEST:cam1:Gain_RBV"
    state.fallback_shape = (300, 300)
    state.connected = True
    state.frame_count = 42
    state.background_frame = None
    state.bg_subtraction_enabled = False
    state.frame_state = None
    return state


def _make_mock_window():
    """Create a mock BeamViewerWindow with the signals and attributes the bridge reads."""
    window = MagicMock()

    # Signals that the bridge emits
    window.prefix_change_requested = MagicMock()
    window.exposure_set_requested = MagicMock()
    window.gain_set_requested = MagicMock()
    window.streaming_toggled = MagicMock()
    window.acquire_background_requested = MagicMock()
    window.bg_subtraction_toggled = MagicMock()
    window.save_background_requested = MagicMock()
    window.load_background_requested = MagicMock()
    window.fit_full_toggled = MagicMock()
    window.colormap_changed = MagicMock()
    window.overlay_settings_changed = MagicMock()
    window.trending_depth_changed = MagicMock()

    # Control panel mock
    cp = MagicMock()
    cp.fit_roi_btn.isChecked.return_value = False
    cp.fit_full_btn = MagicMock()
    cp.stream_btn = MagicMock()
    cp.show_crosshair_btn = MagicMock()
    cp.trending_btn = MagicMock()
    cp.trending_depth_input.value.return_value = 300
    cp.colormap_combo.currentText.return_value = "hot"
    window.control_panel = cp

    # Image pane
    window.image_pane_1 = MagicMock()
    window.image_pane_1.current_roi = None

    # Window attributes
    window._centroid_reference = None
    window._live_roi_centroid = None
    window._crosshair_enabled = False
    window._trending_visible = False
    window._start_time = None
    window._calibration = SimpleNamespace(
        is_calibrated=False,
        um_per_pixel=1.0,
        unit_label="px",
        description="No calibration",
    )
    window._theme = SimpleNamespace(name="dark")
    _overlay = SimpleNamespace(
        to_dict=lambda: {
            "h_enabled": False, "h_side": "bottom",
            "v_enabled": False, "v_side": "left",
            "scale": 0.25, "show_full": True, "show_roi": True,
        },
    )
    window._overlay_state = _overlay
    # The bridge reads via the property `overlay_state` on BeamViewerWindow
    type(window).overlay_state = PropertyMock(return_value=_overlay)

    # Public methods
    window.get_current_roi = MagicMock(return_value=None)

    return window


def _make_mock_controller():
    """Create a mock BeamController."""
    ctrl = MagicMock()
    ctrl._active_prefix = "TEST"
    ctrl._streaming = True
    ctrl._fit_full = True
    ctrl._trending_buffer = MagicMock()
    ctrl._trending_buffer.count = 0
    ctrl._trending_buffer.get_history.return_value = {
        "frame_number": np.array([]),
        "sigma_x": np.array([]),
        "sigma_y": np.array([]),
        "centroid_x": np.array([]),
        "centroid_y": np.array([]),
        "roi_sigma_x": np.array([]),
        "roi_sigma_y": np.array([]),
        "drift_x": np.array([]),
        "drift_y": np.array([]),
    }
    return ctrl


@pytest.fixture
def bridge():
    state = _make_mock_state()
    ctrl = _make_mock_controller()
    window = _make_mock_window()
    with patch("api.bridge.QMetaObject"):
        yield ApiBridge(state, ctrl, window)


@pytest.fixture
def bridge_parts():
    state = _make_mock_state()
    ctrl = _make_mock_controller()
    window = _make_mock_window()
    with patch("api.bridge.QMetaObject"):
        yield ApiBridge(state, ctrl, window), state, ctrl, window


# ---------------------------------------------------------------------------
# Camera tests
# ---------------------------------------------------------------------------

class TestCameraBridge:
    def test_get_camera_info(self, bridge):
        info = bridge.get_camera_info()
        # active_prefix comes from config.json, not from the mock controller
        assert isinstance(info["active_prefix"], str)
        assert info["host"] == "127.0.0.1"
        assert info["port"] == 15064
        assert info["image_pv"] == "TEST:image1:ArrayData"
        assert info["fallback_shape"] == [300, 300]

    def test_select_prefix_valid(self, bridge):
        with patch("config.config.load_config", return_value={
            "pv_prefixes": {"TEST": {}, "OTHER": {}},
        }):
            bridge.select_prefix("OTHER")
            bridge._window.prefix_change_requested.emit.assert_called_once_with("OTHER")

    def test_select_prefix_invalid(self, bridge):
        with patch("config.config.load_config", return_value={
            "pv_prefixes": {"TEST": {}},
        }):
            with pytest.raises(ValueError, match="Unknown prefix"):
                bridge.select_prefix("NOPE")

    def test_set_exposure(self, bridge):
        bridge.set_exposure(0.5)
        bridge._window.exposure_set_requested.emit.assert_called_once_with(0.5)

    def test_set_gain(self, bridge):
        bridge.set_gain(10)
        bridge._window.gain_set_requested.emit.assert_called_once_with(10)


# ---------------------------------------------------------------------------
# Streaming tests
# ---------------------------------------------------------------------------

class TestStreamingBridge:
    def test_get_streaming_status(self, bridge):
        status = bridge.get_streaming_status()
        assert status["streaming"] is True
        assert status["connected"] is True
        assert status["frame_count"] == 42


# ---------------------------------------------------------------------------
# Background tests
# ---------------------------------------------------------------------------

class TestBackgroundBridge:
    def test_get_background_status_none(self, bridge):
        status = bridge.get_background_status()
        assert status["has_background"] is False
        assert status["subtraction_enabled"] is False

    def test_get_background_status_with_bg(self, bridge_parts):
        bridge, state, _, _ = bridge_parts
        state.background_frame = np.zeros((100, 100))
        state.bg_subtraction_enabled = True
        status = bridge.get_background_status()
        assert status["has_background"] is True
        assert status["subtraction_enabled"] is True

    def test_acquire_background(self, bridge):
        bridge.acquire_background()
        bridge._window.acquire_background_requested.emit.assert_called_once()

    def test_set_background_subtraction(self, bridge):
        bridge.set_background_subtraction(True)
        bridge._window.bg_subtraction_toggled.emit.assert_called_once_with(True)

    def test_save_background(self, bridge):
        bridge.save_background()
        bridge._window.save_background_requested.emit.assert_called_once()

    def test_load_background(self, bridge):
        from pathlib import Path
        from config.config import _get_backgrounds_dir
        # Create a fake background file inside the allowed directory
        bg_dir = _get_backgrounds_dir()
        fake_bg = bg_dir / "test_bg.npy"
        fake_bg.touch()
        try:
            bridge.load_background(str(fake_bg))
            bridge._window.load_background_requested.emit.assert_called_once()
        finally:
            fake_bg.unlink(missing_ok=True)

    def test_load_background_path_traversal(self, bridge):
        with pytest.raises(ValueError, match="outside the backgrounds directory"):
            bridge.load_background("/etc/passwd")

    def test_list_backgrounds(self, bridge):
        from pathlib import Path
        with patch("config.config.list_saved_backgrounds", return_value=[
            Path("/tmp/TEST_20240101_120000.npy"),
        ]):
            bgs = bridge.list_backgrounds()
            assert len(bgs) == 1
            assert bgs[0]["filename"] == "TEST_20240101_120000.npy"


# ---------------------------------------------------------------------------
# Analysis tests
# ---------------------------------------------------------------------------

class TestAnalysisBridge:
    def test_get_analysis_status_no_frame(self, bridge):
        status = bridge.get_analysis_status()
        assert status["fit_full_enabled"] is True
        assert status["fit_roi_enabled"] is False
        assert status["x_fit"] is None
        assert status["y_fit"] is None

    def test_get_analysis_status_with_results(self, bridge_parts):
        bridge, state, _, _ = bridge_parts
        x_fit = SimpleNamespace(
            success=True, sigma=12.0, sigma_um=22.6,
            centroid=100.0, centroid_um=188.5,
            amplitude=5000.0, offset=100.0, residual=0.5,
            unit_label="µm",
        )
        analysis = SimpleNamespace(x_fit=x_fit, y_fit=None, x_projection=np.zeros(100), y_projection=np.zeros(100))
        state.frame_state = SimpleNamespace(
            frame=np.zeros((100, 100), dtype=np.uint16),
            frame_number=10,
            analysis=analysis,
        )
        status = bridge.get_analysis_status()
        assert status["x_fit"]["success"] is True
        assert status["x_fit"]["sigma"] == 12.0
        assert status["y_fit"] is None


# ---------------------------------------------------------------------------
# ROI tests
# ---------------------------------------------------------------------------

class TestRoiBridge:
    def test_get_roi_none(self, bridge):
        roi = bridge.get_roi()
        assert roi["active"] is False
        assert roi["roi"] is None

    def test_get_roi_active(self, bridge):
        bridge._window.get_current_roi.return_value = (10, 20, 100, 200)
        roi = bridge.get_roi()
        assert roi["active"] is True
        assert roi["roi"]["x0"] == 10
        assert roi["roi"]["y1"] == 200


# ---------------------------------------------------------------------------
# Centroid / Drift tests
# ---------------------------------------------------------------------------

class TestCentroidBridge:
    def test_get_drift_no_reference(self, bridge):
        drift = bridge.get_drift()
        assert drift["has_reference"] is False
        assert drift["crosshair_enabled"] is False

    def test_get_drift_with_reference_and_live(self, bridge):
        bridge._window._centroid_reference = (100.0, 100.0)
        bridge._window._live_roi_centroid = (102.0, 98.5)
        bridge._window._crosshair_enabled = True
        drift = bridge.get_drift()
        assert drift["has_reference"] is True
        assert drift["crosshair_enabled"] is True
        assert drift["drift_x"] == pytest.approx(2.0)
        assert drift["drift_y"] == pytest.approx(-1.5)


# ---------------------------------------------------------------------------
# Display tests
# ---------------------------------------------------------------------------

class TestDisplayBridge:
    def test_get_theme(self, bridge):
        assert bridge.get_theme() == "dark"

    def test_get_colormap(self, bridge):
        assert bridge.get_colormap() == "hot"

    def test_set_colormap_valid(self, bridge):
        bridge.set_colormap("viridis")
        bridge._window.colormap_changed.emit.assert_called_once_with("viridis")

    def test_set_colormap_invalid(self, bridge):
        with pytest.raises(ValueError, match="Invalid colormap"):
            bridge.set_colormap("rainbow_unicorn")


# ---------------------------------------------------------------------------
# Overlay tests
# ---------------------------------------------------------------------------

class TestOverlayBridge:
    def test_get_overlay_settings(self, bridge):
        settings = bridge.get_overlay_settings()
        assert settings["h_enabled"] is False
        assert settings["scale"] == 0.25


# ---------------------------------------------------------------------------
# Trending tests
# ---------------------------------------------------------------------------

class TestTrendingBridge:
    def test_get_trending_config(self, bridge):
        config = bridge.get_trending_config()
        assert config["visible"] is False
        assert config["depth"] == 300

    def test_get_trending_history_empty(self, bridge):
        history = bridge.get_trending_history()
        assert history["count"] == 0
        assert history["frame_number"] == []


# ---------------------------------------------------------------------------
# Frame data tests
# ---------------------------------------------------------------------------

class TestFrameDataBridge:
    def test_get_frame_metadata_no_frame(self, bridge):
        meta = bridge.get_frame_metadata()
        assert meta["frame_number"] == 0
        assert meta["fps"] == 0.0

    def test_get_frame_metadata_with_frame(self, bridge_parts):
        bridge, state, _, window = bridge_parts
        frame = np.zeros((200, 300), dtype=np.uint16)
        state.frame_state = SimpleNamespace(frame=frame, frame_number=50)
        window._start_time = 0.0  # set a start time
        meta = bridge.get_frame_metadata()
        assert meta["frame_number"] == 50
        assert meta["height"] == 200
        assert meta["width"] == 300
        assert meta["dtype"] == "uint16"

    def test_get_frame_png_b64_empty(self, bridge):
        assert bridge.get_frame_png_b64() == ""

    def test_get_frame_png_b64_with_frame(self, bridge_parts):
        bridge, state, _, _ = bridge_parts
        frame = np.random.randint(0, 1000, (50, 50), dtype=np.uint16)
        state.frame_state = SimpleNamespace(frame=frame, frame_number=1)
        b64 = bridge.get_frame_png_b64()
        assert len(b64) > 0
        # Verify it's valid base64
        import base64
        raw = base64.b64decode(b64)
        assert raw[:4] == b"\x89PNG"

    def test_get_projections_no_frame(self, bridge):
        proj = bridge.get_projections()
        assert proj["x_projection"] == []
        assert proj["y_projection"] == []

    def test_get_projections_with_frame(self, bridge_parts):
        bridge, state, _, _ = bridge_parts
        x_proj = np.array([1.0, 2.0, 3.0])
        y_proj = np.array([4.0, 5.0, 6.0])
        analysis = SimpleNamespace(
            x_projection=x_proj, y_projection=y_proj,
            x_fit=None, y_fit=None,
        )
        state.frame_state = SimpleNamespace(
            frame=np.zeros((3, 3)), frame_number=1, analysis=analysis,
        )
        proj = bridge.get_projections()
        assert proj["x_projection"] == [1.0, 2.0, 3.0]
        assert proj["y_projection"] == [4.0, 5.0, 6.0]


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------

class TestUtilityFunctions:
    def test_nan_to_none(self):
        assert _nan_to_none(1.0) == 1.0
        assert _nan_to_none(float("nan")) is None
        assert _nan_to_none("hello") == "hello"

    def test_ndarray_to_list_empty(self):
        assert _ndarray_to_list(np.array([])) == []

    def test_ndarray_to_list_with_nans(self):
        arr = np.array([1.0, float("nan"), 3.0])
        result = _ndarray_to_list(arr)
        assert result[0] == 1.0
        assert result[1] is None
        assert result[2] == 3.0

    def test_frame_to_png_b64(self):
        frame = np.random.randint(0, 1000, (20, 20), dtype=np.uint16)
        b64 = _frame_to_png_b64(frame)
        assert len(b64) > 0
        import base64
        raw = base64.b64decode(b64)
        assert raw[:4] == b"\x89PNG"

    def test_frame_to_png_b64_flat(self):
        frame = np.full((10, 10), 500, dtype=np.uint16)
        b64 = _frame_to_png_b64(frame)
        assert len(b64) > 0
