"""Tests for core.epics_layer — pure logic, no real network connections.

Strategy:
- `drain()` and `_reshape()` are pure functions that can be tested with
  mock sockets and fake CA commands.
- `epics_get` / `epics_put` dispatch logic (tunnel vs. native mode) is
  verified by mocking the lower-level helpers.
- `connect_epics_socket` / `open_channel_socket` are network-dependent
  and are intentionally left to integration tests.
"""

from __future__ import annotations

import socket
import threading
from typing import Optional
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

from core.epics_layer import EpicsWorker


# ===================================================================
# EpicsWorker._reshape — the most critical pure-logic method
# ===================================================================

def _make_worker(
    fallback_shape: Optional[tuple] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> EpicsWorker:
    """Create an EpicsWorker with mocked Qt wiring."""
    with patch("core.epics_layer.QThread.__init__", return_value=None):
        w = EpicsWorker.__new__(EpicsWorker)
        w.host = ""
        w.port = 15064
        w.image_pv = "TEST:img"
        w.width_pv = "TEST:w"
        w.height_pv = "TEST:h"
        w.fallback_shape = fallback_shape
        w.debug = False
        w._stop_event = threading.Event()
        w._width = width
        w._height = height
        return w


class TestReshape:
    """Tests for EpicsWorker._reshape() — the frame-dimensioning logic."""

    def test_known_dimensions_correct_size(self):
        w = _make_worker(width=10, height=5)
        raw = np.arange(50, dtype=np.uint16)
        frame = w._reshape(raw)
        assert frame is not None
        assert frame.shape == (5, 10)

    def test_known_dimensions_larger_raw(self):
        """Extra pixels beyond width×height should be sliced off."""
        w = _make_worker(width=10, height=5)
        raw = np.arange(100, dtype=np.uint16)
        frame = w._reshape(raw)
        assert frame is not None
        assert frame.shape == (5, 10)
        np.testing.assert_array_equal(frame.ravel(), raw[:50])

    def test_known_dimensions_too_small_uses_fallback(self):
        """When known dims require more pixels than available, try the fallback."""
        w = _make_worker(fallback_shape=(4, 4), width=10, height=10)
        raw = np.arange(16, dtype=np.uint16)  # Only 16 pixels — not enough for 10×10
        frame = w._reshape(raw)
        assert frame is not None
        assert frame.shape == (4, 4)

    def test_fallback_shape_used_when_dims_unknown(self):
        """No width/height known → use configured fallback."""
        w = _make_worker(fallback_shape=(8, 8))
        raw = np.ones(64, dtype=np.uint16)
        frame = w._reshape(raw)
        assert frame is not None
        assert frame.shape == (8, 8)

    def test_fallback_too_small_returns_none(self):
        """If even the fallback shape requires more pixels, return None."""
        w = _make_worker(fallback_shape=(100, 100))
        raw = np.ones(50, dtype=np.uint16)  # Only 50; need 10000
        frame = w._reshape(raw)
        assert frame is None

    def test_square_inference(self):
        """When no dims or fallback: infer square shape from pixel count."""
        w = _make_worker()  # no fallback, no dims
        raw = np.arange(64, dtype=np.uint16)
        frame = w._reshape(raw)
        assert frame is not None
        assert frame.shape == (8, 8)

    def test_non_square_no_dims_no_fallback_returns_none(self):
        """If frame isn't square and we have no metadata, return None."""
        w = _make_worker()
        raw = np.arange(50, dtype=np.uint16)  # Not a perfect square
        frame = w._reshape(raw)
        assert frame is None

    def test_reshape_preserves_data(self):
        """The reshaped values should match the original raw data order."""
        w = _make_worker(width=4, height=3)
        raw = np.arange(12, dtype=np.uint16)
        frame = w._reshape(raw)
        np.testing.assert_array_equal(frame.ravel(), raw)

    def test_reshape_logs_warning_on_size_mismatch(self, caplog):
        """When known dims don't match and fallback succeeds, a warning is logged."""
        import logging
        w = _make_worker(width=100, height=100, fallback_shape=(4, 4))
        raw = np.ones(16, dtype=np.uint16)   # Too small for 100×100, fits 4×4
        with caplog.at_level(logging.WARNING, logger="core.epics_layer"):
            frame = w._reshape(raw)
        assert frame is not None
        assert frame.shape == (4, 4)
        assert "fallback" in caplog.text.lower() or "expected" in caplog.text.lower()

    def test_reshape_logs_warning_no_dims_at_all(self, caplog):
        """When no path succeeds, a warning is emitted."""
        import logging
        w = _make_worker()  # no dims, no fallback
        raw = np.ones(7, dtype=np.uint16)   # 7 is not a perfect square
        with caplog.at_level(logging.WARNING, logger="core.epics_layer"):
            frame = w._reshape(raw)
        assert frame is None
        assert len(caplog.records) > 0


# ===================================================================
# epics_get / epics_put dispatch (tunnel vs. native mode)
# ===================================================================

class TestEpicsGetDispatch:
    """Verify that epics_get routes to the right implementation."""

    def test_tunnel_mode_when_host_set(self):
        """Non-empty host → tunnel mode (connect_epics_socket called)."""
        from core.epics_layer import epics_get
        import caproto as ca

        mock_resp = MagicMock()
        mock_resp.data = np.array([42.0])

        mock_sock = MagicMock()
        mock_circuit = MagicMock()
        mock_chan = MagicMock()
        mock_chan.read.return_value = MagicMock()

        with patch("core.epics_layer.connect_epics_socket", return_value=(mock_sock, mock_circuit)) as mock_connect, \
             patch("core.epics_layer.open_channel_socket", return_value=mock_chan) as mock_open, \
             patch("core.epics_layer.drain", return_value=[mock_resp]) as mock_drain:

            # Make drain return a ReadNotifyResponse
            mock_resp.__class__ = ca.ReadNotifyResponse

            result = epics_get("192.168.1.1", 15064, "TEST:pv", timeout=5.0)

        mock_connect.assert_called_once_with("192.168.1.1", 15064, 5.0)
        mock_open.assert_called_once()
        mock_sock.close.assert_called_once()

    def test_native_mode_when_host_empty(self):
        """Empty host → native mode (_get_native_ctx called)."""
        from core.epics_layer import epics_get

        mock_ctx = MagicMock()
        mock_pv = MagicMock()
        mock_pv.read.return_value = MagicMock(data=np.array([1.0]))
        mock_ctx.get_pvs.return_value = [mock_pv]

        with patch("core.epics_layer._get_native_ctx", return_value=mock_ctx) as mock_get_ctx:
            result = epics_get("", 15064, "TEST:pv", timeout=2.0)

        mock_get_ctx.assert_called_once()
        mock_pv.wait_for_connection.assert_called_once_with(timeout=2.0)
        mock_pv.read.assert_called_once_with(timeout=2.0)


class TestEpicsPutDispatch:
    """Verify that epics_put routes to the right implementation."""

    def test_tunnel_mode_when_host_set(self):
        """Non-empty host → tunnel mode."""
        from core.epics_layer import epics_put
        import caproto as ca

        mock_resp = MagicMock()
        mock_sock = MagicMock()
        mock_circuit = MagicMock()
        mock_chan = MagicMock()
        mock_chan.write.return_value = MagicMock()

        with patch("core.epics_layer.connect_epics_socket", return_value=(mock_sock, mock_circuit)) as mock_connect, \
             patch("core.epics_layer.open_channel_socket", return_value=mock_chan), \
             patch("core.epics_layer.drain", return_value=[mock_resp]):

            mock_resp.__class__ = ca.WriteNotifyResponse
            epics_put("192.168.1.1", 15064, "TEST:pv", 3.14, timeout=5.0)

        mock_connect.assert_called_once()
        mock_sock.close.assert_called_once()

    def test_native_mode_when_host_empty(self):
        """Empty host → native mode."""
        from core.epics_layer import epics_put

        mock_ctx = MagicMock()
        mock_pv = MagicMock()
        mock_ctx.get_pvs.return_value = [mock_pv]

        with patch("core.epics_layer._get_native_ctx", return_value=mock_ctx):
            epics_put("", 15064, "TEST:pv", 42, timeout=2.0)

        mock_pv.wait_for_connection.assert_called_once_with(timeout=2.0)
        mock_pv.write.assert_called_once_with(42, wait=True, timeout=2.0)

    def test_scalar_value_wrapped_in_tuple(self):
        """Scalar values should be wrapped in a tuple before write."""
        from core.epics_layer import epics_put
        import caproto as ca

        mock_resp = MagicMock()
        mock_resp.__class__ = ca.WriteNotifyResponse
        mock_sock = MagicMock()
        mock_circuit = MagicMock()
        mock_chan = MagicMock()
        mock_chan.write.return_value = MagicMock()

        with patch("core.epics_layer.connect_epics_socket", return_value=(mock_sock, mock_circuit)), \
             patch("core.epics_layer.open_channel_socket", return_value=mock_chan), \
             patch("core.epics_layer.drain", return_value=[mock_resp]):
            epics_put("host", 15064, "TEST:pv", 99, timeout=5.0)

        # The write call should have received (99,) not 99
        call_args = mock_chan.write.call_args
        assert call_args.kwargs["data"] == (99,)


# ===================================================================
# EpicsWorker stop event
# ===================================================================

class TestEpicsWorkerStop:
    def test_request_stop_sets_event(self):
        w = _make_worker()
        assert not w._stop_event.is_set()
        w.request_stop()
        assert w._stop_event.is_set()
