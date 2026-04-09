"""Integration test: EVT_FRAME_READY → WebSocket broadcast → client receives frame.

Tests that create_app() produces an app where connected WebSocket clients
receive frame payloads when the controller's dispatcher emits EVT_FRAME_READY.

Regression test for: WebSocket clients connecting but never receiving frames
("waiting for frames..." forever in the web panel).
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import numpy as np
import pytest
from starlette.testclient import TestClient

from beam_viewer.api.server import create_app
from beam_viewer.core.dispatcher import CallbackDispatcher
from beam_viewer.core.headless_controller import EVT_FRAME_READY


def _make_mock_bridge(dispatcher: CallbackDispatcher):
    """Create a mock bridge with a dispatcher and valid WS payload."""
    bridge = MagicMock()
    bridge._controller = MagicMock()
    bridge._controller.dispatcher = dispatcher
    bridge.build_ws_frame_payload.return_value = {
        "type": "frame",
        "frame_number": 1,
        "timestamp": time.time(),
        "fps": 2.0,
        "frame_jpeg_b64": "dGVzdA==",
        "projections": {"x_projection": [], "y_projection": []},
        "analysis": {"fit_full_enabled": False, "fit_roi_enabled": False,
                      "x_fit": None, "y_fit": None},
        "roi": {"x": 0, "y": 0, "width": 100, "height": 100},
        "drift": {"dx": 0.0, "dy": 0.0},
    }
    bridge.get_streaming_status.return_value = {
        "streaming": True, "connected": True, "frame_count": 1,
    }
    return bridge


def test_ws_client_receives_frame_on_dispatch():
    """A WebSocket client MUST receive a frame when EVT_FRAME_READY fires.

    This tests the production create_app() wiring. If the event loop capture
    or dispatcher→broadcast hookup is broken, this test fails — exactly as
    the web panel would show 'waiting for frames...' forever.
    """
    dispatcher = CallbackDispatcher()
    bridge = _make_mock_bridge(dispatcher)
    app = create_app(bridge, dispatcher=dispatcher)

    with TestClient(app) as client:
        with client.websocket_connect("/frames/ws/stream") as ws:
            # Fire the event from a background thread (like the EPICS worker)
            def fire():
                time.sleep(0.2)
                dispatcher.emit(EVT_FRAME_READY, MagicMock())

            t = threading.Thread(target=fire)
            t.start()

            data = ws.receive_json(mode="text")
            t.join(timeout=3.0)

            assert data["type"] == "frame"
            assert "frame_jpeg_b64" in data
            assert "frame_number" in data


def test_ws_client_receives_nothing_without_dispatch():
    """Sanity: no frame arrives unless the dispatcher event fires."""
    dispatcher = CallbackDispatcher()
    bridge = _make_mock_bridge(dispatcher)
    app = create_app(bridge, dispatcher=dispatcher)

    with TestClient(app) as client:
        with client.websocket_connect("/frames/ws/stream") as ws:
            ws.send_text("ping")
            data = ws.receive_json(mode="text")
            assert data["type"] == "pong"
