"""Tests for concurrent WebSocket broadcast in ws_manager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from beam_viewer.api.ws_manager import WebSocketManager


def _make_ws(*, slow: float = 0, fail: bool = False) -> MagicMock:
    """Create a mock WebSocket with configurable send behaviour."""
    ws = MagicMock()

    async def _send_json(payload):
        if slow:
            await asyncio.sleep(slow)
        if fail:
            raise RuntimeError("connection lost")

    ws.send_json = AsyncMock(side_effect=_send_json)
    ws.accept = AsyncMock()
    return ws


@pytest.fixture()
def manager() -> WebSocketManager:
    return WebSocketManager()


@pytest.mark.asyncio
async def test_broadcast_sends_to_all(manager):
    ws1 = _make_ws()
    ws2 = _make_ws()
    manager._connections = [ws1, ws2]

    await manager.broadcast({"type": "frame"})

    ws1.send_json.assert_called_once_with({"type": "frame"})
    ws2.send_json.assert_called_once_with({"type": "frame"})


@pytest.mark.asyncio
async def test_broadcast_evicts_failed_connection(manager):
    good = _make_ws()
    bad = _make_ws(fail=True)
    manager._connections = [good, bad]

    await manager.broadcast({"type": "frame"})

    assert good in manager._connections
    assert bad not in manager._connections
    assert manager.connection_count == 1


@pytest.mark.asyncio
async def test_broadcast_evicts_slow_connection(manager):
    good = _make_ws()
    slow = _make_ws(slow=5.0)  # well over the 1s timeout
    manager._connections = [good, slow]

    await manager.broadcast({"type": "frame"})

    assert good in manager._connections
    assert slow not in manager._connections
    assert manager.connection_count == 1


@pytest.mark.asyncio
async def test_broadcast_noop_when_empty(manager):
    # Should not raise
    await manager.broadcast({"type": "frame"})
    assert manager.connection_count == 0


@pytest.mark.asyncio
async def test_broadcast_concurrent_not_sequential(manager):
    """Verify sends happen concurrently: two 0.3s sends should finish in
    well under 0.6s (sequential) if gathered properly."""
    ws1 = _make_ws(slow=0.3)
    ws2 = _make_ws(slow=0.3)
    manager._connections = [ws1, ws2]

    loop = asyncio.get_event_loop()
    t0 = loop.time()
    await manager.broadcast({"type": "frame"})
    elapsed = loop.time() - t0

    # Concurrent: should be ~0.3s, not ~0.6s.  Allow generous margin.
    assert elapsed < 0.5, f"Broadcast took {elapsed:.2f}s — likely sequential"
    assert manager.connection_count == 2
