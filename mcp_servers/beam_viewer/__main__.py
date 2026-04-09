"""Headless beam viewer entry point.

Usage::

    python -m beam_viewer --host 0.0.0.0 --port 8007

Starts the EPICS acquisition pipeline and serves the FastAPI application.
"""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="PyBeamViewer headless server",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8007, help="Port number (default: 8007)")
    parser.add_argument("--config", default=None, help="Path to config.json")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger(__name__)

    # If a config path is specified, set it via env var before importing
    # config-dependent modules (config.py reads BEAMVIEWER_CONFIG).
    if args.config is not None:
        import os
        os.environ["BEAMVIEWER_CONFIG"] = args.config

    from beam_viewer.core.state import AppState
    from beam_viewer.core.headless_controller import HeadlessController
    from beam_viewer.api.headless_bridge import HeadlessBridge
    from beam_viewer.api.server import create_app

    # Build the headless pipeline
    state = AppState()
    controller = HeadlessController(state)
    bridge = HeadlessBridge(state, controller)

    # Create FastAPI app with WS broadcast wiring
    app = create_app(bridge, dispatcher=controller.dispatcher)

    # Start EPICS acquisition
    log.info("Starting EPICS worker and analysis pipeline")
    controller.start()
    bridge.mark_start_time()

    log.info("Serving on http://%s:%d", args.host, args.port)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        log.info("Shutting down headless controller")
        controller.stop()


if __name__ == "__main__":
    main()
