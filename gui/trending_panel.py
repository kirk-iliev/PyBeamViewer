"""Trending panel — time-series plots of fit results and centroid drift.

Shows stacked `pyqtgraph` plots that auto-scroll with incoming data.
Individual sub-plots are conditionally visible based on which fit
toggles are active in the control panel.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import Theme, _MONO


class _TrendSubPlot(QWidget):
    """A single trending sub-plot with a title header and two traces."""

    def __init__(
        self,
        title: str,
        trace_a_label: str,
        trace_b_label: str,
        color_a: str,
        color_b: str,
        theme: Theme,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._color_a = color_a
        self._color_b = color_b

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 0)
        lay.setSpacing(1)

        # --- title row: label + auto-scale toggle ---
        # When auto is on, the x-axis auto-scrolls with incoming data. As soon
        # as the user pans/zooms or edits the axis range, auto turns off so the
        # manual range sticks during streaming (no need to pause). Clicking the
        # button re-enables auto.
        self._auto = True
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        self.title_label = QLabel(title)
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        self.auto_btn = QPushButton("⟲ Auto")
        self.auto_btn.setCheckable(True)
        self.auto_btn.setChecked(True)
        self.auto_btn.setMaximumHeight(20)
        self.auto_btn.setToolTip(
            "Auto-scale axes with incoming data. Turns off automatically when "
            "you pan, zoom, or set a range manually; click to re-enable."
        )
        self.auto_btn.toggled.connect(self._on_auto_toggled)
        title_row.addWidget(self.auto_btn)
        lay.addLayout(title_row)

        # --- legend-style stats bar ---
        self.stats_label = QLabel(f"  {trace_a_label}: ——    {trace_b_label}: ——")
        self._trace_a_label = trace_a_label
        self._trace_b_label = trace_b_label
        lay.addWidget(self.stats_label)

        # --- pyqtgraph plot ---
        self.pw = pg.PlotWidget()
        self.pw.getPlotItem().showGrid(x=True, y=True, alpha=0.12)
        self.pw.setMinimumHeight(70)
        self.pw.setLabel("bottom", "Frame #")
        lay.addWidget(self.pw, stretch=1)

        # Detect manual pan/zoom/range edits so auto-scroll yields to the user.
        self.pw.getPlotItem().getViewBox().sigRangeChangedManually.connect(
            self._on_manual_range
        )

        self.curve_a = self.pw.plot(
            pen=pg.mkPen(color_a, width=1.3), name=trace_a_label,
        )
        self.curve_b = self.pw.plot(
            pen=pg.mkPen(color_b, width=1.3), name=trace_b_label,
        )

        self._apply_theme_internals(theme)

    def _apply_theme_internals(self, theme: Theme) -> None:
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
        self.stats_label.setStyleSheet(
            f"color: {theme.text_dim}; font-family: {_MONO}; font-size: 11px; "
            f"padding-left: 4px;"
        )

    def apply_theme(self, theme: Theme) -> None:
        self._apply_theme_internals(theme)
        self.curve_a.setPen(pg.mkPen(self._color_a, width=1.3))
        self.curve_b.setPen(pg.mkPen(self._color_b, width=1.3))

    def _on_manual_range(self) -> None:
        """User panned/zoomed/edited the range — stop auto-scrolling."""
        if self._auto:
            # setChecked(False) -> _on_auto_toggled keeps state consistent.
            self.auto_btn.setChecked(False)

    def _on_auto_toggled(self, checked: bool) -> None:
        self._auto = checked
        if checked:
            # Resume: let pyqtgraph rescale the y-axis; the next update_data
            # re-applies the x auto-scroll.
            self.pw.enableAutoRange(axis="y")

    def update_data(
        self,
        x: np.ndarray,
        y_a: np.ndarray,
        y_b: np.ndarray,
    ) -> None:
        """Push new data to both traces and update the stats label."""
        # Filter out NaN for display
        mask_a = ~np.isnan(y_a)
        mask_b = ~np.isnan(y_b)

        if np.any(mask_a):
            self.curve_a.setData(x[mask_a], y_a[mask_a])
            latest_a = f"{y_a[mask_a][-1]:.3f}"
        else:
            self.curve_a.clear()
            latest_a = "——"

        if np.any(mask_b):
            self.curve_b.setData(x[mask_b], y_b[mask_b])
            latest_b = f"{y_b[mask_b][-1]:.3f}"
        else:
            self.curve_b.clear()
            latest_b = "——"

        self.stats_label.setText(
            f"  {self._trace_a_label}: {latest_a}    "
            f"{self._trace_b_label}: {latest_b}"
        )

        # Auto-scroll x-axis to show all available data (unless the user has
        # taken manual control of the range during streaming).
        if self._auto and len(x) > 0:
            x_min = float(x[0])
            x_max = float(x[-1])
            pad = max((x_max - x_min) * 0.02, 1)
            self.pw.setXRange(x_min - pad, x_max + pad, padding=0)

    def clear_data(self) -> None:
        self.curve_a.clear()
        self.curve_b.clear()
        self.stats_label.setText(
            f"  {self._trace_a_label}: ——    {self._trace_b_label}: ——"
        )


class TrendingPanel(QWidget):
    """Collapsible panel with stacked time-series plots.

    Sub-plots are conditionally visible:
    - ROI σ plot → only when 'Fit ROI' is active
    - Full σ plot → only when 'Fit Full Image' is active
    - Drift plot → only when a crosshair reference is set
    """

    def __init__(self, theme: Theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # Header
        self._header = QLabel("Trending")
        self._header.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._header)

        # --- ROI Beam Size (priority — on top) ---
        self.roi_sigma_plot = _TrendSubPlot(
            title="ROI Beam Size",
            trace_a_label="σx",
            trace_b_label="σy",
            color_a="#00e5ff",   # cyan — matches h_curve
            color_b="#ce93d8",   # lavender — matches v_curve
            theme=theme,
        )
        self.roi_sigma_plot.hide()
        lay.addWidget(self.roi_sigma_plot, stretch=1)

        # --- Full-Image Beam Size ---
        self.full_sigma_plot = _TrendSubPlot(
            title="Full Image Beam Size",
            trace_a_label="σx",
            trace_b_label="σy",
            color_a="#00e5ff",
            color_b="#ce93d8",
            theme=theme,
        )
        self.full_sigma_plot.hide()
        lay.addWidget(self.full_sigma_plot, stretch=1)

        # --- Centroid Drift ---
        self.drift_plot = _TrendSubPlot(
            title="Centroid Drift",
            trace_a_label="Δx",
            trace_b_label="Δy",
            color_a="#2ecc71",   # green
            color_b="#e67e22",   # orange
            theme=theme,
        )
        self.drift_plot.hide()
        lay.addWidget(self.drift_plot, stretch=1)

        # --- Placeholder when nothing is active ---
        self._placeholder = QLabel("No active trending sources")
        self._placeholder.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._placeholder, stretch=1)

        # State tracking
        self._fit_roi_visible = False
        self._fit_full_visible = False
        self._drift_visible = False

        self._apply_header_style(theme)
        self._update_placeholder()

    # ------------------------------------------------------------------
    # Visibility controls
    # ------------------------------------------------------------------

    def set_fit_roi_visible(self, visible: bool) -> None:
        """Show or hide the ROI sigma trending plot."""
        self._fit_roi_visible = visible
        self.roi_sigma_plot.setVisible(visible)
        if not visible:
            self.roi_sigma_plot.clear_data()
        self._update_placeholder()

    def set_fit_full_visible(self, visible: bool) -> None:
        """Show or hide the full-image sigma trending plot."""
        self._fit_full_visible = visible
        self.full_sigma_plot.setVisible(visible)
        if not visible:
            self.full_sigma_plot.clear_data()
        self._update_placeholder()

    def set_drift_visible(self, visible: bool) -> None:
        """Show or hide the centroid drift trending plot."""
        self._drift_visible = visible
        self.drift_plot.setVisible(visible)
        if not visible:
            self.drift_plot.clear_data()
        self._update_placeholder()

    def _update_placeholder(self) -> None:
        """Show the placeholder only when no sub-plots are visible."""
        any_visible = (
            self._fit_roi_visible
            or self._fit_full_visible
            or self._drift_visible
        )
        self._placeholder.setVisible(not any_visible)

    # ------------------------------------------------------------------
    # Data update
    # ------------------------------------------------------------------

    def update(self, history: Dict[str, np.ndarray]) -> None:
        """Push new trending data from the buffer to all visible plots."""
        frames = history.get("frame_number", np.array([]))
        if len(frames) == 0:
            return

        if self._fit_roi_visible:
            self.roi_sigma_plot.update_data(
                frames,
                history.get("roi_sigma_x", np.full_like(frames, np.nan)),
                history.get("roi_sigma_y", np.full_like(frames, np.nan)),
            )

        if self._fit_full_visible:
            self.full_sigma_plot.update_data(
                frames,
                history.get("sigma_x", np.full_like(frames, np.nan)),
                history.get("sigma_y", np.full_like(frames, np.nan)),
            )

        if self._drift_visible:
            self.drift_plot.update_data(
                frames,
                history.get("drift_x", np.full_like(frames, np.nan)),
                history.get("drift_y", np.full_like(frames, np.nan)),
            )

    def clear(self) -> None:
        """Clear all trending data from all sub-plots."""
        self.roi_sigma_plot.clear_data()
        self.full_sigma_plot.clear_data()
        self.drift_plot.clear_data()

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def _apply_header_style(self, theme: Theme) -> None:
        self._header.setStyleSheet(
            f"background: {theme.panel_bg}; color: {theme.accent}; "
            f"font-size: 12px; font-weight: 600; padding: 4px;"
        )
        self._placeholder.setStyleSheet(
            f"color: {theme.text_dim}; font-size: 12px; font-style: italic;"
        )

    def apply_theme(self, theme: Theme) -> None:
        """Update all chrome and curve colours to match *theme*."""
        self._theme = theme
        self._apply_header_style(theme)
        # Update sub-plot curve colours for dark/light mode
        self.roi_sigma_plot.apply_theme(theme)
        self.roi_sigma_plot._color_a = theme.h_curve
        self.roi_sigma_plot._color_b = theme.v_curve
        self.roi_sigma_plot.curve_a.setPen(pg.mkPen(theme.h_curve, width=1.3))
        self.roi_sigma_plot.curve_b.setPen(pg.mkPen(theme.v_curve, width=1.3))

        self.full_sigma_plot.apply_theme(theme)
        self.full_sigma_plot._color_a = theme.h_curve
        self.full_sigma_plot._color_b = theme.v_curve
        self.full_sigma_plot.curve_a.setPen(pg.mkPen(theme.h_curve, width=1.3))
        self.full_sigma_plot.curve_b.setPen(pg.mkPen(theme.v_curve, width=1.3))

        self.drift_plot.apply_theme(theme)
