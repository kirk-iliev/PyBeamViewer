"""
BeamViewerWindow — main application window (pure View layer).

Implements the Beam Profile Viewer display window matching the reference
layout:

    ┌────────────┬──────────────────────┬──────────────┐
    │ Full Image │ H Projection (Full)  │              │
    │ (+ ROI     │ V Projection (Full)  │  Control     │
    │  overlay)  ├──────────────────────┤  Panel       │
    ├────────────┤ H Projection (ROI)   │              │
    │  ROI crop  │ V Projection (ROI)   │              │
    └────────────┴──────────────────────┴──────────────┘

Click and drag the ROI rectangle on the full image to select a region of
interest.  The cropped ROI is shown in the bottom-left pane with its own
horizontal and vertical projections.

The view is **passive** — it exposes ``update_display(FrameState)``
which the controller calls whenever new data is ready.  It never touches
the network or analysis layers directly.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import replace
from typing import Optional

import numpy as np
from PyQt5.QtCore import QEvent, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from analysis.analysis import compute_projections
from analysis.calibration import Calibration
from core.state import FrameState

from .control_panel import ControlPanel
from .dialogs import LoadBackgroundDialog
from .image_pane import ImagePane
from .overlay_state import OverlayState
from .projection_plot import ProjectionPlot
from .theme import DARK, LIGHT, Theme, _MONO
from .trending_panel import TrendingPanel


@contextmanager
def _block_signals(*widgets):
    """Block Qt signals on *widgets* for the duration of the context."""
    for w in widgets:
        w.blockSignals(True)
    try:
        yield
    finally:
        for w in widgets:
            w.blockSignals(False)


class BeamViewerWindow(QMainWindow):
    """Main application window (pure View)."""

    closing = pyqtSignal()
    prefix_change_requested = pyqtSignal(str)
    exposure_set_requested = pyqtSignal(float)
    gain_set_requested = pyqtSignal(int)
    streaming_toggled = pyqtSignal(bool)
    colormap_changed = pyqtSignal(str)
    fit_full_toggled = pyqtSignal(bool)
    roi_changed = pyqtSignal(object)  # (x0, y0, x1, y1) tuple or None when cleared
    center_roi_requested = pyqtSignal()
    acquire_background_requested = pyqtSignal()
    bg_subtraction_toggled = pyqtSignal(bool)
    save_background_requested = pyqtSignal()
    load_background_requested = pyqtSignal(str)   # carries the .npy file path
    overlay_settings_changed = pyqtSignal(object)  # OverlayState
    roi_fit_requested = pyqtSignal(object, np.ndarray)  # (roi_coords_tuple, roi_frame_copy)
    centroid_reference_changed = pyqtSignal(float, float)  # (cx, cy) after Center ROI
    crosshair_toggled = pyqtSignal(bool)  # crosshair visibility toggle
    trending_depth_changed = pyqtSignal(int)  # history depth in frames

    def __init__(self, fallback_shape: Optional[tuple] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme: Theme = DARK
        self._fallback_shape = fallback_shape  # (height, width) for axis ranges
        self._overlay_state = OverlayState()
        self._bg_file_list_for_dialog: list = []
        self._calibration: Calibration = Calibration()  # uncalibrated default
        self._centroid_reference: Optional[tuple] = None  # (cx, cy) in full-image coords
        self._crosshair_enabled: bool = False
        self._live_roi_centroid: Optional[tuple] = None  # updated each frame
        self._trending_visible: bool = False

        self.setWindowTitle("Beam Profile Viewer")
        self.resize(1500, 920)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(0)

        # === outer splitter: [images + plots] | [control panel] ===
        outer = QSplitter(Qt.Horizontal)
        outer.setHandleWidth(3)
        root_layout.addWidget(outer)

        # --- left+centre area (images + projections) ---
        inner = QSplitter(Qt.Horizontal)
        inner.setHandleWidth(3)

        #  ┌── images column ──┐
        img_col = QWidget()
        img_lay = QVBoxLayout(img_col)
        img_lay.setContentsMargins(0, 0, 0, 0)
        img_lay.setSpacing(4)

        self.image_pane_1 = ImagePane("Full Image", self._theme, enable_roi=True)
        self.image_pane_2 = ImagePane("ROI", self._theme)

        self._last_frame: Optional[np.ndarray] = None
        self._last_frame_number: int = 0
        # Frame rate tracking
        self._start_time: Optional[float] = None
        self._last_frame_time: Optional[float] = None

        # ROI selection: _on_roi_changed handles visibility + persistence
        self.image_pane_1.roi_changed.connect(self._on_roi_changed)

        img_lay.addWidget(self.image_pane_1, stretch=1)
        img_lay.addWidget(self.image_pane_2, stretch=1)

        self.drift_label = QLabel("")
        self.drift_label.setAlignment(Qt.AlignCenter)
        self.drift_label.hide()
        img_lay.addWidget(self.drift_label)

        inner.addWidget(img_col)

        #  ┌── projections column ──┐
        proj_col = QWidget()
        proj_lay = QVBoxLayout(proj_col)
        proj_lay.setContentsMargins(0, 0, 0, 0)
        proj_lay.setSpacing(4)

        self.h_proj_1 = ProjectionPlot(
            "Horizontal Projection  (Full Image)", "h", self._theme,
        )
        self.v_proj_1 = ProjectionPlot(
            "Vertical Projection  (Full Image)", "v", self._theme,
        )
        self.h_proj_2 = ProjectionPlot(
            "Horizontal Projection  (ROI)", "h", self._theme,
        )
        self.v_proj_2 = ProjectionPlot(
            "Vertical Projection  (ROI)", "v", self._theme,
        )

        proj_lay.addWidget(self.h_proj_1, stretch=1)
        proj_lay.addWidget(self.v_proj_1, stretch=1)
        proj_lay.addWidget(self.h_proj_2, stretch=1)
        proj_lay.addWidget(self.v_proj_2, stretch=1)
        inner.addWidget(proj_col)

        #  ┌── trending panel ──┐  (initially hidden)
        self.trending_panel = TrendingPanel(self._theme)
        self.trending_panel.hide()
        inner.addWidget(self.trending_panel)

        inner.setStretchFactor(0, 2)   # images
        inner.setStretchFactor(1, 3)   # projections
        inner.setStretchFactor(2, 2)   # trending

        # ROI section (bottom pane + ROI projections) hidden until the user
        # draws a selection on the full image.
        self.image_pane_2.hide()
        self.h_proj_2.hide()
        self.v_proj_2.hide()

        outer.addWidget(inner)

        #  ┌── control panel (right) ──┐
        self.control_panel = ControlPanel(self._theme)
        outer.addWidget(self.control_panel)


        self._wire_control_signals()

        # Track last confirmed RBV values so spinboxes can be reverted
        self._last_confirmed_exposure: float = self.control_panel.exposure_input.value()
        self._last_confirmed_gain: int = self.control_panel.gain_input.value()

        # Escape key on either spinbox reverts to last confirmed value
        self.control_panel.exposure_input.installEventFilter(self)
        self.control_panel.gain_input.installEventFilter(self)

        outer.setStretchFactor(0, 5)
        outer.setStretchFactor(1, 1)

        # --- status bar ---
        self.frame_label = QLabel("Frame: 0")
        self.statusBar().addPermanentWidget(self.frame_label)

        self._theme_btn = QPushButton("☀  Light")
        self._theme_btn.setFixedHeight(22)
        self._theme_btn.setCursor(Qt.PointingHandCursor)
        self._theme_btn.clicked.connect(self.toggle_theme)
        self.statusBar().addWidget(self._theme_btn)

        # Apply initial theme (sets all stylesheets)
        self._apply_theme(self._theme)

    # ------------------------------------------------------------------
    # Control-panel signal wiring
    # ------------------------------------------------------------------

    def _wire_control_signals(self) -> None:
        """Connect control-panel widget signals to window signals/slots."""
        cp = self.control_panel
        cp.prefix_combo.currentTextChanged.connect(
            self.prefix_change_requested.emit,
        )
        cp.exposure_input.valueChanged.connect(
            lambda _: self._mark_spinbox_pending(cp.exposure_input),
        )
        cp.gain_input.valueChanged.connect(
            lambda _: self._mark_spinbox_pending(cp.gain_input),
        )
        cp.exposure_set_btn.clicked.connect(
            lambda: self.exposure_set_requested.emit(cp.exposure_input.value()),
        )
        cp.gain_set_btn.clicked.connect(
            lambda: self.gain_set_requested.emit(cp.gain_input.value()),
        )
        cp.stream_btn.toggled.connect(self._on_stream_toggled)
        cp.fit_full_btn.toggled.connect(self._on_fit_full_toggled)
        cp.fit_roi_btn.toggled.connect(self._on_fit_roi_toggled)
        cp.clear_roi_btn.clicked.connect(self._on_clear_roi_clicked)
        cp.center_roi_btn.clicked.connect(self._on_center_roi_clicked)
        cp.colormap_combo.currentTextChanged.connect(
            self.colormap_changed.emit,
        )
        cp.acquire_bg_btn.clicked.connect(self.acquire_background_requested.emit)
        cp.bg_subtract_btn.toggled.connect(self._on_bg_subtraction_toggled)
        cp.save_bg_btn.clicked.connect(self.save_background_requested.emit)
        cp.load_bg_btn.clicked.connect(self._on_load_bg_clicked)

        # Overlay controls
        cp.show_crosshair_btn.toggled.connect(self._on_crosshair_toggled)

        cp.h_overlay_btn.toggled.connect(self._on_overlay_changed)
        cp.h_overlay_side.currentTextChanged.connect(
            lambda _: self._on_overlay_changed(),
        )
        cp.v_overlay_btn.toggled.connect(self._on_overlay_changed)
        cp.v_overlay_side.currentTextChanged.connect(
            lambda _: self._on_overlay_changed(),
        )
        cp.overlay_scale_slider.valueChanged.connect(self._on_overlay_scale_changed)
        cp.overlay_show_full_btn.toggled.connect(self._on_overlay_changed)
        cp.overlay_show_roi_btn.toggled.connect(self._on_overlay_changed)

        # Trending panel controls
        cp.trending_btn.toggled.connect(self._on_trending_toggled)
        cp.trending_depth_input.valueChanged.connect(
            self.trending_depth_changed.emit,
        )

    # ------------------------------------------------------------------
    # Theme toggle
    # ------------------------------------------------------------------

    @pyqtSlot()
    def toggle_theme(self) -> None:
        """Switch between dark and light mode."""
        self._apply_theme(LIGHT if self._theme.name == "dark" else DARK)

    def _apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme.palette())
        self.setStyleSheet(theme.stylesheet())

        self.frame_label.setStyleSheet(
            f"color: {theme.text_dim}; font-size: 12px; padding: 2px 8px;"
        )

        # Toggle button label + style
        self._theme_btn.setText("☀  Light" if theme.name == "dark" else "🌙  Dark")
        self._theme_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.panel_bg}; color: {theme.accent}; "
            f"border: 1px solid {theme.border}; border-radius: 9px; "
            f"padding: 2px 10px; font-size: 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {theme.accent}; color: {theme.bg}; }}"
        )

        for plot in (self.h_proj_1, self.v_proj_1, self.h_proj_2, self.v_proj_2):
            plot.apply_theme(theme)

        for pane in (self.image_pane_1, self.image_pane_2):
            pane.apply_theme(theme)

        self.trending_panel.apply_theme(theme)

        self.drift_label.setStyleSheet(
            f"color: #00cc44; font-size: 11px; font-family: {_MONO}; "
            f"font-weight: 600; padding: 2px 0px;"
        )

        self.control_panel.apply_theme(theme)

        # Refresh bg status label colour with new theme colours
        has_bg = self.control_panel.bg_status_label.property("has_bg") or False
        sub_on = self.control_panel.bg_subtract_btn.isChecked()
        self._update_bg_status_label(has_bg, sub_on)

    # ------------------------------------------------------------------
    # Control-panel slot handlers
    # ------------------------------------------------------------------

    def _on_stream_toggled(self, checked: bool) -> None:
        """Update button text, color, and emit streaming signal."""
        if checked:
            self.control_panel.stream_btn.setText("Streaming")
            # Green background for streaming
            self.control_panel.stream_btn.setStyleSheet(
                f"QPushButton {{ background-color: #2ecc71; color: #ffffff; font-weight: 600; }}"
            )
        else:
            self.control_panel.stream_btn.setText("Paused")
            # Red background for paused
            self.control_panel.stream_btn.setStyleSheet(
                f"QPushButton {{ background-color: #e74c3c; color: #ffffff; font-weight: 600; }}"
            )
        self.streaming_toggled.emit(checked)

    def _on_bg_subtraction_toggled(self, checked: bool) -> None:
        self.control_panel.bg_subtract_btn.setText(
            "✓  Background Sub ON" if checked else "Background Sub OFF"
        )
        self.bg_subtraction_toggled.emit(checked)
        # Refresh the status label text to reflect the new state
        has_bg = self.control_panel.bg_status_label.property("has_bg") or False
        self._update_bg_status_label(has_bg, checked)

    def _on_overlay_changed(self, _checked: bool = False) -> None:
        """Read the overlay controls, update state, refresh overlays, and emit."""
        cp = self.control_panel
        h_on = cp.h_overlay_btn.isChecked()
        v_on = cp.v_overlay_btn.isChecked()
        cp.h_overlay_btn.setText("✓  H Overlay" if h_on else "H Overlay")
        cp.v_overlay_btn.setText("✓  V Overlay" if v_on else "V Overlay")
        cp.h_overlay_side.setEnabled(h_on)
        cp.v_overlay_side.setEnabled(v_on)

        show_full = cp.overlay_show_full_btn.isChecked()
        show_roi = cp.overlay_show_roi_btn.isChecked()
        cp.overlay_show_full_btn.setText("✓  Full" if show_full else "Full")
        cp.overlay_show_roi_btn.setText("✓  ROI" if show_roi else "ROI")

        self._overlay_state = replace(
            self._overlay_state,
            h_enabled=h_on,
            h_side=cp.h_overlay_side.currentText().lower(),
            v_enabled=v_on,
            v_side=cp.v_overlay_side.currentText().lower(),
            show_full=show_full,
            show_roi=show_roi,
        )

        self._refresh_overlays()
        self.overlay_settings_changed.emit(self._overlay_state)

    def _on_overlay_scale_changed(self, value: int) -> None:
        """Update overlay scale from the slider (5–50 → 0.05–0.50)."""
        self._overlay_state = replace(self._overlay_state, scale=value / 100.0)
        self.control_panel.overlay_scale_label.setText(f"{value}%")
        self._refresh_overlays()
        self.overlay_settings_changed.emit(self._overlay_state)

    def _refresh_overlays(self) -> None:
        """Recompute and redraw projection overlays on both image panes."""
        if self._last_frame is None:
            return
        frame = self._last_frame
        h, w = frame.shape[:2]

        # Full-image pane
        if self._overlay_state.show_full:
            x_proj = np.mean(frame, axis=0)
            y_proj = np.mean(frame, axis=1)
            self.image_pane_1.update_projections(x_proj, y_proj, (h, w), self._overlay_state)
        else:
            self.image_pane_1.clear_projections()

        # ROI pane
        if self._overlay_state.show_roi:
            roi_frame = self.image_pane_1.get_roi_slice(frame)
            if roi_frame is not None and roi_frame.size > 0:
                roi = self.image_pane_1.current_roi
                rx0, ry0 = (roi[0], roi[1]) if roi is not None else (0, 0)
                roi_x = np.mean(roi_frame, axis=0)
                roi_y = np.mean(roi_frame, axis=1)
                self.image_pane_2.update_projections(
                    roi_x, roi_y, roi_frame.shape[:2], self._overlay_state,
                    x_offset=float(rx0), y_offset=float(ry0),
                )
            else:
                self.image_pane_2.clear_projections()
        else:
            self.image_pane_2.clear_projections()

    def _on_crosshair_toggled(self, checked: bool) -> None:
        self._crosshair_enabled = checked
        self.control_panel.show_crosshair_btn.setText(
            "✓  Show Centroid Ref" if checked else "Show Centroid Ref"
        )
        self._update_crosshair_display(self._live_roi_centroid)
        self.trending_panel.set_drift_visible(checked)
        self.crosshair_toggled.emit(checked)

    def _on_trending_toggled(self, checked: bool) -> None:
        """Show or hide the trending panel."""
        self._trending_visible = checked
        self.trending_panel.setVisible(checked)
        self.control_panel.trending_btn.setText(
            "✓  📈  Trending" if checked else "📈  Trending"
        )
        self.control_panel.trending_depth_input.setEnabled(checked)
        if not checked:
            self.trending_panel.clear()

    def _on_fit_full_toggled(self, checked: bool) -> None:
        self.control_panel.fit_full_btn.setText(
            "✓  Fit Full Image" if checked else "Fit Full Image"
        )
        self.trending_panel.set_fit_full_visible(checked)
        self.fit_full_toggled.emit(checked)

    def _on_fit_roi_toggled(self, checked: bool) -> None:
        self.control_panel.fit_roi_btn.setText(
            "✓  Fit ROI" if checked else "Fit ROI"
        )
        self.trending_panel.set_fit_roi_visible(checked)
        # ROI fitting is handled entirely in the GUI; just refresh
        self._update_roi()

    @pyqtSlot("QVariant")
    def _on_set_roi(self, roi: object) -> None:
        """Set the ROI programmatically (called from the API bridge)."""
        x0, y0, x1, y1 = roi  # type: ignore[misc]
        self.image_pane_1.set_roi((int(x0), int(y0), int(x1), int(y1)))

    @pyqtSlot()
    def _on_clear_roi_clicked(self) -> None:
        self.image_pane_1.clear_roi()

    @pyqtSlot()
    def _on_center_roi_clicked(self) -> None:
        """Re-center the ROI as a square around the intensity-weighted centroid."""
        if self._last_frame is None:
            return
        roi = self.image_pane_1.current_roi
        if roi is None:
            return
        x0, y0, x1, y1 = roi
        # Clamp to frame bounds
        fh, fw = self._last_frame.shape[:2]
        x0c = max(0, x0);  y0c = max(0, y0)
        x1c = min(fw, x1); y1c = min(fh, y1)
        if x1c <= x0c or y1c <= y0c:
            return

        patch = self._last_frame[y0c:y1c, x0c:x1c].astype(np.float64)
        total = patch.sum()
        if total <= 0:
            return

        # Intensity-weighted centroid in full-image coordinates
        col_idx = np.arange(x0c, x1c, dtype=np.float64)
        row_idx = np.arange(y0c, y1c, dtype=np.float64)
        cx = int(round(np.dot(patch.sum(axis=0), col_idx) / total))
        cy = int(round(np.dot(patch.sum(axis=1), row_idx) / total))

        # Square half-side from the user-set ROI size (full side length)
        half = self.control_panel.roi_size_input.value() // 2

        # New ROI clamped to image bounds
        nx0 = max(0,  cx - half)
        ny0 = max(0,  cy - half)
        nx1 = min(fw, cx + half)
        ny1 = min(fh, cy + half)

        self.image_pane_1.set_roi((nx0, ny0, nx1, ny1))

        # Save centroid reference for crosshair / drift tracking
        self._centroid_reference = (float(cx), float(cy))
        self.centroid_reference_changed.emit(float(cx), float(cy))
        self.control_panel.show_crosshair_btn.setEnabled(True)
        self._update_crosshair_display(self._live_roi_centroid)

    # ------------------------------------------------------------------
    # Background subtraction UI
    # ------------------------------------------------------------------

    def _update_bg_status_label(self, has_bg: bool, sub_enabled: bool) -> None:
        """Internal helper — update bg_status_label text and colour."""
        if not has_bg:
            text = "BG: none"
            style = f"color: {self._theme.text_dim}; font-size: 11px; font-family: {_MONO};"
        elif sub_enabled:
            text = "BG: acquired  |  Sub: ON"
            style = f"color: {self._theme.accent}; font-size: 11px; font-family: {_MONO}; font-weight: 600;"
        else:
            text = "BG: acquired  |  Sub: OFF"
            style = f"color: {self._theme.text_dim}; font-size: 11px; font-family: {_MONO};"
        self.control_panel.bg_status_label.setText(text)
        self.control_panel.bg_status_label.setStyleSheet(style)
        self.control_panel.bg_status_label.setProperty("has_bg", has_bg)

    def set_bg_status(self, has_bg: bool, sub_enabled: bool) -> None:
        """Called by the controller after background acquisition or toggle.

        Enables/disables the subtraction toggle and updates the status label.
        Does NOT emit any signal (controller-driven update).
        """
        self.control_panel.bg_subtract_btn.setEnabled(has_bg)
        self.control_panel.save_bg_btn.setEnabled(has_bg)
        with _block_signals(self.control_panel.bg_subtract_btn):
            self.control_panel.bg_subtract_btn.setChecked(sub_enabled)
            self.control_panel.bg_subtract_btn.setText(
                "✓  Background Sub ON" if sub_enabled else "Background Sub OFF"
            )
        self._update_bg_status_label(has_bg, sub_enabled)

    def reset_bg_controls(self) -> None:
        """Reset all background controls to their initial state (e.g. on camera switch)."""
        with _block_signals(self.control_panel.bg_subtract_btn):
            self.control_panel.bg_subtract_btn.setChecked(False)
            self.control_panel.bg_subtract_btn.setText("Background Sub")
            self.control_panel.bg_subtract_btn.setEnabled(False)
        self.control_panel.save_bg_btn.setEnabled(False)
        self._update_bg_status_label(has_bg=False, sub_enabled=False)

    def _on_load_bg_clicked(self) -> None:
        """Open the load-background dialog and emit the chosen path."""
        files = self._bg_file_list_for_dialog
        if not files:
            return
        dlg = LoadBackgroundDialog(files, parent=self)
        if dlg.exec_() == QDialog.Accepted and dlg.selected_path:
            self.load_background_requested.emit(str(dlg.selected_path))

    def set_bg_file_list(self, files: list) -> None:
        """Cache the list of background files for the current prefix."""
        self._bg_file_list_for_dialog = files

    # ------------------------------------------------------------------
    # Control panel public API
    # ------------------------------------------------------------------

    def set_available_prefixes(self, prefixes: list, active: str) -> None:
        """Populate the camera prefix dropdown without triggering signals."""
        with _block_signals(self.control_panel.prefix_combo):
            self.control_panel.prefix_combo.clear()
            self.control_panel.prefix_combo.addItems(prefixes)
            idx = self.control_panel.prefix_combo.findText(active)
            if idx >= 0:
                self.control_panel.prefix_combo.setCurrentIndex(idx)

    def eventFilter(self, obj: object, event: QEvent) -> bool:  # type: ignore[override]
        """Revert spinbox to last confirmed RBV when Escape is pressed."""
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:  # type: ignore[attr-defined]
                if obj is self.control_panel.exposure_input:
                    self.revert_exposure_spinbox()
                    return True
                if obj is self.control_panel.gain_input:
                    self.revert_gain_spinbox()
                    return True
        return super().eventFilter(obj, event)

    @pyqtSlot()
    def revert_exposure_spinbox(self) -> None:
        """Revert exposure spinbox to the last confirmed RBV and clear pending state."""
        self.set_exposure_rbv(self._last_confirmed_exposure)

    @pyqtSlot()
    def revert_gain_spinbox(self) -> None:
        """Revert gain spinbox to the last confirmed RBV and clear pending state."""
        self.set_gain_rbv(self._last_confirmed_gain)

    def set_exposure_rbv(self, value: float) -> None:
        """Update the exposure input to the confirmed RBV value and clear pending state."""
        self._last_confirmed_exposure = value
        with _block_signals(self.control_panel.exposure_input):
            self.control_panel.exposure_input.setValue(value)
        self.control_panel.exposure_input.setStyleSheet("")  # clear pending indicator
        self.control_panel.camera_status_label.setVisible(False)

    def set_gain_rbv(self, value: int) -> None:
        """Update the gain input to the confirmed RBV value and clear pending state."""
        self._last_confirmed_gain = value
        with _block_signals(self.control_panel.gain_input):
            self.control_panel.gain_input.setValue(value)
        self.control_panel.gain_input.setStyleSheet("")  # clear pending indicator
        self.control_panel.camera_status_label.setVisible(False)

    def _mark_spinbox_pending(self, widget: QWidget) -> None:
        """Apply an amber border to indicate a setpoint is pending confirmation."""
        cls = type(widget).__name__
        widget.setStyleSheet(
            f"{cls} {{ border: 1.5px solid #e8a020; border-radius: 4px; }}"
        )
        self.control_panel.camera_status_label.setVisible(True)

    # ------------------------------------------------------------------
    # Public API  (called by the controller on the main thread)
    # ------------------------------------------------------------------

    def update_display(self, fs: FrameState) -> None:
        """Render a fully-processed :class:`FrameState` — full image + ROI."""
        frame = fs.frame
        self._last_frame = frame
        self._last_frame_number = fs.frame_number

        # Calculate frame rate
        current_time = time.time()
        if self._start_time is None:
            self._start_time = current_time
            self._last_frame_time = current_time
            fps = 0.0
        else:
            elapsed = current_time - self._start_time
            if elapsed > 0:
                fps = fs.frame_number / elapsed
            else:
                fps = 0.0

        self.frame_label.setText(f"Frame: {fs.frame_number} | {fps:.1f} Hz")

        # full image
        self.image_pane_1.set_image(frame, fs.frame_number)
        # Set axis ranges based on frame shape or fallback shape
        h, w = frame.shape[:2]
        self.image_pane_1.set_axis_range(0, w, 0, h)

        # full-image projections + fits
        if fs.analysis is not None:
            self.h_proj_1.set_projection(fs.analysis.x_projection)
            self.v_proj_1.set_projection(fs.analysis.y_projection)

            xf = fs.analysis.x_fit
            if xf is not None and xf.success:
                self.h_proj_1.set_fit(
                    xf.fitted_curve, xf.sigma, xf.centroid, xf.amplitude,
                    sigma_um=xf.sigma_um, unit_label=xf.unit_label,
                )
            else:
                self.h_proj_1.clear_fit()

            yf = fs.analysis.y_fit
            if yf is not None and yf.success:
                self.v_proj_1.set_fit(
                    yf.fitted_curve, yf.sigma, yf.centroid, yf.amplitude,
                    sigma_um=yf.sigma_um, unit_label=yf.unit_label,
                )
            else:
                self.v_proj_1.clear_fit()
        else:
            self.h_proj_1.set_projection(np.mean(frame, axis=0))
            self.v_proj_1.set_projection(np.mean(frame, axis=1))
            self.h_proj_1.clear_fit()
            self.v_proj_1.clear_fit()

        # full-image projection overlays
        if self._overlay_state.show_full:
            x_proj = np.mean(frame, axis=0)
            y_proj = np.mean(frame, axis=1)
            if fs.analysis is not None:
                x_proj = fs.analysis.x_projection
                y_proj = fs.analysis.y_projection
            self.image_pane_1.update_projections(x_proj, y_proj, (h, w), self._overlay_state)
        else:
            self.image_pane_1.clear_projections()

        # ROI pane
        self._update_roi()

    # ------------------------------------------------------------------
    # ROI helpers
    # ------------------------------------------------------------------

    def _set_roi_section_visible(self, visible: bool) -> None:
        """Show or hide the ROI image pane and its projection plots."""
        self.image_pane_2.setVisible(visible)
        self.h_proj_2.setVisible(visible)
        self.v_proj_2.setVisible(visible)
        if not visible:
            self.drift_label.hide()

    @pyqtSlot(object)
    def _on_roi_changed(self, roi: object) -> None:
        """Called when the user draws a new ROI or clears the existing one."""
        self._set_roi_section_visible(roi is not None)
        self.control_panel.center_roi_btn.setEnabled(roi is not None)
        if roi is not None:
            self._update_roi()
            # Clear stale projections from a previous ROI when a new one is drawn
        else:
            self._live_roi_centroid = None
            self.image_pane_2.clear_centroid_crosshair()
            self.h_proj_2.clear_fit()
            self.v_proj_2.clear_fit()
        self.roi_changed.emit(roi)

    def restore_roi(self, roi: Optional[tuple]) -> None:
        """Silently restore a saved ROI (does not trigger save-to-config)."""
        with _block_signals(self.image_pane_1):
            self.image_pane_1.set_roi(roi)
        self._set_roi_section_visible(roi is not None)
        self.control_panel.center_roi_btn.setEnabled(roi is not None)
        if roi is not None and self._last_frame is not None:
            self._update_roi()

    def get_current_roi(self) -> Optional[tuple]:
        """Return the active ROI as ``(x0, y0, x1, y1)`` or None."""
        return self.image_pane_1.current_roi

    # ------------------------------------------------------------------
    # Overlay state public API
    # ------------------------------------------------------------------

    @property
    def overlay_state(self) -> OverlayState:
        """Return the current projection overlay settings."""
        return self._overlay_state

    def restore_overlay_state(self, state: OverlayState) -> None:
        """Silently restore overlay settings without emitting signals."""
        self._overlay_state = state
        cp = self.control_panel
        with _block_signals(
            cp.h_overlay_btn, cp.h_overlay_side,
            cp.v_overlay_btn, cp.v_overlay_side,
            cp.overlay_scale_slider,
            cp.overlay_show_full_btn, cp.overlay_show_roi_btn,
        ):
            cp.h_overlay_btn.setChecked(state.h_enabled)
            cp.h_overlay_btn.setText("✓  H Overlay" if state.h_enabled else "H Overlay")
            cp.h_overlay_side.setCurrentText(state.h_side.capitalize())
            cp.h_overlay_side.setEnabled(state.h_enabled)

            cp.v_overlay_btn.setChecked(state.v_enabled)
            cp.v_overlay_btn.setText("✓  V Overlay" if state.v_enabled else "V Overlay")
            cp.v_overlay_side.setCurrentText(state.v_side.capitalize())
            cp.v_overlay_side.setEnabled(state.v_enabled)

            slider_val = max(5, min(50, int(state.scale * 100)))
            cp.overlay_scale_slider.setValue(slider_val)
            cp.overlay_scale_label.setText(f"{slider_val}%")

            cp.overlay_show_full_btn.setChecked(state.show_full)
            cp.overlay_show_full_btn.setText("✓  Full" if state.show_full else "Full")
            cp.overlay_show_roi_btn.setChecked(state.show_roi)
            cp.overlay_show_roi_btn.setText("✓  ROI" if state.show_roi else "ROI")

    def _update_crosshair_display(self, live: Optional[tuple]) -> None:
        """Update crosshair overlays and drift label from the live centroid.

        Red crosshair = reference anchor (where beam was when Center ROI clicked).
        Green crosshair = current live centroid, updated every frame.
        """
        ref = self._centroid_reference
        if not self._crosshair_enabled or ref is None:
            self.image_pane_2.clear_centroid_crosshair()
            self.drift_label.hide()
            return

        rx, ry = ref
        self.image_pane_2.set_reference_crosshair(rx, ry, visible=True)

        if live is not None:
            lx, ly = live
            self.image_pane_2.set_live_crosshair(lx, ly, visible=True)
            dx_px = lx - rx
            dy_px = ly - ry
            if self._calibration.is_calibrated:
                dx_um = self._calibration.pixel_to_um(dx_px)
                dy_um = self._calibration.pixel_to_um(dy_px)
                text = (
                    f"Drift  Δx: {dx_px:+.1f} px ({dx_um:+.1f} µm)  "
                    f"Δy: {dy_px:+.1f} px ({dy_um:+.1f} µm)"
                )
            else:
                text = f"Drift  Δx: {dx_px:+.1f} px  Δy: {dy_px:+.1f} px"
            self.drift_label.setText(text)
            self.drift_label.show()
        else:
            self.image_pane_2.set_live_crosshair(0, 0, visible=False)
            self.drift_label.hide()

    def _update_roi(self) -> None:
        """Extract the ROI from the cached frame and refresh the bottom pane.

        Projections are updated immediately on the main thread (cheap).
        When ROI fitting is enabled, the View emits ``roi_fit_requested``
        so the controller can run the fit on a background thread.
        """
        if self._last_frame is None:
            return
        roi_frame = self.image_pane_1.get_roi_slice(self._last_frame)
        if roi_frame is None or roi_frame.size == 0:
            return

        # Set axis ranges for ROI based on current ROI coordinates
        # and position the cropped sub-image at its full-image offset so
        # that it aligns with the pixel-coordinate axes.
        roi = self.image_pane_1.current_roi
        x0, y0 = 0, 0
        if roi is not None:
            x0, y0, x1, y1 = roi
            self.image_pane_2.set_axis_range(x0, x1, y0, y1)
            self.image_pane_2.image_item.setPos(x0, y0)

        self.image_pane_2.set_image(roi_frame, self._last_frame_number)

        # Compute live intensity-weighted centroid for drift tracking (cheap COM).
        patch = roi_frame.astype(np.float64)
        total = patch.sum()
        if total > 0:
            col_idx = np.arange(x0, x0 + roi_frame.shape[1], dtype=np.float64)
            row_idx = np.arange(y0, y0 + roi_frame.shape[0], dtype=np.float64)
            cx_live = float(np.dot(patch.sum(axis=0), col_idx) / total)
            cy_live = float(np.dot(patch.sum(axis=1), row_idx) / total)
            self._live_roi_centroid = (cx_live, cy_live)
        else:
            self._live_roi_centroid = None
        self._update_crosshair_display(self._live_roi_centroid)

        # Compute projections synchronously — just array summations, fast.
        x_proj, y_proj = compute_projections(roi_frame)
        self.h_proj_2.set_projection(x_proj, offset=x0)
        self.v_proj_2.set_projection(y_proj, offset=y0)

        # ROI projection overlays
        if self._overlay_state.show_roi:
            self.image_pane_2.update_projections(
                x_proj, y_proj,
                roi_frame.shape[:2], self._overlay_state,
                x_offset=float(x0), y_offset=float(y0),
            )
        else:
            self.image_pane_2.clear_projections()

        if not self.control_panel.fit_roi_btn.isChecked():
            # Fitting is off — clear stats immediately and stop here.
            self.h_proj_2.clear_fit()
            self.v_proj_2.clear_fit()
            return

        # Request fitting from the controller (runs on a background thread).
        self.roi_fit_requested.emit(roi, roi_frame.copy())

    @pyqtSlot(object)
    def deliver_roi_fit_result(self, bp) -> None:
        """Apply finished ROI fit results delivered by the controller."""
        roi = self.image_pane_1.current_roi
        x0, y0 = (roi[0], roi[1]) if roi is not None else (0, 0)
        if bp.x_fit is not None and bp.x_fit.success:
            self.h_proj_2.set_fit(
                bp.x_fit.fitted_curve, bp.x_fit.sigma,
                bp.x_fit.centroid, bp.x_fit.amplitude,
                sigma_um=bp.x_fit.sigma_um, unit_label=bp.x_fit.unit_label,
                offset=x0,
            )
        else:
            self.h_proj_2.clear_fit()

        if bp.y_fit is not None and bp.y_fit.success:
            self.v_proj_2.set_fit(
                bp.y_fit.fitted_curve, bp.y_fit.sigma,
                bp.y_fit.centroid, bp.y_fit.amplitude,
                sigma_um=bp.y_fit.sigma_um, unit_label=bp.y_fit.unit_label,
                offset=y0,
            )
        else:
            self.v_proj_2.clear_fit()

    # ------------------------------------------------------------------
    # Centroid crosshair public API (called by controller)
    # ------------------------------------------------------------------

    def restore_centroid_reference(self, xy: Optional[tuple]) -> None:
        """Restore a saved centroid reference without triggering save-to-config."""
        self._centroid_reference = xy
        self.control_panel.show_crosshair_btn.setEnabled(xy is not None)
        self._update_crosshair_display(self._live_roi_centroid)

    def restore_crosshair_enabled(self, enabled: bool) -> None:
        """Restore the crosshair toggle state without emitting the toggle signal."""
        self._crosshair_enabled = enabled
        with _block_signals(self.control_panel.show_crosshair_btn):
            self.control_panel.show_crosshair_btn.setChecked(enabled)
            self.control_panel.show_crosshair_btn.setText(
                "✓  Show Centroid Ref" if enabled else "Show Centroid Ref"
            )
        self._update_crosshair_display(self._live_roi_centroid)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def set_calibration(self, calibration: Calibration) -> None:
        """Update the calibration used for ROI fitting and display."""
        self._calibration = calibration

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closing.emit()
        super().closeEvent(event)
