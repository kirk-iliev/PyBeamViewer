"""Analysis and fitting endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..headless_bridge import HeadlessBridge
from ..dependencies import get_bridge
from ..schemas.analysis import AnalysisStatus, FitFullSet, FitRoiSet
from ..schemas.common import AckResponse

router = APIRouter(prefix="/analysis", tags=["Analysis"])


@router.get("", response_model=AnalysisStatus)
def get_analysis_status(bridge: HeadlessBridge = Depends(get_bridge)):
    """Get current analysis status including fit results."""
    return bridge.get_analysis_status()


@router.post("/fit-full", response_model=AckResponse)
def set_fit_full(body: FitFullSet, bridge: HeadlessBridge = Depends(get_bridge)):
    """Enable or disable Gaussian fitting on the full image."""
    bridge.set_fit_full(body.enabled)
    action = "enabled" if body.enabled else "disabled"
    return AckResponse(message=f"Full-image fitting {action}")


@router.post("/fit-roi", response_model=AckResponse)
def set_fit_roi(body: FitRoiSet, bridge: HeadlessBridge = Depends(get_bridge)):
    """Enable or disable Gaussian fitting on the ROI."""
    bridge.set_fit_roi(body.enabled)
    action = "enabled" if body.enabled else "disabled"
    return AckResponse(message=f"ROI fitting {action}")
