# PyBeamViewer

Real-time beam profile viewer for synchrotron beamlines via EPICS/Channel Access.

## Project Context

### Tech Stack
- **Language:** Python 3.11+, JavaScript (frontend)
- **Build:** setuptools via pyproject.toml
- **Backend:** FastAPI + uvicorn, caproto (EPICS), scipy/numpy (analysis), Pillow (imaging)
- **Frontend:** Vanilla JS with Canvas API, CSS custom properties for theming
- **Testing:** pytest (unit/integration), Playwright (E2E)
- **Container:** Docker (python:3.12-slim), docker-compose

### Running Tests
```bash
# Unit tests (headless backend)
pytest mcp_servers/beam_viewer/tests/ -v --override-ini="addopts=" --override-ini="testpaths=mcp_servers"

# Integration tests
pytest tests/integration/test_beam_viewer.py -v --override-ini="addopts=" --override-ini="testpaths=tests"

# E2E (requires running server on port 8007)
npx playwright test tests/e2e/beam-viewer.spec.js --reporter=list
```

### Architecture
- `core/` — Qt desktop app (controller, epics_layer, state)
- `gui/` — PyQt5 desktop UI
- `api/` — REST API layer (routes, schemas, bridge, WebSocket manager)
- `analysis/` — Beam analysis (Gaussian fitting, calibration)
- `config/` — Configuration loader
- `mcp_servers/beam_viewer/` — **Headless container variant:**
  - `core/` — headless_controller, headless_epics, headless_analysis, dispatcher
  - `api/` — headless_bridge, server (FastAPI app factory), routes, schemas
  - `static/` — Web panel (index.html, JS modules, CSS)
- `docker/Dockerfile.beam-viewer` — Container image (port 8007)
- `tests/e2e/` — Playwright E2E tests
- `tests/integration/` — MCP integration tests

### Pitfalls and Conventions
- All `mcp_servers/beam_viewer/` imports use `beam_viewer.*` prefix (PYTHONPATH=mcp_servers)
- Tests need `--override-ini` flags to override pyproject.toml defaults
- Commit messages require `Log: manual` in the body (pre-commit hook)
- Qt modules (`core/controller.py`, `api/bridge.py`) and headless modules are separate — never mix imports
- WebSocket frames use JPEG (`frame_jpeg_b64`), REST `/frames/current` uses PNG
- `/health` returns HTTP 200 always — `"degraded"` status when EPICS disconnected
