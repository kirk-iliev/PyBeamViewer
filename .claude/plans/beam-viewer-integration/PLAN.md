<!-- IMMUTABILITY CONSTRAINT
This document is an IMMUTABLE SPECIFICATION. It is written once during
planning and MUST NOT be modified by agents during execution.
All execution state is tracked via the native team task list.
-->

# Beam Viewer Integration — Execution Plan

> **Created:** 2026-04-09
> **Status:** Ready
> **Proposal:** See `PROPOSAL.md` in this directory

## Prerequisites

**Source repository:** `~/LBL/ML/PyBeamViewer` — cloned from `github.com/kirk-iliev/PyBeamViewer`, branch `api-test`.

```bash
git clone https://github.com/kirk-iliev/PyBeamViewer.git ~/LBL/ML/PyBeamViewer
cd ~/LBL/ML/PyBeamViewer && git checkout api-test
```

All Phase 1-2 headless work creates new files under `mcp_servers/beam_viewer/` in the als-profiles repo, copying and adapting code from `~/LBL/ML/PyBeamViewer/`. The Qt-independent modules (`analysis/`, `config/`, `core/state.py`, `api/schemas/`, `api/routes/`) are copied directly. The Qt-coupled modules (`core/controller.py`, `core/epics_layer.py`, `api/bridge.py`, `api/server.py`, `api/ws_manager.py`) are rewritten as headless variants.

## Technical Architecture

```
┌──────────────────────────── Container (port 8007, --network=host) ─────────────────────────────┐
│                                                                                                 │
│  ┌─ HeadlessController ──────────────────────┐  ┌─ FastAPI App ─────────────────────────────┐  │
│  │  CallbackDispatcher (event→callback map)   │  │  REST routes (11 groups)                  │  │
│  │  HeadlessEpicsWorker (threading.Thread)    │  │  WebSocket /frames/ws/stream (JPEG 5-10Hz)│  │
│  │  HeadlessAnalysisWorker (threading.Thread)  │  │  Static web panel (/panel)                │  │
│  │  AppState (RLock, unchanged)               │  │  MCP endpoint (/mcp via fastmcp)          │  │
│  │  TrendingBuffer (unchanged)                │  │  /health (ok | degraded)                  │  │
│  └────────────────────────────────────────────┘  └──────────────────────────────────────────┘  │
│                     │                                            │                              │
│              HeadlessBridge ──────────────────────────────────────┘                              │
│              (shared singleton, direct method calls)                                             │
│                     │                                                                           │
│  ┌─ Config ────────────────────────────┐                                                        │
│  │ BEAMVIEWER_CONFIG → config.json     │                                                        │
│  │ OSPREY_CONFIG → config.yml          │                                                        │
│  └─────────────────────────────────────┘                                                        │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
         │                           │                          │
    EPICS CA (host)           Web Browser (panel)         ALS Assistant (MCP)
```

**Data flow:** EPICS PV → HeadlessEpicsWorker → HeadlessController._on_new_frame → bg subtract → AnalysisWorker.queue_frame → analyze_frame() → callback → WS broadcast (JPEG) + trending append → HeadlessBridge → REST/MCP responses

**Reused unchanged:** `AppState`, `TrendingBuffer`, `analysis/` module, `config/` module (with env var patch), all `api/schemas/`, all `api/routes/`

**Headless rewrites:** `core/controller.py` → `headless_controller.py`, `core/epics_layer.py` → `headless_epics.py`, `api/bridge.py` → `headless_bridge.py`, `api/server.py` (modified), `api/ws_manager.py` (concurrent broadcast)

## Tasks

<!-- PLAN METADATA
max_parallelism: 6
critical_path_length: 9
total_tasks: 25
station_0_count: 12
station_1_plus_count: 13
-->

### Phase 0: Infrastructure

#### Task 0.1: scaffold-playwright-infrastructure
- **Description:** Install Playwright and create `tests/e2e/` with a `playwright.config.js` pointing to `http://localhost:8007/panel`. Create a minimal smoke test (`smoke.spec.js`) that loads the page and verifies it renders. Add `@playwright/test` to dev dependencies.
- **Phase:** infrastructure
- **Blocked By:** none
- **Blocks:** e2e-playwright-tests
- **Risk Tier:** 1
- **File Ownership:** `tests/e2e/`, `playwright.config.js`, `package.json`
- **Validation Gate:** `npx playwright --version && npx playwright test tests/e2e/smoke.spec.js --reporter=list`
- **Acceptance Gate:** N/A

### Phase 1: Headless Backend

#### Task 1.1: headless-epics-worker
- **Description:** Create `mcp_servers/beam_viewer/core/headless_epics.py` — a `threading.Thread` replacement for Qt's `EpicsWorker`. Reuse caproto dual-mode logic (native + tunnel) but replace `QThread` with `threading.Thread` and `pyqtSignal` with registered Python callbacks (`on_new_frame`, `on_connection_changed`, `on_error`). Keep module-level native context singleton and `epics_get()`/`epics_put()` one-shot functions.
- **Phase:** implementation
- **Blocked By:** none
- **Blocks:** headless-controller
- **Risk Tier:** 1
- **File Ownership:** `mcp_servers/beam_viewer/core/headless_epics.py`
- **Validation Gate:** `pytest mcp_servers/beam_viewer/tests/test_headless_epics.py -v`
- **Acceptance Gate:** N/A

#### Task 1.2: headless-analysis-worker
- **Description:** Create `mcp_servers/beam_viewer/core/headless_analysis.py` — a `threading.Thread` with `queue.Queue(maxsize=1)` replacing Qt's `AnalysisWorker`. Dequeues `FrameState`, calls `analyze_frame()`, invokes registered `on_analysis_done` callback. Drop-on-full semantics: stale frames discarded when queue is full.
- **Phase:** implementation
- **Blocked By:** none
- **Blocks:** headless-controller
- **Risk Tier:** 0
- **File Ownership:** `mcp_servers/beam_viewer/core/headless_analysis.py`
- **Validation Gate:** `pytest mcp_servers/beam_viewer/tests/test_headless_analysis.py -v`
- **Acceptance Gate:** N/A

#### Task 1.3: callback-dispatcher
- **Description:** Create `mcp_servers/beam_viewer/core/dispatcher.py` — lightweight event dispatcher replacing Qt signal/slot. Interface: `register(event, callback)`, `emit(event, *args)`. Thread-safe via `threading.Lock`. All ~22 Qt signal connections become `register()` calls. Synchronous callback invocation (matching Qt's direct connection within same thread).
- **Phase:** implementation
- **Blocked By:** none
- **Blocks:** headless-controller
- **Risk Tier:** 0
- **File Ownership:** `mcp_servers/beam_viewer/core/dispatcher.py`
- **Validation Gate:** `pytest mcp_servers/beam_viewer/tests/test_dispatcher.py -v`
- **Acceptance Gate:** N/A

#### Task 1.4: headless-controller
- **Description:** Create `mcp_servers/beam_viewer/core/headless_controller.py` — orchestration class replacing `BeamController` with zero Qt dependency. Wire `HeadlessEpicsWorker` and `HeadlessAnalysisWorker` via `CallbackDispatcher`. Replicate all logic: frame pipeline (bg subtraction, analysis queuing), streaming toggle, prefix switching, exposure/gain control (`epics_put`), background acquire/save/load, ROI, calibration, trending, overlay/crosshair state. Owns `AppState`, `TrendingBuffer`, workers.
- **Phase:** implementation
- **Blocked By:** headless-epics-worker, headless-analysis-worker, callback-dispatcher
- **Blocks:** headless-bridge
- **Risk Tier:** 2
- **File Ownership:** `mcp_servers/beam_viewer/core/headless_controller.py`
- **Validation Gate:** `pytest mcp_servers/beam_viewer/tests/test_headless_controller.py -v`
- **Acceptance Gate:** N/A

#### Task 1.5: headless-bridge
- **Description:** Create `mcp_servers/beam_viewer/api/headless_bridge.py` — API adapter with same method signatures as `ApiBridge` but calling `HeadlessController` directly instead of `QMetaObject.invokeMethod`. No Qt imports. Mutations go directly to controller (state protected by `AppState`'s `RLock`). Copy utility functions unchanged (`_nan_to_none`, `_ndarray_to_list`, `_frame_to_png_b64`).
- **Phase:** implementation
- **Blocked By:** headless-controller
- **Blocks:** headless-server-entry, jpeg-frame-encoding, mcp-tool-definitions
- **Risk Tier:** 1
- **File Ownership:** `mcp_servers/beam_viewer/api/headless_bridge.py`
- **Validation Gate:** `pytest mcp_servers/beam_viewer/tests/test_headless_bridge.py -v`
- **Acceptance Gate:** N/A

#### Task 1.6: headless-server-entry
- **Description:** Create `mcp_servers/beam_viewer/__main__.py` and update `api/server.py` for headless mode. Entry point: parse CLI args (host, port, config path), instantiate `HeadlessController` + `HeadlessBridge`, create FastAPI app with all existing routes (reuse `api/routes/` unchanged), start EPICS worker, run uvicorn. Serve web panel static files at `/panel`. No Qt imports.
- **Phase:** implementation
- **Blocked By:** headless-bridge
- **Blocks:** concurrent-ws-broadcast, degraded-health-endpoint, dockerfile-beam-viewer
- **Risk Tier:** 1
- **File Ownership:** `mcp_servers/beam_viewer/__main__.py`, `mcp_servers/beam_viewer/api/server.py`
- **Validation Gate:** `python -c "from beam_viewer.__main__ import main; print('OK')"`
- **Acceptance Gate:** N/A

### Phase 2: API Refinements

#### Task 2.1: jpeg-frame-encoding
- **Description:** Add `_frame_to_jpeg_b64(frame, quality=80)` to headless bridge. JPEG encoding via Pillow (~50-100 KB vs PNG ~200-500 KB). Update `build_ws_frame_payload()` to use JPEG for WebSocket streaming. Keep `_frame_to_png_b64` for REST `/frames/current` (lossless).
- **Phase:** implementation
- **Blocked By:** headless-bridge
- **Blocks:** ws-client-image-canvas
- **Risk Tier:** 0
- **File Ownership:** `mcp_servers/beam_viewer/api/headless_bridge.py`
- **Validation Gate:** `pytest mcp_servers/beam_viewer/tests/test_jpeg_encoding.py -v`
- **Acceptance Gate:** N/A

#### Task 2.2: concurrent-ws-broadcast
- **Description:** Refactor `ws_manager.py` `broadcast()`: replace sequential sends with `asyncio.gather(*[asyncio.wait_for(ws.send_json(payload), timeout=1.0)], return_exceptions=True)`. Evict connections whose send raised an exception. Prevents slow clients from blocking others.
- **Phase:** implementation
- **Blocked By:** headless-server-entry
- **Blocks:** dockerfile-beam-viewer
- **Risk Tier:** 0
- **File Ownership:** `mcp_servers/beam_viewer/api/ws_manager.py`
- **Validation Gate:** `pytest mcp_servers/beam_viewer/tests/test_ws_manager.py -v`
- **Acceptance Gate:** N/A

#### Task 2.3: degraded-health-endpoint
- **Description:** Modify `/health` in `server.py`: return `{"status": "degraded", "connected": false, "reason": "EPICS disconnected"}` when EPICS is down. Always HTTP 200. `status: ok` only when connected and streaming frames.
- **Phase:** implementation
- **Blocked By:** headless-server-entry
- **Blocks:** dockerfile-beam-viewer
- **Risk Tier:** 0
- **File Ownership:** `mcp_servers/beam_viewer/api/server.py`
- **Validation Gate:** `pytest mcp_servers/beam_viewer/tests/test_health.py -v`
- **Acceptance Gate:** N/A

#### Task 2.4: dual-config-support
- **Description:** Patch `config/config.py` to read `BEAMVIEWER_CONFIG` env var instead of hardcoded `Path(__file__).parent / "config.json"`. Fallback to original path if env var unset. Enables container volume-mounted config.
- **Phase:** implementation
- **Blocked By:** none
- **Blocks:** entrypoint-first-start, dockerfile-beam-viewer
- **Risk Tier:** 0
- **File Ownership:** `mcp_servers/beam_viewer/config/config.py`
- **Validation Gate:** `BEAMVIEWER_CONFIG=/dev/null python -c "from beam_viewer.config.config import load_config; print('OK')" 2>&1 | grep -q OK`
- **Acceptance Gate:** N/A

### Phase 3: MCP Tools

#### Task 3.1: mcp-tool-definitions
- **Description:** Create `mcp_servers/beam_viewer/tools.py` with fastmcp tools calling `HeadlessBridge` directly. Tools: `beam_capture`, `beam_status`, `beam_set_camera`, `beam_set_exposure`, `beam_set_gain`, `beam_analysis`, `beam_roi_set`, `beam_roi_clear`, `beam_roi_center`, `beam_background_acquire`, `beam_background_toggle`, `beam_trending`, `beam_calibration`, `beam_drift`, `beam_config`. Follow `mcp_servers/phoebus/tools.py` pattern.
- **Phase:** implementation
- **Blocked By:** headless-bridge
- **Blocks:** beam-viewer-skill, mcp-integration-tests
- **Risk Tier:** 1
- **File Ownership:** `mcp_servers/beam_viewer/tools.py`
- **Validation Gate:** `python -c "from beam_viewer.tools import *; print('OK')"`
- **Acceptance Gate:** N/A

### Phase 4: Web Frontend

#### Task 4.1: ws-client-image-canvas
- **Description:** Create `mcp_servers/beam_viewer/static/index.html` — web panel entry point. WebSocket client for `/frames/ws/stream`, render JPEG frames on HTML Canvas with colormap support (apply via lookup table on grayscale data). Colormap selector dropdown. Reconnection on WS close. Connection status indicator + FPS counter. Self-contained HTML/JS/CSS.
- **Phase:** implementation
- **Blocked By:** jpeg-frame-encoding
- **Blocks:** projection-plots, interactive-roi, control-panel-ui, trending-panel, overlay-crosshair-drift, error-states-ui, theme-toggle
- **Risk Tier:** 2
- **File Ownership:** `mcp_servers/beam_viewer/static/`
- **Validation Gate:** `manual: open http://localhost:8007/panel, verify live image with colormap`
- **Acceptance Gate:** `manual: live beam image displays, colormap selector works, matches Qt quality`

#### Task 4.2: projection-plots
- **Description:** Add H/V projection plot components. Render 1D arrays from WebSocket `projections` payload as line charts. Overlay Gaussian fit curves from `analysis` payload. Show fit parameters (σ, centroid, amplitude) as labels. Use Chart.js or canvas-based plotting.
- **Phase:** implementation
- **Blocked By:** ws-client-image-canvas
- **Blocks:** none
- **Risk Tier:** 1
- **File Ownership:** `mcp_servers/beam_viewer/static/js/projections.js`
- **Validation Gate:** `manual: projections render with Gaussian overlay`
- **Acceptance Gate:** `manual: side-by-side with Qt — fit curves match`

#### Task 4.3: interactive-roi
- **Description:** Click-drag ROI on image canvas. Send `POST /roi` with `{x0, y0, x1, y1}` on release. Render ROI rectangle overlay. Clear/Center buttons via `DELETE /roi` and `POST /roi/center`. Secondary cropped image panel with ROI projections when active.
- **Phase:** implementation
- **Blocked By:** ws-client-image-canvas
- **Blocks:** overlay-crosshair-drift
- **Risk Tier:** 2
- **File Ownership:** `mcp_servers/beam_viewer/static/js/roi.js`
- **Validation Gate:** `manual: draw ROI, verify rectangle renders, clear/center work`
- **Acceptance Gate:** `manual: side-by-side with Qt ROI — draw, resize, clear, center match`

#### Task 4.4: control-panel-ui
- **Description:** Right-side control panel matching Qt ControlPanel. Sections: Camera (prefix dropdown, exposure/gain spinboxes), Acquisition (Stream/Fit Full/Fit ROI toggles), Background (Acquire, Subtraction toggle, Save, Load with file list), Display (colormap, crosshair toggle). Controls call corresponding REST endpoints. Read-back from WebSocket keeps controls in sync.
- **Phase:** implementation
- **Blocked By:** ws-client-image-canvas
- **Blocks:** none
- **Risk Tier:** 1
- **File Ownership:** `mcp_servers/beam_viewer/static/js/controls.js`
- **Validation Gate:** `manual: all controls render and fire correct API calls`
- **Acceptance Gate:** `manual: side-by-side with Qt control panel — all controls present`

#### Task 4.5: trending-panel
- **Description:** Toggleable trending panel with 8 time-series charts (σ_x, σ_y, centroid_x, centroid_y, roi_σ_x, roi_σ_y, drift_x, drift_y). Fetch from `GET /trending/history`. Depth control spinbox (50-2000, `POST /trending/depth`). Chart.js or similar for line charts with scrolling x-axis.
- **Phase:** implementation
- **Blocked By:** ws-client-image-canvas
- **Blocks:** none
- **Risk Tier:** 1
- **File Ownership:** `mcp_servers/beam_viewer/static/js/trending.js`
- **Validation Gate:** `manual: 8 charts render, depth control works`
- **Acceptance Gate:** `manual: side-by-side with Qt trending — data matches`

#### Task 4.6: overlay-crosshair-drift
- **Description:** Projection overlay rendering on image canvas (H/V curves on 2D image, configurable side/scale). Crosshair at centroid reference. Drift labels (Δx/Δy in px and µm). Controls: H/V toggles + side selectors, scale slider, show-full/show-roi, crosshair toggle. Read from `GET /overlays`, update via `POST /overlays`.
- **Phase:** implementation
- **Blocked By:** ws-client-image-canvas, interactive-roi
- **Blocks:** none
- **Risk Tier:** 2
- **File Ownership:** `mcp_servers/beam_viewer/static/js/overlays.js`
- **Validation Gate:** `manual: projection overlays render, crosshair shows at reference`
- **Acceptance Gate:** `manual: side-by-side with Qt — overlays and crosshair match`

#### Task 4.7: error-states-ui
- **Description:** Error states matching Qt: EPICS disconnect → "Disconnected" banner, freeze frame, gray controls. Fit failure → "Fit failed" in projection plots. No camera → empty state with message. Detect from WebSocket payload and `/health`.
- **Phase:** implementation
- **Blocked By:** ws-client-image-canvas
- **Blocks:** none
- **Risk Tier:** 1
- **File Ownership:** `mcp_servers/beam_viewer/static/js/errors.js`
- **Validation Gate:** `manual: disconnect EPICS, verify disconnected state renders`
- **Acceptance Gate:** `manual: side-by-side with Qt error states — all match`

#### Task 4.8: theme-toggle
- **Description:** Dark/light theme toggle matching Qt Theme system. CSS custom properties for theme colors. Default dark. Toggle button calls `POST /display/theme/toggle`. Apply to all components: canvas bg, chart colors, controls, text.
- **Phase:** implementation
- **Blocked By:** ws-client-image-canvas
- **Blocks:** e2e-playwright-tests
- **Risk Tier:** 0
- **File Ownership:** `mcp_servers/beam_viewer/static/css/theme.css`, `mcp_servers/beam_viewer/static/js/theme.js`
- **Validation Gate:** `manual: toggle theme, all components update`
- **Acceptance Gate:** `manual: side-by-side with Qt themes — colors match`

### Phase 5: Container + Deployment

#### Task 5.1: dockerfile-beam-viewer
- **Description:** Create `docker/Dockerfile.beam-viewer` following `Dockerfile.phoebus` pattern. Base: `python:3.12-slim`. Install: caproto, scipy, numpy, FastAPI, uvicorn, Pillow, fastmcp, websockets. Copy source, defaults, static files. Env: `MCP_TRANSPORT=http`, `MCP_PORT=8007`, `BEAMVIEWER_CONFIG`, `OSPREY_CONFIG`, `PYTHONPATH=/app`.
- **Phase:** infrastructure
- **Blocked By:** headless-server-entry, jpeg-frame-encoding, concurrent-ws-broadcast, degraded-health-endpoint, dual-config-support, mcp-tool-definitions
- **Blocks:** docker-compose-service
- **Risk Tier:** 1
- **File Ownership:** `docker/Dockerfile.beam-viewer`
- **Validation Gate:** `docker build -f docker/Dockerfile.beam-viewer -t beam-viewer-test . && echo OK`
- **Acceptance Gate:** N/A

#### Task 5.2: entrypoint-first-start
- **Description:** Create `mcp_servers/beam_viewer/entrypoint.sh` — copy `/app/config.default/config.json` to `/app/config/` if missing, create `backgrounds/` dir, then `exec python -m beam_viewer "$@"`. Update Dockerfile: `COPY entrypoint.sh`, `ENTRYPOINT`.
- **Phase:** infrastructure
- **Blocked By:** dockerfile-beam-viewer, dual-config-support
- **Blocks:** docker-compose-service
- **Risk Tier:** 0
- **File Ownership:** `mcp_servers/beam_viewer/entrypoint.sh`, `docker/Dockerfile.beam-viewer`
- **Validation Gate:** `bash -n mcp_servers/beam_viewer/entrypoint.sh`
- **Acceptance Gate:** N/A

#### Task 5.3: docker-compose-service
- **Description:** Add `beam-viewer` to `docker-compose.yml`: image `${REGISTRY}/mcp-beam-viewer:latest`, build `docker/Dockerfile.beam-viewer`, port `0.0.0.0:8007:8007`, network `als-net`, volume `./beam-viewer-data:/app/config`, env_file `.env.production`. Add to `docker-compose.host.yml`: `network_mode: host`.
- **Phase:** infrastructure
- **Blocked By:** dockerfile-beam-viewer, entrypoint-first-start
- **Blocks:** profile-yaml-registration, mcp-integration-tests, e2e-playwright-tests
- **Risk Tier:** 1
- **File Ownership:** `docker-compose.yml`, `docker-compose.host.yml`
- **Validation Gate:** `docker-compose config --quiet`
- **Acceptance Gate:** N/A

#### Task 5.4: profile-yaml-registration
- **Description:** Register in profile YAMLs. `als-base.yml`: add `beam-viewer` to `web_panels`, add `beam_viewer` to `mcp_servers` with tool permissions, add `web.panels.beam-viewer.label: "BEAM"`. `als-prod.yml`: add panel URL `http://localhost:8007`, health endpoint, MCP URL `http://localhost:8007/mcp`. `als-client.yml`: add MCP URL `http://appsdev2:8007/mcp`, panel URL `http://appsdev2:8007`.
- **Phase:** infrastructure
- **Blocked By:** docker-compose-service
- **Blocks:** none
- **Risk Tier:** 1
- **File Ownership:** `als-base.yml`, `als-prod.yml`, `als-client.yml`
- **Validation Gate:** `python -c "import yaml; [yaml.safe_load(open(f)) for f in ('als-base.yml','als-prod.yml','als-client.yml')]; print('OK')"`
- **Acceptance Gate:** `manual: OSPREY build succeeds with updated profiles`

### Phase 6: Agent Skill

#### Task 6.1: beam-viewer-skill
- **Description:** Create `overlays/skills/beam-viewer/SKILL.md` teaching the agent beam viewer MCP tool workflows: beam diagnostic, camera setup, beam optimization (ROI + trending), background subtraction, drift monitoring. Include reference docs with tool descriptions and example workflows. Register in `als-base.yml` overlay section.
- **Phase:** implementation
- **Blocked By:** mcp-tool-definitions
- **Blocks:** none
- **Risk Tier:** 1
- **File Ownership:** `overlays/skills/beam-viewer/`, `als-base.yml`
- **Validation Gate:** `test -f overlays/skills/beam-viewer/SKILL.md`
- **Acceptance Gate:** `manual: agent invokes skill and completes beam diagnostic workflow`

### Phase 7: Integration + Validation

#### Task 7.1: mcp-integration-tests
- **Description:** Create `tests/integration/test_beam_viewer.py` following existing pattern. Test all MCP tools return valid responses with expected schema. Include health check test for ok and degraded states.
- **Phase:** testing
- **Blocked By:** mcp-tool-definitions, docker-compose-service
- **Blocks:** side-by-side-validation
- **Risk Tier:** 1
- **File Ownership:** `tests/integration/test_beam_viewer.py`
- **Validation Gate:** `pytest tests/integration/test_beam_viewer.py -v`
- **Acceptance Gate:** N/A

#### Task 7.2: e2e-playwright-tests
- **Description:** Create `tests/e2e/beam-viewer.spec.js` — Playwright E2E tests for web panel. Cover: page load, image canvas, colormap, projections, ROI draw/clear/center, controls, trending, background, overlays, crosshair, theme, error states.
- **Phase:** testing
- **Blocked By:** scaffold-playwright-infrastructure, theme-toggle, docker-compose-service
- **Blocks:** side-by-side-validation
- **Risk Tier:** 2
- **File Ownership:** `tests/e2e/beam-viewer.spec.js`
- **Validation Gate:** `npx playwright test tests/e2e/beam-viewer.spec.js --reporter=list`
- **Acceptance Gate:** N/A

#### Task 7.3: side-by-side-validation
- **Description:** Run Qt app and web panel on same camera. Screenshot every feature side-by-side: image, projections, ROI, trending, background, overlays, crosshair/drift, error states, theme. Create `docs/beam-viewer-validation/` with comparison screenshots.
- **Phase:** testing
- **Blocked By:** mcp-integration-tests, e2e-playwright-tests
- **Blocks:** none
- **Risk Tier:** 1
- **File Ownership:** `docs/beam-viewer-validation/`
- **Validation Gate:** `ls docs/beam-viewer-validation/*.png | wc -l`
- **Acceptance Gate:** `manual: all features pass side-by-side comparison with Qt`

## Testing Strategy

**Unit tests** (Phase 1-2): Port existing API tests to headless backend. New tests for HeadlessEpicsWorker, HeadlessAnalysisWorker, CallbackDispatcher, HeadlessController, HeadlessBridge. JPEG encoding, concurrent broadcast, health states, config env var.

**Integration tests** (Phase 7): MCP tool endpoints against running container. Health check ok/degraded. Follow `tests/integration/` pytest pattern.

**E2E browser tests** (Phase 7): Playwright against running web panel. All interactive features, error state simulation.

**Acceptance**: Side-by-side visual comparison Qt ↔ web, documented with screenshots.

## Success Criteria

- [ ] Container builds and `/health` returns ok (or degraded without EPICS)
- [ ] Every Qt feature has working web panel equivalent (documented screenshots)
- [ ] WebSocket streaming ≥5 Hz with JPEG frames <150 KB
- [ ] Agent completes beam diagnostic workflow via skill
- [ ] All unit, integration, and E2E tests pass
- [ ] Container image ~250-300 MB (no Qt/X11)

## Dependency Graph

```
Phase 0             Phase 1                     Phase 2           Phase 3
──────              ──────                      ──────            ──────
0.1 scaffold ──────────────────────────────────────────────────────────────┐
                                                                           │
1.1 epics ──────┐                                                          │
1.2 analysis ───┼── 1.4 ctrl ── 1.5 bridge ──┬── 1.6 server ──┐          │
1.3 dispatch ───┘                             │                 │          │
                                              ├── 2.1 jpeg ────┼───┐      │
                                              │                 │   │      │
                                              └── 3.1 mcp ─────┼─┐ │      │
                                                                │ │ │      │
2.4 config ────────────────────────────────────────────────┐    │ │ │      │
                                               2.2 ws-bc ──┤   │ │ │      │
                                               2.3 health ─┤   │ │ │      │
                                                            │   │ │ │      │
Phase 4                Phase 5           Phase 6  Phase 7   │   │ │ │      │
──────                 ──────            ──────   ──────    │   │ │ │      │
                       5.1 docker ◄─────────────────────────┘   │ │ │      │
4.1 canvas ◄────────────────────────────────────────────────────┘ │ │      │
├── 4.2 projections    5.2 entry ◄── 5.1                    │     │ │      │
├── 4.3 roi            5.3 compose ◄── 5.1, 5.2             │     │ │      │
├── 4.4 controls       5.4 profile ◄── 5.3                  │     │ │      │
├── 4.5 trending                                             │     │ │      │
├── 4.6 overlays ◄ 4.3                6.1 skill ◄── 3.1 ────┘     │ │      │
├── 4.7 errors                                                     │ │      │
└── 4.8 theme ─────────────────────────────────────────────────────┼─┼──────┤
                                                                   │ │      │
                                       7.1 mcp-tests ◄── 3.1, 5.3 ┘ │      │
                                       7.2 e2e ◄── 4.8, 5.3, 0.1 ───┘      │
                                       7.3 validation ◄── 7.1, 7.2 ─────────┘
```
