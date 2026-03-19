"""Background analysis worker QThread.

Offloads computationally intensive beam fitting operations from the main thread,
keeping the GUI responsive while processing frames.
"""

from __future__ import annotations

import numpy as np
from queue import Empty, Full, Queue
from typing import Optional
from PyQt5.QtCore import QThread, pyqtSignal, QObject

from core.state import FrameState
from analysis.analysis import analyze_frame


class AnalysisWorker(QThread):
    """Worker thread for performing beam analysis on frames.

    This class runs in a separate thread and performs the computationally
    intensive analysis (Gaussian fitting) of each frame. It uses a thread-safe
    queue to receive work items and emits signals with the results, which are
    then picked up by the main thread to update the GUI. This design keeps
    the GUI responsive while processing frames.

    Parameters
    ----------
    parent : QObject | None
        Optional Qt parent.

    Signals
    -------
    analysis_done : pyqtSignal(FrameState)
        Emitted when analysis of a frame is complete, passing the updated
        FrameState with analysis results attached.
    """

    # Signal emitted when analysis completes (carries the analyzed FrameState)
    analysis_done = pyqtSignal(FrameState)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        # maxsize=1 so the worker always processes the latest frame;
        # frames that arrive while a fit is in progress are dropped (see queue_frame).
        self._queue: Queue = Queue(maxsize=1)
        self._should_stop = False

    def run(self) -> None:
        """Main loop of the worker thread.

        Blocks on the queue waiting for frame states to analyze. When a frame
        arrives, runs the analysis pipeline and emits results. Continues until
        stop() is called.
        """
        while not self._should_stop:
            try:
                # Block with timeout to allow periodic stop checks
                frame_state: FrameState = self._queue.get(timeout=0.1)

                # Perform the computationally intensive analysis
                analyzed_state = analyze_frame(
                    frame_state.frame,
                    do_fit=frame_state.do_fit,
                )

                # Package results back into FrameState
                updated_state = FrameState(
                    frame=frame_state.frame,
                    frame_number=frame_state.frame_number,
                    analysis=analyzed_state,
                    do_fit=frame_state.do_fit,
                )

                # Emit the analyzed state back to the main thread
                self.analysis_done.emit(updated_state)

            except Empty:
                # Queue timeout (empty queue) — continue waiting
                continue

    def queue_frame(self, frame_state: FrameState) -> None:
        """Queue a frame state for analysis.

        This method can be called from any thread to provide a new frame state
        for analysis. The worker will pick it up from the queue.

        If a frame is already waiting (i.e. the worker hasn't started it yet),
        the waiting frame is discarded and replaced with the newer one so the
        worker always processes the most-recent data.

        Parameters
        ----------
        frame_state : FrameState
            The frame state to analyze (must have frame and frame_number set).
        """
        # Drain any stale waiting frame, then enqueue the new one.
        try:
            self._queue.get_nowait()
        except Empty:
            pass
        try:
            self._queue.put_nowait(frame_state)
        except Full:
            pass  # worker just picked up a frame; next one will arrive soon

    def stop(self) -> None:
        """Signal the worker to stop and wait for it to finish."""
        self._should_stop = True
        self.wait()
