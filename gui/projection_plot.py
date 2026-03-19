"""Single projection plot widget with stats label and Gaussian fit overlay."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from .theme import Theme, _MONO


class ProjectionPlot(QWidget):
    """Single projection plot with a title + stats label above it."""

    def __init__(
        self,
        title: str,
        curve_role: str,   # "h" | "v"  — determines which theme curve colour to use
        theme: Theme,
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

    def _apply_theme_internals(self, theme: Theme) -> None:
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

    def apply_theme(self, theme: Theme) -> None:
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
