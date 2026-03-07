"""
config.py — Configuration management.

Loads PV names and settings from config.json. To switch between PV prefixes,
simply change the 'active_prefix' field in config.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


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


def get_available_prefixes() -> list:
    """Return the list of configured PV prefix names (e.g. ['BL31', 'BL72'])."""
    config = load_config()
    return list(config.get("pv_prefixes", {}).keys())


def get_active_prefix() -> str:
    """Return the currently active PV prefix from config."""
    config = load_config()
    return config.get("active_prefix", "BL31")
