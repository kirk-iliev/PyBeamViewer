"""
controller.py — Application controller.

Orchestrates the data pipeline:

    EPICS worker (thread)  ──signal──▶  Controller (main thread)
         │                                   │
         │  new_frame(ndarray)               │  1. queue frame to AnalysisWorker
         │                                   │  2. AnalysisWorker ──signal──▶ Controller
         ▼                                   │  3. update state
                                             │  4. push FrameState to GUI
                                             ▼
                                        GUI.update_display()

EPICS and Analysis workers run on separate threads; controller processes
their signals synchronously on the main thread, keeping GUI and state
logic inherently single-threaded and free of race conditions.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

log = logging.getLogger(__name__)

from analysis.analysis import analyze_frame
from analysis.analysis_worker import AnalysisWorker
from analysis.calibration import load_calibration
from config.config import (
    get_available_prefixes,
    get_active_prefix,
    get_pv_names,
    get_roi_for_prefix,
    save_roi_for_prefix,
    load_overlay_settings,
    save_overlay_settings,
    save_background_to_file,
    load_background_from_file,
    list_saved_backgrounds,
    get_active_background_path,
    set_active_background_path,
    save_centroid_reference,
    get_centroid_reference,
    save_crosshair_enabled,
    get_crosshair_enabled,
)
from core.epics_layer import EpicsWorker, epics_get, epics_put
from gui import BeamViewerWindow
from core.state import AppState, FrameState


class BeamController(QObject):
    """Central coordinator that wires the EPICS layer, analysis worker, state,
    and GUI together.  Also manages camera controls (exposure, gain, prefix
    switching) and the streaming toggle.
    """

    # Internal signals for thread-safe GUI updates from background IO threads
    _exposure_rbv_updated = pyqtSignal(float)
    _gain_rbv_updated = pyqtSignal(int)
    _exposure_rbv_reverted = pyqtSignal()
    _gain_rbv_reverted = pyqtSignal()
    _roi_fit_done = pyqtSignal(object)  # BeamParameters

    def __init__(
        self,
        state: AppState,
        gui: BeamViewerWindow,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.state = state
        self.gui = gui
        self._streaming: bool = True
        self._fit_full: bool = True
        self._acquire_next_frame: bool = False
        self._active_prefix: str = get_active_prefix()
        self._roi_seq: int = 0
        self._roi_fit_running: bool = False

        # --- create workers (not started yet) ---
        self._epics_worker = EpicsWorker(
            host=state.host,
            port=state.port,
            image_pv=state.image_pv,
            width_pv=state.width_pv,
            height_pv=state.height_pv,
            fallback_shape=state.fallback_shape,
        )
        self._analysis_worker = AnalysisWorker()

        # --- load calibration for the active camera ---
        self._calibration = load_calibration(self._active_prefix)
        self._analysis_worker.set_calibration(self._calibration)

        # --- connect EPICS / analysis signals ---
        self._connect_epics_signals()
        self._analysis_worker.analysis_done.connect(self._on_analysis_done)
        self.gui.closing.connect(self.stop)

        # --- connect control panel signals ---
        self.gui.prefix_change_requested.connect(self._on_prefix_change)
        self.gui.exposure_set_requested.connect(self._on_exposure_set)
        self.gui.gain_set_requested.connect(self._on_gain_set)
        self.gui.streaming_toggled.connect(self._on_streaming_toggled)
        self.gui.fit_full_toggled.connect(self._on_fit_full_toggled)
        self.gui.colormap_changed.connect(self._on_colormap_changed)
        self.gui.roi_changed.connect(self._on_roi_changed)
        self.gui.acquire_background_requested.connect(self._on_acquire_background_requested)
        self.gui.bg_subtraction_toggled.connect(self._on_bg_subtraction_toggled)
        self.gui.save_background_requested.connect(self._on_save_background_requested)
        self.gui.load_background_requested.connect(self._on_load_background_requested)
        self.gui.overlay_settings_changed.connect(self._on_overlay_settings_changed)
        self.gui.roi_fit_requested.connect(self._on_roi_fit_requested)
        self.gui.centroid_reference_changed.connect(self._on_centroid_reference_changed)
        self.gui.crosshair_toggled.connect(self._on_crosshair_toggled_save)

        # --- thread-safe RBV update signals ---
        self._exposure_rbv_updated.connect(self.gui.set_exposure_rbv)
        self._gain_rbv_updated.connect(self.gui.set_gain_rbv)
        self._exposure_rbv_reverted.connect(self.gui.revert_exposure_spinbox)
        self._gain_rbv_reverted.connect(self.gui.revert_gain_spinbox)
        self._roi_fit_done.connect(self.gui.deliver_roi_fit_result)

        # --- initialise GUI state ---
        self.gui.set_available_prefixes(
            get_available_prefixes(),
            get_active_prefix(),
        )
        # Set initial colormap from config
        idx = self.gui.control_panel.colormap_combo.findText(state.colormap_name)
        if idx >= 0:
            self.gui.control_panel.colormap_combo.blockSignals(True)
            self.gui.control_panel.colormap_combo.setCurrentIndex(idx)
            self.gui.control_panel.colormap_combo.blockSignals(False)
        self._on_colormap_changed(state.colormap_name)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the EPICS acquisition and analysis worker threads."""
        self._analysis_worker.start()
        self._epics_worker.start()
        self._refresh_camera_settings()
        # Push calibration to the GUI for ROI fitting
        self.gui.set_calibration(self._calibration)
        # Restore any previously saved ROI for the active camera
        saved_roi = get_roi_for_prefix(self._active_prefix)
        if saved_roi is not None:
            self.gui.restore_roi(saved_roi)
        # Restore projection overlay settings
        from gui import OverlayState
        overlay_dict = load_overlay_settings()
        self.gui.restore_overlay_state(OverlayState.from_dict(overlay_dict))
        # Restore active background for the current prefix
        self._restore_background_for_prefix(self._active_prefix)
        # Restore centroid crosshair state
        self.gui.restore_crosshair_enabled(get_crosshair_enabled())
        self.gui.restore_centroid_reference(get_centroid_reference(self._active_prefix))

    def stop(self) -> None:
        """Gracefully shut down both worker threads."""
        self._epics_worker.request_stop()
        self._analysis_worker.stop()
        # Give the EPICS worker a bounded wait after the analysis worker is done
        if not self._epics_worker.wait(5000):
            log.warning("EPICS worker did not stop within 5 s — terminating.")
            self._epics_worker.terminate()
            self._epics_worker.wait(2000)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _connect_epics_signals(self) -> None:
        """Wire the current EPICS worker's signals to controller slots."""
        self._epics_worker.new_frame.connect(self._on_new_frame)
        self._epics_worker.connection_changed.connect(self._on_connection_changed)
        self._epics_worker.error_occurred.connect(self._on_error)

    # ------------------------------------------------------------------
    # EPICS / analysis slots
    # ------------------------------------------------------------------

    @pyqtSlot(np.ndarray)
    def _on_new_frame(self, frame: np.ndarray) -> None:
        """Handle incoming frame — drop silently when streaming is paused."""
        if not self._streaming:
            return

        # --- Background acquisition ---
        if self._acquire_next_frame:
            self.state.background_frame = frame.copy()
            self._acquire_next_frame = False
            # Cache for this prefix so it survives beamline switches
            self.state.store_background_for_prefix(self._active_prefix, frame.copy())
            self.state.store_bg_enabled_for_prefix(self._active_prefix, True)
            # Automatically activate subtraction after acquiring (mirrors MATLAB behaviour)
            self.state.bg_subtraction_enabled = True
            self.gui.set_bg_status(has_bg=True, sub_enabled=True)
            # Persist as the active background for this prefix
            path = save_background_to_file(self._active_prefix, frame)
            set_active_background_path(self._active_prefix, path)
            self._refresh_bg_file_list()
            log.info("Background frame captured.")

        # --- Background subtraction ---
        bg = self.state.background_frame
        if self.state.bg_subtraction_enabled and bg is not None:
            if frame.shape == bg.shape:
                # Cast to int32 to prevent unsigned underflow, clip to [0, …], restore dtype
                subtracted = np.clip(
                    frame.astype(np.int32) - bg.astype(np.int32),
                    0,
                    None,
                ).astype(frame.dtype)
                frame = subtracted
            else:
                log.warning(
                    "Background subtraction shape mismatch: frame %s vs background %s — "
                    "subtraction skipped for this frame.",
                    frame.shape, bg.shape,
                )

        count = self.state.increment_frame_count()
        frame_state = FrameState(
            frame=frame,
            frame_number=count,
            analysis=None,
            do_fit=self._fit_full,
        )
        self._analysis_worker.queue_frame(frame_state)

    @pyqtSlot(FrameState)
    def _on_analysis_done(self, analyzed_state: FrameState) -> None:
        self.state.frame_state = analyzed_state
        self.gui.update_display(analyzed_state)

    @pyqtSlot(bool)
    def _on_connection_changed(self, connected: bool) -> None:
        self.state.connected = connected
        log.info("EPICS %s", "connected" if connected else "disconnected")

    @pyqtSlot(str)
    def _on_error(self, message: str) -> None:
        log.error("%s", message)

    # ------------------------------------------------------------------
    # Control panel slots
    # ------------------------------------------------------------------

    def _on_prefix_change(self, prefix: str) -> None:
        """Switch to a different camera PV prefix."""
        log.info("Switching to prefix: %s", prefix)

        old_prefix = self._active_prefix

        # Save the current ROI for the camera we are leaving
        save_roi_for_prefix(old_prefix, self.gui.get_current_roi())

        # Save the outgoing prefix's bg subtraction-enabled state
        self.state.store_bg_enabled_for_prefix(
            old_prefix, self.state.bg_subtraction_enabled
        )

        self._epics_worker.stop()
        self._active_prefix = prefix

        pv_names = get_pv_names(prefix)
        self.state.update_connection_config(pv_names)

        self._epics_worker = EpicsWorker(
            host=self.state.host,
            port=self.state.port,
            image_pv=pv_names["image_pv"],
            width_pv=pv_names["width_pv"],
            height_pv=pv_names["height_pv"],
            fallback_shape=self.state.fallback_shape,
        )
        self._connect_epics_signals()
        self._epics_worker.start()
        self._refresh_camera_settings()
        # Reload calibration for the new prefix
        self._calibration = load_calibration(prefix)
        self._analysis_worker.set_calibration(self._calibration)
        self.gui.set_calibration(self._calibration)
        # Restore any previously saved ROI for the newly selected camera
        self.gui.restore_roi(get_roi_for_prefix(prefix))

        # Save current prefix bg state, then restore the new prefix's background
        self._restore_background_for_prefix(prefix)

        # Restore centroid reference for the new prefix
        self.gui.restore_centroid_reference(get_centroid_reference(prefix))

    def _refresh_camera_settings(self) -> None:
        """Read exposure and gain RBVs from EPICS in a background thread."""
        host, port = self.state.host, self.state.port
        exp_pv = self.state.exposure_rbv_pv
        gain_pv = self.state.gain_rbv_pv

        def _read():
            if exp_pv:
                try:
                    data = epics_get(host, port, exp_pv)
                    self._exposure_rbv_updated.emit(float(data[0]))
                except Exception as exc:
                    log.warning("Failed to read exposure RBV: %s", exc)
            if gain_pv:
                try:
                    data = epics_get(host, port, gain_pv)
                    self._gain_rbv_updated.emit(int(data[0]))
                except Exception as exc:
                    log.warning("Failed to read gain RBV: %s", exc)

        threading.Thread(target=_read, daemon=True).start()

    def _on_exposure_set(self, value: float) -> None:
        """Write a new exposure time to the IOC and read back the RBV."""
        host, port = self.state.host, self.state.port
        set_pv = self.state.exposure_pv
        rbv_pv = self.state.exposure_rbv_pv
        if not set_pv:
            return

        def _write():
            try:
                epics_put(host, port, set_pv, value)
                time.sleep(0.3)
                if rbv_pv:
                    data = epics_get(host, port, rbv_pv)
                    self._exposure_rbv_updated.emit(float(data[0]))
            except Exception as exc:
                log.error("Failed to set exposure: %s", exc)
                self._exposure_rbv_reverted.emit()

        threading.Thread(target=_write, daemon=True).start()

    def _on_gain_set(self, value: int) -> None:
        """Write a new gain value to the IOC and read back the RBV."""
        host, port = self.state.host, self.state.port
        set_pv = self.state.gain_pv
        rbv_pv = self.state.gain_rbv_pv
        if not set_pv:
            return

        def _write():
            try:
                epics_put(host, port, set_pv, value)
                time.sleep(0.3)
                if rbv_pv:
                    data = epics_get(host, port, rbv_pv)
                    self._gain_rbv_updated.emit(int(data[0]))
            except Exception as exc:
                log.error("Failed to set gain: %s", exc)
                self._gain_rbv_reverted.emit()

        threading.Thread(target=_write, daemon=True).start()

    def _on_streaming_toggled(self, streaming: bool) -> None:
        """Pause or resume frame forwarding (EPICS worker keeps running)."""
        self._streaming = streaming
        log.info("Streaming %s", "resumed" if streaming else "paused")

    @pyqtSlot()
    def _on_acquire_background_requested(self) -> None:
        """Flag that the next incoming frame should be stored as the background."""
        self._acquire_next_frame = True
        log.info("Background acquisition requested — will capture on next frame.")

    @pyqtSlot(bool)
    def _on_bg_subtraction_toggled(self, enabled: bool) -> None:
        """Enable or disable background subtraction."""
        self.state.bg_subtraction_enabled = enabled
        self.state.store_bg_enabled_for_prefix(self._active_prefix, enabled)
        has_bg = self.state.background_frame is not None
        # Update status label to reflect new toggle state
        self.gui.set_bg_status(has_bg=has_bg, sub_enabled=enabled)
        log.info("Background subtraction %s.", "enabled" if enabled else "disabled")

    @pyqtSlot()
    def _on_save_background_requested(self) -> None:
        """Save the current in-memory background to a timestamped .npy file."""
        bg = self.state.background_frame
        if bg is None:
            return
        path = save_background_to_file(self._active_prefix, bg)
        set_active_background_path(self._active_prefix, path)
        self._refresh_bg_file_list()
        log.info("Background saved to %s", path)

    @pyqtSlot(str)
    def _on_load_background_requested(self, path_str: str) -> None:
        """Load a background frame from a .npy file on disk."""
        from pathlib import Path
        path = Path(path_str)
        if not path.exists():
            log.warning("Background file not found: %s", path)
            return
        bg = load_background_from_file(path)
        self.state.background_frame = bg
        self.state.store_background_for_prefix(self._active_prefix, bg)
        self.state.bg_subtraction_enabled = True
        self.state.store_bg_enabled_for_prefix(self._active_prefix, True)
        set_active_background_path(self._active_prefix, path)
        self.gui.set_bg_status(has_bg=True, sub_enabled=True)
        log.info("Background loaded from %s", path.name)

    # ------------------------------------------------------------------
    # Background persistence helpers
    # ------------------------------------------------------------------

    def _restore_background_for_prefix(self, prefix: str) -> None:
        """Restore the background for *prefix* from cache or disk."""
        # Try in-memory cache first
        bg = self.state.get_background_for_prefix(prefix)
        if bg is None:
            # Fall back to persisted active background on disk
            active_path = get_active_background_path(prefix)
            if active_path is not None:
                try:
                    bg = load_background_from_file(active_path)
                    self.state.store_background_for_prefix(prefix, bg)
                except Exception as exc:
                    log.warning("Failed to restore background %s: %s", active_path, exc)

        if bg is not None:
            self.state.background_frame = bg
            sub_enabled = self.state.get_bg_enabled_for_prefix(prefix)
            self.state.bg_subtraction_enabled = sub_enabled
            self.gui.set_bg_status(has_bg=True, sub_enabled=sub_enabled)
        else:
            self.state.background_frame = None
            self.state.bg_subtraction_enabled = False
            self.gui.reset_bg_controls()

        self._refresh_bg_file_list()

    def _refresh_bg_file_list(self) -> None:
        """Update the GUI's cached list of saved backgrounds for the active prefix."""
        files = list_saved_backgrounds(self._active_prefix)
        self.gui.set_bg_file_list(files)

    def _on_fit_full_toggled(self, enabled: bool) -> None:
        """Enable or disable Gaussian fitting on the full image."""
        self._fit_full = enabled
        log.info("Full-image fitting %s", "enabled" if enabled else "disabled")

    def _on_colormap_changed(self, name: str) -> None:
        """Apply a new colormap to both image panes."""
        try:
            cmap = pg.colormap.get(name, source="matplotlib")
            lut = cmap.getLookupTable()
            self.gui.image_pane_1.image_item.setLookupTable(lut)
            self.gui.image_pane_2.image_item.setLookupTable(lut)
        except Exception as exc:
            log.warning("Failed to set colormap '%s': %s", name, exc)

    @pyqtSlot(object)
    def _on_roi_changed(self, roi: object) -> None:
        """Persist the ROI for the active camera whenever it changes."""
        save_roi_for_prefix(self._active_prefix, roi)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # ROI fitting (runs on a background thread, delivers via signal)
    # ------------------------------------------------------------------

    @pyqtSlot(object, np.ndarray)
    def _on_roi_fit_requested(self, roi: object, roi_frame: np.ndarray) -> None:
        """Run a Gaussian fit on the ROI sub-frame in a background thread."""
        self._roi_seq += 1
        seq = self._roi_seq

        if self._roi_fit_running:
            # A fit is already in-flight; the next frame will supersede anyway.
            return

        self._roi_fit_running = True
        x0, y0 = (roi[0], roi[1]) if roi is not None else (0, 0)  # type: ignore[index]

        def _run() -> None:
            try:
                bp = analyze_frame(
                    roi_frame,
                    do_fit=True,
                    calibration=self._calibration,
                    x_offset=x0,
                    y_offset=y0,
                )
                # Only deliver if this result is still the latest request.
                if seq == self._roi_seq:
                    self._roi_fit_done.emit(bp)
            finally:
                self._roi_fit_running = False

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot(object)
    def _on_overlay_settings_changed(self, state: object) -> None:
        """Persist overlay settings whenever they change."""
        save_overlay_settings(state.to_dict())  # type: ignore[union-attr]

    @pyqtSlot(float, float)
    def _on_centroid_reference_changed(self, x: float, y: float) -> None:
        """Persist the centroid reference for the active prefix."""
        save_centroid_reference(self._active_prefix, x, y)

    @pyqtSlot(bool)
    def _on_crosshair_toggled_save(self, enabled: bool) -> None:
        """Persist the crosshair visibility toggle."""
        save_crosshair_enabled(enabled)
