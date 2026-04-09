"""
Tests for headless_bridge.py — HeadlessBridge API adapter.
"""

from __future__ import annotations

import base64
import io
import math
import time
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import numpy as np
import pytest

from mcp_servers.beam_viewer.api.headless_bridge import (
    HeadlessBridge,
    _nan_to_none,
    _ndarray_to_list,
    _frame_to_png_b64,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_state():
    state = MagicMock()
    state.host = "localhost"
    state.port = 5064
    state.image_pv = "TEST:Image"
    state.width_pv = "TEST:Width"
    state.height_pv = "TEST:Height"
    state.exposure_pv = "TEST:Exp"
    state.exposure_rbv_pv = "TEST:Exp:RBV"
    state.gain_pv = "TEST:Gain"
    state.gain_rbv_pv = "TEST:Gain:RBV"
    state.fallback_shape = (480, 640)
    state.colormap_name = "hot"
    state.background_frame = None
    state.bg_subtraction_enabled = False
    state.connected = True
    state.frame_count = 42
    state.frame_state = None
    return state


@pytest.fixture
def mock_controller():
    ctrl = MagicMock()
    ctrl.active_prefix = "TEST"
    ctrl.streaming = True
    ctrl.fit_full = True
    ctrl.current_roi = None
    ctrl.centroid_reference = None
    ctrl.live_roi_centroid = None
    ctrl.crosshair_enabled = False
    ctrl.overlay_settings = {"h_enabled": False, "v_enabled": False}
    ctrl.get_available_prefixes.return_value = ["TEST", "OTHER"]
    ctrl.get_bg_file_list.return_value = []

    # Mock calibration
    mock_cal = MagicMock()
    mock_cal.is_calibrated = False
    mock_cal.um_per_pixel = 1.0
    mock_cal.unit_label = "px"
    mock_cal.description = "No calibration"
    ctrl.calibration = mock_cal

    # Mock trending buffer
    mock_buf = MagicMock()
    mock_buf._max_len = 300
    mock_buf.count = 0
    mock_buf.get_history.return_value = {
        k: np.array([]) for k in [
            "frame_number", "sigma_x", "sigma_y", "centroid_x", "centroid_y",
            "roi_sigma_x", "roi_sigma_y", "drift_x", "drift_y",
        ]
    }
    ctrl.trending_buffer = mock_buf

    return ctrl


@pytest.fixture
def bridge(mock_state, mock_controller):
    return HeadlessBridge(mock_state, mock_controller)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

class TestNanToNone:

    def test_nan_becomes_none(self):
        assert _nan_to_none(float("nan")) is None

    def test_normal_float_unchanged(self):
        assert _nan_to_none(3.14) == 3.14

    def test_non_float_unchanged(self):
        assert _nan_to_none("hello") == "hello"
        assert _nan_to_none(42) == 42
        assert _nan_to_none(None) is None


class TestNdarrayToList:

    def test_empty_array(self):
        assert _ndarray_to_list(np.array([])) == []

    def test_with_nans(self):
        arr = np.array([1.0, float("nan"), 3.0])
        result = _ndarray_to_list(arr)
        assert result[0] == 1.0
        assert result[1] is None
        assert result[2] == 3.0

    def test_rounding(self):
        arr = np.array([1.123456789])
        result = _ndarray_to_list(arr)
        assert result[0] == 1.123457  # rounded to 6 decimals


class TestFrameToPngB64:

    def test_uniform_frame(self):
        frame = np.zeros((10, 10), dtype=np.uint16)
        result = _frame_to_png_b64(frame)
        assert isinstance(result, str)
        assert len(result) > 0
        # Should be valid base64
        decoded = base64.b64decode(result)
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_gradient_frame(self):
        frame = np.arange(100).reshape(10, 10).astype(np.float64)
        result = _frame_to_png_b64(frame)
        assert len(result) > 0

    def test_empty_frame(self):
        frame = np.zeros((1, 1), dtype=np.uint8)
        result = _frame_to_png_b64(frame)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

class TestCamera:

    def test_get_camera_info(self, bridge, mock_state):
        info = bridge.get_camera_info()
        assert info["active_prefix"] == "TEST"
        assert info["host"] == "localhost"
        assert info["port"] == 5064
        assert info["image_pv"] == "TEST:Image"
        assert info["fallback_shape"] == [480, 640]

    def test_get_camera_info_no_fallback(self, bridge, mock_state):
        mock_state.fallback_shape = None
        info = bridge.get_camera_info()
        assert info["fallback_shape"] is None

    def test_select_prefix(self, bridge, mock_controller):
        bridge.select_prefix("OTHER")
        mock_controller.switch_prefix.assert_called_once_with("OTHER")

    def test_select_prefix_invalid(self, bridge):
        with pytest.raises(ValueError, match="Unknown prefix"):
            bridge.select_prefix("NONEXISTENT")

    def test_set_exposure(self, bridge, mock_controller):
        bridge.set_exposure(0.5)
        mock_controller.set_exposure.assert_called_once_with(0.5)

    def test_set_gain(self, bridge, mock_controller):
        bridge.set_gain(10)
        mock_controller.set_gain.assert_called_once_with(10)


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

class TestStreaming:

    def test_get_streaming_status(self, bridge):
        status = bridge.get_streaming_status()
        assert status["streaming"] is True
        assert status["connected"] is True
        assert status["frame_count"] == 42

    def test_set_streaming(self, bridge, mock_controller):
        bridge.set_streaming(False)
        mock_controller.set_streaming.assert_called_once_with(False)


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------

class TestBackground:

    def test_get_background_status_no_bg(self, bridge):
        status = bridge.get_background_status()
        assert status["has_background"] is False
        assert status["subtraction_enabled"] is False

    def test_get_background_status_with_bg(self, bridge, mock_state):
        mock_state.background_frame = np.zeros((10, 10))
        mock_state.bg_subtraction_enabled = True
        status = bridge.get_background_status()
        assert status["has_background"] is True
        assert status["subtraction_enabled"] is True

    def test_acquire_background(self, bridge, mock_controller):
        bridge.acquire_background()
        mock_controller.acquire_background.assert_called_once()

    def test_set_background_subtraction(self, bridge, mock_controller):
        bridge.set_background_subtraction(True)
        mock_controller.toggle_bg_subtraction.assert_called_once_with(True)

    def test_save_background(self, bridge, mock_controller):
        bridge.save_background()
        mock_controller.save_background.assert_called_once()

    def test_list_backgrounds(self, bridge, mock_controller):
        mock_controller.get_bg_file_list.return_value = [
            Path("/bgs/TEST_20260101.npy"),
        ]
        result = bridge.list_backgrounds()
        assert len(result) == 1
        assert result[0]["filename"] == "TEST_20260101.npy"


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

class TestAnalysis:

    def test_get_analysis_status_no_frame(self, bridge):
        status = bridge.get_analysis_status()
        assert status["fit_full_enabled"] is True
        assert status["x_fit"] is None
        assert status["y_fit"] is None

    def test_get_analysis_status_with_fits(self, bridge, mock_state):
        mock_xfit = MagicMock()
        mock_xfit.success = True
        mock_xfit.sigma = 5.0
        mock_xfit.sigma_um = 50.0
        mock_xfit.centroid = 100.0
        mock_xfit.centroid_um = 1000.0
        mock_xfit.amplitude = 255.0
        mock_xfit.offset = 10.0
        mock_xfit.residual = 0.5
        mock_xfit.unit_label = "um"

        mock_bp = MagicMock()
        mock_bp.x_fit = mock_xfit
        mock_bp.y_fit = None

        mock_fs = MagicMock()
        mock_fs.analysis = mock_bp
        mock_state.frame_state = mock_fs

        status = bridge.get_analysis_status()
        assert status["x_fit"]["success"] is True
        assert status["x_fit"]["sigma"] == 5.0
        assert status["y_fit"] is None

    def test_set_fit_full(self, bridge, mock_controller):
        bridge.set_fit_full(False)
        mock_controller.set_fit_full.assert_called_once_with(False)

    def test_set_fit_roi_noop(self, bridge):
        # Should not raise
        bridge.set_fit_roi(True)


# ---------------------------------------------------------------------------
# ROI
# ---------------------------------------------------------------------------

class TestROI:

    def test_get_roi_none(self, bridge):
        result = bridge.get_roi()
        assert result["active"] is False
        assert result["roi"] is None

    def test_get_roi_active(self, bridge, mock_controller):
        mock_controller.current_roi = (10, 20, 110, 120)
        result = bridge.get_roi()
        assert result["active"] is True
        assert result["roi"] == {"x0": 10, "y0": 20, "x1": 110, "y1": 120}

    def test_set_roi(self, bridge, mock_controller):
        bridge.set_roi(10, 20, 110, 120)
        mock_controller.set_roi.assert_called_once_with((10, 20, 110, 120))

    def test_clear_roi(self, bridge, mock_controller):
        bridge.clear_roi()
        mock_controller.set_roi.assert_called_once_with(None)

    def test_center_roi(self, bridge, mock_controller, mock_state):
        mock_controller.current_roi = (0, 0, 50, 50)
        mock_fs = MagicMock()
        mock_fs.frame = np.zeros((200, 300))
        mock_state.frame_state = mock_fs

        bridge.center_roi()
        mock_controller.set_roi.assert_called_once()
        args = mock_controller.set_roi.call_args[0][0]
        # Center of 300x200 is (150, 100); ROI is 50x50
        assert args == (125, 75, 175, 125)

    def test_center_roi_no_roi(self, bridge, mock_controller):
        mock_controller.current_roi = None
        bridge.center_roi()
        mock_controller.set_roi.assert_not_called()


# ---------------------------------------------------------------------------
# Centroid / Drift
# ---------------------------------------------------------------------------

class TestDrift:

    def test_get_drift_no_reference(self, bridge):
        result = bridge.get_drift()
        assert result["has_reference"] is False
        assert result["reference"] is None
        assert result["live"] is None

    def test_get_drift_with_reference_and_live(self, bridge, mock_controller):
        mock_controller.centroid_reference = (100.0, 200.0)
        mock_controller.live_roi_centroid = (105.0, 203.0)
        mock_controller.crosshair_enabled = True

        result = bridge.get_drift()
        assert result["has_reference"] is True
        assert result["crosshair_enabled"] is True
        assert result["drift_x"] == 5.0
        assert result["drift_y"] == 3.0

    def test_get_drift_calibrated(self, bridge, mock_controller):
        mock_controller.centroid_reference = (100.0, 200.0)
        mock_controller.live_roi_centroid = (110.0, 210.0)
        mock_controller.calibration.is_calibrated = True
        mock_controller.calibration.pixel_to_um.side_effect = lambda x: x * 5.0

        result = bridge.get_drift()
        assert result["drift_x_um"] == 50.0
        assert result["drift_y_um"] == 50.0

    def test_set_crosshair(self, bridge, mock_controller):
        bridge.set_crosshair(True)
        mock_controller.set_crosshair_enabled.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

class TestDisplay:

    def test_get_theme(self, bridge):
        assert bridge.get_theme() == "dark"

    def test_toggle_theme_noop(self, bridge):
        bridge.toggle_theme()  # Should not raise

    def test_set_colormap(self, bridge, mock_controller):
        bridge.set_colormap("viridis")
        mock_controller.set_colormap.assert_called_once_with("viridis")

    def test_set_colormap_invalid(self, bridge):
        with pytest.raises(ValueError, match="Invalid colormap"):
            bridge.set_colormap("nonexistent_cmap")

    def test_get_colormap(self, bridge, mock_state):
        mock_state.colormap_name = "inferno"
        assert bridge.get_colormap() == "inferno"


# ---------------------------------------------------------------------------
# Overlays
# ---------------------------------------------------------------------------

class TestOverlays:

    def test_get_overlay_settings(self, bridge, mock_controller):
        result = bridge.get_overlay_settings()
        assert result == {"h_enabled": False, "v_enabled": False}

    def test_set_overlay_settings_merge(self, bridge, mock_controller):
        bridge.set_overlay_settings({"h_enabled": True})
        mock_controller.set_overlay_settings.assert_called_once_with(
            {"h_enabled": True, "v_enabled": False}
        )

    def test_set_overlay_ignores_none_values(self, bridge, mock_controller):
        bridge.set_overlay_settings({"h_enabled": None, "v_enabled": True})
        mock_controller.set_overlay_settings.assert_called_once_with(
            {"h_enabled": False, "v_enabled": True}
        )


# ---------------------------------------------------------------------------
# Trending
# ---------------------------------------------------------------------------

class TestTrending:

    def test_get_trending_config(self, bridge):
        config = bridge.get_trending_config()
        assert config["visible"] is True
        assert config["depth"] == 300

    def test_set_trending_depth(self, bridge, mock_controller):
        bridge.set_trending_depth(100)
        mock_controller.set_trending_depth.assert_called_once_with(100)

    def test_set_trending_visible_noop(self, bridge):
        bridge.set_trending_visible(False)  # Should not raise

    def test_get_trending_history_empty(self, bridge):
        history = bridge.get_trending_history()
        assert history["count"] == 0
        assert history["frame_number"] == []
        assert history["sigma_x"] == []

    def test_get_trending_history_with_data(self, bridge, mock_controller):
        mock_controller.trending_buffer.count = 2
        mock_controller.trending_buffer.get_history.return_value = {
            "frame_number": np.array([1.0, 2.0]),
            "sigma_x": np.array([10.0, float("nan")]),
            "sigma_y": np.array([20.0, 25.0]),
            "centroid_x": np.array([100.0, 105.0]),
            "centroid_y": np.array([200.0, 205.0]),
            "roi_sigma_x": np.array([float("nan"), float("nan")]),
            "roi_sigma_y": np.array([float("nan"), float("nan")]),
            "drift_x": np.array([0.0, 1.0]),
            "drift_y": np.array([0.0, 2.0]),
        }
        history = bridge.get_trending_history()
        assert history["count"] == 2
        assert history["sigma_x"] == [10.0, None]  # NaN → None


# ---------------------------------------------------------------------------
# Frame data
# ---------------------------------------------------------------------------

class TestFrameData:

    def test_get_frame_metadata_no_frame(self, bridge):
        meta = bridge.get_frame_metadata()
        assert meta["frame_number"] == 0
        assert meta["fps"] == 0.0

    def test_get_frame_metadata_with_frame(self, bridge, mock_state):
        mock_fs = MagicMock()
        mock_fs.frame = np.zeros((100, 200), dtype=np.uint16)
        mock_fs.frame_number = 10
        mock_state.frame_state = mock_fs

        bridge._start_time = time.time() - 1.0  # 1 second ago
        meta = bridge.get_frame_metadata()
        assert meta["frame_number"] == 10
        assert meta["height"] == 100
        assert meta["width"] == 200
        assert meta["dtype"] == "uint16"
        assert meta["fps"] == 10.0

    def test_get_frame_png_b64_no_frame(self, bridge):
        assert bridge.get_frame_png_b64() == ""

    def test_get_frame_png_b64_with_frame(self, bridge, mock_state):
        mock_fs = MagicMock()
        mock_fs.frame = np.arange(100).reshape(10, 10).astype(np.uint16)
        mock_state.frame_state = mock_fs
        result = bridge.get_frame_png_b64()
        assert len(result) > 0

    def test_get_frame_raw_no_frame(self, bridge):
        assert bridge.get_frame_raw() is None

    def test_get_frame_raw_with_frame(self, bridge, mock_state):
        frame = np.arange(25).reshape(5, 5).astype(np.float32)
        mock_fs = MagicMock()
        mock_fs.frame = frame
        mock_state.frame_state = mock_fs

        raw = bridge.get_frame_raw()
        assert raw is not None
        loaded = np.load(io.BytesIO(raw))
        np.testing.assert_array_equal(loaded, frame)

    def test_get_projections_no_frame(self, bridge):
        result = bridge.get_projections()
        assert result == {"x_projection": [], "y_projection": []}

    def test_get_projections_with_frame(self, bridge, mock_state):
        mock_bp = MagicMock()
        mock_bp.x_projection = np.array([1.0, 2.0, 3.0])
        mock_bp.y_projection = np.array([4.0, 5.0])

        mock_fs = MagicMock()
        mock_fs.analysis = mock_bp
        mock_state.frame_state = mock_fs

        result = bridge.get_projections()
        assert result["x_projection"] == [1.0, 2.0, 3.0]
        assert result["y_projection"] == [4.0, 5.0]


# ---------------------------------------------------------------------------
# ROI frame data
# ---------------------------------------------------------------------------

class TestROIFrameData:

    def test_get_roi_frame_data_no_roi(self, bridge):
        result = bridge.get_roi_frame_data()
        assert result == {"active": False}

    def test_get_roi_frame_data_no_frame(self, bridge, mock_controller, mock_state):
        mock_controller.current_roi = (10, 10, 50, 50)
        mock_state.frame_state = None
        result = bridge.get_roi_frame_data()
        assert result["active"] is True
        assert result["metadata"] is None

    def test_get_roi_frame_data_with_frame(self, bridge, mock_controller, mock_state):
        mock_controller.current_roi = (10, 10, 50, 50)
        mock_fs = MagicMock()
        mock_fs.frame = np.arange(10000).reshape(100, 100).astype(np.uint16)
        mock_fs.frame_number = 5
        mock_state.frame_state = mock_fs

        result = bridge.get_roi_frame_data()
        assert result["active"] is True
        assert result["metadata"]["height"] == 40
        assert result["metadata"]["width"] == 40
        assert "image_b64_png" in result
        assert "projections" in result

    def test_get_roi_frame_data_degenerate_roi(self, bridge, mock_controller, mock_state):
        mock_controller.current_roi = (50, 50, 50, 50)  # zero-size
        mock_fs = MagicMock()
        mock_fs.frame = np.zeros((100, 100))
        mock_state.frame_state = mock_fs

        result = bridge.get_roi_frame_data()
        assert result["active"] is True
        assert result["metadata"] is None


# ---------------------------------------------------------------------------
# Calibration info
# ---------------------------------------------------------------------------

class TestCalibration:

    def test_get_calibration_info(self, bridge, mock_controller):
        result = bridge.get_calibration_info()
        assert result["is_calibrated"] is False
        assert result["um_per_pixel"] == 1.0
        assert result["unit_label"] == "px"


# ---------------------------------------------------------------------------
# WebSocket payload
# ---------------------------------------------------------------------------

class TestWSPayload:

    def test_build_ws_frame_payload_no_frame(self, bridge):
        assert bridge.build_ws_frame_payload() is None

    def test_build_ws_frame_payload_with_frame(self, bridge, mock_state, mock_controller):
        mock_fs = MagicMock()
        mock_fs.frame = np.arange(100).reshape(10, 10).astype(np.uint16)
        mock_fs.frame_number = 7
        mock_fs.analysis = None
        mock_state.frame_state = mock_fs

        payload = bridge.build_ws_frame_payload()
        assert payload is not None
        assert payload["type"] == "frame"
        assert "frame_png_b64" in payload
        assert "projections" in payload
        assert "analysis" in payload
        assert "roi" in payload
        assert "drift" in payload


# ---------------------------------------------------------------------------
# Mark start time
# ---------------------------------------------------------------------------

class TestStartTime:

    def test_mark_start_time(self, bridge):
        assert bridge._start_time is None
        bridge.mark_start_time()
        assert bridge._start_time is not None
        assert abs(bridge._start_time - time.time()) < 1.0
