"""
main.py — Application entry point.

Creates the MVC components, wires them via the controller, and starts the
Qt event loop.
"""

from __future__ import annotations

import sys

import pyqtgraph as pg
from PyQt6.QtWidgets import QApplication

from controller import BeamController
from gui import BeamViewerWindow
from state import AppState


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # pyqtgraph global config (must be set before any widget creation)
    pg.setConfigOption("background", "k")
    pg.setConfigOption("foreground", "w")
    pg.setConfigOption("imageAxisOrder", "row-major")

    # --- MVC wiring ---
    state = AppState()
    window = BeamViewerWindow()
    controller = BeamController(state, window)

    window.show()
    controller.start()

    exit_code = app.exec()
    controller.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
