"""Headless analysis worker — Qt-free replacement for AnalysisWorker.

A daemon ``threading.Thread`` that dequeues ``FrameState`` objects from a
``queue.Queue(maxsize=1)``, runs ``analyze_frame()``, and invokes a
registered callback with the results.  Drop-on-full semantics ensure the
worker always processes the most recent frame.
"""

from __future__ import annotations

import logging
import threading
from queue import Empty, Full, Queue
from typing import Callable, Optional

import numpy as np

from mcp_servers.beam_viewer.analysis.analysis import analyze_frame, BeamParameters
from mcp_servers.beam_viewer.analysis.calibration import Calibration
from mcp_servers.beam_viewer.core.state import FrameState

log = logging.getLogger(__name__)


class HeadlessAnalysisWorker(threading.Thread):
    """Background thread that performs beam analysis on queued frames.

    Parameters
    ----------
    on_analysis_done : callable, optional
        ``fn(FrameState)`` invoked (on the worker thread) after each
        frame is analysed.
    """

    def __init__(
        self,
        on_analysis_done: Optional[Callable[[FrameState], None]] = None,
    ) -> None:
        super().__init__(daemon=True)
        self._queue: Queue[FrameState] = Queue(maxsize=1)
        self._running = threading.Event()
        self._running.set()
        self._callback = on_analysis_done
        self._calibration: Calibration = Calibration()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_calibration(self, calibration: Calibration) -> None:
        """Update the calibration used for subsequent fits."""
        self._calibration = calibration

    def queue_frame(self, frame_state: FrameState) -> None:
        """Enqueue a frame for analysis (non-blocking, drop-on-full).

        If a frame is already waiting, it is discarded and replaced with
        the newer one so the worker always processes the most recent data.
        """
        # Drain any stale waiting frame, then enqueue the new one.
        try:
            self._queue.get_nowait()
        except Empty:
            pass
        try:
            self._queue.put_nowait(frame_state)
        except Full:
            pass  # worker just grabbed a frame; next call will succeed

    def stop(self) -> None:
        """Signal the worker to stop and wait for it to finish."""
        self._running.clear()
        self.join()

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Dequeue frames, analyse, invoke callback."""
        while self._running.is_set():
            try:
                frame_state: FrameState = self._queue.get(timeout=0.1)
            except Empty:
                continue

            try:
                analysis: BeamParameters = analyze_frame(
                    frame_state.frame,
                    do_fit=frame_state.do_fit,
                    calibration=self._calibration,
                )

                updated = FrameState(
                    frame=frame_state.frame,
                    frame_number=frame_state.frame_number,
                    analysis=analysis,
                    do_fit=frame_state.do_fit,
                )

                if self._callback is not None:
                    self._callback(updated)

            except Exception:
                log.exception("Analysis failed for frame %d", frame_state.frame_number)
