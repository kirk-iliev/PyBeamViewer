# Beam Viewer Integration — Feature Proposal

> **Created:** 2026-04-09
> **Status:** Draft (DA-reviewed, 10/11 revisions applied)
> **Clarity Score:** 90/100 (5 rounds)

---

## Overview

Integrate PyBeamViewer into the ALS Assistant deployment as a native web panel tab, MCP server, and agent skill. The `api-test` branch at `github.com/kirk-iliev/PyBeamViewer` (cloned to `~/LBL/ML/PyBeamViewer`) provides a complete REST + WebSocket API layer (3,400+ lines) covering all viewer functionality. The work involves: (1) headless refactoring to remove the Qt GUI dependency for container deployment, (2) building a 100%-parity web frontend, (3) containerizing as an HTTP MCP server on port 8007 as a single-process service, and (4) creating a skill for agent-driven beam diagnostics.

## Goals and Objectives

### Primary Goals
1. **Headless backend**: Refactor `core/controller.py` and `api/bridge.py` to run without Qt GUI — replace `QThread`, `QMetaObject.invokeMethod`, and Qt signal/slot wiring (~22 signal connections) with plain Python threading + asyncio
2. **Web panel with 100% feature parity**: Browser-based beam viewer matching every feature of the Qt desktop app — live image, interactive ROI, Gaussian fit overlays, projection plots, trending charts, background subtraction, camera control, calibration display, crosshair/drift tracking, overlay settings
3. **MCP server**: Single-process FastAPI service on port 8007 exposing MCP tools via direct bridge calls (not HTTP-wrapped), with `/health` endpoint for the OSPREY panel system
4. **Agent skill**: Skill in `overlays/skills/` enabling the ALS Assistant to perform beam diagnostics, camera control, and analysis programmatically

### Secondary Goals
1. Clean container image (~250-300 MB, comparable to existing MCP servers) by excluding Qt5 and X11
2. Serve as reference implementation for future instrument viewer integrations

## Scope

### In Scope
- Headless refactor of `core/controller.py` (~22 signal connections → plain Python callback dispatch)
- Headless refactor of `core/epics_layer.py` (`QThread` → `threading.Thread`)
- Headless `ApiBridge` replacing `QMetaObject.invokeMethod` with direct method calls
- Web frontend: live WebSocket image canvas, interactive ROI drag, projection plots with Gaussian fit curves, trending time-series charts, control panel (camera/exposure/gain/streaming/background/ROI/overlay/colormap/crosshair)
- WebSocket streaming at 5-10 Hz with JPEG compression (~50-100 KB/frame, ~1 MB/s at 10 Hz)
- All 11 REST route groups: camera, streaming, background, analysis, ROI, centroid, display, overlays, trending, frames, config
- Single-process FastAPI app on port 8007 serving: REST API, WebSocket, static web panel, `/mcp` endpoint (fastmcp), `/health`
- MCP tools calling bridge methods directly (shared bridge instance with REST routes — no HTTP indirection)
- Docker container (`docker/Dockerfile.beam-viewer`) with dual-network support: `als-net` bridge + `host` mode override for EPICS
- Dual config: PyBeamViewer `config.json` (volume-mounted writable) for camera/PV/calibration + `OSPREY_CONFIG` for service discovery only
- Writable volume mount with first-start initialization (entrypoint copies defaults)
- Registration in profile YAML (`als-prod.yml`, `als-client.yml`) as `web_panels` + `mcp_servers` entry
- Port existing test suite (4 API test files, 1,311 lines) to headless mode
- E2E browser tests (Playwright) exercising every web panel feature
- MCP integration tests matching `tests/integration/` pattern
- Edge state handling matching Qt behavior: EPICS disconnection, fit failure, no camera configured
- Concurrent WebSocket broadcast with per-client timeouts (replace sequential sends)
- Degraded `/health` status when EPICS is disconnected

### Out of Scope
- Multi-camera simultaneous view (Qt app supports one camera with prefix switching; same constraint applies)
- Historical frame playback or recording
- User authentication or access control (internal beamline network only)
- Changes to the Qt desktop application itself (it continues to work independently)
- EPICS tunnel mode in the container (host networking provides direct CA access)

## Requirements

### Functional Requirements
1. The headless backend must run `EpicsWorker` (from `core/epics_layer.py`) as a plain Python thread, subscribing to camera PVs via `caproto.threading.client.Context`
2. Frame processing pipeline: EPICS acquisition → background subtraction → `analyze_frame()` (from `analysis/analysis.py`) → WebSocket broadcast → trending buffer append
3. Web panel must display live 2D beam image with user-selectable colormap (hot, viridis, inferno, plasma, magma, cividis, gray)
4. Interactive ROI: click-drag selection on the image canvas, with ROI fit results displayed separately
5. Projection plots (horizontal + vertical) with Gaussian fit curves overlaid, matching the MATLAB `beam_fit_gaussian` pipeline in `analysis/analysis.py`
6. Trending panel: 8 time-series charts (σ_x, σ_y, centroid_x, centroid_y, roi_σ_x, roi_σ_y, drift_x, drift_y) from `TrendingBuffer` (ring buffer, configurable depth 50-2000)
7. Camera controls: prefix switching, exposure time, gain — writing to EPICS PVs via `epics_put()` from `core/epics_layer.py`
8. Background subtraction: acquire, save/load `.npy` files, toggle subtraction
9. Calibration display: pixel-to-µm conversion from `analysis/calibration.py` (`calibration_from_config`)
10. Centroid reference crosshair with drift tracking (Δx, Δy in pixels and µm)

### Technical Requirements
- Python 3.11+ runtime with caproto ≥1.1, scipy ≥1.11, numpy ≥1.24, FastAPI, uvicorn, Pillow
- Single-process architecture: one FastAPI app on port 8007 serves REST API, WebSocket streaming, static web panel, `/mcp` endpoint (fastmcp), and `/health`
- Docker networking: defined in `docker-compose.yml` on `als-net` with `ports: 0.0.0.0:8007:8007`; `docker-compose.host.yml` adds `network_mode: host` for EPICS CA access
- Dual config: `BEAMVIEWER_CONFIG` env var → `/app/config/config.json` (camera/PV/calibration, writable volume); `OSPREY_CONFIG` env var → standard config.yml (service discovery only)
- Writable volume: `docker-compose.yml` mounts `./beam-viewer-data:/app/config`; entrypoint copies defaults from `/app/config.default/` on first start
- WebSocket transport: JPEG-encoded frames (base64, quality=80, ~50-100 KB) for streaming at 5-10 Hz; PNG encoding retained for REST `/frames/current` endpoint (lossless fidelity)
- Concurrent WebSocket broadcast: `asyncio.gather()` with 1s per-client timeout, evicting stalled clients
- Health endpoint: returns `status: ok` when EPICS connected, `status: degraded` with `connected: false` when disconnected (always HTTP 200)
- Verify OSPREY supports custom panel registration via config keys (`web.panels.beam-viewer.label`, `.url`, `.health_endpoint`). If not supported, OSPREY panel system change is a prerequisite
- Web frontend served as self-contained static files from the FastAPI server (HTML/JS/CSS)
- MCP tools import the headless bridge directly (shared singleton) — no HTTP round-trips

## Success Criteria

### Build & Installation
- [ ] `docker build -f docker/Dockerfile.beam-viewer .` completes without errors
- [ ] Container starts with `--network=host` and `/health` returns `{"status": "ok"}` (or `"degraded"` if no EPICS)
- [ ] MCP tools are accessible from the ALS Assistant via profile configuration
- [ ] First-start entrypoint correctly initializes config volume from defaults

### Functionality
- [ ] Side-by-side comparison: every feature in the Qt desktop app has a working equivalent in the web panel, documented with comparison screenshots
- [ ] WebSocket streaming delivers JPEG frames at ≥5 Hz when camera is active
- [ ] EPICS PV reads and writes work correctly through the headless backend (same PV values as Qt app)
- [ ] Agent can perform a complete beam diagnostic workflow using the skill: select camera → enable streaming → analyze beam → report σ and centroid → set ROI → compare ROI fit

### Test Coverage
- [ ] All existing API tests (test_api_bridge, test_api_routes, test_api_schemas, test_api_ws_manager) pass against headless backend
- [ ] E2E Playwright tests cover: image display, ROI interaction, projection plots, trending, camera switching, background subtraction, overlay toggles
- [ ] MCP integration tests verify all tool endpoints return valid responses

### Edge Cases
- [ ] EPICS disconnection: web panel shows "Disconnected" status, freezes last frame, grays out camera controls; `/health` returns `status: degraded`
- [ ] Gaussian fit failure: displays "Fit failed" in projection plots, reports failure in API response
- [ ] No camera configured: shows appropriate empty state with guidance
- [ ] Slow WebSocket client: evicted after 1s timeout, does not block other clients

### Performance
- [ ] WebSocket frame delivery latency < 200ms from EPICS acquisition to browser render
- [ ] Container memory usage < 512 MB under normal operation (single camera, trending active)
- [ ] JPEG frame size < 150 KB at quality=80 for typical 1300x1038 beam images

## Timeline

| Milestone | Date |
|-----------|------|
| Start | 2026-04-09 |
| Target Completion | TBD |

## Dependencies

- **PyBeamViewer api-test branch**: `github.com/kirk-iliev/PyBeamViewer` (branch: `api-test`) — provides REST API layer, schemas, bridge, WebSocket manager
- **OSPREY panel system**: `web_panels` configuration — may require changes to support custom panel registration (TBD, needs investigation)
- **Docker infrastructure**: `docker-compose.yml` service definition, `docker-compose.host.yml` EPICS override, CI/CD pipeline for image builds
- **EPICS network**: appsdev2 host networking with CA access to beamline cameras
- **Python packages**: caproto ≥1.1, scipy ≥1.11, numpy ≥1.24, FastAPI, uvicorn, Pillow, websockets

## Risks and Considerations

| Risk | Mitigation |
|------|------------|
| Headless refactor complexity: ~22 Qt signal connections in `BeamController.__init__` must be replaced with plain Python dispatch | Incremental approach: first extract a `Dispatcher` interface, then implement headless variant. Existing test suite validates behavior preservation |
| 100% web feature parity is a large frontend effort (interactive ROI, projection overlays, trending charts in JS) | Use proven JS libraries: Canvas API for image + ROI, Chart.js or Plotly for projections and trending. Start with the image + projection core, add features incrementally |
| WebSocket bandwidth at 5-10 Hz for 1300x1038 frames | JPEG compression (quality=80) reduces frame size to ~50-100 KB. At 10 Hz = ~1 MB/s, well within local network capacity |
| EPICS CA broadcast behavior may differ with host networking | Test `caproto.threading.client.Context` in Docker with `--network=host` early. `EpicsWorker` already handles reconnection loops |
| OSPREY may not support custom panel registration | Investigate early; if not supported, implement config-based panel registration in OSPREY as a prerequisite |

## Stakeholders

- **Project Owner:** Thorsten Hellert
- **Developer:** Kirk Iliev (PyBeamViewer author, api-test branch)
