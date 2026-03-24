"""
config.py — Configuration management.

Loads PV names and settings from config.json. To switch between PV prefixes,
simply change the 'active_prefix' field in config.json.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

log = logging.getLogger(__name__)

# Module-level lock protects read-modify-write cycles on config.json
_config_lock = threading.Lock()


def _get_config_path() -> Path:
    """Get the path to config.json (same directory as this file)."""
    return Path(__file__).parent / "config.json"


def load_config() -> Dict[str, Any]:
    """Load configuration from config.json."""
    config_path = _get_config_path()
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}\n"
            "Please create config.json in the project root."
        )
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in config.json: {e}")


def get_pv_names(prefix: Optional[str] = None) -> Dict[str, str]:
    """
    Get PV names for a given prefix.

    Parameters
    ----------
    prefix : str, optional
        PV prefix (e.g., 'BL31', 'BL72'). If None, uses active_prefix from config.

    Returns
    -------
    Dict[str, str]
        Dictionary with 'image_pv', 'width_pv', 'height_pv' keys.
    """
    config = load_config()

    if prefix is None:
        prefix = config.get("active_prefix", "BL31")

    pv_prefixes = config.get("pv_prefixes", {})

    if prefix not in pv_prefixes:
        raise ValueError(
            f"Unknown PV prefix: {prefix}\n"
            f"Available prefixes: {', '.join(pv_prefixes.keys())}"
        )

    return pv_prefixes[prefix]


def get_epics_connection() -> Dict[str, Any]:
    """Get EPICS connection settings (host, port)."""
    config = load_config()
    return config.get("epics", {"host": "127.0.0.1", "port": 15064})


def get_display_settings() -> Dict[str, Any]:
    """Get display settings (colormaps, fitting, levels, etc.)."""
    config = load_config()
    return config.get("display", {
        "enable_fitting": True,
        "auto_levels": True,
        "levels_interval": 30,
        "colormap_name": "hot",
    })


def get_calibration_config(prefix: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the ``"calibration"`` dict for *prefix*, or ``None`` if absent."""
    pv_names = get_pv_names(prefix)
    return pv_names.get("calibration")


def get_available_prefixes() -> list:
    """Return the list of configured PV prefix names (e.g. ['BL31', 'BL72'])."""
    config = load_config()
    return list(config.get("pv_prefixes", {}).keys())


def get_active_prefix() -> str:
    """Return the currently active PV prefix from config."""
    config = load_config()
    return config.get("active_prefix", "BL31")


# ---------------------------------------------------------------------------
# ROI persistence
# ---------------------------------------------------------------------------

def _atomic_write_config(config_path: Path, data: Dict[str, Any]) -> None:
    """Write *data* to *config_path* atomically via a temp-file + rename."""
    dir_fd = None
    try:
        fd, tmp = tempfile.mkstemp(
            dir=str(config_path.parent), suffix=".tmp", prefix=".config_"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
        except BaseException:
            os.unlink(tmp)
            raise
        os.replace(tmp, str(config_path))
    except Exception:
        log.exception("Failed to write config atomically to %s", config_path)
        raise


def save_roi_for_prefix(prefix: str, roi: Optional[tuple]) -> None:
    """Persist the ROI ``(x0, y0, x1, y1)`` for *prefix* in config.json.

    Pass *roi=None* to remove a previously saved selection.
    """
    with _config_lock:
        config_path = _get_config_path()
        config = load_config()
        rois: Dict[str, Any] = config.setdefault("roi_selections", {})
        if roi is None:
            rois.pop(prefix, None)
        else:
            x0, y0, x1, y1 = roi
            rois[prefix] = {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
        _atomic_write_config(config_path, config)


def get_roi_for_prefix(prefix: str) -> Optional[tuple]:
    """Return the saved ROI ``(x0, y0, x1, y1)`` for *prefix*, or None."""
    config = load_config()
    entry = config.get("roi_selections", {}).get(prefix)
    if entry is None:
        return None
    return (entry["x0"], entry["y0"], entry["x1"], entry["y1"])


# ---------------------------------------------------------------------------
# Overlay settings persistence
# ---------------------------------------------------------------------------

def save_overlay_settings(settings: dict) -> None:
    """Persist projection overlay settings to config.json."""
    with _config_lock:
        config_path = _get_config_path()
        config = load_config()
        config["overlay"] = settings
        _atomic_write_config(config_path, config)


def load_overlay_settings() -> dict:
    """Load projection overlay settings from config.json, or return defaults."""
    config = load_config()
    return config.get("overlay", {
        "h_enabled": False,
        "h_side": "bottom",
        "v_enabled": False,
        "v_side": "left",
        "scale": 0.25,
    })


# ---------------------------------------------------------------------------
# Background persistence
# ---------------------------------------------------------------------------

def _get_backgrounds_dir() -> Path:
    """Return (and create if needed) the backgrounds/ directory."""
    bg_dir = Path(__file__).parent / "backgrounds"
    bg_dir.mkdir(exist_ok=True)
    return bg_dir


def save_background_to_file(prefix: str, frame: np.ndarray) -> Path:
    """Save *frame* as a .npy file in ``backgrounds/<prefix>_<timestamp>.npy``.

    Returns the path to the saved file.
    """
    bg_dir = _get_backgrounds_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{ts}.npy"
    path = bg_dir / filename
    np.save(path, frame)
    return path


def load_background_from_file(path: Path | str) -> np.ndarray:
    """Load a background frame from a ``.npy`` file."""
    return np.load(Path(path))


def list_saved_backgrounds(prefix: Optional[str] = None) -> List[Path]:
    """List saved background .npy files, optionally filtered by *prefix*.

    Returns paths sorted newest-first (by filename timestamp).
    """
    bg_dir = _get_backgrounds_dir()
    if prefix:
        files = sorted(bg_dir.glob(f"{prefix}_*.npy"), reverse=True)
    else:
        files = sorted(bg_dir.glob("*.npy"), reverse=True)
    return files


def get_active_background_path(prefix: str) -> Optional[Path]:
    """Return the path to the currently active background for *prefix*, or None."""
    config = load_config()
    entry = config.get("active_backgrounds", {}).get(prefix)
    if entry is None:
        return None
    p = Path(entry)
    if p.exists():
        return p
    return None


def set_active_background_path(prefix: str, path: Optional[Path | str]) -> None:
    """Persist the active background file path for *prefix* in config.json."""
    config_path = _get_config_path()
    config = load_config()
    active: Dict[str, Any] = config.setdefault("active_backgrounds", {})
    if path is None:
        active.pop(prefix, None)
    else:
        active[prefix] = str(path)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
