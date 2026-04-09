"""Streaming status schemas."""

from __future__ import annotations

from pydantic import BaseModel


class StreamingStatus(BaseModel):
    streaming: bool
    connected: bool
    frame_count: int


class StreamingSet(BaseModel):
    streaming: bool
