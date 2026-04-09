"""
headless_controller.py — Qt-free application controller.

Orchestrates the data pipeline in headless mode:

    HeadlessEpicsWorker (thread)  ──callback──▶  Controller
         │                                           │
         │  on_new_frame(ndarray)                   │  1. bg subtraction
         │                                           │  2. queue frame to HeadlessAnalysisWorker
         ▼                                           │  3. analysis callback → update state
                                                     │  4. emit "frame_ready" via dispatcher
                                                     ▼

All public state mutations and event emissions go through the
``CallbackDispatcher`` so that downstream consumers (bridge, MCP server)
can register callbacks without any Qt dependency.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)

from analysis.analysis import analyze_frame, BeamParameters
from analysis.calibration import Calibration, load_calibration
from analysis.trending_buffer import TrendingBuffer
from mcp_servers.beam_viewer.config.config import (
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
from mcp_servers.beam_viewer.core.dispatcher import CallbackDispatcher
from mcp_servers.beam_viewer.core.headless_epics import (
    HeadlessEpicsWorker,
    epics_get,
    epics_put,
)
from mcp_servers.beam_viewer.core.headless_analysis import HeadlessAnalysisWorker
from mcp_servers.beam_viewer.core.state import AppState, FrameState


# ---------------------------------------------------------------------------
# Dispatcher event names
# ---------------------------------------------------------------------------

EVT_FRAME_READY = "frame_ready"           # (FrameState,)
EVT_CONNECTION_CHANGED = "connection_changed"  # (bool,)
EVT_ERROR = "error"                        # (str,)
EVT_EXPOSURE_RBV = "exposure_rbv"          # (float,)
EVT_GAIN_RBV = "gain_rbv"                  # (int,)
EVT_EXPOSURE_REVERTED = "exposure_reverted"    # ()
EVT_GAIN_REVERTED = "gain_reverted"            # ()
EVT_ROI_FIT_DONE = "roi_fit_done"          # (BeamParameters,)
EVT_BG_STATUS = "bg_status"                # (bool has_bg, bool sub_enabled)
EVT_BG_FILE_LIST = "bg_file_list"          # (list[Path],)
EVT_TRENDING_UPDATE = "trending_update"    # (dict history,)


class HeadlessController:
    """Central coordinator — Qt-free replacement for ``BeamController``.

    Wires ``HeadlessEpicsWorker``, ``HeadlessAnalysisWorker``, ``AppState``,
    ``TrendingBuffer``, and ``CallbackDispatcher`` together.  All outgoing
    events are emitted through ``self.dispatcher``.
    """

    def __init__(self, state: AppState) -> None:
        self.state = state
        self.dispatcher = CallbackDispatcher()

        self._streaming: bool = True
        self._fit_full: bool = True
        self._fit_roi: bool = False
        self._acquire_next_frame: bool = False
        self._active_prefix: str = get_active_prefix()
        self._roi_seq: int = 0
        self._roi_fit_running: bool = False
        self._trending_buffer = TrendingBuffer(max_len=300)

        # Centroid tracking state (headless equivalent of gui fields)
        self._centroid_reference: Optional[Tuple[float, float]] = None
        self._live_roi_centroid: Optional[Tuple[float, float]] = None

        # Overlay settings (in-memory cache, persisted via config)
        self._overlay_settings: dict = load_overlay_settings()

        # Crosshair toggle
        self._crosshair_enabled: bool = get_crosshair_enabled()

        # Current ROI (x0, y0, x1, y1) or None
        self._current_roi: Optional[Tuple[int, int, int, int]] = None

        # --- load calibration for the active camera ---
        self._calibration: Calibration = load_calibration(self._active_prefix)

        # --- create workers (not started yet) ---
        self._epics_worker = self._make_epics_worker()
        self._analysis_worker = HeadlessAnalysisWorker(
            on_analysis_done=self._on_analysis_done,
        )
        self._analysis_worker.set_calibration(self._calibration)

    # ------------------------------------------------------------------
    # Worker factory
    # ------------------------------------------------------------------

    def _make_epics_worker(self) -> HeadlessEpicsWorker:
        """Create a new ``HeadlessEpicsWorker`` wired to this controller."""
        return HeadlessEpicsWorker(
            host=self.state.host,
            port=self.state.port,
            image_pv=self.state.image_pv,
            width_pv=self.state.width_pv,
            height_pv=self.state.height_pv,
            fallback_shape=self.state.fallback_shape,
            on_new_frame=self._on_new_frame,
            on_connection_changed=self._on_connection_changed,
            on_error=self._on_error,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the EPICS acquisition and analysis worker threads."""
        self._analysis_worker.start()
        self._epics_worker.start()
        self._refresh_camera_settings()

        # Restore saved ROI
        saved_roi = get_roi_for_prefix(self._active_prefix)
        if saved_roi is not None:
            self._current_roi = saved_roi

        # Restore background for active prefix
        self._restore_background_for_prefix(self._active_prefix)

        # Restore centroid reference
        self._centroid_reference = get_centroid_reference(self._active_prefix)
        self._crosshair_enabled = get_crosshair_enabled()

    def stop(self) -> None:
        """Gracefully shut down both worker threads."""
        self._epics_worker.request_stop()
        self._analysis_worker.stop()
        self._epics_worker.stop()

    # ------------------------------------------------------------------
    # EPICS / analysis callbacks
    # ------------------------------------------------------------------

    def _on_new_frame(self, frame: np.ndarray) -> None:
        """Handle incoming frame — drop silently when streaming is paused."""
        if not self._streaming:
            return

        # --- Background acquisition ---
        if self._acquire_next_frame:
            self.state.background_frame = frame.copy()
            self._acquire_next_frame = False
            self.state.store_background_for_prefix(self._active_prefix, frame.copy())
            self.state.store_bg_enabled_for_prefix(self._active_prefix, True)
            self.state.bg_subtraction_enabled = True
            # Persist as active background
            path = save_background_to_file(self._active_prefix, frame)
            set_active_background_path(self._active_prefix, path)
            self.dispatcher.emit(EVT_BG_STATUS, True, True)
            self._refresh_bg_file_list()
            log.info("Background frame captured.")

        # --- Background subtraction ---
        bg = self.state.background_frame
        if self.state.bg_subtraction_enabled and bg is not None:
            if frame.shape == bg.shape:
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

    def _on_analysis_done(self, analyzed_state: FrameState) -> None:
        self.state.frame_state = analyzed_state
        self.dispatcher.emit(EVT_FRAME_READY, analyzed_state)
        self._append_trending_record(analyzed_state)

        # Auto-trigger ROI fit when enabled and ROI is active
        if self._fit_roi and self._current_roi is not None:
            frame = analyzed_state.frame
            x0, y0, x1, y1 = self._current_roi
            x0 = max(0, x0)
            y0 = max(0, y0)
            x1 = min(frame.shape[1], x1)
            y1 = min(frame.shape[0], y1)
            if x1 > x0 and y1 > y0:
                roi_frame = frame[y0:y1, x0:x1]
                self.request_roi_fit(self._current_roi, roi_frame)

    def _on_connection_changed(self, connected: bool) -> None:
        self.state.connected = connected
        self.dispatcher.emit(EVT_CONNECTION_CHANGED, connected)
        log.info("EPICS %s", "connected" if connected else "disconnected")

    def _on_error(self, message: str) -> None:
        self.dispatcher.emit(EVT_ERROR, message)
        log.error("%s", message)

    # ------------------------------------------------------------------
    # Streaming control
    # ------------------------------------------------------------------

    def set_streaming(self, streaming: bool) -> None:
        """Pause or resume frame forwarding (EPICS worker keeps running)."""
        self._streaming = streaming
        log.info("Streaming %s", "resumed" if streaming else "paused")

    @property
    def streaming(self) -> bool:
        return self._streaming

    # ------------------------------------------------------------------
    # Fitting control
    # ------------------------------------------------------------------

    def set_fit_full(self, enabled: bool) -> None:
        """Enable or disable Gaussian fitting on the full image."""
        self._fit_full = enabled
        log.info("Full-image fitting %s", "enabled" if enabled else "disabled")

    @property
    def fit_full(self) -> bool:
        return self._fit_full

    def set_fit_roi(self, enabled: bool) -> None:
        """Enable or disable Gaussian fitting on the ROI region."""
        self._fit_roi = enabled
        log.info("ROI fitting %s", "enabled" if enabled else "disabled")

    @property
    def fit_roi(self) -> bool:
        return self._fit_roi

    # ------------------------------------------------------------------
    # Camera settings (exposure / gain)
    # ------------------------------------------------------------------

    def _refresh_camera_settings(self) -> None:
        """Read exposure and gain RBVs from EPICS in a background thread."""
        host, port = self.state.host, self.state.port
        exp_pv = self.state.exposure_rbv_pv
        gain_pv = self.state.gain_rbv_pv

        def _read():
            if exp_pv:
                try:
                    data = epics_get(host, port, exp_pv)
                    self.dispatcher.emit(EVT_EXPOSURE_RBV, float(data[0]))
                except Exception as exc:
                    log.warning("Failed to read exposure RBV: %s", exc)
            if gain_pv:
                try:
                    data = epics_get(host, port, gain_pv)
                    self.dispatcher.emit(EVT_GAIN_RBV, int(data[0]))
                except Exception as exc:
                    log.warning("Failed to read gain RBV: %s", exc)

        threading.Thread(target=_read, daemon=True).start()

    def set_exposure(self, value: float) -> None:
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
                    self.dispatcher.emit(EVT_EXPOSURE_RBV, float(data[0]))
            except Exception as exc:
                log.error("Failed to set exposure: %s", exc)
                self.dispatcher.emit(EVT_EXPOSURE_REVERTED)

        threading.Thread(target=_write, daemon=True).start()

    def set_gain(self, value: int) -> None:
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
                    self.dispatcher.emit(EVT_GAIN_RBV, int(data[0]))
            except Exception as exc:
                log.error("Failed to set gain: %s", exc)
                self.dispatcher.emit(EVT_GAIN_REVERTED)

        threading.Thread(target=_write, daemon=True).start()

    # ------------------------------------------------------------------
    # Prefix (camera) switching
    # ------------------------------------------------------------------

    @property
    def active_prefix(self) -> str:
        return self._active_prefix

    def switch_prefix(self, prefix: str) -> None:
        """Switch to a different camera PV prefix."""
        log.info("Switching to prefix: %s", prefix)
        old_prefix = self._active_prefix

        # Save the current ROI for the camera we are leaving
        save_roi_for_prefix(old_prefix, self._current_roi)

        # Save outgoing prefix's bg-subtraction-enabled state
        self.state.store_bg_enabled_for_prefix(
            old_prefix, self.state.bg_subtraction_enabled
        )

        # Clear trending history
        self._trending_buffer.clear()

        # Stop old EPICS worker
        self._epics_worker.stop()
        self._active_prefix = prefix

        # Update state with new PV names
        pv_names = get_pv_names(prefix)
        self.state.update_connection_config(pv_names)

        # Create and start new EPICS worker
        self._epics_worker = self._make_epics_worker()
        self._epics_worker.start()
        self._refresh_camera_settings()

        # Reload calibration
        self._calibration = load_calibration(prefix)
        self._analysis_worker.set_calibration(self._calibration)

        # Restore ROI
        self._current_roi = get_roi_for_prefix(prefix)

        # Restore background
        self._restore_background_for_prefix(prefix)

        # Restore centroid reference
        self._centroid_reference = get_centroid_reference(prefix)

    # ------------------------------------------------------------------
    # Background management
    # ------------------------------------------------------------------

    def acquire_background(self) -> None:
        """Flag that the next incoming frame should be stored as the background."""
        self._acquire_next_frame = True
        log.info("Background acquisition requested — will capture on next frame.")

    def toggle_bg_subtraction(self, enabled: bool) -> None:
        """Enable or disable background subtraction."""
        self.state.bg_subtraction_enabled = enabled
        self.state.store_bg_enabled_for_prefix(self._active_prefix, enabled)
        has_bg = self.state.background_frame is not None
        self.dispatcher.emit(EVT_BG_STATUS, has_bg, enabled)
        log.info("Background subtraction %s.", "enabled" if enabled else "disabled")

    def save_background(self) -> Optional[Path]:
        """Save the current in-memory background to a timestamped .npy file."""
        bg = self.state.background_frame
        if bg is None:
            return None
        path = save_background_to_file(self._active_prefix, bg)
        set_active_background_path(self._active_prefix, path)
        self._refresh_bg_file_list()
        log.info("Background saved to %s", path)
        return path

    def load_background(self, path_str: str) -> bool:
        """Load a background frame from a .npy file on disk."""
        path = Path(path_str)
        if not path.exists():
            log.warning("Background file not found: %s", path)
            return False
        bg = load_background_from_file(path)
        self.state.background_frame = bg
        self.state.store_background_for_prefix(self._active_prefix, bg)
        self.state.bg_subtraction_enabled = True
        self.state.store_bg_enabled_for_prefix(self._active_prefix, True)
        set_active_background_path(self._active_prefix, path)
        self.dispatcher.emit(EVT_BG_STATUS, True, True)
        log.info("Background loaded from %s", path.name)
        return True

    def _restore_background_for_prefix(self, prefix: str) -> None:
        """Restore the background for *prefix* from cache or disk."""
        bg = self.state.get_background_for_prefix(prefix)
        if bg is None:
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
            self.dispatcher.emit(EVT_BG_STATUS, True, sub_enabled)
        else:
            self.state.background_frame = None
            self.state.bg_subtraction_enabled = False
            self.dispatcher.emit(EVT_BG_STATUS, False, False)

        self._refresh_bg_file_list()

    def _refresh_bg_file_list(self) -> None:
        """Emit the updated list of saved backgrounds for the active prefix."""
        files = list_saved_backgrounds(self._active_prefix)
        self.dispatcher.emit(EVT_BG_FILE_LIST, files)

    # ------------------------------------------------------------------
    # ROI management
    # ------------------------------------------------------------------

    @property
    def current_roi(self) -> Optional[Tuple[int, int, int, int]]:
        return self._current_roi

    def set_roi(self, roi: Optional[Tuple[int, int, int, int]]) -> None:
        """Update and persist the ROI for the active camera."""
        self._current_roi = roi
        save_roi_for_prefix(self._active_prefix, roi)

    def request_roi_fit(
        self,
        roi: Optional[Tuple[int, int, int, int]],
        roi_frame: np.ndarray,
    ) -> None:
        """Run a Gaussian fit on the ROI sub-frame in a background thread."""
        self._roi_seq += 1
        seq = self._roi_seq

        if self._roi_fit_running:
            return

        self._roi_fit_running = True
        x0, y0 = (roi[0], roi[1]) if roi is not None else (0, 0)

        def _run() -> None:
            try:
                # No x_offset/y_offset: centroid stays in ROI-local
                # coordinates (0..roi_width) so the projection plot
                # overlay renders at the correct position. Sigma/sigma_um
                # are unaffected by axis shift.
                bp = analyze_frame(
                    roi_frame,
                    do_fit=True,
                    calibration=self._calibration,
                )
                if seq == self._roi_seq:
                    self.dispatcher.emit(EVT_ROI_FIT_DONE, bp)
                    self._update_trending_roi(bp)
            finally:
                self._roi_fit_running = False

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    @property
    def calibration(self) -> Calibration:
        return self._calibration

    # ------------------------------------------------------------------
    # Overlay settings
    # ------------------------------------------------------------------

    @property
    def overlay_settings(self) -> dict:
        return self._overlay_settings

    def set_overlay_settings(self, settings: dict) -> None:
        """Update and persist overlay settings."""
        self._overlay_settings = settings
        save_overlay_settings(settings)

    # ------------------------------------------------------------------
    # Centroid / crosshair
    # ------------------------------------------------------------------

    @property
    def centroid_reference(self) -> Optional[Tuple[float, float]]:
        return self._centroid_reference

    def set_centroid_reference(self, x: float, y: float) -> None:
        """Persist the centroid reference for the active prefix."""
        self._centroid_reference = (x, y)
        save_centroid_reference(self._active_prefix, x, y)

    @property
    def crosshair_enabled(self) -> bool:
        return self._crosshair_enabled

    def set_crosshair_enabled(self, enabled: bool) -> None:
        """Persist the crosshair visibility toggle."""
        self._crosshair_enabled = enabled
        save_crosshair_enabled(enabled)

    @property
    def live_roi_centroid(self) -> Optional[Tuple[float, float]]:
        return self._live_roi_centroid

    def set_live_roi_centroid(self, x: float, y: float) -> None:
        """Update the live ROI centroid (for drift tracking)."""
        self._live_roi_centroid = (x, y)

    # ------------------------------------------------------------------
    # Trending
    # ------------------------------------------------------------------

    @property
    def trending_buffer(self) -> TrendingBuffer:
        return self._trending_buffer

    def set_trending_depth(self, depth: int) -> None:
        """Resize the trending buffer when the history depth changes."""
        self._trending_buffer.resize(depth)

    def _append_trending_record(self, fs: FrameState) -> None:
        """Extract metrics from a completed FrameState and append to the
        trending buffer.
        """
        record: dict = {
            "frame_number": float(fs.frame_number),
            "sigma_x": float("nan"),
            "sigma_y": float("nan"),
            "centroid_x": float("nan"),
            "centroid_y": float("nan"),
            "roi_sigma_x": float("nan"),
            "roi_sigma_y": float("nan"),
            "drift_x": float("nan"),
            "drift_y": float("nan"),
        }

        if fs.analysis is not None:
            xf = fs.analysis.x_fit
            yf = fs.analysis.y_fit
            if xf is not None and xf.success:
                record["sigma_x"] = xf.sigma_um if xf.sigma_um is not None else xf.sigma
                record["centroid_x"] = xf.centroid
            if yf is not None and yf.success:
                record["sigma_y"] = yf.sigma_um if yf.sigma_um is not None else yf.sigma
                record["centroid_y"] = yf.centroid

        # Drift from centroid tracking
        ref = self._centroid_reference
        live = self._live_roi_centroid
        if ref is not None and live is not None:
            record["drift_x"] = live[0] - ref[0]
            record["drift_y"] = live[1] - ref[1]

        self._trending_buffer.append(record)
        self.dispatcher.emit(
            EVT_TRENDING_UPDATE,
            self._trending_buffer.get_history(),
        )

    def _update_trending_roi(self, bp: BeamParameters) -> None:
        """Back-fill the latest trending buffer entry with ROI fit results."""
        roi_sx = float("nan")
        roi_sy = float("nan")
        if bp.x_fit is not None and bp.x_fit.success:
            roi_sx = bp.x_fit.sigma_um if bp.x_fit.sigma_um is not None else bp.x_fit.sigma
        if bp.y_fit is not None and bp.y_fit.success:
            roi_sy = bp.y_fit.sigma_um if bp.y_fit.sigma_um is not None else bp.y_fit.sigma
        self._trending_buffer.update_latest_roi(roi_sx, roi_sy)
        self.dispatcher.emit(
            EVT_TRENDING_UPDATE,
            self._trending_buffer.get_history(),
        )

    # ------------------------------------------------------------------
    # Colormap (headless equivalent — stored in state, no LUT application)
    # ------------------------------------------------------------------

    def set_colormap(self, name: str) -> None:
        """Update the colormap name in state."""
        self.state.colormap_name = name

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def get_available_prefixes(self) -> list:
        """Return configured camera prefixes."""
        return get_available_prefixes()

    def get_bg_file_list(self) -> list:
        """Return saved background files for the active prefix."""
        return list_saved_backgrounds(self._active_prefix)
