"""FastMCP tool definitions for the beam viewer MCP server.

Each tool delegates to :class:`HeadlessBridge` methods.  The bridge
instance is set at application startup via :func:`set_bridge`.
"""

from __future__ import annotations

from typing import Any, Optional

from fastmcp import FastMCP

from beam_viewer.api.headless_bridge import HeadlessBridge

mcp = FastMCP("beam-viewer")

_bridge: Optional[HeadlessBridge] = None


def set_bridge(bridge: HeadlessBridge) -> None:
    """Set the module-level bridge instance (called at app startup)."""
    global _bridge
    _bridge = bridge


def _get_bridge() -> HeadlessBridge:
    if _bridge is None:
        raise RuntimeError("HeadlessBridge not initialised — call set_bridge() first")
    return _bridge


# ------------------------------------------------------------------
# Capture
# ------------------------------------------------------------------


@mcp.tool()
def beam_capture() -> dict[str, Any]:
    """Capture the current frame as a base64-encoded PNG image."""
    bridge = _get_bridge()
    metadata = bridge.get_frame_metadata()
    png_b64 = bridge.get_frame_png_b64()
    return {
        "metadata": metadata,
        "image_b64_png": png_b64,
    }


# ------------------------------------------------------------------
# Status
# ------------------------------------------------------------------


@mcp.tool()
def beam_status() -> dict[str, Any]:
    """Get current beam status including streaming state, connection, and camera info."""
    bridge = _get_bridge()
    return {
        "streaming": bridge.get_streaming_status(),
        "camera": bridge.get_camera_info(),
        "frame": bridge.get_frame_metadata(),
    }


# ------------------------------------------------------------------
# Camera controls
# ------------------------------------------------------------------


@mcp.tool()
def beam_set_camera(prefix: str) -> dict[str, str]:
    """Set the active camera by EPICS PV prefix."""
    bridge = _get_bridge()
    bridge.select_prefix(prefix)
    return {"status": "ok", "prefix": prefix}


@mcp.tool()
def beam_set_exposure(value: float) -> dict[str, Any]:
    """Set the camera exposure time."""
    bridge = _get_bridge()
    bridge.set_exposure(value)
    return {"status": "ok", "exposure": value}


@mcp.tool()
def beam_set_gain(value: int) -> dict[str, Any]:
    """Set the camera gain."""
    bridge = _get_bridge()
    bridge.set_gain(value)
    return {"status": "ok", "gain": value}


# ------------------------------------------------------------------
# Analysis
# ------------------------------------------------------------------


@mcp.tool()
def beam_analysis() -> dict[str, Any]:
    """Get current beam analysis results (sigma, centroid, amplitude) for full frame and ROI."""
    bridge = _get_bridge()
    return bridge.get_analysis_status()


# ------------------------------------------------------------------
# ROI
# ------------------------------------------------------------------


@mcp.tool()
def beam_roi_set(x0: int, y0: int, x1: int, y1: int) -> dict[str, Any]:
    """Set the Region of Interest coordinates."""
    bridge = _get_bridge()
    bridge.set_roi(x0, y0, x1, y1)
    return {"status": "ok", "roi": {"x0": x0, "y0": y0, "x1": x1, "y1": y1}}


@mcp.tool()
def beam_roi_clear() -> dict[str, str]:
    """Clear the current Region of Interest."""
    bridge = _get_bridge()
    bridge.clear_roi()
    return {"status": "ok"}


@mcp.tool()
def beam_roi_center() -> dict[str, Any]:
    """Center the ROI on the current frame centroid."""
    bridge = _get_bridge()
    bridge.center_roi()
    roi = bridge.get_roi()
    return {"status": "ok", "roi": roi}


# ------------------------------------------------------------------
# Background
# ------------------------------------------------------------------


@mcp.tool()
def beam_background_acquire() -> dict[str, Any]:
    """Acquire a background frame for subtraction."""
    bridge = _get_bridge()
    bridge.acquire_background()
    return {"status": "ok", "background": bridge.get_background_status()}


@mcp.tool()
def beam_background_toggle(enabled: bool) -> dict[str, Any]:
    """Toggle background subtraction on or off."""
    bridge = _get_bridge()
    bridge.set_background_subtraction(enabled)
    return {"status": "ok", "subtraction_enabled": enabled}


# ------------------------------------------------------------------
# Trending
# ------------------------------------------------------------------


@mcp.tool()
def beam_trending() -> dict[str, Any]:
    """Get trending history (sigma, centroid, drift over recent frames)."""
    bridge = _get_bridge()
    config = bridge.get_trending_config()
    history = bridge.get_trending_history()
    return {"config": config, "history": history}


# ------------------------------------------------------------------
# Calibration
# ------------------------------------------------------------------


@mcp.tool()
def beam_calibration() -> dict[str, Any]:
    """Get calibration information (pixel-to-micron mapping)."""
    bridge = _get_bridge()
    return bridge.get_calibration_info()


# ------------------------------------------------------------------
# Drift
# ------------------------------------------------------------------


@mcp.tool()
def beam_drift() -> dict[str, Any]:
    """Get centroid drift/tracking data (reference, live position, drift delta)."""
    bridge = _get_bridge()
    return bridge.get_drift()


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------


@mcp.tool()
def beam_config(updates: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Get or update configuration. Pass updates dict to modify settings, or omit for read-only."""
    bridge = _get_bridge()
    if updates:
        if "prefix" in updates:
            bridge.select_prefix(updates["prefix"])
        if "exposure" in updates:
            bridge.set_exposure(updates["exposure"])
        if "gain" in updates:
            bridge.set_gain(updates["gain"])
        if "colormap" in updates:
            bridge.set_colormap(updates["colormap"])
        if "trending_depth" in updates:
            bridge.set_trending_depth(updates["trending_depth"])
        if "overlays" in updates:
            bridge.set_overlay_settings(updates["overlays"])
    return bridge.get_config_overview()
