"""Lightweight event dispatcher replacing Qt signal/slot connections."""

import threading
from typing import Callable


class CallbackDispatcher:
    """Plain-Python event dispatcher with thread-safe register/emit.

    Provides the same semantics as Qt direct connections:
    synchronous, in-order callback invocation.
    """

    def __init__(self) -> None:
        self._callbacks: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()

    def register(self, event: str, callback: Callable) -> None:
        """Register *callback* for *event*. Multiple callbacks per event are allowed."""
        with self._lock:
            self._callbacks.setdefault(event, []).append(callback)

    def unregister(self, event: str, callback: Callable) -> None:
        """Remove *callback* from *event*. Raises ValueError if not found."""
        with self._lock:
            self._callbacks[event].remove(callback)

    def emit(self, event: str, *args, **kwargs) -> None:
        """Invoke all callbacks registered for *event* in registration order.

        No-op if no callbacks are registered for the event.
        """
        with self._lock:
            callbacks = list(self._callbacks.get(event, ()))
        for cb in callbacks:
            cb(*args, **kwargs)
