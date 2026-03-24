"""
main.py — Application entry point.

Creates the MVC components, wires them via the controller, and starts the
Qt event loop.
"""

from __future__ import annotations

import logging
import sys
import traceback

import pyqtgraph as pg
from PyQt5.QtWidgets import QApplication, QMessageBox

from core.controller import BeamController
from core.epics_layer import shutdown_native_ctx
from gui import BeamViewerWindow
from core.state import AppState


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # pyqtgraph global config (must be set before any widget creation)
    pg.setConfigOption("background", "k")
    pg.setConfigOption("foreground", "w")
    pg.setConfigOption("imageAxisOrder", "row-major")

    try:
        # --- MVC wiring ---
        state = AppState()
        window = BeamViewerWindow(fallback_shape=state.fallback_shape)
        controller = BeamController(state, window)
    except Exception:
        QMessageBox.critical(
            None,
            "Startup Error",
            f"Failed to initialise the application:\n\n{traceback.format_exc()}",
        )
        sys.exit(1)

    window.show()
    controller.start()

    exit_code = app.exec_()
    controller.stop()
    shutdown_native_ctx()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
