"""Right-hand control panel widget (Camera, Acquire, Analysis, Display settings)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .theme import Theme, _MONO


class ControlPanel(QWidget):
    """Builds all control panel widgets as attributes — no signal wiring.

    Signal wiring is handled by the parent :class:`BeamViewerWindow` so
    that the panel stays a simple, layout-only component.
    """

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(320)
        self.setMaximumWidth(320)

        # Outer layout holds only the scroll area — no margins so the
        # scroll area fills the full 320 px width.
        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)

        # Scroll area: vertical scroll only, no frame border.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)
        outer_lay.addWidget(scroll)

        # Content widget that actually owns all the group boxes.
        _content = QWidget()
        scroll.setWidget(_content)
        lay = QVBoxLayout(_content)
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
            f"color: {theme.text_dim}; font-size: 11px; font-family: {_MONO};"
        )
        acq_lay.addWidget(self.bg_status_label)

        # Save / Load background buttons (side by side)
        bg_io_row = QHBoxLayout()
        bg_io_row.setSpacing(6)
        self.save_bg_btn = QPushButton("Save BG")
        self.save_bg_btn.setMinimumHeight(28)
        self.save_bg_btn.setEnabled(False)   # enabled once a BG exists
        self.save_bg_btn.setToolTip("Save the current background to disk")
        bg_io_row.addWidget(self.save_bg_btn)
        self.load_bg_btn = QPushButton("Load BG")
        self.load_bg_btn.setMinimumHeight(28)
        self.load_bg_btn.setToolTip("Load a previously saved background from disk")
        bg_io_row.addWidget(self.load_bg_btn)
        acq_lay.addLayout(bg_io_row)

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

        roi_size_row = QHBoxLayout()
        roi_size_row.setSpacing(6)
        roi_size_row.addWidget(QLabel("ROI size:"))
        self.roi_size_input = QSpinBox()
        self.roi_size_input.setRange(4, 4096)
        self.roi_size_input.setSingleStep(2)
        self.roi_size_input.setValue(40)
        self.roi_size_input.setSuffix(" px")
        self.roi_size_input.setToolTip(
            "Side length of the square ROI applied by Center ROI"
        )
        roi_size_row.addWidget(self.roi_size_input, stretch=1)
        analysis_lay.addLayout(roi_size_row)

        self.show_crosshair_btn = QPushButton("Show Centroid Ref")
        self.show_crosshair_btn.setCheckable(True)
        self.show_crosshair_btn.setChecked(False)
        self.show_crosshair_btn.setMinimumHeight(28)
        self.show_crosshair_btn.setEnabled(False)
        self.show_crosshair_btn.setToolTip(
            "Overlay a crosshair at the last centered position and show beam drift"
        )
        analysis_lay.addWidget(self.show_crosshair_btn)

        # Trending toggle + history depth
        self.trending_btn = QPushButton("📈  Trending")
        self.trending_btn.setCheckable(True)
        self.trending_btn.setChecked(False)
        self.trending_btn.setMinimumHeight(28)
        self.trending_btn.setToolTip(
            "Show time-series plots of fit results and centroid drift"
        )
        analysis_lay.addWidget(self.trending_btn)

        trending_depth_row = QHBoxLayout()
        trending_depth_row.setSpacing(6)
        trending_depth_row.addWidget(QLabel("History:"))
        self.trending_depth_input = QSpinBox()
        self.trending_depth_input.setRange(50, 2000)
        self.trending_depth_input.setSingleStep(50)
        self.trending_depth_input.setValue(300)
        self.trending_depth_input.setSuffix(" frames")
        self.trending_depth_input.setEnabled(False)  # enabled when trending is on
        self.trending_depth_input.setToolTip(
            "Number of frames to display in the trending plots"
        )
        trending_depth_row.addWidget(self.trending_depth_input, stretch=1)
        analysis_lay.addLayout(trending_depth_row)

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
        self.h_overlay_btn.setMinimumWidth(85)
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
        self.v_overlay_btn.setMinimumWidth(85)
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

        # Show-on scope: which panes receive the overlays
        overlay_lay.addWidget(QLabel("Show on:"), 3, 0)
        scope_row = QHBoxLayout()
        scope_row.setSpacing(6)
        self.overlay_show_full_btn = QPushButton("✓  Full")
        self.overlay_show_full_btn.setCheckable(True)
        self.overlay_show_full_btn.setChecked(True)
        self.overlay_show_full_btn.setMinimumHeight(26)
        self.overlay_show_full_btn.setMinimumWidth(65)
        scope_row.addWidget(self.overlay_show_full_btn)
        self.overlay_show_roi_btn = QPushButton("✓  ROI")
        self.overlay_show_roi_btn.setCheckable(True)
        self.overlay_show_roi_btn.setChecked(True)
        self.overlay_show_roi_btn.setMinimumHeight(26)
        self.overlay_show_roi_btn.setMinimumWidth(60)
        scope_row.addWidget(self.overlay_show_roi_btn)
        scope_container = QWidget()
        scope_container.setLayout(scope_row)
        overlay_lay.addWidget(scope_container, 3, 1)

        lay.addWidget(overlay_grp)

        lay.addStretch()

    def apply_theme(self, theme: Theme) -> None:
        """Re-style labels inside group-boxes for the given *theme*."""
        for grp in self.findChildren(QGroupBox):
            for lbl in grp.findChildren(QLabel):
                lbl.setStyleSheet(f"color: {theme.text_dim}; font-size: 12px;")
