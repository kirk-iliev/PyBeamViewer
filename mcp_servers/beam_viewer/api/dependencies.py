"""FastAPI dependency injection for the HeadlessBridge singleton."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .headless_bridge import HeadlessBridge

_bridge: HeadlessBridge | None = None


def init_bridge(bridge: "HeadlessBridge") -> None:
    """Set the global HeadlessBridge instance. Call once at startup."""
    global _bridge
    _bridge = bridge


def get_bridge() -> "HeadlessBridge":
    """FastAPI dependency -- returns the HeadlessBridge singleton."""
    if _bridge is None:
        raise RuntimeError("HeadlessBridge not initialized")
    return _bridge
