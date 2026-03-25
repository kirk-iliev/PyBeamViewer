"""Shared pytest fixtures for the PyBeamViewer test suite."""

from __future__ import annotations

# Force pyqtgraph to use PyQt5 — must be set before pyqtgraph is imported anywhere.
import os
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from analysis.calibration import Calibration


# ---------------------------------------------------------------------------
# Synthetic image fixtures
# ---------------------------------------------------------------------------

def _make_gaussian_frame(
    shape: tuple[int, int] = (200, 200),
    center: tuple[float, float] = (100.0, 100.0),
    sigma: float = 12.0,
    amplitude: float = 5000.0,
    offset: float = 100.0,
    dtype=np.uint16,
) -> np.ndarray:
    """Create a 2-D Gaussian frame with known parameters."""
    rows, cols = shape
    y = np.arange(rows, dtype=np.float64)
    x = np.arange(cols, dtype=np.float64)
    X, Y = np.meshgrid(x, y)
    cx, cy = center
    frame = amplitude * np.exp(
        -0.5 * ((X - cx) ** 2 + (Y - cy) ** 2) / sigma ** 2
    ) + offset
    return frame.astype(dtype)


@pytest.fixture
def gaussian_frame() -> np.ndarray:
    """200×200 synthetic Gaussian: σ=12, center=(100,100), amp=5000, offset=100."""
    return _make_gaussian_frame()


@pytest.fixture
def flat_frame() -> np.ndarray:
    """200×200 constant-value frame (all pixels = 500)."""
    return np.full((200, 200), 500, dtype=np.uint16)


@pytest.fixture
def noisy_frame() -> np.ndarray:
    """200×200 Gaussian with Poisson noise added."""
    rng = np.random.default_rng(42)
    clean = _make_gaussian_frame(amplitude=10000.0, offset=200.0).astype(np.float64)
    noisy = rng.poisson(clean).astype(np.uint16)
    return noisy


# ---------------------------------------------------------------------------
# Calibration fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def uncalibrated() -> Calibration:
    """Default uncalibrated Calibration (identity)."""
    return Calibration()


@pytest.fixture
def calibrated() -> Calibration:
    """Calibrated Calibration: 1.8852 µm/px."""
    return Calibration(
        um_per_pixel=1.8852,
        unit_label="µm",
        is_calibrated=True,
        description="Test calibration",
    )


# ---------------------------------------------------------------------------
# Temporary config fixtures
# ---------------------------------------------------------------------------

_SAMPLE_CONFIG: Dict[str, Any] = {
    "active_prefix": "TEST",
    "pv_prefixes": {
        "TEST": {
            "image_pv": "TEST:image1:ArrayData",
            "width_pv": "TEST:image1:ArraySize0_RBV",
            "height_pv": "TEST:image1:ArraySize1_RBV",
            "exposure_pv": "TEST:cam1:AcquireTime",
            "exposure_rbv_pv": "TEST:cam1:AcquireTime_RBV",
            "gain_pv": "TEST:cam1:Gain",
            "gain_rbv_pv": "TEST:cam1:Gain_RBV",
            "fallback_shape": [300, 300],
        },
        "OTHER": {
            "image_pv": "OTHER:image1:ArrayData",
            "width_pv": "OTHER:image1:ArraySize0_RBV",
            "height_pv": "OTHER:image1:ArraySize1_RBV",
            "fallback_shape": [512, 512],
        },
    },
    "epics": {"host": "127.0.0.1", "port": 15064},
    "display": {
        "enable_fitting": True,
        "auto_levels": True,
        "levels_interval": 30,
        "colormap_name": "hot",
    },
    "roi_selections": {},
    "overlay": {
        "h_enabled": False,
        "h_side": "bottom",
        "v_enabled": False,
        "v_side": "left",
        "scale": 0.25,
    },
}


@pytest.fixture
def sample_config() -> Dict[str, Any]:
    """Return a copy of the sample config dict (not written to disk)."""
    import copy
    return copy.deepcopy(_SAMPLE_CONFIG)


@pytest.fixture
def tmp_config_dir(tmp_path: Path, sample_config: Dict[str, Any]):
    """Create a temp directory with a config.json and monkeypatch _get_config_path.

    Yields the directory path.  The real config.json is never touched.
    """
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(sample_config, indent=2))
    # Also create a backgrounds sub-directory
    (tmp_path / "backgrounds").mkdir()
    with patch("config.config._get_config_path", return_value=config_path), \
         patch("config.config._get_backgrounds_dir", return_value=tmp_path / "backgrounds"):
        yield tmp_path
