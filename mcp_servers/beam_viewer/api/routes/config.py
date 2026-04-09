"""Configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..headless_bridge import HeadlessBridge
from ..dependencies import get_bridge
from ..schemas.config_schemas import CalibrationInfo, ConfigOverview, PrefixInfo

router = APIRouter(prefix="/config", tags=["Config"])


@router.get("", response_model=ConfigOverview)
def get_config(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get overall configuration: active prefix, available prefixes, EPICS settings."""
    return bridge.get_config_overview()


@router.get("/prefix/{prefix}", response_model=PrefixInfo)
def get_prefix_info(prefix: str, bridge: HeadlessBridge = Depends(get_bridge)):
    """Get detailed PV and calibration info for a specific prefix."""
    try:
        return bridge.get_prefix_info(prefix)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/calibration", response_model=CalibrationInfo)
def get_calibration(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get the calibration settings for the active camera."""
    return bridge.get_calibration_info()
