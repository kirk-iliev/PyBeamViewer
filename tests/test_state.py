"""Tests for core.state — AppState and FrameState."""

from __future__ import annotations

import threading
from unittest.mock import patch

import numpy as np
import pytest

from analysis.analysis import BeamParameters
from core.state import AppState, FrameState


# ---------------------------------------------------------------------------
# Mock config so AppState.__init__ doesn't require real config.json
# ---------------------------------------------------------------------------

_MOCK_PV_NAMES = {
    "image_pv": "TEST:image",
    "width_pv": "TEST:width",
    "height_pv": "TEST:height",
    "exposure_pv": "TEST:exp",
    "exposure_rbv_pv": "TEST:exp_rbv",
    "gain_pv": "TEST:gain",
    "gain_rbv_pv": "TEST:gain_rbv",
    "fallback_shape": [300, 300],
}

_MOCK_EPICS_CONN = {"host": "127.0.0.1", "port": 15064}

_MOCK_DISPLAY = {
    "enable_fitting": True,
    "auto_levels": True,
    "levels_interval": 30,
    "colormap_name": "hot",
}


@pytest.fixture
def app_state():
    """Return an AppState constructed with mocked config functions."""
    with patch("core.state.get_epics_connection", return_value=_MOCK_EPICS_CONN), \
         patch("core.state.get_pv_names", return_value=_MOCK_PV_NAMES), \
         patch("core.state.get_display_settings", return_value=_MOCK_DISPLAY):
        yield AppState()


# ===================================================================
# FrameState
# ===================================================================

class TestFrameState:
    """Tests for the immutable FrameState dataclass."""

    def test_creation_defaults(self):
        frame = np.zeros((10, 10), dtype=np.uint16)
        fs = FrameState(frame=frame, frame_number=1)
        assert fs.analysis is None
        assert fs.do_fit is True
        assert fs.frame_number == 1
        np.testing.assert_array_equal(fs.frame, frame)

    def test_frozen(self):
        frame = np.zeros((10, 10), dtype=np.uint16)
        fs = FrameState(frame=frame, frame_number=1)
        with pytest.raises(AttributeError):
            fs.frame_number = 2  # type: ignore[misc]

    def test_with_analysis(self):
        frame = np.zeros((10, 10), dtype=np.uint16)
        bp = BeamParameters(
            x_projection=np.zeros(10),
            y_projection=np.zeros(10),
        )
        fs = FrameState(frame=frame, frame_number=5, analysis=bp, do_fit=False)
        assert fs.analysis is bp
        assert fs.do_fit is False


# ===================================================================
# AppState properties
# ===================================================================

class TestAppStateProperties:
    """Test lock-protected property getters/setters."""

    def test_frame_state_roundtrip(self, app_state):
        assert app_state.frame_state is None
        frame = np.zeros((10, 10), dtype=np.uint16)
        fs = FrameState(frame=frame, frame_number=42)
        app_state.frame_state = fs
        assert app_state.frame_state.frame_number == 42

    def test_connected_roundtrip(self, app_state):
        assert app_state.connected is False
        app_state.connected = True
        assert app_state.connected is True

    def test_bg_subtraction_enabled_roundtrip(self, app_state):
        assert app_state.bg_subtraction_enabled is False
        app_state.bg_subtraction_enabled = True
        assert app_state.bg_subtraction_enabled is True

    def test_background_frame_roundtrip(self, app_state):
        assert app_state.background_frame is None
        bg = np.ones((50, 50), dtype=np.uint16) * 100
        app_state.background_frame = bg
        np.testing.assert_array_equal(app_state.background_frame, bg)
        app_state.background_frame = None
        assert app_state.background_frame is None


# ===================================================================
# increment_frame_count
# ===================================================================

class TestFrameCount:
    """Tests for the atomic frame counter."""

    def test_monotonic_increment(self, app_state):
        assert app_state.frame_count == 0
        assert app_state.increment_frame_count() == 1
        assert app_state.increment_frame_count() == 2
        assert app_state.frame_count == 2

    def test_thread_safety(self, app_state):
        """Concurrent increments should not lose counts."""
        n_threads = 10
        increments_per_thread = 100

        def _inc():
            for _ in range(increments_per_thread):
                app_state.increment_frame_count()

        threads = [threading.Thread(target=_inc) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert app_state.frame_count == n_threads * increments_per_thread


# ===================================================================
# Per-prefix background cache
# ===================================================================

class TestPerPrefixBackground:
    """Tests for per-prefix background storage and retrieval."""

    def test_store_and_get(self, app_state):
        bg = np.ones((50, 50), dtype=np.uint16) * 200
        app_state.store_background_for_prefix("BL31", bg)
        result = app_state.get_background_for_prefix("BL31")
        np.testing.assert_array_equal(result, bg)

    def test_missing_prefix_returns_none(self, app_state):
        assert app_state.get_background_for_prefix("NONEXISTENT") is None

    def test_multiple_prefixes(self, app_state):
        bg1 = np.ones((10, 10), dtype=np.uint16) * 1
        bg2 = np.ones((10, 10), dtype=np.uint16) * 2
        app_state.store_background_for_prefix("A", bg1)
        app_state.store_background_for_prefix("B", bg2)

        np.testing.assert_array_equal(
            app_state.get_background_for_prefix("A"), bg1
        )
        np.testing.assert_array_equal(
            app_state.get_background_for_prefix("B"), bg2
        )

    def test_bg_enabled_roundtrip(self, app_state):
        assert app_state.get_bg_enabled_for_prefix("X") is False
        app_state.store_bg_enabled_for_prefix("X", True)
        assert app_state.get_bg_enabled_for_prefix("X") is True
        app_state.store_bg_enabled_for_prefix("X", False)
        assert app_state.get_bg_enabled_for_prefix("X") is False


# ===================================================================
# update_connection_config
# ===================================================================

class TestUpdateConnectionConfig:
    """Tests for the atomic PV-config update."""

    def test_updates_all_fields(self, app_state):
        new_pvs = {
            "image_pv": "NEW:img",
            "width_pv": "NEW:w",
            "height_pv": "NEW:h",
            "exposure_pv": "NEW:exp",
            "exposure_rbv_pv": "NEW:exp_rbv",
            "gain_pv": "NEW:g",
            "gain_rbv_pv": "NEW:g_rbv",
            "fallback_shape": [512, 640],
        }
        app_state.update_connection_config(new_pvs)

        assert app_state.image_pv == "NEW:img"
        assert app_state.width_pv == "NEW:w"
        assert app_state.height_pv == "NEW:h"
        assert app_state.exposure_pv == "NEW:exp"
        assert app_state.fallback_shape == (512, 640)

    def test_missing_optional_fields(self, app_state):
        """Optional PVs should default to empty strings."""
        new_pvs = {
            "image_pv": "MIN:img",
            "width_pv": "MIN:w",
            "height_pv": "MIN:h",
        }
        app_state.update_connection_config(new_pvs)
        assert app_state.exposure_pv == ""
        assert app_state.gain_pv == ""
        assert app_state.fallback_shape is None

    def test_init_reads_from_config(self, app_state):
        """__init__ should populate fields from mocked config."""
        assert app_state.host == "127.0.0.1"
        assert app_state.port == 15064
        assert app_state.image_pv == "TEST:image"
        assert app_state.fallback_shape == (300, 300)
        assert app_state.colormap_name == "hot"
