"""Tests for the /health endpoint with degraded status."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from beam_viewer.api.server import create_app


def _make_bridge(connected: bool, streaming: bool, frame_count: int = 0) -> MagicMock:
    bridge = MagicMock()
    bridge.get_streaming_status.return_value = {
        "connected": connected,
        "streaming": streaming,
        "frame_count": frame_count,
    }
    return bridge


def test_health_ok_when_connected_and_streaming():
    client = TestClient(create_app(_make_bridge(connected=True, streaming=True, frame_count=42)))
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["connected"] is True
    assert data["streaming"] is True
    assert data["frame_count"] == 42
    assert "reason" not in data


def test_health_degraded_when_epics_disconnected():
    client = TestClient(create_app(_make_bridge(connected=False, streaming=True)))
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["connected"] is False
    assert data["reason"] == "EPICS disconnected"


def test_health_degraded_when_streaming_paused():
    client = TestClient(create_app(_make_bridge(connected=True, streaming=False)))
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["reason"] == "streaming paused"


def test_health_degraded_when_disconnected_and_paused():
    client = TestClient(create_app(_make_bridge(connected=False, streaming=False)))
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["reason"] == "EPICS disconnected"


def test_health_always_returns_200():
    """Health endpoint must always return HTTP 200, even when degraded."""
    for connected, streaming in [(True, True), (True, False), (False, True), (False, False)]:
        client = TestClient(create_app(_make_bridge(connected=connected, streaming=streaming)))
        resp = client.get("/health")
        assert resp.status_code == 200
