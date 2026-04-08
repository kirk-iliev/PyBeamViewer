"""Tests for the WebSocket connection manager."""

from __future__ import annotations

import asyncio

import pytest

from api.ws_manager import WebSocketManager


class FakeWebSocket:
    """Minimal WebSocket mock for testing."""

    def __init__(self, *, should_fail: bool = False):
        self.accepted = False
        self.sent: list = []
        self._should_fail = should_fail

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        if self._should_fail:
            raise RuntimeError("connection lost")
        self.sent.append(data)


@pytest.fixture
def manager():
    return WebSocketManager()


@pytest.mark.asyncio
async def test_connect(manager):
    ws = FakeWebSocket()
    await manager.connect(ws)
    assert ws.accepted
    assert manager.connection_count == 1


@pytest.mark.asyncio
async def test_disconnect(manager):
    ws = FakeWebSocket()
    await manager.connect(ws)
    await manager.disconnect(ws)
    assert manager.connection_count == 0


@pytest.mark.asyncio
async def test_disconnect_not_connected(manager):
    ws = FakeWebSocket()
    await manager.disconnect(ws)  # should not raise
    assert manager.connection_count == 0


@pytest.mark.asyncio
async def test_broadcast(manager):
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    await manager.connect(ws1)
    await manager.connect(ws2)

    payload = {"type": "frame", "frame_number": 1}
    await manager.broadcast(payload)

    assert len(ws1.sent) == 1
    assert ws1.sent[0]["frame_number"] == 1
    assert len(ws2.sent) == 1


@pytest.mark.asyncio
async def test_broadcast_removes_dead_clients(manager):
    ws_ok = FakeWebSocket()
    ws_dead = FakeWebSocket(should_fail=True)
    await manager.connect(ws_ok)
    await manager.connect(ws_dead)
    assert manager.connection_count == 2

    await manager.broadcast({"type": "test"})

    # Dead client should have been removed
    assert manager.connection_count == 1
    assert len(ws_ok.sent) == 1


@pytest.mark.asyncio
async def test_broadcast_no_clients(manager):
    # Should not raise
    await manager.broadcast({"type": "test"})
