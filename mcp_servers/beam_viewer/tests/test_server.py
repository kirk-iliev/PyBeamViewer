"""Tests for the headless FastAPI server factory."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from beam_viewer.api.server import create_app


@pytest.fixture()
def mock_bridge():
    bridge = MagicMock()
    bridge.get_streaming_status.return_value = {
        "streaming": True,
        "connected": False,
        "frame_count": 0,
    }
    return bridge


@pytest.fixture()
def client(mock_bridge):
    app = create_app(mock_bridge)
    return TestClient(app)


def test_create_app_returns_fastapi(mock_bridge):
    app = create_app(mock_bridge)
    assert isinstance(app, FastAPI)


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "streaming" in data
    assert "connected" in data
    assert "frame_count" in data
    assert "ws_clients" in data
