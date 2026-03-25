"""GUI smoke tests for BeamViewerWindow.

These tests verify that the GUI can be instantiated, that all key widgets
exist, and that critical public API methods work without crashing.  They
use pytest-qt's `qtbot` fixture which ensures a QApplication exists and
handles widget cleanup.

No real EPICS connection or camera is needed — frames are synthetic.
"""

from __future__ import annotations

import numpy as np
import pytest

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from gui.window import BeamViewerWindow
from gui.overlay_state import OverlayState
from analysis.calibration import Calibration
from core.state import FrameState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_window(qtbot, fallback_shape=(300, 300)) -> BeamViewerWindow:
    """Instantiate a BeamViewerWindow, register it with qtbot for cleanup."""
    win = BeamViewerWindow(fallback_shape=fallback_shape)
    qtbot.addWidget(win)
    return win


def _gaussian_frame(
    shape=(200, 200), center=(100, 100), sigma=15.0, amplitude=5000.0
) -> np.ndarray:
    rows, cols = shape
    y = np.arange(rows, dtype=np.float64)
    x = np.arange(cols, dtype=np.float64)
    X, Y = np.meshgrid(x, y)
    cx, cy = center
    frame = amplitude * np.exp(
        -0.5 * ((X - cx) ** 2 + (Y - cy) ** 2) / sigma ** 2
    ) + 100.0
    return frame.astype(np.uint16)


# ---------------------------------------------------------------------------
# Instantiation smoke tests
# ---------------------------------------------------------------------------

class TestWindowInstantiation:
    """The window must construct without errors."""

    def test_creates_without_error(self, qtbot):
        win = _make_window(qtbot)
        assert win is not None

    def test_title(self, qtbot):
        win = _make_window(qtbot)
        assert "Beam" in win.windowTitle()

    def test_has_control_panel(self, qtbot):
        win = _make_window(qtbot)
        assert win.control_panel is not None

    def test_has_two_image_panes(self, qtbot):
        win = _make_window(qtbot)
        assert win.image_pane_1 is not None
        assert win.image_pane_2 is not None

    def test_has_four_projection_plots(self, qtbot):
        win = _make_window(qtbot)
        assert win.h_proj_1 is not None
        assert win.v_proj_1 is not None
        assert win.h_proj_2 is not None
        assert win.v_proj_2 is not None

    def test_roi_pane_hidden_initially(self, qtbot):
        """ROI view should be invisible until user draws a selection."""
        win = _make_window(qtbot)
        assert not win.image_pane_2.isVisible()
        assert not win.h_proj_2.isVisible()
        assert not win.v_proj_2.isVisible()


# ---------------------------------------------------------------------------
# Control panel widget existence
# ---------------------------------------------------------------------------

class TestControlPanelWidgets:
    """Key control panel widgets must exist and be in the expected initial state."""

    def test_stream_btn_exists_and_checked(self, qtbot):
        win = _make_window(qtbot)
        assert win.control_panel.stream_btn is not None
        assert win.control_panel.stream_btn.isChecked()

    def test_fit_full_btn_exists_and_checked(self, qtbot):
        win = _make_window(qtbot)
        assert win.control_panel.fit_full_btn.isChecked()

    def test_fit_roi_btn_not_checked_initially(self, qtbot):
        win = _make_window(qtbot)
        assert not win.control_panel.fit_roi_btn.isChecked()

    def test_bg_subtract_disabled_initially(self, qtbot):
        win = _make_window(qtbot)
        assert not win.control_panel.bg_subtract_btn.isEnabled()

    def test_prefix_combo_exists(self, qtbot):
        win = _make_window(qtbot)
        assert win.control_panel.prefix_combo is not None

    def test_colormap_combo_has_items(self, qtbot):
        win = _make_window(qtbot)
        assert win.control_panel.colormap_combo.count() > 0

    def test_exposure_spinbox_exists(self, qtbot):
        win = _make_window(qtbot)
        assert win.control_panel.exposure_input is not None

    def test_gain_spinbox_exists(self, qtbot):
        win = _make_window(qtbot)
        assert win.control_panel.gain_input is not None


# ---------------------------------------------------------------------------
# Public API — controller-called methods
# ---------------------------------------------------------------------------

class TestPublicAPI:
    """Methods the controller calls must not crash and must update state."""

    def test_set_available_prefixes(self, qtbot):
        win = _make_window(qtbot)
        win.set_available_prefixes(["BL31", "BL72"], "BL72")
        assert win.control_panel.prefix_combo.count() == 2
        assert win.control_panel.prefix_combo.currentText() == "BL72"

    def test_set_bg_status_has_bg(self, qtbot):
        win = _make_window(qtbot)
        win.set_bg_status(has_bg=True, sub_enabled=True)
        assert win.control_panel.bg_subtract_btn.isEnabled()
        assert win.control_panel.bg_subtract_btn.isChecked()

    def test_set_bg_status_no_bg(self, qtbot):
        win = _make_window(qtbot)
        win.set_bg_status(has_bg=False, sub_enabled=False)
        assert not win.control_panel.bg_subtract_btn.isEnabled()

    def test_reset_bg_controls(self, qtbot):
        win = _make_window(qtbot)
        win.set_bg_status(has_bg=True, sub_enabled=True)
        win.reset_bg_controls()
        assert not win.control_panel.bg_subtract_btn.isEnabled()
        assert not win.control_panel.bg_subtract_btn.isChecked()

    def test_set_exposure_rbv(self, qtbot):
        win = _make_window(qtbot)
        win.set_exposure_rbv(0.25)
        assert win.control_panel.exposure_input.value() == pytest.approx(0.25)

    def test_set_gain_rbv(self, qtbot):
        win = _make_window(qtbot)
        win.set_gain_rbv(10)
        assert win.control_panel.gain_input.value() == 10

    def test_set_calibration(self, qtbot):
        win = _make_window(qtbot)
        cal = Calibration(um_per_pixel=2.0, unit_label="µm", is_calibrated=True)
        win.set_calibration(cal)  # must not raise
        assert win._calibration == cal

    def test_set_bg_file_list(self, qtbot):
        from pathlib import Path
        win = _make_window(qtbot)
        files = [Path("/tmp/fake.npy")]
        win.set_bg_file_list(files)
        assert win._bg_file_list_for_dialog == files

    def test_restore_roi_none(self, qtbot):
        win = _make_window(qtbot)
        win.restore_roi(None)  # must not raise, ROI panes stay hidden
        assert not win.image_pane_2.isVisible()

    def test_restore_roi_tuple(self, qtbot):
        win = _make_window(qtbot)
        win.restore_roi((10, 10, 50, 50))
        # isVisible() returns False on a not-yet-shown window even if setVisible(True)
        # was called, so check isHidden() instead (setVisible sets hidden=False).
        assert not win.image_pane_2.isHidden()

    def test_get_current_roi_none_initially(self, qtbot):
        win = _make_window(qtbot)
        assert win.get_current_roi() is None


# ---------------------------------------------------------------------------
# update_display
# ---------------------------------------------------------------------------

class TestUpdateDisplay:
    """The main display update path must not crash on valid frame data."""

    def test_update_display_no_analysis(self, qtbot):
        win = _make_window(qtbot)
        frame = _gaussian_frame()
        fs = FrameState(frame=frame, frame_number=1, analysis=None, do_fit=False)
        win.update_display(fs)  # must not raise
        assert win._last_frame_number == 1

    def test_update_display_with_analysis(self, qtbot):
        from analysis.analysis import analyze_frame
        win = _make_window(qtbot)
        frame = _gaussian_frame()
        bp = analyze_frame(frame, do_fit=True)
        fs = FrameState(frame=frame, frame_number=5, analysis=bp, do_fit=True)
        win.update_display(fs)
        assert win._last_frame_number == 5

    def test_frame_label_updates(self, qtbot):
        win = _make_window(qtbot)
        frame = _gaussian_frame()
        fs = FrameState(frame=frame, frame_number=42, analysis=None, do_fit=False)
        win.update_display(fs)
        assert "42" in win.frame_label.text()

    def test_update_display_flat_frame(self, qtbot):
        """A flat (no beam) frame should not crash, even when fitting is on."""
        from analysis.analysis import analyze_frame
        win = _make_window(qtbot)
        frame = np.full((100, 100), 500, dtype=np.uint16)
        bp = analyze_frame(frame, do_fit=True)
        fs = FrameState(frame=frame, frame_number=1, analysis=bp, do_fit=True)
        win.update_display(fs)  # must not raise


# ---------------------------------------------------------------------------
# Theme toggle
# ---------------------------------------------------------------------------

class TestThemeToggle:
    def test_toggle_theme_switches(self, qtbot):
        win = _make_window(qtbot)
        initial_name = win._theme.name
        win.toggle_theme()
        assert win._theme.name != initial_name

    def test_toggle_theme_twice_returns_to_original(self, qtbot):
        win = _make_window(qtbot)
        original = win._theme.name
        win.toggle_theme()
        win.toggle_theme()
        assert win._theme.name == original


# ---------------------------------------------------------------------------
# Signal emissions
# ---------------------------------------------------------------------------

class TestSignalEmissions:
    """Key user interactions should emit the expected signals."""

    def test_stream_btn_emits_streaming_toggled(self, qtbot):
        win = _make_window(qtbot)
        with qtbot.waitSignal(win.streaming_toggled, timeout=1000) as blocker:
            win.control_panel.stream_btn.click()
        assert isinstance(blocker.args[0], bool)

    def test_fit_full_btn_emits_fit_full_toggled(self, qtbot):
        win = _make_window(qtbot)
        with qtbot.waitSignal(win.fit_full_toggled, timeout=1000) as blocker:
            win.control_panel.fit_full_btn.click()
        assert isinstance(blocker.args[0], bool)

    def test_acquire_bg_btn_emits_signal(self, qtbot):
        win = _make_window(qtbot)
        with qtbot.waitSignal(win.acquire_background_requested, timeout=1000):
            win.control_panel.acquire_bg_btn.click()

    def test_prefix_change_emits_signal(self, qtbot):
        win = _make_window(qtbot)
        win.set_available_prefixes(["BL31", "BL72"], "BL31")
        with qtbot.waitSignal(win.prefix_change_requested, timeout=1000) as blocker:
            win.control_panel.prefix_combo.setCurrentIndex(1)
        assert blocker.args[0] == "BL72"


# ---------------------------------------------------------------------------
# Overlay state
# ---------------------------------------------------------------------------

class TestOverlayState:
    def test_restore_overlay_state_no_crash(self, qtbot):
        win = _make_window(qtbot)
        state = OverlayState(h_enabled=True, h_side="top", v_enabled=False,
                             v_side="left", scale=0.3, show_full=True, show_roi=False)
        win.restore_overlay_state(state)
        assert win._overlay_state.h_enabled is True
        assert win._overlay_state.scale == pytest.approx(0.3)

    def test_overlay_state_default(self, qtbot):
        win = _make_window(qtbot)
        state = win.overlay_state
        assert isinstance(state, OverlayState)
