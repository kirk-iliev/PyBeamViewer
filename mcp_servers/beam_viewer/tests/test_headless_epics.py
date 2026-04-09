"""
Tests for headless_epics.py — HeadlessEpicsWorker and one-shot API functions.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from mcp_servers.beam_viewer.core.headless_epics import (
    HeadlessEpicsWorker,
    epics_get,
    epics_put,
    _get_native_ctx,
    shutdown_native_ctx,
)


# ---------------------------------------------------------------------------
# HeadlessEpicsWorker — creation & lifecycle
# ---------------------------------------------------------------------------

class TestWorkerCreation:
    """Test worker construction and basic threading behaviour."""

    def test_create_with_defaults(self):
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="W:PV", height_pv="H:PV",
        )
        assert w.daemon is True
        assert w.image_pv == "IMG:PV"
        assert w._on_new_frame is None
        assert w._on_connection_changed is None
        assert w._on_error is None

    def test_create_with_callbacks(self):
        cb_frame = MagicMock()
        cb_conn = MagicMock()
        cb_err = MagicMock()
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="W:PV", height_pv="H:PV",
            on_new_frame=cb_frame,
            on_connection_changed=cb_conn,
            on_error=cb_err,
        )
        assert w._on_new_frame is cb_frame
        assert w._on_connection_changed is cb_conn
        assert w._on_error is cb_err

    def test_create_with_fallback_shape(self):
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
            fallback_shape=(480, 640),
        )
        assert w.fallback_shape == (480, 640)

    def test_is_daemon_thread(self):
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
        )
        assert w.daemon is True
        assert isinstance(w, threading.Thread)

    def test_stop_before_start(self):
        """stop() on an unstarted worker should not raise."""
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
        )
        w.stop()  # should not raise

    def test_request_stop_sets_event(self):
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
        )
        assert not w._stop_event.is_set()
        w.request_stop()
        assert w._stop_event.is_set()


# ---------------------------------------------------------------------------
# Callback registration via setters
# ---------------------------------------------------------------------------

class TestCallbackSetters:

    def test_set_on_new_frame(self):
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
        )
        cb = MagicMock()
        w.set_on_new_frame(cb)
        assert w._on_new_frame is cb

    def test_set_on_connection_changed(self):
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
        )
        cb = MagicMock()
        w.set_on_connection_changed(cb)
        assert w._on_connection_changed is cb

    def test_set_on_error(self):
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
        )
        cb = MagicMock()
        w.set_on_error(cb)
        assert w._on_error is cb


# ---------------------------------------------------------------------------
# Callback invocation (emit helpers)
# ---------------------------------------------------------------------------

class TestCallbackInvocation:

    def test_emit_new_frame_invokes_callback(self):
        cb = MagicMock()
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
            on_new_frame=cb,
        )
        frame = np.zeros((100, 100), dtype=np.uint16)
        w._emit_new_frame(frame)
        cb.assert_called_once()
        np.testing.assert_array_equal(cb.call_args[0][0], frame)

    def test_emit_connection_changed_invokes_callback(self):
        cb = MagicMock()
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
            on_connection_changed=cb,
        )
        w._emit_connection_changed(True)
        cb.assert_called_once_with(True)

    def test_emit_error_invokes_callback(self):
        cb = MagicMock()
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
            on_error=cb,
        )
        w._emit_error("something broke")
        cb.assert_called_once_with("something broke")

    def test_emit_with_no_callback_is_noop(self):
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
        )
        # Should not raise even though no callbacks registered
        w._emit_new_frame(np.zeros((10, 10)))
        w._emit_connection_changed(False)
        w._emit_error("err")

    def test_emit_callback_exception_does_not_propagate(self):
        """If a callback raises, it must not crash the worker."""
        bad_cb = MagicMock(side_effect=RuntimeError("boom"))
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
            on_new_frame=bad_cb,
            on_connection_changed=bad_cb,
            on_error=bad_cb,
        )
        # None of these should raise
        w._emit_new_frame(np.zeros((10, 10)))
        w._emit_connection_changed(True)
        w._emit_error("x")


# ---------------------------------------------------------------------------
# Reshape logic
# ---------------------------------------------------------------------------

class TestReshape:

    def _make_worker(self, **kw):
        defaults = dict(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
        )
        defaults.update(kw)
        return HeadlessEpicsWorker(**defaults)

    def test_reshape_with_width_height(self):
        w = self._make_worker()
        w._width = 10
        w._height = 5
        raw = np.arange(50, dtype=np.float64)
        result = w._reshape(raw)
        assert result.shape == (5, 10)

    def test_reshape_with_extra_pixels(self):
        w = self._make_worker()
        w._width = 4
        w._height = 3
        raw = np.arange(20, dtype=np.float64)  # 20 > 12
        result = w._reshape(raw)
        assert result.shape == (3, 4)

    def test_reshape_fallback_shape(self):
        w = self._make_worker(fallback_shape=(8, 8))
        raw = np.arange(64, dtype=np.float64)
        result = w._reshape(raw)
        assert result.shape == (8, 8)

    def test_reshape_square_fallback(self):
        w = self._make_worker()
        raw = np.arange(49, dtype=np.float64)
        result = w._reshape(raw)
        assert result.shape == (7, 7)

    def test_reshape_fails_non_square(self):
        w = self._make_worker()
        raw = np.arange(50, dtype=np.float64)
        result = w._reshape(raw)
        assert result is None

    def test_reshape_too_few_pixels(self):
        w = self._make_worker()
        w._width = 100
        w._height = 100
        raw = np.arange(50, dtype=np.float64)
        # width*height = 10000 > 50 — should try fallback, then fail
        result = w._reshape(raw)
        assert result is None


# ---------------------------------------------------------------------------
# Thread start / stop with mocked EPICS
# ---------------------------------------------------------------------------

class TestThreadLifecycle:

    def test_start_native_mode_and_stop(self):
        """Worker starts, enters native reconnect loop, and stops cleanly."""
        cb_conn = MagicMock()
        cb_err = MagicMock()
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
            on_connection_changed=cb_conn,
            on_error=cb_err,
        )

        # Mock Context so it raises on get_pvs (triggering error path + retry)
        with patch(
            "mcp_servers.beam_viewer.core.headless_epics.Context"
        ) as MockCtx:
            mock_ctx_inst = MagicMock()
            mock_ctx_inst.get_pvs.side_effect = RuntimeError("no IOC")
            MockCtx.return_value = mock_ctx_inst

            w.start()
            # Give it a moment to hit the error path
            time.sleep(0.3)
            w.stop()
            assert not w.is_alive()

        # Should have reported the error
        cb_err.assert_called()
        assert "no IOC" in cb_err.call_args[0][0]

    def test_start_tunnel_mode_and_stop(self):
        """Worker starts in tunnel mode, fails to connect, and stops cleanly."""
        cb_err = MagicMock()
        w = HeadlessEpicsWorker(
            host="localhost", port=19999,
            image_pv="IMG:PV", width_pv="", height_pv="",
            on_error=cb_err,
        )

        with patch(
            "mcp_servers.beam_viewer.core.headless_epics.connect_epics_socket"
        ) as mock_connect:
            mock_connect.side_effect = ConnectionRefusedError("refused")

            w.start()
            time.sleep(0.3)
            w.stop()
            assert not w.is_alive()

        cb_err.assert_called()
        assert "refused" in cb_err.call_args[0][0]

    def test_native_mode_frame_delivery(self):
        """Full native-mode lifecycle: connect, subscribe, deliver a frame, stop."""
        received_frames = []
        conn_states = []

        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
            fallback_shape=(4, 4),
            on_new_frame=lambda f: received_frames.append(f),
            on_connection_changed=lambda c: conn_states.append(c),
        )

        with patch(
            "mcp_servers.beam_viewer.core.headless_epics.Context"
        ) as MockCtx:
            mock_ctx_inst = MagicMock()
            MockCtx.return_value = mock_ctx_inst

            # Create a mock PV that is immediately "connected"
            mock_pv = MagicMock()
            mock_pv.name = "IMG:PV"
            mock_pv.wait_for_connection.return_value = None  # succeeds

            mock_ctx_inst.get_pvs.return_value = [mock_pv]

            # Capture the subscription callback
            mock_sub = MagicMock()
            image_callback = None

            def capture_add_callback(cb):
                nonlocal image_callback
                image_callback = cb

            mock_sub.add_callback.side_effect = capture_add_callback
            mock_pv.subscribe.return_value = mock_sub

            w.start()
            # Wait for the worker to reach subscription setup
            deadline = time.monotonic() + 2.0
            while image_callback is None and time.monotonic() < deadline:
                time.sleep(0.05)

            assert image_callback is not None, "Image callback was not registered"

            # Simulate a frame arriving via the subscription callback
            mock_response = MagicMock()
            mock_response.data = np.arange(16, dtype=np.float64)
            image_callback(mock_sub, mock_response)

            time.sleep(0.1)
            w.stop()

        assert len(received_frames) == 1
        assert received_frames[0].shape == (4, 4)
        assert True in conn_states   # connected at some point
        assert False in conn_states  # disconnected in finally


# ---------------------------------------------------------------------------
# One-shot epics_get / epics_put (native mode, mocked)
# ---------------------------------------------------------------------------

class TestOneShotAPI:

    def test_epics_get_native(self):
        with patch(
            "mcp_servers.beam_viewer.core.headless_epics._get_native_ctx"
        ) as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx_fn.return_value = mock_ctx

            mock_pv = MagicMock()
            mock_ctx.get_pvs.return_value = (mock_pv,)
            mock_response = MagicMock()
            mock_response.data = np.array([42.0])
            mock_pv.read.return_value = mock_response

            result = epics_get("", 0, "TEST:PV", timeout=1.0)
            np.testing.assert_array_equal(result, np.array([42.0]))
            mock_pv.wait_for_connection.assert_called_once_with(timeout=1.0)

    def test_epics_put_native(self):
        with patch(
            "mcp_servers.beam_viewer.core.headless_epics._get_native_ctx"
        ) as mock_ctx_fn:
            mock_ctx = MagicMock()
            mock_ctx_fn.return_value = mock_ctx

            mock_pv = MagicMock()
            mock_ctx.get_pvs.return_value = (mock_pv,)

            epics_put("", 0, "TEST:PV", 3.14, timeout=1.0)
            mock_pv.write.assert_called_once_with(3.14, wait=True, timeout=1.0)

    def test_epics_get_tunnel(self):
        with patch(
            "mcp_servers.beam_viewer.core.headless_epics.connect_epics_socket"
        ) as mock_connect, patch(
            "mcp_servers.beam_viewer.core.headless_epics.open_channel_socket"
        ) as mock_open_ch, patch(
            "mcp_servers.beam_viewer.core.headless_epics.drain"
        ) as mock_drain:
            mock_sock = MagicMock()
            mock_circuit = MagicMock()
            mock_connect.return_value = (mock_sock, mock_circuit)

            mock_chan = MagicMock()
            mock_open_ch.return_value = mock_chan
            mock_chan.read.return_value = MagicMock()
            mock_circuit.send.return_value = [b"data"]

            import caproto as ca
            mock_resp = MagicMock(spec=ca.ReadNotifyResponse)
            mock_resp.data = np.array([99.0])
            mock_drain.return_value = [mock_resp]

            result = epics_get("localhost", 5064, "TEST:PV", timeout=1.0)
            np.testing.assert_array_equal(result, np.array([99.0]))
            mock_sock.close.assert_called_once()

    def test_epics_put_tunnel(self):
        with patch(
            "mcp_servers.beam_viewer.core.headless_epics.connect_epics_socket"
        ) as mock_connect, patch(
            "mcp_servers.beam_viewer.core.headless_epics.open_channel_socket"
        ) as mock_open_ch, patch(
            "mcp_servers.beam_viewer.core.headless_epics.drain"
        ) as mock_drain:
            mock_sock = MagicMock()
            mock_circuit = MagicMock()
            mock_connect.return_value = (mock_sock, mock_circuit)

            mock_chan = MagicMock()
            mock_open_ch.return_value = mock_chan
            mock_chan.write.return_value = MagicMock()
            mock_circuit.send.return_value = [b"data"]

            import caproto as ca
            mock_resp = MagicMock(spec=ca.WriteNotifyResponse)
            mock_drain.return_value = [mock_resp]

            epics_put("localhost", 5064, "TEST:PV", 7.0, timeout=1.0)
            mock_sock.close.assert_called_once()


# ---------------------------------------------------------------------------
# Connection state handling
# ---------------------------------------------------------------------------

class TestConnectionState:

    def test_connection_true_then_false_on_disconnect(self):
        """On native-mode error, connection_changed(True) then (False)."""
        states = []
        w = HeadlessEpicsWorker(
            host="", port=0,
            image_pv="IMG:PV", width_pv="", height_pv="",
            on_connection_changed=lambda c: states.append(c),
            on_error=MagicMock(),
        )

        with patch(
            "mcp_servers.beam_viewer.core.headless_epics.Context"
        ) as MockCtx:
            mock_ctx_inst = MagicMock()
            MockCtx.return_value = mock_ctx_inst

            mock_pv = MagicMock()
            mock_pv.name = "IMG:PV"
            mock_pv.wait_for_connection.return_value = None
            mock_ctx_inst.get_pvs.return_value = [mock_pv]

            # subscribe raises to trigger the error/finally path
            mock_pv.subscribe.side_effect = RuntimeError("sub failed")

            w.start()
            time.sleep(0.3)
            w.stop()

        # Must have emitted True (connected) then False (finally block)
        assert True in states
        assert False in states
        # The last state must be False (cleanup in finally)
        assert states[-1] is False


# ---------------------------------------------------------------------------
# shutdown_native_ctx
# ---------------------------------------------------------------------------

class TestShutdownNativeCtx:

    def test_shutdown_disconnects(self):
        with patch(
            "mcp_servers.beam_viewer.core.headless_epics._native_ctx",
            new=MagicMock(),
        ):
            import mcp_servers.beam_viewer.core.headless_epics as mod
            mock_ctx = MagicMock()
            mod._native_ctx = mock_ctx
            shutdown_native_ctx()
            mock_ctx.disconnect.assert_called_once()
            assert mod._native_ctx is None

    def test_shutdown_when_none(self):
        import mcp_servers.beam_viewer.core.headless_epics as mod
        mod._native_ctx = None
        shutdown_native_ctx()  # should not raise
        assert mod._native_ctx is None
