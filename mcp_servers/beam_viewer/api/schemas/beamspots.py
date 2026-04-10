"""Beamspot grid detection schemas."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel


class BeamspotPosition(BaseModel):
    row: int
    col: int
    x: int
    y: int


class BeamspotGridResponse(BaseModel):
    x_peaks: List[int]
    y_peaks: List[int]
    grid: List[BeamspotPosition]
