"""FastAPI dependency injection for the ApiBridge singleton."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bridge import ApiBridge

_bridge: ApiBridge | None = None


def init_bridge(bridge: "ApiBridge") -> None:
    """Set the global ApiBridge instance. Call once at startup."""
    global _bridge
    _bridge = bridge


def get_bridge() -> "ApiBridge":
    """FastAPI dependency — returns the ApiBridge singleton."""
    if _bridge is None:
        raise RuntimeError("ApiBridge not initialized — API server started before bridge was set up")
    return _bridge
