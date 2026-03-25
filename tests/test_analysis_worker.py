"""Tests for analysis.analysis_worker — AnalysisWorker QThread.

These tests require PyQt5 and pytest-qt.  If either is unavailable the
entire module is skipped.
"""

from __future__ import annotations

import numpy as np
import pytest

# --- Guard: skip the entire file if Qt or pytest-qt are missing -----------

try:
    from PyQt5.QtWidgets import QApplication  # noqa: F401
    _QT_OK = True
except ImportError:
    _QT_OK = False

try:
    import pytestqt  # noqa: F401
    _QTBOT_OK = True
except ImportError:
    _QTBOT_OK = False

pytestmark = pytest.mark.skipif(not _QT_OK, reason="PyQt5 not available")

if _QT_OK:
    from analysis.analysis_worker import AnalysisWorker
    from analysis.calibration import Calibration
    from core.state import FrameState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame_state(sigma: float = 12.0, shape=(100, 100)) -> "FrameState":
    """Create a FrameState with a synthetic Gaussian frame."""
    rows, cols = shape
    y = np.arange(rows, dtype=np.float64)
    x = np.arange(cols, dtype=np.float64)
    X, Y = np.meshgrid(x, y)
    cx, cy = cols / 2, rows / 2
    frame = (5000.0 * np.exp(
        -0.5 * ((X - cx) ** 2 + (Y - cy) ** 2) / sigma ** 2
    ) + 100).astype(np.uint16)
    return FrameState(frame=frame, frame_number=1, analysis=None, do_fit=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def qapp():
    """Ensure a QApplication exists for QThread tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAnalysisWorkerQueue:
    """Tests for queue_frame drain-and-replace logic."""

    def test_latest_frame_replaces_stale(self, qapp):
        worker = AnalysisWorker()
        fs1 = _make_frame_state()
        fs2 = FrameState(
            frame=fs1.frame,
            frame_number=2,
            analysis=None,
            do_fit=True,
        )

        # Queue two frames without starting the worker
        worker.queue_frame(fs1)
        worker.queue_frame(fs2)

        # Only the latest should be in the queue
        item = worker._queue.get_nowait()
        assert item.frame_number == 2
        assert worker._queue.empty()

    def test_queue_frame_does_not_block(self, qapp):
        """queue_frame should never block the caller."""
        worker = AnalysisWorker()
        for i in range(10):
            fs = FrameState(
                frame=np.zeros((10, 10), dtype=np.uint16),
                frame_number=i,
                analysis=None,
                do_fit=False,
            )
            worker.queue_frame(fs)
        # If we got here without hanging, the test passes.
        assert True


class TestAnalysisWorkerLifecycle:
    """Tests for start/stop lifecycle."""

    def test_stop_terminates_cleanly(self, qapp):
        worker = AnalysisWorker()
        worker.start()
        assert worker.isRunning()
        worker.stop()
        assert not worker.isRunning()

    @pytest.mark.skipif(not _QTBOT_OK, reason="pytest-qt not installed")
    def test_processes_frame_and_emits_signal(self, qapp, qtbot):
        """Worker should analyse a frame and emit analysis_done."""
        worker = AnalysisWorker()
        fs = _make_frame_state()

        with qtbot.waitSignal(worker.analysis_done, timeout=5000) as blocker:
            worker.start()
            worker.queue_frame(fs)

        result = blocker.args[0]
        assert result.frame_number == 1
        assert result.analysis is not None
        assert result.analysis.x_fit is not None

        worker.stop()


class TestAnalysisWorkerCalibration:
    """Tests for calibration propagation."""

    @pytest.mark.skipif(not _QTBOT_OK, reason="pytest-qt not installed")
    def test_set_calibration_affects_results(self, qapp, qtbot):
        worker = AnalysisWorker()
        cal = Calibration(um_per_pixel=2.0, unit_label="µm", is_calibrated=True)
        worker.set_calibration(cal)

        fs = _make_frame_state()
        with qtbot.waitSignal(worker.analysis_done, timeout=5000) as blocker:
            worker.start()
            worker.queue_frame(fs)

        result = blocker.args[0]
        x_fit = result.analysis.x_fit
        assert x_fit.success
        assert x_fit.sigma_um is not None
        assert x_fit.unit_label == "µm"

        worker.stop()


class TestAnalysisWorkerDoFit:
    """Tests for do_fit flag propagation through the worker."""

    def test_do_fit_false_produces_no_fit(self, qapp):
        """A FrameState with do_fit=False should result in analysis with no fits."""
        from core.state import FrameState
        from analysis.analysis import analyze_frame

        # Test the underlying analyze_frame directly (no Qt threading needed)
        rows, cols = 100, 100
        y = np.arange(rows, dtype=np.float64)
        x = np.arange(cols, dtype=np.float64)
        X, Y = np.meshgrid(x, y)
        frame = (5000.0 * np.exp(
            -0.5 * ((X - 50) ** 2 + (Y - 50) ** 2) / 12.0 ** 2
        ) + 100).astype(np.uint16)

        fs = FrameState(frame=frame, frame_number=1, analysis=None, do_fit=False)

        # Worker's run() calls analyze_frame with do_fit=frame_state.do_fit
        result = analyze_frame(fs.frame, do_fit=fs.do_fit)
        assert result.x_fit is None
        assert result.y_fit is None
        assert result.x_projection is not None

    def test_do_fit_true_produces_fits(self, qapp):
        """A FrameState with do_fit=True should result in a successful fit."""
        from core.state import FrameState
        from analysis.analysis import analyze_frame

        rows, cols = 100, 100
        y = np.arange(rows, dtype=np.float64)
        x = np.arange(cols, dtype=np.float64)
        X, Y = np.meshgrid(x, y)
        frame = (5000.0 * np.exp(
            -0.5 * ((X - 50) ** 2 + (Y - 50) ** 2) / 12.0 ** 2
        ) + 100).astype(np.uint16)

        fs = FrameState(frame=frame, frame_number=1, analysis=None, do_fit=True)
        result = analyze_frame(fs.frame, do_fit=fs.do_fit)
        assert result.x_fit is not None
        assert result.x_fit.success
