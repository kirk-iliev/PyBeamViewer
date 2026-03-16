"""
gui.py — PyQt5 GUI (View layer).

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
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QEvent, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from analysis import analyze_frame
from state import FrameState


# ---------------------------------------------------------------------------
# Projection overlay state
# ---------------------------------------------------------------------------

@dataclass
class OverlayState:
    """Settings for projection overlays drawn on top of the image."""
    h_enabled: bool = False
    h_side: str = "bottom"    # "bottom" | "top"
    v_enabled: bool = False
    v_side: str = "left"      # "left" | "right"
    scale: float = 0.25       # 0.0 – 0.5, fraction of image dimension

    def to_dict(self) -> dict:
        return {
            "h_enabled": self.h_enabled,
            "h_side": self.h_side,
            "v_enabled": self.v_enabled,
            "v_side": self.v_side,
            "scale": self.scale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OverlayState":
        return cls(
            h_enabled=d.get("h_enabled", False),
            h_side=d.get("h_side", "bottom"),
            v_enabled=d.get("v_enabled", False),
            v_side=d.get("v_side", "left"),
            scale=d.get("scale", 0.25),
        )


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
    bg="#141423",       panel_bg="#16213e",  border="#1a3a5c",
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
            pen=pg.mkPen(theme.fit_curve, width=1.6, style=Qt.DashLine),
        )

        # Y-axis range smoothing — expand instantly, shrink slowly.
        self._smooth_y_min: Optional[float] = None
        self._smooth_y_max: Optional[float] = None
        self._DECAY = 0.12  # fraction to move toward actual range per frame

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
            pg.mkPen(theme.fit_curve, width=1.6, style=Qt.DashLine)
        )

    def apply_theme(self, theme: _Theme) -> None:
        """Switch this widget to *theme* at runtime."""
        self._apply_theme_internals(theme)

    # public API
    def set_projection(self, data: np.ndarray) -> None:
        self.curve.setData(data)

        if len(data) > 0:
            y_min = float(np.min(data))
            y_max = float(np.max(data))

            # --- smoothed y-range: expand instantly, shrink slowly ---
            if self._smooth_y_min is None or self._smooth_y_max is None:
                # First frame — seed directly.
                self._smooth_y_min = y_min
                self._smooth_y_max = y_max
            else:
                # Expand immediately so data is never clipped.
                if y_min < self._smooth_y_min:
                    self._smooth_y_min = y_min
                else:
                    self._smooth_y_min += self._DECAY * (y_min - self._smooth_y_min)

                if y_max > self._smooth_y_max:
                    self._smooth_y_max = y_max
                else:
                    self._smooth_y_max += self._DECAY * (y_max - self._smooth_y_max)

            y_range = self._smooth_y_max - self._smooth_y_min
            padding = max(y_range * 0.10, 1e-6)
            self.pw.setYRange(
                self._smooth_y_min - padding,
                self._smooth_y_max + padding,
                padding=0,
            )

            # X-axis: full range of data indices
            x_max = len(data) - 1
            x_padding = max(x_max * 0.02, 1)
            self.pw.setXRange(-x_padding, x_max + x_padding, padding=0)

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
    """Camera image display with a thin header label and optional ROI overlay.

    When *enable_roi* is True the pane supports click-and-drag to draw a
    rectangular region of interest.  The result is emitted via *roi_changed*
    as a ``(x0, y0, x1, y1)`` tuple in image-pixel coordinates, or ``None``
    when the ROI is cleared.  The overlay rectangle is purely decorative —
    it is not interactive after being drawn.
    """

    # Emits (x0, y0, x1, y1) when drawn, or None when cleared.
    roi_changed = pyqtSignal(object)

    def __init__(
        self,
        label_text: str,
        theme: _Theme,
        enable_roi: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._enable_roi = enable_roi

        # Click-drag state
        self._drawing: bool = False
        self._draw_start: Optional[tuple] = None   # (x, y) in data coords
        self._current_roi: Optional[tuple] = None  # (x0, y0, x1, y1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # header
        self.header = QLabel(label_text)
        self.header.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.header)

        # image view — background stays dark regardless of theme for visibility
        self.plot = pg.PlotWidget()
        self.plot.setBackground(theme.image_bg)
        self.plot.setAspectLocked(True)
        self.plot.invertY(True)
        self.plot.setLabel('bottom', 'X (pixels)')
        self.plot.setLabel('left', 'Y (pixels)')
        self.plot.showAxis('bottom')
        self.plot.showAxis('left')
        lay.addWidget(self.plot, stretch=1)

        self.image_item = pg.ImageItem()
        self.plot.addItem(self.image_item)

        cmap = pg.colormap.get("hot", source="matplotlib")
        self.image_item.setLookupTable(cmap.getLookupTable())

        # auto-levels bookkeeping
        self._levels_set = False
        self._levels_interval = 30

        # --- optional ROI overlay (click-drag to draw) ---
        self._roi_display: Optional[pg.ROI] = None
        if enable_roi:
            # Non-interactive display rectangle — no handles, not movable.
            # Lives in data/view space so it scales correctly with the image.
            self._roi_display = pg.ROI(
                [0, 0], [1, 1],
                movable=False,
                pen=pg.mkPen("#ff5555", width=2),
            )
            self._roi_display.setAcceptHoverEvents(False)
            self._roi_display.setAcceptedMouseButtons(Qt.NoButton)
            self._roi_display.hide()
            self.plot.addItem(self._roi_display)

            # Crosshair cursor signals that the user can draw here
            self.plot.setCursor(Qt.CrossCursor)

            # Disable ViewBox pan/zoom — the image auto-fits; we own the mouse
            self.plot.getViewBox().setMouseEnabled(x=False, y=False)

            # Capture viewport mouse events for drag-to-draw
            self.plot.viewport().installEventFilter(self)

        # --- Projection overlay curves (hidden until enabled) ---
        self._h_baseline = pg.PlotDataItem(pen=pg.mkPen(None))
        self._h_overlay_curve = pg.PlotDataItem(
            pen=pg.mkPen(QColor(theme.h_curve), width=1.4),
        )
        h_fill_color = QColor(theme.h_curve)
        h_fill_color.setAlpha(50)
        self._h_fill = pg.FillBetweenItem(
            self._h_baseline, self._h_overlay_curve, brush=h_fill_color,
        )
        self.plot.addItem(self._h_baseline)
        self.plot.addItem(self._h_overlay_curve)
        self.plot.addItem(self._h_fill)
        self._h_baseline.hide()
        self._h_overlay_curve.hide()
        self._h_fill.hide()

        self._v_baseline = pg.PlotDataItem(pen=pg.mkPen(None))
        self._v_overlay_curve = pg.PlotDataItem(
            pen=pg.mkPen(QColor(theme.v_curve), width=1.4),
        )
        v_fill_color = QColor(theme.v_curve)
        v_fill_color.setAlpha(50)
        self._v_fill = pg.FillBetweenItem(
            self._v_baseline, self._v_overlay_curve, brush=v_fill_color,
        )
        self.plot.addItem(self._v_baseline)
        self.plot.addItem(self._v_overlay_curve)
        self.plot.addItem(self._v_fill)
        self._v_baseline.hide()
        self._v_overlay_curve.hide()
        self._v_fill.hide()

        self._apply_header_style(theme)

    # ------------------------------------------------------------------
    # Projection overlay API
    # ------------------------------------------------------------------

    def update_projections(
        self,
        x_proj: Optional[np.ndarray],
        y_proj: Optional[np.ndarray],
        img_shape: tuple,
        state: OverlayState,
    ) -> None:
        """Render projection overlays on the image according to *state*.

        Parameters
        ----------
        x_proj : 1-D array (length = image width), or None
        y_proj : 1-D array (length = image height), or None
        img_shape : (height, width)
        state : current OverlayState
        """
        H, W = img_shape[:2]

        # --- horizontal overlay ---
        if state.h_enabled and x_proj is not None and len(x_proj) > 0:
            x_coords = np.arange(len(x_proj), dtype=np.float64)
            pmax = float(np.max(x_proj))
            norm = x_proj / pmax if pmax > 0 else np.zeros_like(x_proj)
            amp_px = state.scale * H

            if state.h_side == "bottom":
                baseline_y = np.full_like(x_coords, float(H))
                curve_y = H - norm * amp_px
            else:  # top
                baseline_y = np.zeros_like(x_coords)
                curve_y = norm * amp_px

            self._h_baseline.setData(x_coords, baseline_y)
            self._h_overlay_curve.setData(x_coords, curve_y)
            self._h_baseline.show()
            self._h_overlay_curve.show()
            self._h_fill.show()
        else:
            self._h_baseline.hide()
            self._h_overlay_curve.hide()
            self._h_fill.hide()

        # --- vertical overlay ---
        if state.v_enabled and y_proj is not None and len(y_proj) > 0:
            y_coords = np.arange(len(y_proj), dtype=np.float64)
            pmax = float(np.max(y_proj))
            norm = y_proj / pmax if pmax > 0 else np.zeros_like(y_proj)
            amp_px = state.scale * W

            if state.v_side == "left":
                baseline_x = np.zeros_like(y_coords)
                curve_x = norm * amp_px
            else:  # right
                baseline_x = np.full_like(y_coords, float(W))
                curve_x = W - norm * amp_px

            self._v_baseline.setData(baseline_x, y_coords)
            self._v_overlay_curve.setData(curve_x, y_coords)
            self._v_baseline.show()
            self._v_overlay_curve.show()
            self._v_fill.show()
        else:
            self._v_baseline.hide()
            self._v_overlay_curve.hide()
            self._v_fill.hide()

    def clear_projections(self) -> None:
        """Hide all projection overlays."""
        for item in (
            self._h_baseline, self._h_overlay_curve, self._h_fill,
            self._v_baseline, self._v_overlay_curve, self._v_fill,
        ):
            item.hide()

    def apply_overlay_theme(self, theme: _Theme) -> None:
        """Update overlay curve and fill colours to match *theme*."""
        self._h_overlay_curve.setPen(pg.mkPen(QColor(theme.h_curve), width=1.4))
        h_fill = QColor(theme.h_curve)
        h_fill.setAlpha(50)
        self._h_fill.setBrush(h_fill)

        self._v_overlay_curve.setPen(pg.mkPen(QColor(theme.v_curve), width=1.4))
        v_fill = QColor(theme.v_curve)
        v_fill.setAlpha(50)
        self._v_fill.setBrush(v_fill)

    # ------------------------------------------------------------------
    # Mouse event filter — ROI drawing
    # ------------------------------------------------------------------

    def eventFilter(self, obj: object, event: QEvent) -> bool:  # type: ignore[override]
        if not self._enable_roi or obj is not self.plot.viewport():
            return super().eventFilter(obj, event)

        etype = event.type()

        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            pt = self._viewport_to_data(event.pos())
            if pt is not None:
                self._drawing = True
                self._draw_start = (pt.x(), pt.y())
                # Hide any previous ROI while the user starts a new draw
                if self._roi_display is not None:
                    self._roi_display.hide()
            return True

        if etype == QEvent.MouseMove and self._drawing:
            pt = self._viewport_to_data(event.pos())
            if pt is not None and self._draw_start is not None:
                self._live_update_display(pt.x(), pt.y())
            return True

        if (
            etype == QEvent.MouseButtonRelease
            and event.button() == Qt.LeftButton
            and self._drawing
        ):
            self._drawing = False
            pt = self._viewport_to_data(event.pos())
            if pt is not None and self._draw_start is not None:
                x0, y0 = self._draw_start
                x1, y1 = pt.x(), pt.y()
                lx, rx = min(x0, x1), max(x0, x1)
                ty, by = min(y0, y1), max(y0, y1)
                if rx - lx >= 5 and by - ty >= 5:
                    self._current_roi = (int(lx), int(ty), int(rx), int(by))
                    self._sync_roi_display()
                    self.roi_changed.emit(self._current_roi)
                else:
                    # Drag too small — treat as a cancelled draw
                    if self._roi_display is not None:
                        self._roi_display.hide()
            return True

        return super().eventFilter(obj, event)

    def _viewport_to_data(self, vp_pos) -> Optional[pg.Point]:
        """Convert a viewport QPoint to view/data coordinates."""
        try:
            scene_pos = self.plot.mapToScene(vp_pos)
            return self.plot.getViewBox().mapSceneToView(scene_pos)
        except Exception:
            return None

    def _live_update_display(self, x1: float, y1: float) -> None:
        """Redraw the overlay rectangle live during a drag."""
        if self._draw_start is None or self._roi_display is None:
            return
        x0, y0 = self._draw_start
        lx, rx = min(x0, x1), max(x0, x1)
        ty, by = min(y0, y1), max(y0, y1)
        self._roi_display.blockSignals(True)
        self._roi_display.setPos([lx, ty])
        self._roi_display.setSize([rx - lx, by - ty])
        self._roi_display.blockSignals(False)
        self._roi_display.show()

    def _sync_roi_display(self) -> None:
        """Update the overlay rectangle to match *_current_roi*."""
        if self._current_roi is None or self._roi_display is None:
            return
        x0, y0, x1, y1 = self._current_roi
        self._roi_display.blockSignals(True)
        self._roi_display.setPos([x0, y0])
        self._roi_display.setSize([x1 - x0, y1 - y0])
        self._roi_display.blockSignals(False)
        self._roi_display.show()

    # ------------------------------------------------------------------
    # Public ROI API
    # ------------------------------------------------------------------

    @property
    def current_roi(self) -> Optional[tuple]:
        """Current ROI as ``(x0, y0, x1, y1)`` in image pixels, or None."""
        return self._current_roi

    def clear_roi(self) -> None:
        """Clear the current ROI selection and emit *roi_changed(None)*."""
        self._current_roi = None
        self._drawing = False
        self._draw_start = None
        if self._roi_display is not None:
            self._roi_display.hide()
        self.roi_changed.emit(None)

    def set_roi(self, roi: Optional[tuple]) -> None:
        """Programmatically set or clear the ROI, emitting *roi_changed*."""
        if roi is None:
            self.clear_roi()
            return
        self._current_roi = roi
        self._sync_roi_display()
        self.roi_changed.emit(self._current_roi)

    # ------------------------------------------------------------------
    # Standard pane API
    # ------------------------------------------------------------------

    def _apply_header_style(self, theme: _Theme) -> None:
        self.header.setStyleSheet(
            f"background: {theme.panel_bg}; color: {theme.accent}; "
            f"font-size: 12px; font-weight: 600; padding: 4px;"
        )

    def apply_theme(self, theme: _Theme) -> None:
        """Update chrome colours.  Image bg intentionally stays dark."""
        self._apply_header_style(theme)
        self.apply_overlay_theme(theme)

    def set_axis_range(self, x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        """Set the visible pixel axis range.

        Parameters
        ----------
        x_min, x_max : float
            Horizontal pixel range (left edge, right edge)
        y_min, y_max : float
            Vertical pixel range (top edge, bottom edge)
        """
        self.plot.setRange(xRange=(x_min, x_max), yRange=(y_min, y_max), padding=0)

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

    def get_roi_slice(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Return the sub-array of *frame* clipped to *current_roi*, or None."""
        if self._current_roi is None:
            return None
        x0, y0, x1, y1 = self._current_roi
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(frame.shape[1], x1)
        y1 = min(frame.shape[0], y1)
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
    roi_changed = pyqtSignal(object)  # (x0, y0, x1, y1) tuple or None when cleared
    center_roi_requested = pyqtSignal()
    acquire_background_requested = pyqtSignal()
    bg_subtraction_toggled = pyqtSignal(bool)
    overlay_settings_changed = pyqtSignal(object)  # OverlayState
    # Emitted from a background thread when ROI fitting completes.
    # Payload is a tuple (seq: int, bp: BeamParameters).
    _roi_analysis_ready = pyqtSignal(object)

    def __init__(self, fallback_shape: Optional[tuple] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme: _Theme = DARK
        self._fallback_shape = fallback_shape  # (height, width) for axis ranges
        self._overlay_state = OverlayState()

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

        self.image_pane_1 = _ImagePane("Full Image", self._theme, enable_roi=True)
        self.image_pane_2 = _ImagePane("ROI", self._theme)

        self._last_frame: Optional[np.ndarray] = None
        self._last_frame_number: int = 0
        # Frame rate tracking
        self._start_time: Optional[float] = None
        self._last_frame_time: Optional[float] = None
        # Sequence counter used to discard stale ROI fit results.
        self._roi_seq: int = 0
        # Prevent more than one ROI fit thread from running at a time.
        self._roi_fit_running: bool = False

        # Wire up the cross-thread ROI result signal.
        self._roi_analysis_ready.connect(self._on_roi_analysis_ready)

        # ROI selection: _on_roi_changed handles visibility + persistence
        self.image_pane_1.roi_changed.connect(self._on_roi_changed)

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

        # ROI section (bottom pane + ROI projections) hidden until the user
        # draws a selection on the full image.
        self.image_pane_2.hide()
        self.h_proj_2.hide()
        self.v_proj_2.hide()

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
        self._theme_btn.setCursor(Qt.PointingHandCursor)
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

        # Refresh bg status label colour with new theme colours
        has_bg = self.bg_status_label.property("has_bg") or False
        sub_on = self.bg_subtract_btn.isChecked()
        self._update_bg_status_label(has_bg, sub_on)

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
        self.stream_btn = QPushButton("Streaming")
        self.stream_btn.setCheckable(True)
        self.stream_btn.setChecked(True)
        self.stream_btn.setMinimumHeight(32)
        # Apply initial streaming style (green)
        self.stream_btn.setStyleSheet(
            "QPushButton { background-color: #2ecc71; color: #ffffff; font-weight: 600; }"
        )
        acq_lay.addWidget(self.stream_btn)

        self.acquire_bg_btn = QPushButton("Acquire Background")
        self.acquire_bg_btn.setMinimumHeight(28)
        self.acquire_bg_btn.setToolTip("Capture the current frame as the background reference")
        acq_lay.addWidget(self.acquire_bg_btn)

        self.bg_subtract_btn = QPushButton("Background Sub")
        self.bg_subtract_btn.setCheckable(True)
        self.bg_subtract_btn.setChecked(False)
        self.bg_subtract_btn.setEnabled(False)   # disabled until a BG is acquired
        self.bg_subtract_btn.setMinimumHeight(28)
        self.bg_subtract_btn.setToolTip("Subtract the stored background from every incoming frame")
        acq_lay.addWidget(self.bg_subtract_btn)

        self.bg_status_label = QLabel("BG: none")
        self.bg_status_label.setAlignment(Qt.AlignCenter)
        self.bg_status_label.setStyleSheet(
            f"color: {self._theme.text_dim}; font-size: 11px; font-family: {_MONO};"
        )
        acq_lay.addWidget(self.bg_status_label)

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

        self.clear_roi_btn = QPushButton("✕  Clear ROI")
        self.clear_roi_btn.setMinimumHeight(28)
        self.clear_roi_btn.setToolTip("Remove the current ROI selection")
        analysis_lay.addWidget(self.clear_roi_btn)

        self.center_roi_btn = QPushButton("⊕  Center ROI")
        self.center_roi_btn.setMinimumHeight(28)
        self.center_roi_btn.setToolTip(
            "Re-center the ROI as a square around the intensity centroid"
        )
        self.center_roi_btn.setEnabled(False)
        analysis_lay.addWidget(self.center_roi_btn)

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

        # ── Projection Overlays ───────────────────────────────────
        overlay_grp = QGroupBox("Projection Overlays")
        overlay_lay = QGridLayout(overlay_grp)
        overlay_lay.setContentsMargins(8, 12, 8, 8)
        overlay_lay.setSpacing(6)
        overlay_lay.setColumnStretch(1, 1)

        # H overlay toggle + side selector
        self.h_overlay_btn = QPushButton("H Overlay")
        self.h_overlay_btn.setCheckable(True)
        self.h_overlay_btn.setChecked(False)
        self.h_overlay_btn.setMinimumHeight(28)
        overlay_lay.addWidget(self.h_overlay_btn, 0, 0)

        self.h_overlay_side = QComboBox()
        self.h_overlay_side.addItems(["Bottom", "Top"])
        self.h_overlay_side.setCurrentIndex(0)
        self.h_overlay_side.setEnabled(False)
        overlay_lay.addWidget(self.h_overlay_side, 0, 1)

        # V overlay toggle + side selector
        self.v_overlay_btn = QPushButton("V Overlay")
        self.v_overlay_btn.setCheckable(True)
        self.v_overlay_btn.setChecked(False)
        self.v_overlay_btn.setMinimumHeight(28)
        overlay_lay.addWidget(self.v_overlay_btn, 1, 0)

        self.v_overlay_side = QComboBox()
        self.v_overlay_side.addItems(["Left", "Right"])
        self.v_overlay_side.setCurrentIndex(0)
        self.v_overlay_side.setEnabled(False)
        overlay_lay.addWidget(self.v_overlay_side, 1, 1)

        # Scale slider
        overlay_lay.addWidget(QLabel("Scale:"), 2, 0)
        scale_row = QHBoxLayout()
        self.overlay_scale_slider = QSlider(Qt.Horizontal)
        self.overlay_scale_slider.setRange(5, 50)   # 5% – 50%
        self.overlay_scale_slider.setValue(25)
        self.overlay_scale_slider.setTickInterval(5)
        self.overlay_scale_label = QLabel("25%")
        scale_row.addWidget(self.overlay_scale_slider, stretch=1)
        scale_row.addWidget(self.overlay_scale_label)
        scale_container = QWidget()
        scale_container.setLayout(scale_row)
        overlay_lay.addWidget(scale_container, 2, 1)

        lay.addWidget(overlay_grp)

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
        self.clear_roi_btn.clicked.connect(self._on_clear_roi_clicked)
        self.center_roi_btn.clicked.connect(self._on_center_roi_clicked)
        self.colormap_combo.currentTextChanged.connect(
            self.colormap_changed.emit,
        )
        self.acquire_bg_btn.clicked.connect(self.acquire_background_requested.emit)
        self.bg_subtract_btn.toggled.connect(self._on_bg_subtraction_toggled)

        # Overlay controls
        self.h_overlay_btn.toggled.connect(self._on_overlay_changed)
        self.h_overlay_side.currentTextChanged.connect(
            lambda _: self._on_overlay_changed(),
        )
        self.v_overlay_btn.toggled.connect(self._on_overlay_changed)
        self.v_overlay_side.currentTextChanged.connect(
            lambda _: self._on_overlay_changed(),
        )
        self.overlay_scale_slider.valueChanged.connect(self._on_overlay_scale_changed)

        return panel

    def _on_stream_toggled(self, checked: bool) -> None:
        """Update button text, color, and emit streaming signal."""
        if checked:
            self.stream_btn.setText("Streaming")
            # Green background for streaming
            self.stream_btn.setStyleSheet(
                f"QPushButton {{ background-color: #2ecc71; color: #ffffff; font-weight: 600; }}"
            )
        else:
            self.stream_btn.setText("Paused")
            # Red background for paused
            self.stream_btn.setStyleSheet(
                f"QPushButton {{ background-color: #e74c3c; color: #ffffff; font-weight: 600; }}"
            )
        self.streaming_toggled.emit(checked)

    def _on_bg_subtraction_toggled(self, checked: bool) -> None:
        self.bg_subtract_btn.setText(
            "✓  Background Sub ON" if checked else "Background Sub OFF"
        )
        self.bg_subtraction_toggled.emit(checked)
        # Refresh the status label text to reflect the new state
        has_bg = self.bg_status_label.property("has_bg") or False
        self._update_bg_status_label(has_bg, checked)

    def _on_overlay_changed(self, _checked: bool = False) -> None:
        """Read the overlay controls, update state, refresh overlays, and emit."""
        h_on = self.h_overlay_btn.isChecked()
        v_on = self.v_overlay_btn.isChecked()
        self.h_overlay_btn.setText("✓  H Overlay" if h_on else "H Overlay")
        self.v_overlay_btn.setText("✓  V Overlay" if v_on else "V Overlay")
        self.h_overlay_side.setEnabled(h_on)
        self.v_overlay_side.setEnabled(v_on)

        self._overlay_state.h_enabled = h_on
        self._overlay_state.h_side = self.h_overlay_side.currentText().lower()
        self._overlay_state.v_enabled = v_on
        self._overlay_state.v_side = self.v_overlay_side.currentText().lower()

        self._refresh_overlays()
        self.overlay_settings_changed.emit(self._overlay_state)

    def _on_overlay_scale_changed(self, value: int) -> None:
        """Update overlay scale from the slider (5–50 → 0.05–0.50)."""
        self._overlay_state.scale = value / 100.0
        self.overlay_scale_label.setText(f"{value}%")
        self._refresh_overlays()
        self.overlay_settings_changed.emit(self._overlay_state)

    def _refresh_overlays(self) -> None:
        """Recompute and redraw projection overlays on both image panes."""
        if self._last_frame is None:
            return
        frame = self._last_frame
        h, w = frame.shape[:2]
        x_proj = np.mean(frame, axis=0)
        y_proj = np.mean(frame, axis=1)
        self.image_pane_1.update_projections(x_proj, y_proj, (h, w), self._overlay_state)

        # ROI pane
        roi_frame = self.image_pane_1.get_roi_slice(frame)
        if roi_frame is not None and roi_frame.size > 0:
            roi_x = np.mean(roi_frame, axis=0)
            roi_y = np.mean(roi_frame, axis=1)
            self.image_pane_2.update_projections(
                roi_x, roi_y, roi_frame.shape[:2], self._overlay_state,
            )
        else:
            self.image_pane_2.clear_projections()

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

    def _on_clear_roi_clicked(self) -> None:
        self.image_pane_1.clear_roi()

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

        # Square half-side = larger of the two current half-dimensions
        half = max(x1c - x0c, y1c - y0c) // 2

        # New ROI clamped to image bounds
        nx0 = max(0,  cx - half)
        ny0 = max(0,  cy - half)
        nx1 = min(fw, cx + half)
        ny1 = min(fh, cy + half)

        self.image_pane_1.set_roi((nx0, ny0, nx1, ny1))

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
        self.bg_status_label.setText(text)
        self.bg_status_label.setStyleSheet(style)
        self.bg_status_label.setProperty("has_bg", has_bg)

    def set_bg_status(self, has_bg: bool, sub_enabled: bool) -> None:
        """Called by the controller after background acquisition or toggle.

        Enables/disables the subtraction toggle and updates the status label.
        Does NOT emit any signal (controller-driven update).
        """
        self.bg_subtract_btn.setEnabled(has_bg)
        self.bg_subtract_btn.blockSignals(True)
        self.bg_subtract_btn.setChecked(sub_enabled)
        self.bg_subtract_btn.setText(
            "✓  Background Sub ON" if sub_enabled else "Background Sub OFF"
        )
        self.bg_subtract_btn.blockSignals(False)
        self._update_bg_status_label(has_bg, sub_enabled)

    def reset_bg_controls(self) -> None:
        """Reset all background controls to their initial state (e.g. on camera switch)."""
        self.bg_subtract_btn.blockSignals(True)
        self.bg_subtract_btn.setChecked(False)
        self.bg_subtract_btn.setText("Background Sub")
        self.bg_subtract_btn.setEnabled(False)
        self.bg_subtract_btn.blockSignals(False)
        self._update_bg_status_label(has_bg=False, sub_enabled=False)

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
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:  # type: ignore[attr-defined]
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

        # full-image projection overlays
        x_proj = np.mean(frame, axis=0)
        y_proj = np.mean(frame, axis=1)
        if fs.analysis is not None:
            x_proj = fs.analysis.x_projection
            y_proj = fs.analysis.y_projection
        self.image_pane_1.update_projections(x_proj, y_proj, (h, w), self._overlay_state)

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

    @pyqtSlot(object)
    def _on_roi_changed(self, roi: object) -> None:
        """Called when the user draws a new ROI or clears the existing one."""
        self._set_roi_section_visible(roi is not None)
        self.center_roi_btn.setEnabled(roi is not None)
        if roi is not None:
            self._update_roi()
            # Clear stale projections from a previous ROI when a new one is drawn
        else:
            self.h_proj_2.clear_fit()
            self.v_proj_2.clear_fit()
        self.roi_changed.emit(roi)

    def restore_roi(self, roi: Optional[tuple]) -> None:
        """Silently restore a saved ROI (does not trigger save-to-config)."""
        self.image_pane_1.blockSignals(True)
        self.image_pane_1.set_roi(roi)
        self.image_pane_1.blockSignals(False)
        self._set_roi_section_visible(roi is not None)
        self.center_roi_btn.setEnabled(roi is not None)
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
        # Update controls to match — block signals to avoid re-emission
        self.h_overlay_btn.blockSignals(True)
        self.h_overlay_btn.setChecked(state.h_enabled)
        self.h_overlay_btn.setText("✓  H Overlay" if state.h_enabled else "H Overlay")
        self.h_overlay_btn.blockSignals(False)

        self.h_overlay_side.blockSignals(True)
        self.h_overlay_side.setCurrentText(state.h_side.capitalize())
        self.h_overlay_side.setEnabled(state.h_enabled)
        self.h_overlay_side.blockSignals(False)

        self.v_overlay_btn.blockSignals(True)
        self.v_overlay_btn.setChecked(state.v_enabled)
        self.v_overlay_btn.setText("✓  V Overlay" if state.v_enabled else "V Overlay")
        self.v_overlay_btn.blockSignals(False)

        self.v_overlay_side.blockSignals(True)
        self.v_overlay_side.setCurrentText(state.v_side.capitalize())
        self.v_overlay_side.setEnabled(state.v_enabled)
        self.v_overlay_side.blockSignals(False)

        slider_val = max(5, min(50, int(state.scale * 100)))
        self.overlay_scale_slider.blockSignals(True)
        self.overlay_scale_slider.setValue(slider_val)
        self.overlay_scale_slider.blockSignals(False)
        self.overlay_scale_label.setText(f"{slider_val}%")

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

        # Set axis ranges for ROI based on current ROI coordinates
        # and position the cropped sub-image at its full-image offset so
        # that it aligns with the pixel-coordinate axes.
        roi = self.image_pane_1.current_roi
        if roi is not None:
            x0, y0, x1, y1 = roi
            self.image_pane_2.set_axis_range(x0, x1, y0, y1)
            self.image_pane_2.image_item.setPos(x0, y0)

        self.image_pane_2.set_image(roi_frame, self._last_frame_number)

        # Always compute projections synchronously — this is just array
        # summations and is never a source of hangs.
        bp_no_fit = analyze_frame(roi_frame, do_fit=False)
        self.h_proj_2.set_projection(bp_no_fit.x_projection)
        self.v_proj_2.set_projection(bp_no_fit.y_projection)

        # ROI projection overlays
        self.image_pane_2.update_projections(
            bp_no_fit.x_projection, bp_no_fit.y_projection,
            roi_frame.shape[:2], self._overlay_state,
        )

        if not self.fit_roi_btn.isChecked():
            # Fitting is off — clear stats immediately and stop here.
            self.h_proj_2.clear_fit()
            self.v_proj_2.clear_fit()
            return
        # Fitting is on — leave the previous fit stats visible while the new
        # fit is being computed in the background (avoids the flash-to-dashes
        # on every tick).  Stats will be replaced when _on_roi_analysis_ready
        # fires, mirroring how the full-image projections behave.

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
