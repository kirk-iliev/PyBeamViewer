"""Common response schemas shared across all API routes."""

from __future__ import annotations

from pydantic import BaseModel


class AckResponse(BaseModel):
    ok: bool = True
    message: str = ""


class ErrorResponse(BaseModel):
    error: str
    detail: str = ""
