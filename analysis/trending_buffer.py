"""
trending_buffer.py — Fixed-size ring buffer for trending history.

Stores per-frame fit metrics (sigma, centroid, amplitude, drift) in a
pre-allocated NumPy structured array.  Thread-safe for single-writer /
single-reader use (controller appends, GUI reads).
"""

from __future__ import annotations

import threading
from typing import Dict

import numpy as np

# Field names stored in the buffer.
FIELDS = (
    "frame_number",
    "sigma_x",
    "sigma_y",
    "centroid_x",
    "centroid_y",
    "roi_sigma_x",
    "roi_sigma_y",
    "drift_x",
    "drift_y",
)

_DTYPE = np.float64


class TrendingBuffer:
    """Circular buffer that accumulates per-frame trending metrics.

    Parameters
    ----------
    max_len : int
        Maximum number of frames retained.  Older entries are silently
        overwritten once capacity is reached.
    """

    def __init__(self, max_len: int = 300) -> None:
        self._lock = threading.Lock()
        self._max_len = max_len
        self._data: Dict[str, np.ndarray] = {
            f: np.full(max_len, np.nan, dtype=_DTYPE) for f in FIELDS
        }
        self._write_idx: int = 0  # next slot to write
        self._count: int = 0       # total entries stored (capped at max_len)

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def append(self, record: Dict[str, float]) -> None:
        """Append a single record.

        *record* is a dict mapping field names to values.  Missing fields
        default to NaN.
        """
        with self._lock:
            idx = self._write_idx
            for f in FIELDS:
                self._data[f][idx] = record.get(f, np.nan)
            self._write_idx = (idx + 1) % self._max_len
            self._count = min(self._count + 1, self._max_len)

    def update_latest_roi(
        self,
        roi_sigma_x: float,
        roi_sigma_y: float,
    ) -> None:
        """Patch the most-recently-appended entry with ROI fit results.

        ROI fitting runs asynchronously and typically completes after the
        main record has already been appended, so this back-fills the
        latest slot.
        """
        with self._lock:
            if self._count == 0:
                return
            idx = (self._write_idx - 1) % self._max_len
            self._data["roi_sigma_x"][idx] = roi_sigma_x
            self._data["roi_sigma_y"][idx] = roi_sigma_y

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_history(self) -> Dict[str, np.ndarray]:
        """Return the buffered history as ``{field_name: 1-D ndarray}``.

        The arrays are ordered oldest → newest and contain only the valid
        portion (length = ``count``).  The caller receives *copies* so
        concurrent writes cannot race.
        """
        with self._lock:
            n = self._count
            if n == 0:
                return {f: np.array([], dtype=_DTYPE) for f in FIELDS}

            if n < self._max_len:
                # Buffer not yet full — data sits at indices 0..n-1.
                return {f: self._data[f][:n].copy() for f in FIELDS}

            # Buffer is full — unwrap the ring.
            start = self._write_idx  # oldest entry
            out: Dict[str, np.ndarray] = {}
            for f in FIELDS:
                arr = self._data[f]
                out[f] = np.concatenate([arr[start:], arr[:start]])
            return out

    @property
    def count(self) -> int:
        """Number of entries currently stored."""
        with self._lock:
            return self._count

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Reset the buffer, discarding all stored history."""
        with self._lock:
            for f in FIELDS:
                self._data[f][:] = np.nan
            self._write_idx = 0
            self._count = 0

    def resize(self, new_max: int) -> None:
        """Change the buffer capacity, preserving as much recent history
        as fits in the new size.
        """
        with self._lock:
            old_history = self._get_history_unlocked()
            self._max_len = new_max
            self._data = {
                f: np.full(new_max, np.nan, dtype=_DTYPE) for f in FIELDS
            }
            # Copy the most recent entries that fit.
            keep = min(len(old_history["frame_number"]), new_max)
            for f in FIELDS:
                self._data[f][:keep] = old_history[f][-keep:]
            self._write_idx = keep % new_max
            self._count = keep

    # internal unlocked helper (caller must hold lock)
    def _get_history_unlocked(self) -> Dict[str, np.ndarray]:
        n = self._count
        if n == 0:
            return {f: np.array([], dtype=_DTYPE) for f in FIELDS}
        if n < self._max_len:
            return {f: self._data[f][:n].copy() for f in FIELDS}
        start = self._write_idx
        out: Dict[str, np.ndarray] = {}
        for f in FIELDS:
            arr = self._data[f]
            out[f] = np.concatenate([arr[start:], arr[:start]])
        return out
