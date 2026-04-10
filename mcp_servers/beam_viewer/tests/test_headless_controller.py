"""
Tests for headless_controller.py — HeadlessController orchestration.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from mcp_servers.beam_viewer.core.headless_controller import (
    HeadlessController,
    EVT_FRAME_READY,
    EVT_CONNECTION_CHANGED,
    EVT_ERROR,
    EVT_EXPOSURE_RBV,
    EVT_GAIN_RBV,
    EVT_EXPOSURE_REVERTED,
    EVT_GAIN_REVERTED,
    EVT_ROI_FIT_DONE,
    EVT_BG_STATUS,
    EVT_BG_FILE_LIST,
    EVT_TRENDING_UPDATE,
)
from mcp_servers.beam_viewer.core.state import AppState, FrameState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_state():
    """Create a mock AppState without requiring config.json."""
    state = MagicMock(spec=AppState)
    state.host = ""
    state.port = 0
    state.image_pv = "TEST:Image"
    state.width_pv = "TEST:Width"
    state.height_pv = "TEST:Height"
    state.exposure_pv = "TEST:Exposure"
    state.exposure_rbv_pv = "TEST:Exposure:RBV"
    state.gain_pv = "TEST:Gain"
    state.gain_rbv_pv = "TEST:Gain:RBV"
    state.fallback_shape = (100, 100)
    state.colormap_name = "hot"
    state.background_frame = None
    state.bg_subtraction_enabled = False
    state.connected = False
    state.frame_state = None
    state.increment_frame_count.return_value = 1
    state.get_background_for_prefix.return_value = None
    state.get_bg_enabled_for_prefix.return_value = False
    return state


# Patches that prevent real config/calibration/EPICS access
_CONTROLLER_MODULE = "mcp_servers.beam_viewer.core.headless_controller"

_COMMON_PATCHES = {
    "get_active_prefix": f"{_CONTROLLER_MODULE}.get_active_prefix",
    "get_available_prefixes": f"{_CONTROLLER_MODULE}.get_available_prefixes",
    "get_pv_names": f"{_CONTROLLER_MODULE}.get_pv_names",
    "get_roi_for_prefix": f"{_CONTROLLER_MODULE}.get_roi_for_prefix",
    "save_roi_for_prefix": f"{_CONTROLLER_MODULE}.save_roi_for_prefix",
    "load_overlay_settings": f"{_CONTROLLER_MODULE}.load_overlay_settings",
    "save_overlay_settings": f"{_CONTROLLER_MODULE}.save_overlay_settings",
    "save_background_to_file": f"{_CONTROLLER_MODULE}.save_background_to_file",
    "load_background_from_file": f"{_CONTROLLER_MODULE}.load_background_from_file",
    "list_saved_backgrounds": f"{_CONTROLLER_MODULE}.list_saved_backgrounds",
    "get_active_background_path": f"{_CONTROLLER_MODULE}.get_active_background_path",
    "set_active_background_path": f"{_CONTROLLER_MODULE}.set_active_background_path",
    "save_centroid_reference": f"{_CONTROLLER_MODULE}.save_centroid_reference",
    "get_centroid_reference": f"{_CONTROLLER_MODULE}.get_centroid_reference",
    "clear_centroid_reference": f"{_CONTROLLER_MODULE}.clear_centroid_reference",
    "save_crosshair_enabled": f"{_CONTROLLER_MODULE}.save_crosshair_enabled",
    "get_crosshair_enabled": f"{_CONTROLLER_MODULE}.get_crosshair_enabled",
    "load_calibration": f"{_CONTROLLER_MODULE}.load_calibration",
    "HeadlessEpicsWorker": f"{_CONTROLLER_MODULE}.HeadlessEpicsWorker",
    "HeadlessAnalysisWorker": f"{_CONTROLLER_MODULE}.HeadlessAnalysisWorker",
    "epics_get": f"{_CONTROLLER_MODULE}.epics_get",
    "epics_put": f"{_CONTROLLER_MODULE}.epics_put",
    "analyze_frame": f"{_CONTROLLER_MODULE}.analyze_frame",
}


def _apply_patches(monkeypatch_or_patcher=None):
    """Return a dict of started mock patches."""
    mocks = {}
    patchers = {}
    for name, target in _COMMON_PATCHES.items():
        p = patch(target)
        mocks[name] = p.start()
        patchers[name] = p

    # Set sensible defaults
    mocks["get_active_prefix"].return_value = "TEST"
    mocks["get_available_prefixes"].return_value = ["TEST", "OTHER"]
    mocks["get_pv_names"].return_value = {
        "image_pv": "TEST:Image",
        "width_pv": "TEST:Width",
        "height_pv": "TEST:Height",
    }
    mocks["get_roi_for_prefix"].return_value = None
    mocks["load_overlay_settings"].return_value = {}
    mocks["get_crosshair_enabled"].return_value = False
    mocks["get_centroid_reference"].return_value = None
    mocks["get_active_background_path"].return_value = None
    mocks["list_saved_backgrounds"].return_value = []
    mocks["load_calibration"].return_value = MagicMock()

    # Workers should be mocks
    mock_epics = MagicMock()
    mocks["HeadlessEpicsWorker"].return_value = mock_epics
    mock_analysis = MagicMock()
    mocks["HeadlessAnalysisWorker"].return_value = mock_analysis

    return mocks, patchers


def _stop_patches(patchers):
    for p in patchers.values():
        p.stop()


@pytest.fixture
def controller_env(mock_state):
    """Yield (controller, mocks) with all external deps patched."""
    mocks, patchers = _apply_patches()
    try:
        ctrl = HeadlessController(mock_state)
        yield ctrl, mocks
    finally:
        _stop_patches(patchers)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:

    def test_creates_with_state(self, controller_env):
        ctrl, mocks = controller_env
        assert ctrl.state is not None
        assert ctrl.dispatcher is not None

    def test_initial_streaming_true(self, controller_env):
        ctrl, _ = controller_env
        assert ctrl.streaming is True

    def test_initial_fit_full_true(self, controller_env):
        ctrl, _ = controller_env
        assert ctrl.fit_full is True

    def test_creates_epics_worker(self, controller_env):
        ctrl, mocks = controller_env
        mocks["HeadlessEpicsWorker"].assert_called_once()

    def test_creates_analysis_worker(self, controller_env):
        ctrl, mocks = controller_env
        mocks["HeadlessAnalysisWorker"].assert_called_once()

    def test_loads_calibration(self, controller_env):
        ctrl, mocks = controller_env
        mocks["load_calibration"].assert_called_once_with("TEST")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:

    def test_start_starts_workers(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.start()
        mock_epics = mocks["HeadlessEpicsWorker"].return_value
        mock_analysis = mocks["HeadlessAnalysisWorker"].return_value
        mock_epics.start.assert_called_once()
        mock_analysis.start.assert_called_once()

    def test_stop_stops_workers(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.stop()
        mock_epics = mocks["HeadlessEpicsWorker"].return_value
        mock_analysis = mocks["HeadlessAnalysisWorker"].return_value
        mock_epics.request_stop.assert_called_once()
        mock_epics.stop.assert_called_once()
        mock_analysis.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Streaming toggle
# ---------------------------------------------------------------------------

class TestStreaming:

    def test_set_streaming(self, controller_env):
        ctrl, _ = controller_env
        ctrl.set_streaming(False)
        assert ctrl.streaming is False
        ctrl.set_streaming(True)
        assert ctrl.streaming is True

    def test_frames_dropped_when_paused(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.set_streaming(False)
        mock_analysis = mocks["HeadlessAnalysisWorker"].return_value
        # Directly call the frame handler
        ctrl._on_new_frame(np.zeros((10, 10)))
        mock_analysis.queue_frame.assert_not_called()


# ---------------------------------------------------------------------------
# Fitting toggle
# ---------------------------------------------------------------------------

class TestFitting:

    def test_set_fit_full(self, controller_env):
        ctrl, _ = controller_env
        ctrl.set_fit_full(False)
        assert ctrl.fit_full is False


# ---------------------------------------------------------------------------
# Frame pipeline
# ---------------------------------------------------------------------------

class TestFramePipeline:

    def test_on_new_frame_queues_to_analysis(self, controller_env):
        ctrl, mocks = controller_env
        mock_analysis = mocks["HeadlessAnalysisWorker"].return_value
        frame = np.zeros((10, 10), dtype=np.uint16)
        ctrl._on_new_frame(frame)
        mock_analysis.queue_frame.assert_called_once()
        queued = mock_analysis.queue_frame.call_args[0][0]
        assert isinstance(queued, FrameState)
        assert queued.frame_number == 1

    def test_on_analysis_done_emits_frame_ready(self, controller_env):
        ctrl, _ = controller_env
        cb = MagicMock()
        ctrl.dispatcher.register(EVT_FRAME_READY, cb)

        mock_bp = MagicMock()
        mock_bp.x_fit = None
        mock_bp.y_fit = None
        fs = FrameState(
            frame=np.zeros((10, 10)),
            frame_number=1,
            analysis=mock_bp,
        )
        ctrl._on_analysis_done(fs)
        cb.assert_called_once_with(fs)

    def test_on_connection_changed_emits(self, controller_env):
        ctrl, _ = controller_env
        cb = MagicMock()
        ctrl.dispatcher.register(EVT_CONNECTION_CHANGED, cb)
        ctrl._on_connection_changed(True)
        cb.assert_called_once_with(True)

    def test_on_error_emits(self, controller_env):
        ctrl, _ = controller_env
        cb = MagicMock()
        ctrl.dispatcher.register(EVT_ERROR, cb)
        ctrl._on_error("test error")
        cb.assert_called_once_with("test error")


# ---------------------------------------------------------------------------
# Background subtraction
# ---------------------------------------------------------------------------

class TestBackground:

    def test_acquire_background_flags_next_frame(self, controller_env):
        ctrl, _ = controller_env
        ctrl.acquire_background()
        assert ctrl._acquire_next_frame is True

    def test_background_captured_on_next_frame(self, controller_env):
        ctrl, mocks = controller_env
        mock_state = ctrl.state

        ctrl.acquire_background()
        frame = np.ones((10, 10), dtype=np.uint16) * 42

        # Configure save_background_to_file to return a path
        mocks["save_background_to_file"].return_value = Path("/tmp/bg.npy")

        ctrl._on_new_frame(frame)

        # Background should have been set
        assert ctrl._acquire_next_frame is False
        mock_state.store_background_for_prefix.assert_called()

    def test_bg_subtraction_applied(self, controller_env):
        ctrl, mocks = controller_env
        mock_state = ctrl.state
        mock_analysis = mocks["HeadlessAnalysisWorker"].return_value

        # Set up background
        bg = np.ones((10, 10), dtype=np.uint16) * 10
        mock_state.background_frame = bg
        mock_state.bg_subtraction_enabled = True

        frame = np.ones((10, 10), dtype=np.uint16) * 42
        ctrl._on_new_frame(frame)

        # The queued frame should be background-subtracted
        queued = mock_analysis.queue_frame.call_args[0][0]
        expected = np.ones((10, 10), dtype=np.uint16) * 32
        np.testing.assert_array_equal(queued.frame, expected)

    def test_bg_subtraction_clipped_to_zero(self, controller_env):
        ctrl, mocks = controller_env
        mock_state = ctrl.state
        mock_analysis = mocks["HeadlessAnalysisWorker"].return_value

        bg = np.ones((10, 10), dtype=np.uint16) * 100
        mock_state.background_frame = bg
        mock_state.bg_subtraction_enabled = True

        frame = np.ones((10, 10), dtype=np.uint16) * 10
        ctrl._on_new_frame(frame)

        queued = mock_analysis.queue_frame.call_args[0][0]
        np.testing.assert_array_equal(queued.frame, np.zeros((10, 10), dtype=np.uint16))

    def test_toggle_bg_subtraction(self, controller_env):
        ctrl, _ = controller_env
        cb = MagicMock()
        ctrl.dispatcher.register(EVT_BG_STATUS, cb)
        ctrl.toggle_bg_subtraction(True)
        assert ctrl.state.bg_subtraction_enabled is True or ctrl.state.bg_subtraction_enabled == True
        cb.assert_called()

    def test_save_background_returns_none_when_no_bg(self, controller_env):
        ctrl, _ = controller_env
        ctrl.state.background_frame = None
        assert ctrl.save_background() is None

    def test_load_background_nonexistent(self, controller_env):
        ctrl, _ = controller_env
        result = ctrl.load_background("/nonexistent/file.npy")
        assert result is False


# ---------------------------------------------------------------------------
# Prefix switching
# ---------------------------------------------------------------------------

class TestPrefixSwitch:

    def test_switch_prefix_updates_active(self, controller_env):
        ctrl, mocks = controller_env
        assert ctrl.active_prefix == "TEST"
        ctrl.switch_prefix("OTHER")
        assert ctrl.active_prefix == "OTHER"

    def test_switch_prefix_stops_old_worker(self, controller_env):
        ctrl, mocks = controller_env
        old_worker = mocks["HeadlessEpicsWorker"].return_value
        ctrl.switch_prefix("OTHER")
        old_worker.stop.assert_called_once()

    def test_switch_prefix_starts_new_worker(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.switch_prefix("OTHER")
        # HeadlessEpicsWorker called twice: once in __init__, once in switch
        assert mocks["HeadlessEpicsWorker"].call_count == 2

    def test_switch_prefix_saves_old_roi(self, controller_env):
        ctrl, mocks = controller_env
        ctrl._current_roi = (10, 20, 30, 40)
        ctrl.switch_prefix("OTHER")
        mocks["save_roi_for_prefix"].assert_called_with("TEST", (10, 20, 30, 40))

    def test_switch_prefix_clears_trending(self, controller_env):
        ctrl, _ = controller_env
        # Add a trending entry
        ctrl._trending_buffer.append({"frame_number": 1.0})
        assert ctrl._trending_buffer.count > 0
        ctrl.switch_prefix("OTHER")
        assert ctrl._trending_buffer.count == 0

    def test_switch_prefix_reloads_calibration(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.switch_prefix("OTHER")
        mocks["load_calibration"].assert_called_with("OTHER")


# ---------------------------------------------------------------------------
# ROI management
# ---------------------------------------------------------------------------

class TestROI:

    def test_set_roi_persists(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.set_roi((10, 20, 30, 40))
        assert ctrl.current_roi == (10, 20, 30, 40)
        mocks["save_roi_for_prefix"].assert_called_with("TEST", (10, 20, 30, 40))

    def test_set_roi_none(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.set_roi(None)
        assert ctrl.current_roi is None


# ---------------------------------------------------------------------------
# ROI fitting
# ---------------------------------------------------------------------------

class TestROIFit:

    def test_request_roi_fit_emits_result(self, controller_env):
        ctrl, mocks = controller_env

        mock_bp = MagicMock()
        mock_bp.x_fit = None
        mock_bp.y_fit = None
        mocks["analyze_frame"].return_value = mock_bp

        cb = MagicMock()
        ctrl.dispatcher.register(EVT_ROI_FIT_DONE, cb)

        roi_frame = np.ones((10, 10), dtype=np.float64)
        ctrl.request_roi_fit((5, 5, 15, 15), roi_frame)

        # Wait for background thread
        time.sleep(0.3)
        cb.assert_called_once_with(mock_bp)

    def test_roi_fit_skipped_when_already_running(self, controller_env):
        ctrl, mocks = controller_env
        ctrl._roi_fit_running = True
        roi_frame = np.ones((10, 10), dtype=np.float64)
        ctrl.request_roi_fit((0, 0, 10, 10), roi_frame)
        mocks["analyze_frame"].assert_not_called()


# ---------------------------------------------------------------------------
# Centroid / crosshair
# ---------------------------------------------------------------------------

class TestCentroid:

    def test_set_centroid_reference(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.set_centroid_reference(100.5, 200.3)
        assert ctrl.centroid_reference == (100.5, 200.3)
        mocks["save_centroid_reference"].assert_called_with("TEST", 100.5, 200.3)

    def test_clear_centroid_reference(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.set_centroid_reference(100.0, 200.0)
        ctrl.clear_centroid_reference()
        assert ctrl.centroid_reference is None
        mocks["clear_centroid_reference"].assert_called_with("TEST")

    def test_crosshair_toggle(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.set_crosshair_enabled(True)
        assert ctrl.crosshair_enabled is True
        mocks["save_crosshair_enabled"].assert_called_with(True)

    def test_live_roi_centroid(self, controller_env):
        ctrl, _ = controller_env
        ctrl.set_live_roi_centroid(50.0, 60.0)
        assert ctrl.live_roi_centroid == (50.0, 60.0)

    def test_on_analysis_done_updates_live_centroid_from_full_fit(
        self, controller_env
    ):
        """Drift tracking falls back to the full-image fit centroid."""
        ctrl, _ = controller_env

        mock_xfit = MagicMock(success=True, centroid=123.4)
        mock_yfit = MagicMock(success=True, centroid=234.5)
        mock_bp = MagicMock(x_fit=mock_xfit, y_fit=mock_yfit)
        analyzed_state = FrameState(
            frame=np.zeros((50, 50), dtype=np.uint16),
            frame_number=1,
            analysis=mock_bp,
            do_fit=True,
        )

        ctrl._on_analysis_done(analyzed_state)
        assert ctrl.live_roi_centroid == (123.4, 234.5)

    def test_on_analysis_done_skips_when_fit_failed(self, controller_env):
        """Failed fits must not corrupt the live centroid state."""
        ctrl, _ = controller_env
        ctrl.set_live_roi_centroid(10.0, 20.0)

        mock_bp = MagicMock(
            x_fit=MagicMock(success=False, centroid=999.0),
            y_fit=MagicMock(success=False, centroid=999.0),
        )
        analyzed_state = FrameState(
            frame=np.zeros((50, 50), dtype=np.uint16),
            frame_number=2,
            analysis=mock_bp,
            do_fit=True,
        )
        ctrl._on_analysis_done(analyzed_state)
        # Previous live centroid is preserved
        assert ctrl.live_roi_centroid == (10.0, 20.0)

    def test_request_roi_fit_updates_live_centroid_with_global_offset(
        self, controller_env
    ):
        """ROI fit centroids must be offset by (x0, y0) to land in full-frame coords."""
        ctrl, mocks = controller_env

        # ROI-local centroid (5, 7) inside an ROI starting at (100, 200)
        # → global frame coordinate (105, 207).
        mock_bp = MagicMock(
            x_fit=MagicMock(success=True, centroid=5.0),
            y_fit=MagicMock(success=True, centroid=7.0),
        )
        mocks["analyze_frame"].return_value = mock_bp

        roi_frame = np.ones((20, 20), dtype=np.float64)
        ctrl.request_roi_fit((100, 200, 120, 220), roi_frame)
        time.sleep(0.3)

        assert ctrl.live_roi_centroid == (105.0, 207.0)

    def test_on_analysis_done_clamps_negative_roi_before_request(
        self, controller_env
    ):
        """Negative ROI coordinates from disk must be clamped before slicing
        AND before being used as the centroid offset — otherwise drift is
        shifted by the difference between the stored and sliced origin."""
        ctrl, mocks = controller_env
        ctrl._fit_roi = True
        ctrl._current_roi = (-10, -20, 30, 40)  # loaded from a stale config

        # ROI-local centroid (2, 3) inside the clamped ROI that starts at (0, 0)
        # → global frame coordinate (2, 3).
        mock_bp = MagicMock(
            x_fit=MagicMock(success=True, centroid=2.0),
            y_fit=MagicMock(success=True, centroid=3.0),
        )
        mocks["analyze_frame"].return_value = mock_bp

        # _on_analysis_done triggers request_roi_fit internally
        frame_analysis = MagicMock(
            x_fit=MagicMock(success=False),  # suppress full-fit centroid update
            y_fit=MagicMock(success=False),
        )
        analyzed_state = FrameState(
            frame=np.zeros((100, 100), dtype=np.uint16),
            frame_number=1,
            analysis=frame_analysis,
            do_fit=True,
        )
        ctrl._on_analysis_done(analyzed_state)
        time.sleep(0.3)

        # Must be (2, 3), not (-8, -17) that a buggy unclamped offset would give
        assert ctrl.live_roi_centroid == (2.0, 3.0)


# ---------------------------------------------------------------------------
# Overlay settings
# ---------------------------------------------------------------------------

class TestOverlay:

    def test_set_overlay_settings(self, controller_env):
        ctrl, mocks = controller_env
        settings = {"h_enabled": True, "v_enabled": False}
        ctrl.set_overlay_settings(settings)
        assert ctrl.overlay_settings == settings
        mocks["save_overlay_settings"].assert_called_with(settings)


# ---------------------------------------------------------------------------
# Trending
# ---------------------------------------------------------------------------

class TestTrending:

    def test_trending_depth_change(self, controller_env):
        ctrl, _ = controller_env
        ctrl.set_trending_depth(100)
        assert ctrl._trending_buffer._max_len == 100

    def test_trending_record_appended_on_analysis(self, controller_env):
        ctrl, _ = controller_env
        cb = MagicMock()
        ctrl.dispatcher.register(EVT_TRENDING_UPDATE, cb)

        mock_bp = MagicMock()
        mock_bp.x_fit = None
        mock_bp.y_fit = None
        fs = FrameState(
            frame=np.zeros((10, 10)),
            frame_number=1,
            analysis=mock_bp,
        )
        ctrl._on_analysis_done(fs)
        cb.assert_called_once()
        assert ctrl._trending_buffer.count == 1

    def test_trending_with_fit_data(self, controller_env):
        ctrl, _ = controller_env

        mock_xf = MagicMock()
        mock_xf.success = True
        mock_xf.sigma_um = 42.0
        mock_xf.sigma = 10.0
        mock_xf.centroid = 100.0
        mock_yf = MagicMock()
        mock_yf.success = True
        mock_yf.sigma_um = 35.0
        mock_yf.sigma = 8.0
        mock_yf.centroid = 200.0

        mock_bp = MagicMock()
        mock_bp.x_fit = mock_xf
        mock_bp.y_fit = mock_yf

        fs = FrameState(
            frame=np.zeros((10, 10)),
            frame_number=1,
            analysis=mock_bp,
        )
        ctrl._on_analysis_done(fs)

        history = ctrl._trending_buffer.get_history()
        assert history["sigma_x"][0] == 42.0
        assert history["sigma_y"][0] == 35.0
        assert history["centroid_x"][0] == 100.0
        assert history["centroid_y"][0] == 200.0

    def test_drift_recorded_in_trending(self, controller_env):
        ctrl, _ = controller_env
        ctrl._centroid_reference = (50.0, 60.0)
        ctrl._live_roi_centroid = (52.0, 63.0)

        mock_bp = MagicMock()
        mock_bp.x_fit = None
        mock_bp.y_fit = None
        fs = FrameState(
            frame=np.zeros((10, 10)),
            frame_number=1,
            analysis=mock_bp,
        )
        ctrl._on_analysis_done(fs)

        history = ctrl._trending_buffer.get_history()
        np.testing.assert_almost_equal(history["drift_x"][0], 2.0)
        np.testing.assert_almost_equal(history["drift_y"][0], 3.0)


# ---------------------------------------------------------------------------
# Camera exposure / gain
# ---------------------------------------------------------------------------

class TestCameraControls:

    def test_set_exposure_calls_put(self, controller_env):
        ctrl, mocks = controller_env
        mocks["epics_put"].return_value = None
        mocks["epics_get"].return_value = np.array([0.5])

        ctrl.set_exposure(0.5)
        time.sleep(0.5)  # background thread

        mocks["epics_put"].assert_called_once()

    def test_set_gain_calls_put(self, controller_env):
        ctrl, mocks = controller_env
        mocks["epics_put"].return_value = None
        mocks["epics_get"].return_value = np.array([10])

        ctrl.set_gain(10)
        time.sleep(0.5)

        mocks["epics_put"].assert_called_once()

    def test_set_exposure_no_pv(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.state.exposure_pv = ""
        ctrl.set_exposure(1.0)
        time.sleep(0.3)
        mocks["epics_put"].assert_not_called()

    def test_set_gain_no_pv(self, controller_env):
        ctrl, mocks = controller_env
        ctrl.state.gain_pv = ""
        ctrl.set_gain(5)
        time.sleep(0.3)
        mocks["epics_put"].assert_not_called()


# ---------------------------------------------------------------------------
# Colormap
# ---------------------------------------------------------------------------

class TestColormap:

    def test_set_colormap(self, controller_env):
        ctrl, _ = controller_env
        ctrl.set_colormap("viridis")
        assert ctrl.state.colormap_name == "viridis"


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------

class TestIntrospection:

    def test_get_available_prefixes(self, controller_env):
        ctrl, mocks = controller_env
        result = ctrl.get_available_prefixes()
        assert result == ["TEST", "OTHER"]

    def test_get_bg_file_list(self, controller_env):
        ctrl, mocks = controller_env
        mocks["list_saved_backgrounds"].return_value = [Path("/a.npy")]
        result = ctrl.get_bg_file_list()
        assert result == [Path("/a.npy")]
