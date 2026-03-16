"""
state.py — Thread-safe application state (Model layer).

Centralised store for connection configuration, the current frame snapshot,
and display settings.  All mutable fields are protected by a reentrant lock
so state can be safely read/written from any thread.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from analysis import BeamParameters
from config import get_epics_connection, get_pv_names, get_display_settings


# ---------------------------------------------------------------------------
# Immutable frame snapshot — produced by the controller, consumed by the GUI
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrameState:
    """Everything the view needs to render a single frame."""
    frame: np.ndarray
    frame_number: int
    analysis: Optional[BeamParameters] = None
    do_fit: bool = True


# ---------------------------------------------------------------------------
# Application-wide mutable state
# ---------------------------------------------------------------------------

class AppState:
    """Thread-safe, centralised application state.

    Read/write **any** mutable attribute through the provided properties so
    the internal ``RLock`` is honoured.  Config values (host, port, PV names)
    are intended to be set once before threads start and can be accessed
    directly.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()

        # ---- Connection configuration (set before start, read-only after) --
        epics_conn = get_epics_connection()
        pv_names = get_pv_names()
        display_opts = get_display_settings()

        self.host: str = epics_conn.get("host")
        self.port: int = epics_conn.get("port")
        self.image_pv: str = pv_names.get("image_pv")
        self.width_pv: str = pv_names.get("width_pv")
        self.height_pv: str = pv_names.get("height_pv")
        self.exposure_pv: str = pv_names.get("exposure_pv", "")
        self.exposure_rbv_pv: str = pv_names.get("exposure_rbv_pv", "")
        self.gain_pv: str = pv_names.get("gain_pv", "")
        self.gain_rbv_pv: str = pv_names.get("gain_rbv_pv", "")

        # fallback_shape = (height, width) used when EPICS metadata PVs fail
        _fs = pv_names.get("fallback_shape")
        self.fallback_shape: Optional[Tuple[int, int]] = (
            (int(_fs[0]), int(_fs[1])) if _fs is not None else None
        )

        # ---- Mutable runtime state (lock-protected) -----------------------
        self._frame_state: Optional[FrameState] = None
        self._connected: bool = False
        self._frame_count: int = 0
        self._background_frame: Optional[np.ndarray] = None
        self._bg_subtraction_enabled: bool = False

        # ---- Display / analysis settings ----------------------------------
        self.enable_fitting: bool = display_opts.get("enable_fitting", True)
        self.auto_levels: bool = display_opts.get("auto_levels", True)
        self.levels_interval: int = display_opts.get("levels_interval", 30)
        self.colormap_name: str = display_opts.get("colormap_name", "hot")

    # -- frame_state --------------------------------------------------------
    @property
    def frame_state(self) -> Optional[FrameState]:
        with self._lock:
            return self._frame_state

    @frame_state.setter
    def frame_state(self, value: FrameState) -> None:
        with self._lock:
            self._frame_state = value

    # -- connected ----------------------------------------------------------
    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @connected.setter
    def connected(self, value: bool) -> None:
        with self._lock:
            self._connected = value

    # -- frame_count --------------------------------------------------------
    @property
    def frame_count(self) -> int:
        with self._lock:
            return self._frame_count

    def increment_frame_count(self) -> int:
        """Atomically increment and return the new frame count."""
        with self._lock:
            self._frame_count += 1
            return self._frame_count

    # -- background_frame ---------------------------------------------------
    @property
    def background_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._background_frame

    @background_frame.setter
    def background_frame(self, value: Optional[np.ndarray]) -> None:
        with self._lock:
            self._background_frame = value

    # -- bg_subtraction_enabled ---------------------------------------------
    @property
    def bg_subtraction_enabled(self) -> bool:
        with self._lock:
            return self._bg_subtraction_enabled

    @bg_subtraction_enabled.setter
    def bg_subtraction_enabled(self, value: bool) -> None:
        with self._lock:
            self._bg_subtraction_enabled = value
