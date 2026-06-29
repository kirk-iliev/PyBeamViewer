"""Camera image display pane with optional ROI drawing and projection overlays."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from .overlay_state import OverlayState
from .theme import Theme


class ImagePane(QWidget):
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
        theme: Theme,
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

        # --- Centroid crosshairs: red = reference anchor, green = live position ---
        _ref_pen = pg.mkPen("#ff4444", width=1.5)
        self._ref_crosshair_h = pg.PlotDataItem(pen=_ref_pen)
        self._ref_crosshair_v = pg.PlotDataItem(pen=_ref_pen)
        self._ref_crosshair_circle = pg.ScatterPlotItem(
            symbol='o', size=24,
            pen=pg.mkPen("#ff4444", width=1.5),
            brush=pg.mkBrush(None),
        )
        self.plot.addItem(self._ref_crosshair_h)
        self.plot.addItem(self._ref_crosshair_v)
        self.plot.addItem(self._ref_crosshair_circle)
        self._ref_crosshair_h.hide()
        self._ref_crosshair_v.hide()
        self._ref_crosshair_circle.hide()

        _live_pen = pg.mkPen("#00ff00", width=1.5)
        self._live_crosshair_h = pg.PlotDataItem(pen=_live_pen)
        self._live_crosshair_v = pg.PlotDataItem(pen=_live_pen)
        self._live_crosshair_circle = pg.ScatterPlotItem(
            symbol='o', size=24,
            pen=pg.mkPen("#00ff00", width=1.5),
            brush=pg.mkBrush(None),
        )
        self.plot.addItem(self._live_crosshair_h)
        self.plot.addItem(self._live_crosshair_v)
        self.plot.addItem(self._live_crosshair_circle)
        self._live_crosshair_h.hide()
        self._live_crosshair_v.hide()
        self._live_crosshair_circle.hide()

        self._apply_header_style(theme)

    # ------------------------------------------------------------------
    # Centroid crosshair API
    # ------------------------------------------------------------------

    _CROSSHAIR_ARM = 12.0

    def set_reference_crosshair(self, cx: float, cy: float, visible: bool) -> None:
        """Show or hide the red reference-anchor crosshair at (cx, cy)."""
        if not visible:
            self._ref_crosshair_h.hide()
            self._ref_crosshair_v.hide()
            self._ref_crosshair_circle.hide()
            return
        arm = self._CROSSHAIR_ARM
        self._ref_crosshair_h.setData([cx - arm, cx + arm], [cy, cy])
        self._ref_crosshair_v.setData([cx, cx], [cy - arm, cy + arm])
        self._ref_crosshair_circle.setData([cx], [cy])
        self._ref_crosshair_h.show()
        self._ref_crosshair_v.show()
        self._ref_crosshair_circle.show()

    def set_live_crosshair(self, cx: float, cy: float, visible: bool) -> None:
        """Show or hide the green live-centroid crosshair at (cx, cy)."""
        if not visible:
            self._live_crosshair_h.hide()
            self._live_crosshair_v.hide()
            self._live_crosshair_circle.hide()
            return
        arm = self._CROSSHAIR_ARM
        self._live_crosshair_h.setData([cx - arm, cx + arm], [cy, cy])
        self._live_crosshair_v.setData([cx, cx], [cy - arm, cy + arm])
        self._live_crosshair_circle.setData([cx], [cy])
        self._live_crosshair_h.show()
        self._live_crosshair_v.show()
        self._live_crosshair_circle.show()

    def clear_centroid_crosshair(self) -> None:
        """Hide both the reference and live crosshairs."""
        for item in (
            self._ref_crosshair_h, self._ref_crosshair_v, self._ref_crosshair_circle,
            self._live_crosshair_h, self._live_crosshair_v, self._live_crosshair_circle,
        ):
            item.hide()

    # ------------------------------------------------------------------
    # Projection overlay API
    # ------------------------------------------------------------------

    def update_projections(
        self,
        x_proj: Optional[np.ndarray],
        y_proj: Optional[np.ndarray],
        img_shape: tuple,
        state: OverlayState,
        x_offset: float = 0.0,
        y_offset: float = 0.0,
    ) -> None:
        """Render projection overlays on the image according to *state*.

        Parameters
        ----------
        x_proj : 1-D array (length = image width), or None
        y_proj : 1-D array (length = image height), or None
        img_shape : (height, width)
        state : current OverlayState
        x_offset, y_offset : origin of the image in view/data coordinates.
            Must be non-zero for sub-regions (e.g. the ROI pane) whose
            ``image_item`` has been positioned at the ROI origin so that
            pixel axes show full-image coordinates.
        """
        H, W = img_shape[:2]

        # --- horizontal overlay ---
        if state.h_enabled and x_proj is not None and len(x_proj) > 0:
            x_coords = np.arange(len(x_proj), dtype=np.float64) + x_offset
            pmax = float(np.max(x_proj))
            norm = x_proj / pmax if pmax > 0 else np.zeros_like(x_proj)
            amp_px = state.scale * H

            if state.h_side == "bottom":
                baseline_y = np.full_like(x_coords, float(H) + y_offset)
                curve_y = H - norm * amp_px + y_offset
            else:  # top
                baseline_y = np.full_like(x_coords, y_offset)
                curve_y = norm * amp_px + y_offset

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
            y_coords = np.arange(len(y_proj), dtype=np.float64) + y_offset
            pmax = float(np.max(y_proj))
            norm = y_proj / pmax if pmax > 0 else np.zeros_like(y_proj)
            amp_px = state.scale * W

            if state.v_side == "left":
                baseline_x = np.full_like(y_coords, x_offset)
                curve_x = norm * amp_px + x_offset
            else:  # right
                baseline_x = np.full_like(y_coords, float(W) + x_offset)
                curve_x = W - norm * amp_px + x_offset

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

    def apply_overlay_theme(self, theme: Theme) -> None:
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

    def _apply_header_style(self, theme: Theme) -> None:
        self.header.setStyleSheet(
            f"background: {theme.panel_bg}; color: {theme.accent}; "
            f"font-size: 12px; font-weight: 600; padding: 4px;"
        )

    def apply_theme(self, theme: Theme) -> None:
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
        # Clamp the view to the sensor extent so aspect-lock expansion cannot
        # overscan the axes beyond the actual frame (e.g. V-axis -200..+1200
        # on a ~1024 px sensor). Pixels stay square; perpendicular axis
        # letterboxes with background margin instead.
        self.plot.setLimits(
            xMin=x_min, xMax=x_max, yMin=y_min, yMax=y_max
        )

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
