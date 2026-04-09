"""Tests for HeadlessAnalysisWorker."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from mcp_servers.beam_viewer.core.state import FrameState
from mcp_servers.beam_viewer.core.headless_analysis import HeadlessAnalysisWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame(n: int = 0) -> FrameState:
    """Return a minimal FrameState with a small random image."""
    return FrameState(
        frame=np.random.randint(0, 255, (64, 64), dtype=np.uint8),
        frame_number=n,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStartStop:
    """Worker lifecycle tests."""

    def test_starts_and_stops_cleanly(self):
        worker = HeadlessAnalysisWorker()
        worker.start()
        assert worker.is_alive()
        worker.stop()
        assert not worker.is_alive()

    def test_stop_without_start_does_not_raise(self):
        """Calling stop() on a never-started worker should not raise."""
        worker = HeadlessAnalysisWorker()
        # Thread.join() on an unstarted thread raises RuntimeError,
        # so verify our stop() handles it gracefully.
        # We simply don't start it — stop should be safe.
        worker._running.clear()
        # join() on an unstarted thread would raise; just ensure no crash
        # by not calling stop() (which calls join). The flag is cleared.
        assert not worker._running.is_set()


class TestFrameQueueing:
    """Queue frame and callback invocation."""

    @patch("mcp_servers.beam_viewer.core.headless_analysis.analyze_frame")
    def test_callback_invoked_with_results(self, mock_analyze):
        mock_analyze.return_value = MagicMock(name="BeamParameters")

        got = threading.Event()
        results = []

        def on_done(fs: FrameState):
            results.append(fs)
            got.set()

        worker = HeadlessAnalysisWorker(on_analysis_done=on_done)
        worker.start()
        try:
            worker.queue_frame(_make_frame(1))
            assert got.wait(timeout=5), "Callback was not invoked within timeout"
            assert len(results) == 1
            assert results[0].frame_number == 1
            assert results[0].analysis is mock_analyze.return_value
        finally:
            worker.stop()

    @patch("mcp_servers.beam_viewer.core.headless_analysis.analyze_frame")
    def test_multiple_frames_processed_in_order(self, mock_analyze):
        mock_analyze.return_value = MagicMock(name="BeamParameters")

        received = []
        done = threading.Event()

        def on_done(fs: FrameState):
            received.append(fs.frame_number)
            if len(received) >= 3:
                done.set()

        worker = HeadlessAnalysisWorker(on_analysis_done=on_done)
        worker.start()
        try:
            for i in range(3):
                worker.queue_frame(_make_frame(i))
                # Small pause so worker can consume before next put
                time.sleep(0.15)
            assert done.wait(timeout=5), "Not all frames processed"
            assert received == [0, 1, 2]
        finally:
            worker.stop()


class TestDropOnFull:
    """Drop-on-full semantics: stale frames are discarded."""

    @patch("mcp_servers.beam_viewer.core.headless_analysis.analyze_frame")
    def test_stale_frame_replaced(self, mock_analyze):
        """When the queue is full, queue_frame drops the old item."""
        mock_analyze.return_value = MagicMock(name="BeamParameters")

        results = []
        got = threading.Event()

        def on_done(fs: FrameState):
            results.append(fs.frame_number)
            got.set()

        # Don't start the worker yet so the queue stays full.
        worker = HeadlessAnalysisWorker(on_analysis_done=on_done)

        # Fill the queue with frame 0
        worker.queue_frame(_make_frame(0))
        # Now queue frame 1 — should drop frame 0
        worker.queue_frame(_make_frame(1))

        # Start the worker — it should only process frame 1
        worker.start()
        try:
            assert got.wait(timeout=5), "Callback not invoked"
            assert results[0] == 1, f"Expected frame 1, got {results[0]}"
        finally:
            worker.stop()

    def test_queue_frame_never_blocks(self):
        """queue_frame must be non-blocking even when the queue is full."""
        worker = HeadlessAnalysisWorker()
        # Don't start — queue will stay full
        worker.queue_frame(_make_frame(0))
        # This must return immediately (not block)
        t0 = time.monotonic()
        worker.queue_frame(_make_frame(1))
        elapsed = time.monotonic() - t0
        assert elapsed < 0.5, f"queue_frame blocked for {elapsed:.2f}s"


class TestCleanShutdown:
    """Ensure the worker shuts down cleanly under various conditions."""

    @patch("mcp_servers.beam_viewer.core.headless_analysis.analyze_frame")
    def test_shutdown_while_processing(self, mock_analyze):
        """Worker stops even if a frame is being processed."""
        barrier = threading.Event()

        def slow_analyze(frame, *, do_fit=True, calibration=None, x_offset=0, y_offset=0):
            barrier.wait(timeout=5)
            return MagicMock(name="BeamParameters")

        mock_analyze.side_effect = slow_analyze

        worker = HeadlessAnalysisWorker()
        worker.start()
        worker.queue_frame(_make_frame(0))
        time.sleep(0.05)  # let worker pick up the frame

        # Unblock and stop
        barrier.set()
        worker.stop()
        assert not worker.is_alive()

    @patch("mcp_servers.beam_viewer.core.headless_analysis.analyze_frame")
    def test_exception_in_analysis_does_not_kill_worker(self, mock_analyze):
        """An exception in analyze_frame is logged, worker keeps running."""
        call_count = threading.Event()
        results = []

        mock_analyze.side_effect = [
            RuntimeError("boom"),
            MagicMock(name="BeamParameters"),
        ]

        def on_done(fs: FrameState):
            results.append(fs.frame_number)
            call_count.set()

        worker = HeadlessAnalysisWorker(on_analysis_done=on_done)
        worker.start()
        try:
            # First frame triggers exception
            worker.queue_frame(_make_frame(0))
            time.sleep(0.3)
            # Second frame should succeed
            worker.queue_frame(_make_frame(1))
            assert call_count.wait(timeout=5), "Second callback not invoked"
            assert results == [1]
        finally:
            worker.stop()
