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
    expected_cols: int = 5,
    expected_rows: int = 4,
) -> Tuple[List[int], List[int]]:
    """Find peak positions in each projection.

    Parameters
    ----------
    x_projection : np.ndarray
        1-D horizontal projection (length = image width).
    y_projection : np.ndarray
        1-D vertical projection (length = image height).
    expected_cols : int
        Number of column peaks expected in the horizontal projection.
    expected_rows : int
        Number of row peaks expected in the vertical projection.

    Returns
    -------
    x_peaks : list[int]
        Column positions of peaks, sorted ascending.
    y_peaks : list[int]
        Row positions of peaks, sorted ascending.

    Raises
    ------
    ValueError
        If fewer than the expected number of peaks are found in either
        projection.
    """
    x_peaks = _find_top_peaks(x_projection, expected_cols)
    y_peaks = _find_top_peaks(y_projection, expected_rows)
    return x_peaks, y_peaks


def _find_top_peaks(projection: np.ndarray, n: int) -> List[int]:
    """Return the *n* most prominent peaks in *projection*, sorted by position.

    Selects the combination of *n* peaks whose spacing is most uniform
    (lowest coefficient of variation).  This avoids spurious edge peaks
    that may rival real beamspot peaks in prominence but break the
    expected grid regularity.
    """
    min_distance = max(1, len(projection) // (n * 2))
    peaks, properties = find_peaks(projection, distance=min_distance, prominence=0)

    if len(peaks) < n:
        raise ValueError(
            f"Expected {n} peaks but only found {len(peaks)} "
            f"in projection of length {len(projection)}"
        )

    if len(peaks) == n:
        return sorted(peaks.tolist())

    # Pre-filter to the top candidates by prominence (keep up to 2*n)
    prominences = properties["prominences"]
    n_candidates = min(len(peaks), n * 2)
    candidate_indices = np.argsort(prominences)[-n_candidates:]
    candidate_peaks = np.sort(peaks[candidate_indices])

    # Pick the n-subset with the most uniform spacing, using total
    # prominence as a tiebreaker when spacing regularity is similar.
    from itertools import combinations

    # Build a prominence lookup for scoring
    prom_lookup = dict(zip(peaks.tolist(), prominences.tolist()))

    best_peaks = None
    best_score = (-float("inf"),)

    for combo in combinations(candidate_peaks, n):
        spacings = np.diff(combo)
        mean_sp = np.mean(spacings)
        cv = np.std(spacings) / mean_sp if mean_sp > 0 else float("inf")
        total_prom = sum(prom_lookup.get(int(p), 0) for p in combo)
        # Primary: low CV (uniform spacing). Secondary: high prominence.
        # Quantize CV to 0.05 bins so near-equal spacings don't override
        # a much more prominent set.
        cv_bin = round(cv / 0.05) * 0.05
        score = (-cv_bin, total_prom)
        if score > best_score:
            best_score = score
            best_peaks = combo

    return list(best_peaks)
