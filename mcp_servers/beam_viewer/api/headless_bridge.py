"""HeadlessBridge — Qt-free adapter between the API layer and HeadlessController.

Drop-in replacement for ``ApiBridge`` that calls ``HeadlessController``
methods directly instead of dispatching via ``QMetaObject.invokeMethod``.
All reads go through ``AppState`` (RLock-protected).  All mutations call
the controller's public methods which are thread-safe by design.

Zero Qt imports.
"""

from __future__ import annotations

import base64
import io
import logging
import math
import time
from typing import Any, Optional

import numpy as np

log = logging.getLogger(__name__)


class HeadlessBridge:
    """Thread-safe adapter between API routes and the headless backend.

    Parameters
    ----------
    state : AppState
        Thread-safe application state (model layer).
    controller : HeadlessController
        Headless application controller.
    """

    def __init__(self, state: Any, controller: Any) -> None:
        self._state = state
        self._controller = controller
        self._start_time: Optional[float] = None
        self._last_roi_fit: Optional[dict] = None

        # Listen for ROI fit results from the controller
        from mcp_servers.beam_viewer.core.headless_controller import EVT_ROI_FIT_DONE
        controller.dispatcher.register(EVT_ROI_FIT_DONE, self._on_roi_fit_done)

    def mark_start_time(self) -> None:
        """Record the wall-clock start time for FPS computation."""
        self._start_time = time.time()

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def get_camera_info(self) -> dict:
        s = self._state
        return {
            "active_prefix": self._controller.active_prefix,
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
        available = self._controller.get_available_prefixes()
        if prefix not in available:
            raise ValueError(f"Unknown prefix: {prefix!r}. Available: {available}")
        self._controller.switch_prefix(prefix)

    def set_exposure(self, value: float) -> None:
        self._controller.set_exposure(value)

    def set_gain(self, value: int) -> None:
        self._controller.set_gain(value)

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def get_streaming_status(self) -> dict:
        return {
            "streaming": self._controller.streaming,
            "connected": self._state.connected,
            "frame_count": self._state.frame_count,
        }

    def set_streaming(self, enabled: bool) -> None:
        self._controller.set_streaming(enabled)

    # ------------------------------------------------------------------
    # Background
    # ------------------------------------------------------------------

    def get_background_status(self) -> dict:
        return {
            "has_background": self._state.background_frame is not None,
            "subtraction_enabled": self._state.bg_subtraction_enabled,
        }

    def acquire_background(self) -> None:
        self._controller.acquire_background()

    def set_background_subtraction(self, enabled: bool) -> None:
        self._controller.toggle_bg_subtraction(enabled)

    def save_background(self) -> None:
        self._controller.save_background()

    def load_background(self, path: str) -> None:
        from pathlib import Path as _Path
        from mcp_servers.beam_viewer.config.config import _get_backgrounds_dir
        allowed = _get_backgrounds_dir().resolve()
        resolved = _Path(path).resolve()
        if not str(resolved).startswith(str(allowed) + "/"):
            raise ValueError(f"Path is outside the backgrounds directory: {path!r}")
        if not resolved.exists():
            raise ValueError(f"Background file not found: {path!r}")
        self._controller.load_background(str(resolved))

    def list_backgrounds(self) -> list:
        files = self._controller.get_bg_file_list()
        return [{"filename": p.name, "path": str(p)} for p in files]

    # ------------------------------------------------------------------
    # Beamspot grid detection
    # ------------------------------------------------------------------

    def get_beamspot_grid(self) -> Optional[dict]:
        """Detect the beamspot grid from current frame projections.

        Returns a dict with x_peaks, y_peaks, and grid entries,
        or None if no frame is available, or a dict with 'error' key
        if peak detection fails.
        """
        fs = self._state.frame_state
        if fs is None or fs.analysis is None:
            return None

        from analysis.beamspot_grid import detect_grid_peaks

        try:
            x_peaks, y_peaks = detect_grid_peaks(
                fs.analysis.x_projection,
                fs.analysis.y_projection,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        grid = []
        for row, y in enumerate(y_peaks):
            for col, x in enumerate(x_peaks):
                grid.append({"row": row, "col": col, "x": x, "y": y})

        return {"x_peaks": x_peaks, "y_peaks": y_peaks, "grid": grid}

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def get_analysis_status(self) -> dict:
        result: dict[str, Any] = {
            "fit_full_enabled": self._controller.fit_full,
            "fit_roi_enabled": self._controller.fit_roi,
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
        self._controller.set_fit_full(enabled)

    def set_fit_roi(self, enabled: bool) -> None:
        self._controller.set_fit_roi(enabled)
        if not enabled:
            self._last_roi_fit = None

    def _on_roi_fit_done(self, bp: Any) -> None:
        """Cache the latest ROI fit result from the controller."""
        roi_fit: dict[str, Any] = {}
        for axis, fit in [("roi_x_fit", bp.x_fit), ("roi_y_fit", bp.y_fit)]:
            if fit is not None:
                roi_fit[axis] = {
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
                roi_fit[axis] = None
        self._last_roi_fit = roi_fit

    def get_roi_fit(self) -> Optional[dict]:
        """Return the latest ROI fit result, or None."""
        return self._last_roi_fit

    # ------------------------------------------------------------------
    # ROI
    # ------------------------------------------------------------------

    def get_roi(self) -> dict:
        roi = self._controller.current_roi
        if roi is None:
            return {"active": False, "roi": None}
        x0, y0, x1, y1 = roi
        return {
            "active": True,
            "roi": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        }

    def set_roi(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self._controller.set_roi((x0, y0, x1, y1))

    def clear_roi(self) -> None:
        self._controller.set_roi(None)

    def center_roi(self) -> None:
        """Center the ROI on the current frame centroid."""
        roi = self._controller.current_roi
        fs = self._state.frame_state
        if roi is None or fs is None:
            return
        x0, y0, x1, y1 = roi
        roi_w = x1 - x0
        roi_h = y1 - y0
        frame = fs.frame
        cy, cx = frame.shape[0] // 2, frame.shape[1] // 2
        new_x0 = cx - roi_w // 2
        new_y0 = cy - roi_h // 2
        self._controller.set_roi((
            new_x0, new_y0,
            new_x0 + roi_w, new_y0 + roi_h,
        ))

    # ------------------------------------------------------------------
    # Centroid / Drift
    # ------------------------------------------------------------------

    def get_drift(self) -> dict:
        ref = self._controller.centroid_reference
        live = self._controller.live_roi_centroid
        enabled = self._controller.crosshair_enabled

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
            cal = self._controller.calibration
            if cal.is_calibrated:
                result["drift_x_um"] = cal.pixel_to_um(dx)
                result["drift_y_um"] = cal.pixel_to_um(dy)
        return result

    def set_crosshair(self, enabled: bool) -> None:
        self._controller.set_crosshair_enabled(enabled)

    def set_centroid_reference(self, x: float, y: float) -> None:
        """Persist a new centroid reference (full-frame pixel coordinates)."""
        self._controller.set_centroid_reference(float(x), float(y))

    def clear_centroid_reference(self) -> None:
        """Remove the centroid reference for the active camera."""
        self._controller.clear_centroid_reference()

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def get_theme(self) -> str:
        # Headless mode has no theme — return a default
        return "dark"

    def toggle_theme(self) -> None:
        # No-op in headless mode
        pass

    def set_colormap(self, name: str) -> None:
        from mcp_servers.beam_viewer.api.schemas.display import VALID_COLORMAPS
        if name not in VALID_COLORMAPS:
            raise ValueError(f"Invalid colormap: {name!r}. Valid: {VALID_COLORMAPS}")
        self._controller.set_colormap(name)

    def get_colormap(self) -> str:
        return self._state.colormap_name

    # ------------------------------------------------------------------
    # Overlays
    # ------------------------------------------------------------------

    def get_overlay_settings(self) -> dict:
        return self._controller.overlay_settings

    def set_overlay_settings(self, settings: dict) -> None:
        current = self._controller.overlay_settings
        merged = dict(current)
        for k, v in settings.items():
            if v is not None and k in merged:
                merged[k] = v
        self._controller.set_overlay_settings(merged)

    # ------------------------------------------------------------------
    # Trending
    # ------------------------------------------------------------------

    def get_trending_config(self) -> dict:
        return {
            "visible": True,  # Always "visible" in headless mode
            "depth": self._controller.trending_buffer._max_len,
        }

    def set_trending_depth(self, depth: int) -> None:
        self._controller.set_trending_depth(depth)

    def get_trending_history(self) -> dict:
        buf = self._controller.trending_buffer
        history = buf.get_history()
        return {
            "count": buf.count,
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
        if self._start_time is not None and fs.frame_number > 0:
            elapsed = time.time() - self._start_time
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

    def get_frame_png_bytes(self) -> bytes | None:
        """Return the current frame as raw PNG bytes."""
        fs = self._state.frame_state
        if fs is None:
            return None
        return _frame_to_png_bytes(fs.frame)

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
        roi = self._controller.current_roi
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
            "fit": self._last_roi_fit,
        }

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def get_config_overview(self) -> dict:
        from mcp_servers.beam_viewer.config.config import (
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
        from mcp_servers.beam_viewer.config.config import (
            get_pv_names,
            get_calibration_config,
        )
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
        cal = self._controller.calibration
        return {
            "is_calibrated": cal.is_calibrated,
            "um_per_pixel": cal.um_per_pixel,
            "unit_label": cal.unit_label,
            "description": cal.description,
        }

    # ------------------------------------------------------------------
    # WebSocket frame snapshot
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

        # Attach ROI-local projections so the "Show on: ROI" projection
        # overlay in overlays.js has data to draw. Computed here rather
        # than via a separate REST call so the overlay updates per WS
        # frame instead of polling.
        if roi.get("active"):
            roi_bounds = self._controller.current_roi
            if roi_bounds is not None:
                rx0, ry0, rx1, ry1 = roi_bounds
                rx0 = max(0, rx0)
                ry0 = max(0, ry0)
                rx1 = min(frame.shape[1], rx1)
                ry1 = min(frame.shape[0], ry1)
                if rx1 > rx0 and ry1 > ry0:
                    roi_frame = frame[ry0:ry1, rx0:rx1]
                    roi["x_projection"] = np.mean(roi_frame, axis=0).tolist()
                    roi["y_projection"] = np.mean(roi_frame, axis=1).tolist()

        return {
            "type": "frame",
            "frame_number": metadata["frame_number"],
            "timestamp": time.time(),
            "fps": metadata["fps"],
            "frame_jpeg_b64": _frame_to_jpeg_b64(frame),
            "projections": projections,
            "analysis": {
                "fit_full_enabled": analysis["fit_full_enabled"],
                "fit_roi_enabled": analysis["fit_roi_enabled"],
                "x_fit": analysis.get("x_fit"),
                "y_fit": analysis.get("y_fit"),
                "roi_x_fit": self._last_roi_fit.get("roi_x_fit") if self._last_roi_fit else None,
                "roi_y_fit": self._last_roi_fit.get("roi_y_fit") if self._last_roi_fit else None,
            },
            "roi": roi,
            "drift": drift,
            "streaming": self._controller.streaming,
            "background": self.get_background_status(),
            "colormap": self._state.colormap_name,
        }


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _nan_to_none(value: Any) -> Any:
    """Convert NaN floats to None for JSON serialization."""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _ndarray_to_list(arr: np.ndarray) -> list:
    """Convert a numpy array to a list, replacing NaN with None."""
    return [None if math.isnan(v) else round(v, 6) for v in arr.tolist()]


def _frame_to_jpeg_b64(frame: np.ndarray, quality: int = 80) -> str:
    """Encode a 2D numpy frame as a base64 JPEG string.

    Optimized for WebSocket streaming — smaller output than PNG at the
    cost of lossy compression.  Normalizes to 8-bit grayscale before
    encoding.

    Parameters
    ----------
    frame : np.ndarray
        2-D array (grayscale beam image), uint8 or uint16.
    quality : int
        JPEG quality (1-95). Default 80 balances size vs. fidelity.
    """
    try:
        from PIL import Image
    except ImportError:
        return ""

    f = frame.astype(np.float64)
    fmin, fmax = f.min(), f.max()
    if fmax > fmin:
        normalized = ((f - fmin) / (fmax - fmin) * 255).astype(np.uint8)
    else:
        normalized = np.zeros_like(f, dtype=np.uint8)

    img = Image.fromarray(normalized, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _frame_to_png_bytes(frame: np.ndarray) -> bytes:
    """Encode a 2D numpy frame as raw PNG bytes.

    Normalizes to 8-bit grayscale for PNG encoding.
    """
    from PIL import Image

    f = frame.astype(np.float64)
    fmin, fmax = f.min(), f.max()
    if fmax > fmin:
        normalized = ((f - fmin) / (fmax - fmin) * 255).astype(np.uint8)
    else:
        normalized = np.zeros_like(f, dtype=np.uint8)

    img = Image.fromarray(normalized, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _frame_to_png_b64(frame: np.ndarray) -> str:
    """Encode a 2D numpy frame as a base64 PNG string."""
    try:
        return base64.b64encode(_frame_to_png_bytes(frame)).decode("ascii")
    except ImportError:
        return ""
