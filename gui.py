"""
gui.py — PyQt6 GUI (View layer).

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

import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QEvent, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from analysis import analyze_frame
from state import FrameState


# ---------------------------------------------------------------------------
# Theme system
# ---------------------------------------------------------------------------

_MONO = "'JetBrains Mono', 'Fira Code', Consolas, monospace"


@dataclass(frozen=True)
class _Theme:
    """All colour tokens for one display mode."""
    name: str
    # chrome
    bg: str
    panel_bg: str
    border: str
    accent: str
    text: str
    text_dim: str
    # pyqtgraph surfaces
    plot_bg: str
    image_bg: str
    pg_fg: str
    # data curves
    h_curve: str
    v_curve: str
    fit_curve: str

    def palette(self) -> QPalette:
        """Build a QPalette for Fusion style matching this theme's colours."""
        p = QPalette()
        bg      = QColor(self.bg)
        panel   = QColor(self.panel_bg)
        border  = QColor(self.border)
        accent  = QColor(self.accent)
        text    = QColor(self.text)
        dim     = QColor(self.text_dim)

        p.setColor(QPalette.ColorRole.Window,           bg)
        p.setColor(QPalette.ColorRole.WindowText,       text)
        p.setColor(QPalette.ColorRole.Base,             panel)
        p.setColor(QPalette.ColorRole.AlternateBase,    bg)
        p.setColor(QPalette.ColorRole.ToolTipBase,      panel)
        p.setColor(QPalette.ColorRole.ToolTipText,      text)
        p.setColor(QPalette.ColorRole.Text,             text)
        p.setColor(QPalette.ColorRole.Button,           panel)
        p.setColor(QPalette.ColorRole.ButtonText,       text)
        p.setColor(QPalette.ColorRole.BrightText,       QColor("#ffffff"))
        p.setColor(QPalette.ColorRole.Link,             accent)
        p.setColor(QPalette.ColorRole.Highlight,        accent)
        p.setColor(QPalette.ColorRole.HighlightedText,  bg)
        p.setColor(QPalette.ColorRole.Light,            panel.lighter(130))
        p.setColor(QPalette.ColorRole.Midlight,         border)
        p.setColor(QPalette.ColorRole.Mid,              border)
        p.setColor(QPalette.ColorRole.Dark,             bg.darker(130))
        p.setColor(QPalette.ColorRole.Shadow,           bg.darker(160))
        p.setColor(QPalette.ColorRole.PlaceholderText,  dim)
        return p

    def stylesheet(self) -> str:  # noqa: E501
        """Minimal stylesheet that accents Fusion's native widget rendering."""
        return f"""
            QGroupBox {{
                border: 1px solid {self.border};
                border-radius: 6px;
                margin-top: 16px;
                padding: 12px 10px 10px 10px;
                font-weight: 600;
                font-size: 13px;
                color: {self.accent};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
            QLabel {{ background: transparent; }}
            QSplitter::handle {{
                background: {self.border};
            }}
            QStatusBar {{
                border-top: 1px solid {self.border};
                font-size: 12px;
            }}
            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
                border-color: {self.accent};
            }}
            QComboBox:on {{
                border-color: {self.accent};
            }}
            QComboBox QAbstractItemView {{
                selection-background-color: {self.accent};
                selection-color: {self.bg};
                outline: none;
            }}
            QPushButton {{
                padding: 5px 14px;
                min-height: 26px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                color: {self.accent};
            }}
            QPushButton:checked {{
                background-color: {self.accent};
                color: {self.bg};
            }}
        """


DARK = _Theme(
    name="dark",
    bg="#1a1a2e",       panel_bg="#16213e",  border="#1a3a5c",
    accent="#00adb5",   text="#e0e0e0",      text_dim="#7a7a9a",
    plot_bg="#1a1a2e",  image_bg="#000000",  pg_fg="#e0e0e0",
    h_curve="#00e5ff",  v_curve="#ce93d8",   fit_curve="#ff5555",
)

LIGHT = _Theme(
    name="light",
    bg="#f0f2f5",       panel_bg="#ffffff",   border="#c8ccd8",
    accent="#0077b6",   text="#1a1a2e",       text_dim="#6b6b85",
    plot_bg="#ffffff",  image_bg="#000000",   pg_fg="#1a1a2e",
    h_curve="#0077b6",  v_curve="#7b2d8b",    fit_curve="#c0392b",
)


# ---------------------------------------------------------------------------
# Reusable sub-widgets
# ---------------------------------------------------------------------------

class _ProjectionPlot(QWidget):
    """Single projection plot with a title + stats label above it."""

    def __init__(
        self,
        title: str,
        curve_role: str,   # "h" | "v"  — determines which theme curve colour to use
        theme: _Theme,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._curve_role = curve_role
        self._theme = theme
        self._stats_dim = True

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 0)
        lay.setSpacing(1)

        # --- title ---
        self.title_label = QLabel(title)
        lay.addWidget(self.title_label)

        # --- stats bar ---
        self.stats_label = QLabel(self._blank_stats())
        lay.addWidget(self.stats_label)

        # --- pyqtgraph plot ---
        self.pw = pg.PlotWidget()
        self.pw.getPlotItem().showGrid(x=True, y=True, alpha=0.12)
        self.pw.setMinimumHeight(80)
        lay.addWidget(self.pw, stretch=1)

        curve_col = theme.h_curve if curve_role == "h" else theme.v_curve
        self.curve = self.pw.plot(pen=pg.mkPen(curve_col, width=1.3))
        self.fit_curve = self.pw.plot(
            pen=pg.mkPen(theme.fit_curve, width=1.6, style=Qt.PenStyle.DashLine),
        )

        self._apply_theme_internals(theme)

    # helpers
    @staticmethod
    def _blank_stats() -> str:
        return "Sigma: ——    Centroid: ——    Amp: ——"

    def _stats_style(self, dim: bool) -> str:
        clr = self._theme.text_dim if dim else self._theme.text
        return (
            f"color: {clr}; font-family: {_MONO}; font-size: 11px; "
            f"padding-left: 4px;"
        )

    def _apply_theme_internals(self, theme: _Theme) -> None:
        """Update all pyqtgraph and Qt styling to *theme* (no data changes)."""
        self._theme = theme
        self.pw.setBackground(theme.plot_bg)
        axis_pen = pg.mkPen(theme.border)
        text_pen = pg.mkPen(theme.text)
        for ax_name in ("bottom", "left"):
            ax = self.pw.getPlotItem().getAxis(ax_name)
            ax.setPen(axis_pen)
            ax.setTextPen(text_pen)
        self.title_label.setStyleSheet(
            f"color: {theme.text}; font-size: 12px; font-weight: 600; "
            f"padding-left: 4px;"
        )
        self.stats_label.setStyleSheet(self._stats_style(self._stats_dim))
        curve_col = theme.h_curve if self._curve_role == "h" else theme.v_curve
        self.curve.setPen(pg.mkPen(curve_col, width=1.3))
        self.fit_curve.setPen(
            pg.mkPen(theme.fit_curve, width=1.6, style=Qt.PenStyle.DashLine)
        )

    def apply_theme(self, theme: _Theme) -> None:
        """Switch this widget to *theme* at runtime."""
        self._apply_theme_internals(theme)

    # public API
    def set_projection(self, data: np.ndarray) -> None:
        self.curve.setData(data)

    def set_fit(
        self,
        fitted: np.ndarray,
        sigma: float,
        centroid: float,
        amplitude: float,
    ) -> None:
        self.fit_curve.setData(np.arange(len(fitted), dtype=np.float64), fitted)
        self.stats_label.setText(
            f"Sigma: {sigma:8.3f}    "
            f"Centroid: {centroid:8.2f}    "
            f"Amp: {amplitude:8.1f}"
        )
        self._stats_dim = False
        self.stats_label.setStyleSheet(self._stats_style(dim=False))

    def clear_fit(self) -> None:
        self.fit_curve.clear()
        self.stats_label.setText(self._blank_stats())
        self._stats_dim = True
        self.stats_label.setStyleSheet(self._stats_style(dim=True))


class _ImagePane(QWidget):
    """Camera image display with a thin header label and optional ROI overlay."""

    def __init__(
        self,
        label_text: str,
        theme: _Theme,
        enable_roi: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # header
        self.header = QLabel(label_text)
        self.header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.header)

        # image view — background stays dark regardless of theme for visibility
        self.plot = pg.PlotWidget()
        self.plot.setBackground(theme.image_bg)
        self.plot.setAspectLocked(True)
        self.plot.invertY(True)
        self.plot.hideAxis("bottom")
        self.plot.hideAxis("left")
        lay.addWidget(self.plot, stretch=1)

        self.image_item = pg.ImageItem()
        self.plot.addItem(self.image_item)

        cmap = pg.colormap.get("hot", source="matplotlib")
        self.image_item.setLookupTable(cmap.getLookupTable())

        # auto-levels bookkeeping
        self._levels_set = False
        self._levels_interval = 30

        # --- optional ROI overlay ---
        self.roi_rect: Optional[pg.ROI] = None
        self._roi_initialized = False
        if enable_roi:
            self.roi_rect = pg.RectROI(
                [10, 10], [100, 100],
                pen=pg.mkPen("#ff5555", width=2),
                hoverPen=pg.mkPen("#ffff55", width=2),
            )
            self.roi_rect.addScaleHandle([1, 1], [0, 0])
            self.roi_rect.addScaleHandle([0, 0], [1, 1])
            self.roi_rect.addScaleHandle([1, 0], [0, 1])
            self.roi_rect.addScaleHandle([0, 1], [1, 0])
            self.plot.addItem(self.roi_rect)

        self._apply_header_style(theme)

    def _apply_header_style(self, theme: _Theme) -> None:
        self.header.setStyleSheet(
            f"background: {theme.panel_bg}; color: {theme.accent}; "
            f"font-size: 12px; font-weight: 600; padding: 4px;"
        )

    def apply_theme(self, theme: _Theme) -> None:
        """Update chrome colours.  Image bg intentionally stays dark."""
        self._apply_header_style(theme)

    def set_image(self, frame: np.ndarray, frame_number: int) -> None:
        self.image_item.setImage(frame, autoLevels=False)
        if (
            not self._levels_set
            or frame_number % self._levels_interval == 0
        ):
            lo, hi = float(frame.min()), float(frame.max())
            if lo != hi:
                self.image_item.setLevels([lo, hi])
                self._levels_set = True

        # Auto-initialise ROI to centre 50 % of the first frame
        if self.roi_rect is not None and not self._roi_initialized:
            h, w = frame.shape[:2]
            self.roi_rect.setPos([w * 0.25, h * 0.25])
            self.roi_rect.setSize([w * 0.5, h * 0.5])
            self._roi_initialized = True

    def get_roi_slice(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Return the sub-array of *frame* inside the current ROI, or None."""
        if self.roi_rect is None:
            return None
        pos = self.roi_rect.pos()
        size = self.roi_rect.size()
        x0 = max(0, int(pos.x()))
        y0 = max(0, int(pos.y()))
        x1 = min(frame.shape[1], int(pos.x() + size.x()))
        y1 = min(frame.shape[0], int(pos.y() + size.y()))
        if x1 <= x0 or y1 <= y0:
            return None
        return frame[y0:y1, x0:x1]

    def set_placeholder(self, text: str = "No data source connected") -> None:
        self.header.setText(f"{self.header.text()}  —  {text}")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class BeamViewerWindow(QMainWindow):
    """Main application window (pure View)."""

    closing = pyqtSignal()
    prefix_change_requested = pyqtSignal(str)
    exposure_set_requested = pyqtSignal(float)
    gain_set_requested = pyqtSignal(int)
    streaming_toggled = pyqtSignal(bool)
    colormap_changed = pyqtSignal(str)
    fit_full_toggled = pyqtSignal(bool)
    # Emitted from a background thread when ROI fitting completes.
    # Payload is a tuple (seq: int, bp: BeamParameters).
    _roi_analysis_ready = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme: _Theme = DARK

        self.setWindowTitle("Beam Profile Viewer")
        self.resize(1500, 920)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(0)

        # === outer splitter: [images + plots] | [control panel] ===
        outer = QSplitter(Qt.Orientation.Horizontal)
        outer.setHandleWidth(3)
        root_layout.addWidget(outer)

        # --- left+centre area (images + projections) ---
        inner = QSplitter(Qt.Orientation.Horizontal)
        inner.setHandleWidth(3)

        #  ┌── images column ──┐
        img_col = QWidget()
        img_lay = QVBoxLayout(img_col)
        img_lay.setContentsMargins(0, 0, 0, 0)
        img_lay.setSpacing(4)

        self.image_pane_1 = _ImagePane("Full Image", self._theme, enable_roi=True)
        self.image_pane_2 = _ImagePane("ROI", self._theme)

        self._last_frame: Optional[np.ndarray] = None
        self._last_frame_number: int = 0
        # Sequence counter used to discard stale ROI fit results.
        self._roi_seq: int = 0
        # Prevent more than one ROI fit thread from running at a time.
        self._roi_fit_running: bool = False

        # Wire up the cross-thread ROI result signal.
        self._roi_analysis_ready.connect(self._on_roi_analysis_ready)

        # Update ROI pane whenever the ROI rectangle is moved / resized
        self.image_pane_1.roi_rect.sigRegionChanged.connect(self._update_roi)

        img_lay.addWidget(self.image_pane_1, stretch=1)
        img_lay.addWidget(self.image_pane_2, stretch=1)
        inner.addWidget(img_col)

        #  ┌── projections column ──┐
        proj_col = QWidget()
        proj_lay = QVBoxLayout(proj_col)
        proj_lay.setContentsMargins(0, 0, 0, 0)
        proj_lay.setSpacing(4)

        self.h_proj_1 = _ProjectionPlot(
            "Horizontal Projection  (Full Image)", "h", self._theme,
        )
        self.v_proj_1 = _ProjectionPlot(
            "Vertical Projection  (Full Image)", "v", self._theme,
        )
        self.h_proj_2 = _ProjectionPlot(
            "Horizontal Projection  (ROI)", "h", self._theme,
        )
        self.v_proj_2 = _ProjectionPlot(
            "Vertical Projection  (ROI)", "v", self._theme,
        )

        proj_lay.addWidget(self.h_proj_1, stretch=1)
        proj_lay.addWidget(self.v_proj_1, stretch=1)
        proj_lay.addWidget(self.h_proj_2, stretch=1)
        proj_lay.addWidget(self.v_proj_2, stretch=1)
        inner.addWidget(proj_col)

        inner.setStretchFactor(0, 2)   # images
        inner.setStretchFactor(1, 3)   # projections

        outer.addWidget(inner)

        #  ┌── control panel (right) ──┐
        self.control_panel = self._build_control_panel()
        outer.addWidget(self.control_panel)

        # Track last confirmed RBV values so spinboxes can be reverted
        self._last_confirmed_exposure: float = self.exposure_input.value()
        self._last_confirmed_gain: int = self.gain_input.value()

        # Escape key on either spinbox reverts to last confirmed value
        self.exposure_input.installEventFilter(self)
        self.gain_input.installEventFilter(self)

        outer.setStretchFactor(0, 5)
        outer.setStretchFactor(1, 1)

        # --- status bar ---
        self.frame_label = QLabel("Frame: 0")
        self.statusBar().addPermanentWidget(self.frame_label)

        self._theme_btn = QPushButton("☀  Light")
        self._theme_btn.setFixedHeight(22)
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self.toggle_theme)
        self.statusBar().addWidget(self._theme_btn)

        # Apply initial theme (sets all stylesheets)
        self._apply_theme(self._theme)

    # ------------------------------------------------------------------
    # Theme toggle
    # ------------------------------------------------------------------

    def toggle_theme(self) -> None:
        """Switch between dark and light mode."""
        self._apply_theme(LIGHT if self._theme.name == "dark" else DARK)

    def _apply_theme(self, theme: _Theme) -> None:
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

        # Control panel: style labels
        for grp in self.control_panel.findChildren(QGroupBox):
            for lbl in grp.findChildren(QLabel):
                lbl.setStyleSheet(f"color: {theme.text_dim}; font-size: 12px;")

    # ------------------------------------------------------------------
    # Control panel
    # ------------------------------------------------------------------

    def _build_control_panel(self) -> QWidget:
        """Build the right-hand control panel with camera, acquire, and display settings."""
        panel = QWidget()
        panel.setMinimumWidth(260)
        panel.setMaximumWidth(320)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(8)

        # ── Camera Setup ──────────────────────────────────────────
        cam_grp = QGroupBox("Camera Setup")
        cam_lay = QGridLayout(cam_grp)
        cam_lay.setSpacing(6)
        cam_lay.setContentsMargins(8, 12, 8, 8)
        cam_lay.setColumnStretch(1, 1)
        cam_lay.addWidget(QLabel("Camera:"), 0, 0)
        self.prefix_combo = QComboBox()
        cam_lay.addWidget(self.prefix_combo, 0, 1, 1, 2)

        cam_lay.addWidget(QLabel("Exposure (s):"), 1, 0)
        self.exposure_input = QDoubleSpinBox()
        self.exposure_input.setRange(0.0001, 30.0)
        self.exposure_input.setDecimals(4)
        self.exposure_input.setSingleStep(0.01)
        self.exposure_input.setValue(0.1)
        cam_lay.addWidget(self.exposure_input, 1, 1)
        self.exposure_set_btn = QPushButton("Set")
        self.exposure_set_btn.setMinimumWidth(50)
        cam_lay.addWidget(self.exposure_set_btn, 1, 2)

        cam_lay.addWidget(QLabel("Gain:"), 2, 0)
        self.gain_input = QSpinBox()
        self.gain_input.setRange(0, 40)
        self.gain_input.setValue(0)
        cam_lay.addWidget(self.gain_input, 2, 1)
        self.gain_set_btn = QPushButton("Set")
        self.gain_set_btn.setMinimumWidth(50)
        cam_lay.addWidget(self.gain_set_btn, 2, 2)

        self.camera_status_label = QLabel("Changing camera setting (press escape to cancel)")
        self.camera_status_label.setStyleSheet("font-style: italic;")
        self.camera_status_label.setWordWrap(True)
        self.camera_status_label.setVisible(False)
        cam_lay.addWidget(self.camera_status_label, 3, 0, 1, 3)

        lay.addWidget(cam_grp)

        # ── Acquire ───────────────────────────────────────────────
        acq_grp = QGroupBox("Acquire")
        acq_lay = QVBoxLayout(acq_grp)
        acq_lay.setContentsMargins(8, 12, 8, 8)
        self.stream_btn = QPushButton("▶  Streaming")
        self.stream_btn.setCheckable(True)
        self.stream_btn.setChecked(True)
        self.stream_btn.setMinimumHeight(32)
        acq_lay.addWidget(self.stream_btn)

        lay.addWidget(acq_grp)

        # ── Analysis ──────────────────────────────────────────────
        analysis_grp = QGroupBox("Analysis")
        analysis_lay = QVBoxLayout(analysis_grp)
        analysis_lay.setContentsMargins(8, 12, 8, 8)
        analysis_lay.setSpacing(6)

        self.fit_full_btn = QPushButton("Fit Full Image")
        self.fit_full_btn.setCheckable(True)
        self.fit_full_btn.setChecked(True)
        self.fit_full_btn.setMinimumHeight(28)
        analysis_lay.addWidget(self.fit_full_btn)

        self.fit_roi_btn = QPushButton("Fit ROI")
        self.fit_roi_btn.setCheckable(True)
        self.fit_roi_btn.setChecked(False)
        self.fit_roi_btn.setMinimumHeight(28)
        analysis_lay.addWidget(self.fit_roi_btn)

        lay.addWidget(analysis_grp)

        # ── Image Settings ────────────────────────────────────────
        img_grp = QGroupBox("Image Settings")
        img_lay = QGridLayout(img_grp)
        img_lay.setContentsMargins(8, 12, 8, 8)
        img_lay.setColumnStretch(1, 1)
        img_lay.addWidget(QLabel("Colormap:"), 0, 0)
        self.colormap_combo = QComboBox()
        self.colormap_combo.addItems([
            "hot", "viridis", "inferno",  "plasma", "magma", "cividis", "gray",
        ])
        self.colormap_combo.setCurrentIndex(0)  # Default to "hot"
        img_lay.addWidget(self.colormap_combo, 0, 1)

        lay.addWidget(img_grp)

        lay.addStretch()

        # ── Internal signal wiring ────────────────────────────────
        self.prefix_combo.currentTextChanged.connect(
            self.prefix_change_requested.emit,
        )
        self.exposure_input.valueChanged.connect(
            lambda _: self._mark_spinbox_pending(self.exposure_input),
        )
        self.gain_input.valueChanged.connect(
            lambda _: self._mark_spinbox_pending(self.gain_input),
        )
        self.exposure_set_btn.clicked.connect(
            lambda: self.exposure_set_requested.emit(self.exposure_input.value()),
        )
        self.gain_set_btn.clicked.connect(
            lambda: self.gain_set_requested.emit(self.gain_input.value()),
        )
        self.stream_btn.toggled.connect(self._on_stream_toggled)
        self.fit_full_btn.toggled.connect(self._on_fit_full_toggled)
        self.fit_roi_btn.toggled.connect(self._on_fit_roi_toggled)
        self.colormap_combo.currentTextChanged.connect(
            self.colormap_changed.emit,
        )

        return panel

    def _on_stream_toggled(self, checked: bool) -> None:
        """Update button text and emit streaming signal."""
        self.stream_btn.setText(
            "▶  Streaming" if checked else "⏸  Paused"
        )
        self.streaming_toggled.emit(checked)

    def _on_fit_full_toggled(self, checked: bool) -> None:
        self.fit_full_btn.setText(
            "✓  Fit Full Image" if checked else "Fit Full Image"
        )
        self.fit_full_toggled.emit(checked)

    def _on_fit_roi_toggled(self, checked: bool) -> None:
        self.fit_roi_btn.setText(
            "✓  Fit ROI" if checked else "Fit ROI"
        )
        # ROI fitting is handled entirely in the GUI; just refresh
        self._update_roi()

    # ------------------------------------------------------------------
    # Control panel public API
    # ------------------------------------------------------------------

    def set_available_prefixes(self, prefixes: list, active: str) -> None:
        """Populate the camera prefix dropdown without triggering signals."""
        self.prefix_combo.blockSignals(True)
        self.prefix_combo.clear()
        self.prefix_combo.addItems(prefixes)
        idx = self.prefix_combo.findText(active)
        if idx >= 0:
            self.prefix_combo.setCurrentIndex(idx)
        self.prefix_combo.blockSignals(False)

    def eventFilter(self, obj: object, event: QEvent) -> bool:  # type: ignore[override]
        """Revert spinbox to last confirmed RBV when Escape is pressed."""
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:  # type: ignore[attr-defined]
                if obj is self.exposure_input:
                    self.revert_exposure_spinbox()
                    return True
                if obj is self.gain_input:
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
        self.exposure_input.blockSignals(True)
        self.exposure_input.setValue(value)
        self.exposure_input.blockSignals(False)
        self.exposure_input.setStyleSheet("")  # clear pending indicator
        self.camera_status_label.setVisible(False)

    def set_gain_rbv(self, value: int) -> None:
        """Update the gain input to the confirmed RBV value and clear pending state."""
        self._last_confirmed_gain = value
        self.gain_input.blockSignals(True)
        self.gain_input.setValue(value)
        self.gain_input.blockSignals(False)
        self.gain_input.setStyleSheet("")  # clear pending indicator
        self.camera_status_label.setVisible(False)

    def _mark_spinbox_pending(self, widget: QWidget) -> None:
        """Apply an amber border to indicate a setpoint is pending confirmation."""
        cls = type(widget).__name__
        widget.setStyleSheet(
            f"{cls} {{ border: 1.5px solid #e8a020; border-radius: 4px; }}"
        )
        self.camera_status_label.setVisible(True)

    # ------------------------------------------------------------------
    # Public API  (called by the controller on the main thread)
    # ------------------------------------------------------------------

    def update_display(self, fs: FrameState) -> None:
        """Render a fully-processed :class:`FrameState` — full image + ROI."""
        frame = fs.frame
        self._last_frame = frame
        self._last_frame_number = fs.frame_number
        self.frame_label.setText(f"Frame: {fs.frame_number}")

        # full image
        self.image_pane_1.set_image(frame, fs.frame_number)

        # full-image projections + fits
        if fs.analysis is not None:
            self.h_proj_1.set_projection(fs.analysis.x_projection)
            self.v_proj_1.set_projection(fs.analysis.y_projection)

            xf = fs.analysis.x_fit
            if xf is not None and xf.success:
                self.h_proj_1.set_fit(
                    xf.fitted_curve, xf.sigma, xf.centroid, xf.amplitude,
                )
            else:
                self.h_proj_1.clear_fit()

            yf = fs.analysis.y_fit
            if yf is not None and yf.success:
                self.v_proj_1.set_fit(
                    yf.fitted_curve, yf.sigma, yf.centroid, yf.amplitude,
                )
            else:
                self.v_proj_1.clear_fit()
        else:
            self.h_proj_1.set_projection(np.mean(frame, axis=0))
            self.v_proj_1.set_projection(np.mean(frame, axis=1))
            self.h_proj_1.clear_fit()
            self.v_proj_1.clear_fit()

        # ROI pane
        self._update_roi()

    # ------------------------------------------------------------------
    # ROI helper
    # ------------------------------------------------------------------

    def _update_roi(self) -> None:
        """Extract the ROI from the cached frame and refresh the bottom pane.

        Projections are updated immediately on the main thread (cheap).  When
        ROI fitting is enabled the fitting work is dispatched to a daemon
        background thread so that slow ``scipy.optimize.curve_fit`` calls
        (e.g. with a hot-pixel spike) never block the Qt event loop.
        """
        if self._last_frame is None:
            return
        roi_frame = self.image_pane_1.get_roi_slice(self._last_frame)
        if roi_frame is None or roi_frame.size == 0:
            return

        self.image_pane_2.set_image(roi_frame, self._last_frame_number)

        # Always compute projections synchronously — this is just array
        # summations and is never a source of hangs.
        bp_no_fit = analyze_frame(roi_frame, do_fit=False)
        self.h_proj_2.set_projection(bp_no_fit.x_projection)
        self.v_proj_2.set_projection(bp_no_fit.y_projection)
        self.h_proj_2.clear_fit()
        self.v_proj_2.clear_fit()

        if not self.fit_roi_btn.isChecked():
            return

        # --- off-thread Gaussian fit ---
        # Bump the sequence so any in-flight result from a previous call is
        # considered stale and discarded when it arrives.
        self._roi_seq += 1
        seq = self._roi_seq

        if self._roi_fit_running:
            # A fit is already in-flight; the new result will be superseded
            # by the *next* frame anyway, so just let that one finish and
            # it will clear_fit if the seq doesn't match.
            return

        self._roi_fit_running = True
        frame_snapshot = roi_frame.copy()  # safe to read from another thread

        def _run() -> None:
            try:
                bp = analyze_frame(frame_snapshot, do_fit=True)
                self._roi_analysis_ready.emit((seq, bp))
            finally:
                self._roi_fit_running = False

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot(object)
    def _on_roi_analysis_ready(self, payload: object) -> None:
        """Receive a completed ROI fit result from the background thread."""
        seq, bp = payload  # type: ignore[misc]
        # Discard stale results that arrived after a newer ROI was requested.
        if seq != self._roi_seq:
            return
        if bp.x_fit is not None and bp.x_fit.success:
            self.h_proj_2.set_fit(
                bp.x_fit.fitted_curve, bp.x_fit.sigma,
                bp.x_fit.centroid, bp.x_fit.amplitude,
            )
        else:
            self.h_proj_2.clear_fit()

        if bp.y_fit is not None and bp.y_fit.success:
            self.v_proj_2.set_fit(
                bp.y_fit.fitted_curve, bp.y_fit.sigma,
                bp.y_fit.centroid, bp.y_fit.amplitude,
            )
        else:
            self.v_proj_2.clear_fit()

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closing.emit()
        super().closeEvent(event)
