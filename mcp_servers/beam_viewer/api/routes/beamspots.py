"""Beamspot grid detection endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..headless_bridge import HeadlessBridge
from ..dependencies import get_bridge
from ..schemas.beamspots import BeamspotGridResponse

router = APIRouter(prefix="/beamspots", tags=["Beamspots"])


@router.get("", response_model=BeamspotGridResponse)
def get_beamspot_grid(bridge: HeadlessBridge = Depends(get_bridge)):
    """Detect the beamspot grid positions from current frame projections.

    Uses peak-finding on the horizontal and vertical projections to
    locate a 4x4 grid of beamspots.  Returns peak positions and the
    full grid as (row, col, x, y) entries.
    """
    result = bridge.get_beamspot_grid()
    if result is None:
        raise HTTPException(status_code=503, detail="No frame available")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
