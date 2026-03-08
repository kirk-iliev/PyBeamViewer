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

import threading
import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from analysis_worker import AnalysisWorker
from config import get_available_prefixes, get_active_prefix, get_pv_names
from epics_layer import EpicsWorker, epics_get, epics_put
from gui import BeamViewerWindow
from state import AppState, FrameState


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

        # --- thread-safe RBV update signals ---
        self._exposure_rbv_updated.connect(self.gui.set_exposure_rbv)
        self._gain_rbv_updated.connect(self.gui.set_gain_rbv)
        self._exposure_rbv_reverted.connect(self.gui.revert_exposure_spinbox)
        self._gain_rbv_reverted.connect(self.gui.revert_gain_spinbox)

        # --- initialise GUI state ---
        self.gui.set_available_prefixes(
            get_available_prefixes(),
            get_active_prefix(),
        )
        # Set initial colormap from config
        idx = self.gui.colormap_combo.findText(state.colormap_name)
        if idx >= 0:
            self.gui.colormap_combo.blockSignals(True)
            self.gui.colormap_combo.setCurrentIndex(idx)
            self.gui.colormap_combo.blockSignals(False)
        self._on_colormap_changed(state.colormap_name)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the EPICS acquisition and analysis worker threads."""
        self._analysis_worker.start()
        self._epics_worker.start()
        self._refresh_camera_settings()

    def stop(self) -> None:
        """Gracefully shut down both worker threads."""
        self._epics_worker.stop()
        self._analysis_worker.stop()

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
        status = "connected" if connected else "disconnected"
        print(f"EPICS {status}")

    @pyqtSlot(str)
    def _on_error(self, message: str) -> None:
        print(f"[Controller] {message}")

    # ------------------------------------------------------------------
    # Control panel slots
    # ------------------------------------------------------------------

    def _on_prefix_change(self, prefix: str) -> None:
        """Switch to a different camera PV prefix."""
        print(f"Switching to prefix: {prefix}")
        self._epics_worker.stop()

        pv_names = get_pv_names(prefix)
        self.state.image_pv = pv_names["image_pv"]
        self.state.width_pv = pv_names["width_pv"]
        self.state.height_pv = pv_names["height_pv"]
        self.state.exposure_pv = pv_names.get("exposure_pv", "")
        self.state.exposure_rbv_pv = pv_names.get("exposure_rbv_pv", "")
        self.state.gain_pv = pv_names.get("gain_pv", "")
        self.state.gain_rbv_pv = pv_names.get("gain_rbv_pv", "")
        _fs = pv_names.get("fallback_shape")
        self.state.fallback_shape = (
            (int(_fs[0]), int(_fs[1])) if _fs is not None else None
        )

        self._epics_worker = EpicsWorker(
            host=self.state.host,
            port=self.state.port,
            image_pv=self.state.image_pv,
            width_pv=self.state.width_pv,
            height_pv=self.state.height_pv,
            fallback_shape=self.state.fallback_shape,
        )
        self._connect_epics_signals()
        self._epics_worker.start()
        self._refresh_camera_settings()

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
                    print(f"Failed to read exposure RBV: {exc}")
            if gain_pv:
                try:
                    data = epics_get(host, port, gain_pv)
                    self._gain_rbv_updated.emit(int(data[0]))
                except Exception as exc:
                    print(f"Failed to read gain RBV: {exc}")

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
                print(f"Failed to set exposure: {exc}")
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
                print(f"Failed to set gain: {exc}")
                self._gain_rbv_reverted.emit()

        threading.Thread(target=_write, daemon=True).start()

    def _on_streaming_toggled(self, streaming: bool) -> None:
        """Pause or resume frame forwarding (EPICS worker keeps running)."""
        self._streaming = streaming
        status = "resumed" if streaming else "paused"
        print(f"Streaming {status}")

    def _on_fit_full_toggled(self, enabled: bool) -> None:
        """Enable or disable Gaussian fitting on the full image."""
        self._fit_full = enabled
        print(f"Full-image fitting {'enabled' if enabled else 'disabled'}")

    def _on_colormap_changed(self, name: str) -> None:
        """Apply a new colormap to both image panes."""
        try:
            cmap = pg.colormap.get(name, source="matplotlib")
            lut = cmap.getLookupTable()
            self.gui.image_pane_1.image_item.setLookupTable(lut)
            self.gui.image_pane_2.image_item.setLookupTable(lut)
        except Exception as exc:
            print(f"Failed to set colormap '{name}': {exc}")
