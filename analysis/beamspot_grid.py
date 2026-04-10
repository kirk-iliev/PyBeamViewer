"""Beamspot grid detection via projection peak-finding.

Locates a grid of beamspots (default 4x4) by finding peaks in the
horizontal and vertical projections of the camera image.  The
intersection of X peaks (columns) and Y peaks (rows) gives the 2D
grid positions.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
from scipy.signal import find_peaks


def detect_grid_peaks(
    x_projection: np.ndarray,
    y_projection: np.ndarray,
    expected_peaks: int = 4,
) -> Tuple[List[int], List[int]]:
    """Find peak positions in each projection.

    Parameters
    ----------
    x_projection : np.ndarray
        1-D horizontal projection (length = image width).
    y_projection : np.ndarray
        1-D vertical projection (length = image height).
    expected_peaks : int
        Number of peaks expected in each projection.

    Returns
    -------
    x_peaks : list[int]
        Column positions of peaks, sorted ascending.
    y_peaks : list[int]
        Row positions of peaks, sorted ascending.

    Raises
    ------
    ValueError
        If fewer than *expected_peaks* peaks are found in either projection.
    """
    x_peaks = _find_top_peaks(x_projection, expected_peaks)
    y_peaks = _find_top_peaks(y_projection, expected_peaks)
    return x_peaks, y_peaks


def _find_top_peaks(projection: np.ndarray, n: int) -> List[int]:
    """Return the *n* most prominent peaks in *projection*, sorted by position."""
    min_distance = max(1, len(projection) // (n * 2))
    peaks, properties = find_peaks(projection, distance=min_distance, prominence=0)

    if len(peaks) < n:
        raise ValueError(
            f"Expected {n} peaks but only found {len(peaks)} "
            f"in projection of length {len(projection)}"
        )

    # Select the n most prominent peaks
    prominences = properties["prominences"]
    top_indices = np.argsort(prominences)[-n:]
    selected = np.sort(peaks[top_indices])
    return selected.tolist()
