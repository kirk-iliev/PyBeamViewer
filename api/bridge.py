"""ApiBridge — single adapter between the FastAPI layer and the Qt application.

All reads go directly to AppState (RLock-protected, safe from any thread).
All mutations are dispatched to the Qt main thread via signal emissions
or QMetaObject.invokeMethod with Qt.QueuedConnection.
"""

from __future__ import annotations

import base64
import io
import logging
import math
import time
from typing import Any, Optional

import numpy as np
from PyQt5.QtCore import QMetaObject, Qt, Q_ARG

log = logging.getLogger(__name__)


class ApiBridge:
    """Thread-safe adapter between FastAPI routes and the Qt application.

    Parameters
    ----------
    state : AppState
        Thread-safe application state (model layer).
    controller : BeamController
        Application controller (lives on Qt main thread).
    window : BeamViewerWindow
        Main application window (lives on Qt main thread).
    """

    def __init__(self, state: Any, controller: Any, window: Any) -> None:
        self._state = state
        self._controller = controller
        self._window = window

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _invoke_window(self, slot_name: str) -> None:
        """Fire-and-forget dispatch to a window slot on the Qt main thread."""
        QMetaObject.invokeMethod(self._window, slot_name, Qt.QueuedConnection)

    def _invoke_controller(self, slot_name: str) -> None:
        """Fire-and-forget dispatch to a controller slot on the Qt main thread."""
        QMetaObject.invokeMethod(self._controller, slot_name, Qt.QueuedConnection)

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def get_camera_info(self) -> dict:
        from config.config import get_active_prefix
        s = self._state
        return {
            "active_prefix": get_active_prefix(),
            "host": s.host,
            "port": s.port,
            "image_pv": s.image_pv,
            "width_pv": s.width_pv,
            "height_pv": s.height_pv,
            "exposure_pv": s.exposure_pv,
            "exposure_rbv_pv": s.exposure_rbv_pv,
            "gain_pv": s.gain_pv,
            "gain_rbv_pv": s.gain_rbv_pv,
            "fallback_shape": list(s.fallback_shape) if s.fallback_shape else None,
        }

    def select_prefix(self, prefix: str) -> None:
        from config.config import get_available_prefixes
        available = get_available_prefixes()
        if prefix not in available:
            raise ValueError(f"Unknown prefix: {prefix!r}. Available: {available}")
        self._window.prefix_change_requested.emit(prefix)

    def set_exposure(self, value: float) -> None:
        self._window.exposure_set_requested.emit(value)

    def set_gain(self, value: int) -> None:
        self._window.gain_set_requested.emit(value)

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def get_streaming_status(self) -> dict:
        return {
            "streaming": self._controller._streaming,
            "connected": self._state.connected,
            "frame_count": self._state.frame_count,
        }

    def set_streaming(self, enabled: bool) -> None:
        self._window.streaming_toggled.emit(enabled)
        # Also update the button state on the main thread
        QMetaObject.invokeMethod(
            self._window.control_panel.stream_btn,
            "setChecked",
            Qt.QueuedConnection,
            Q_ARG(bool, enabled),
        )

    # ------------------------------------------------------------------
    # Background
    # ------------------------------------------------------------------

    def get_background_status(self) -> dict:
        return {
            "has_background": self._state.background_frame is not None,
            "subtraction_enabled": self._state.bg_subtraction_enabled,
        }

    def acquire_background(self) -> None:
        self._window.acquire_background_requested.emit()

    def set_background_subtraction(self, enabled: bool) -> None:
        self._window.bg_subtraction_toggled.emit(enabled)

    def save_background(self) -> None:
        self._window.save_background_requested.emit()

    def load_background(self, path: str) -> None:
        from pathlib import Path as _Path
        from config.config import _get_backgrounds_dir
        allowed = _get_backgrounds_dir().resolve()
        resolved = _Path(path).resolve()
        if not str(resolved).startswith(str(allowed) + "/"):
            raise ValueError(f"Path is outside the backgrounds directory: {path!r}")
        if not resolved.exists():
            raise ValueError(f"Background file not found: {path!r}")
        self._window.load_background_requested.emit(str(resolved))

    def list_backgrounds(self) -> list[dict]:
        from config.config import list_saved_backgrounds, get_active_prefix
        prefix = get_active_prefix()
        files = list_saved_backgrounds(prefix)
        return [{"filename": p.name, "path": str(p)} for p in files]

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def get_analysis_status(self) -> dict:
        result: dict[str, Any] = {
            "fit_full_enabled": self._controller._fit_full,
            "fit_roi_enabled": self._window.control_panel.fit_roi_btn.isChecked(),
        }

        fs = self._state.frame_state
        if fs is not None and fs.analysis is not None:
            bp = fs.analysis
            for axis, fit in [("x_fit", bp.x_fit), ("y_fit", bp.y_fit)]:
                if fit is not None:
                    result[axis] = {
                        "success": fit.success,
                        "sigma": _nan_to_none(fit.sigma),
                        "sigma_um": _nan_to_none(fit.sigma_um) if fit.sigma_um is not None else None,
                        "centroid": _nan_to_none(fit.centroid),
                        "centroid_um": _nan_to_none(fit.centroid_um) if fit.centroid_um is not None else None,
                        "amplitude": _nan_to_none(fit.amplitude),
                        "offset": _nan_to_none(fit.offset),
                        "residual": _nan_to_none(fit.residual),
                        "unit_label": fit.unit_label,
                    }
                else:
                    result[axis] = None
        else:
            result["x_fit"] = None
            result["y_fit"] = None

        return result

    def set_fit_full(self, enabled: bool) -> None:
        self._window.fit_full_toggled.emit(enabled)
        QMetaObject.invokeMethod(
            self._window.control_panel.fit_full_btn,
            "setChecked",
            Qt.QueuedConnection,
            Q_ARG(bool, enabled),
        )

    def set_fit_roi(self, enabled: bool) -> None:
        QMetaObject.invokeMethod(
            self._window.control_panel.fit_roi_btn,
            "setChecked",
            Qt.QueuedConnection,
            Q_ARG(bool, enabled),
        )

    # ------------------------------------------------------------------
    # ROI
    # ------------------------------------------------------------------

    def get_roi(self) -> dict:
        roi = self._window.get_current_roi()
        if roi is None:
            return {"active": False, "roi": None}
        x0, y0, x1, y1 = roi
        return {
            "active": True,
            "roi": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        }

    def set_roi(self, x0: int, y0: int, x1: int, y1: int) -> None:
        # ImagePane.set_roi modifies Qt widgets — must run on the main thread.
        QMetaObject.invokeMethod(
            self._window, "_on_set_roi", Qt.QueuedConnection,
            Q_ARG("QVariant", (x0, y0, x1, y1)),
        )

    def clear_roi(self) -> None:
        QMetaObject.invokeMethod(
            self._window, "_on_clear_roi_clicked", Qt.QueuedConnection,
        )

    def center_roi(self) -> None:
        QMetaObject.invokeMethod(
            self._window, "_on_center_roi_clicked", Qt.QueuedConnection,
        )

    # ------------------------------------------------------------------
    # Centroid / Drift
    # ------------------------------------------------------------------

    def get_drift(self) -> dict:
        ref = self._window._centroid_reference
        live = self._window._live_roi_centroid
        enabled = self._window._crosshair_enabled

        result: dict[str, Any] = {
            "has_reference": ref is not None,
            "crosshair_enabled": enabled,
            "reference": {"x": ref[0], "y": ref[1]} if ref else None,
            "live": {"x": live[0], "y": live[1]} if live else None,
        }

        if ref is not None and live is not None:
            dx = live[0] - ref[0]
            dy = live[1] - ref[1]
            result["drift_x"] = dx
            result["drift_y"] = dy
            cal = self._window._calibration
            if cal.is_calibrated:
                result["drift_x_um"] = cal.pixel_to_um(dx)
                result["drift_y_um"] = cal.pixel_to_um(dy)
        return result

    def set_crosshair(self, enabled: bool) -> None:
        QMetaObject.invokeMethod(
            self._window.control_panel.show_crosshair_btn,
            "setChecked",
            Qt.QueuedConnection,
            Q_ARG(bool, enabled),
        )

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def get_theme(self) -> str:
        return self._window._theme.name

    def toggle_theme(self) -> None:
        QMetaObject.invokeMethod(self._window, "toggle_theme", Qt.QueuedConnection)

    def set_colormap(self, name: str) -> None:
        from api.schemas.display import VALID_COLORMAPS
        if name not in VALID_COLORMAPS:
            raise ValueError(f"Invalid colormap: {name!r}. Valid: {VALID_COLORMAPS}")
        self._window.colormap_changed.emit(name)
        QMetaObject.invokeMethod(
            self._window.control_panel.colormap_combo,
            "setCurrentText",
            Qt.QueuedConnection,
            Q_ARG(str, name),
        )

    def get_colormap(self) -> str:
        return self._window.control_panel.colormap_combo.currentText()

    # ------------------------------------------------------------------
    # Overlays
    # ------------------------------------------------------------------

    def get_overlay_settings(self) -> dict:
        return self._window.overlay_state.to_dict()

    def set_overlay_settings(self, settings: dict) -> None:
        from gui.overlay_state import OverlayState as GuiOverlayState
        current = self._window.overlay_state
        merged = current.to_dict()
        for k, v in settings.items():
            if v is not None and k in merged:
                merged[k] = v
        new_state = GuiOverlayState.from_dict(merged)
        # Emit the signal — Qt queues it to the main thread for persistence.
        # The overlay_settings_changed signal is connected to the controller
        # which persists settings. For visual update, we update the overlay
        # state directly (the frozen dataclass is immutable/thread-safe).
        self._window._overlay_state = new_state
        self._window.overlay_settings_changed.emit(new_state)

    # ------------------------------------------------------------------
    # Trending
    # ------------------------------------------------------------------

    def get_trending_config(self) -> dict:
        return {
            "visible": self._window._trending_visible,
            "depth": self._window.control_panel.trending_depth_input.value(),
        }

    def set_trending_visible(self, visible: bool) -> None:
        QMetaObject.invokeMethod(
            self._window.control_panel.trending_btn,
            "setChecked",
            Qt.QueuedConnection,
            Q_ARG(bool, visible),
        )

    def set_trending_depth(self, depth: int) -> None:
        self._window.trending_depth_changed.emit(depth)

    def get_trending_history(self) -> dict:
        history = self._controller._trending_buffer.get_history()
        return {
            "count": self._controller._trending_buffer.count,
            "frame_number": _ndarray_to_list(history.get("frame_number", np.array([]))),
            "sigma_x": _ndarray_to_list(history.get("sigma_x", np.array([]))),
            "sigma_y": _ndarray_to_list(history.get("sigma_y", np.array([]))),
            "centroid_x": _ndarray_to_list(history.get("centroid_x", np.array([]))),
            "centroid_y": _ndarray_to_list(history.get("centroid_y", np.array([]))),
            "roi_sigma_x": _ndarray_to_list(history.get("roi_sigma_x", np.array([]))),
            "roi_sigma_y": _ndarray_to_list(history.get("roi_sigma_y", np.array([]))),
            "drift_x": _ndarray_to_list(history.get("drift_x", np.array([]))),
            "drift_y": _ndarray_to_list(history.get("drift_y", np.array([]))),
        }

    # ------------------------------------------------------------------
    # Frame data
    # ------------------------------------------------------------------

    def get_frame_metadata(self) -> dict:
        fs = self._state.frame_state
        if fs is None:
            return {
                "frame_number": 0,
                "fps": 0.0,
                "height": 0,
                "width": 0,
                "dtype": "",
            }

        frame = fs.frame
        # Calculate FPS from window's tracking
        w = self._window
        if w._start_time is not None and fs.frame_number > 0:
            elapsed = time.time() - w._start_time
            fps = fs.frame_number / elapsed if elapsed > 0 else 0.0
        else:
            fps = 0.0

        return {
            "frame_number": fs.frame_number,
            "fps": round(fps, 1),
            "height": frame.shape[0],
            "width": frame.shape[1],
            "dtype": str(frame.dtype),
        }

    def get_frame_png_b64(self) -> str:
        """Return the current frame as a base64-encoded PNG."""
        fs = self._state.frame_state
        if fs is None:
            return ""
        return _frame_to_png_b64(fs.frame)

    def get_frame_raw(self) -> Optional[bytes]:
        """Return the current frame as raw numpy bytes."""
        fs = self._state.frame_state
        if fs is None:
            return None
        buf = io.BytesIO()
        np.save(buf, fs.frame)
        return buf.getvalue()

    def get_projections(self) -> dict:
        fs = self._state.frame_state
        if fs is None or fs.analysis is None:
            return {"x_projection": [], "y_projection": []}
        return {
            "x_projection": fs.analysis.x_projection.tolist(),
            "y_projection": fs.analysis.y_projection.tolist(),
        }

    def get_roi_frame_data(self) -> dict:
        """Return ROI frame data including cropped image and projections."""
        roi = self._window.get_current_roi()
        if roi is None:
            return {"active": False}

        fs = self._state.frame_state
        if fs is None:
            return {"active": True, "metadata": None}

        frame = fs.frame
        x0, y0, x1, y1 = roi
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(frame.shape[1], x1)
        y1 = min(frame.shape[0], y1)
        if x1 <= x0 or y1 <= y0:
            return {"active": True, "metadata": None}

        roi_frame = frame[y0:y1, x0:x1]
        x_proj = np.mean(roi_frame, axis=0).tolist()
        y_proj = np.mean(roi_frame, axis=1).tolist()

        return {
            "active": True,
            "metadata": {
                "frame_number": fs.frame_number,
                "fps": 0.0,
                "height": roi_frame.shape[0],
                "width": roi_frame.shape[1],
                "dtype": str(roi_frame.dtype),
            },
            "image_b64_png": _frame_to_png_b64(roi_frame),
            "projections": {
                "x_projection": x_proj,
                "y_projection": y_proj,
            },
        }

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def get_config_overview(self) -> dict:
        from config.config import (
            get_available_prefixes,
            get_active_prefix,
            get_epics_connection,
            get_display_settings,
        )
        return {
            "active_prefix": get_active_prefix(),
            "available_prefixes": get_available_prefixes(),
            "epics": get_epics_connection(),
            "display": get_display_settings(),
        }

    def get_prefix_info(self, prefix: str) -> dict:
        from config.config import get_pv_names, get_calibration_config
        from analysis.calibration import calibration_from_config
        pv = get_pv_names(prefix)
        cal_cfg = get_calibration_config(prefix)
        cal = calibration_from_config(cal_cfg)
        return {
            "name": prefix,
            "image_pv": pv.get("image_pv", ""),
            "width_pv": pv.get("width_pv", ""),
            "height_pv": pv.get("height_pv", ""),
            "calibration": {
                "is_calibrated": cal.is_calibrated,
                "um_per_pixel": cal.um_per_pixel,
                "unit_label": cal.unit_label,
                "description": cal.description,
            } if cal else None,
        }

    def get_calibration_info(self) -> dict:
        cal = self._window._calibration
        return {
            "is_calibrated": cal.is_calibrated,
            "um_per_pixel": cal.um_per_pixel,
            "unit_label": cal.unit_label,
            "description": cal.description,
        }

    # ------------------------------------------------------------------
    # WebSocket frame snapshot (called by ws_manager publisher)
    # ------------------------------------------------------------------

    def build_ws_frame_payload(self) -> Optional[dict]:
        """Build a complete frame payload for WebSocket broadcast."""
        fs = self._state.frame_state
        if fs is None:
            return None

        frame = fs.frame
        metadata = self.get_frame_metadata()
        projections = self.get_projections()
        analysis = self.get_analysis_status()
        roi = self.get_roi()
        drift = self.get_drift()

        return {
            "type": "frame",
            "frame_number": metadata["frame_number"],
            "timestamp": time.time(),
            "fps": metadata["fps"],
            "frame_png_b64": _frame_to_png_b64(frame),
            "projections": projections,
            "analysis": {
                "fit_full_enabled": analysis["fit_full_enabled"],
                "fit_roi_enabled": analysis["fit_roi_enabled"],
                "x_fit": analysis.get("x_fit"),
                "y_fit": analysis.get("y_fit"),
            },
            "roi": roi,
            "drift": drift,
        }


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _nan_to_none(value: Any) -> Any:
    """Convert NaN floats to None for JSON serialization."""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _ndarray_to_list(arr: np.ndarray) -> list[float]:
    """Convert a numpy array to a list, replacing NaN with None."""
    return [None if math.isnan(v) else round(v, 6) for v in arr.tolist()]


def _frame_to_png_b64(frame: np.ndarray) -> str:
    """Encode a 2D numpy frame as a base64 PNG string.

    Normalizes to 8-bit grayscale for PNG encoding.
    """
    try:
        from PIL import Image
    except ImportError:
        # Fallback: return empty if Pillow not available
        return ""

    f = frame.astype(np.float64)
    fmin, fmax = f.min(), f.max()
    if fmax > fmin:
        normalized = ((f - fmin) / (fmax - fmin) * 255).astype(np.uint8)
    else:
        normalized = np.zeros_like(f, dtype=np.uint8)

    img = Image.fromarray(normalized, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
