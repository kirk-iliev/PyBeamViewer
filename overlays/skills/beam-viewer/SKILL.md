---
name: beam-viewer
description: "Beam viewer REST API for camera diagnostics — beam capture and analysis, camera setup, ROI-based beam optimization with trending, background subtraction and persistence, drift monitoring with centroid references, streaming control, display settings (colormap, theme, overlays), frame data access, and configuration management. Use when the user asks to view a beam profile, check beam size, optimize beam, monitor drift, set up a camera, acquire/save/load backgrounds, pause or resume streaming, change colormap or theme, set a centroid reference, read frame data or projections, adjust overlays, or any beam diagnostic task. Also use when interacting with the PyBeamViewer web panel or its REST API."
trigger: beam viewer, beam profile, beam size, beam capture, sigma, centroid, ROI, drift, background subtraction, camera, exposure, gain, beam diagnostic, beam optimization, trending, streaming, colormap, crosshair, centroid reference, projection, overlay, web panel
user_invocable: true
---

# Beam Viewer

Operate the PyBeamViewer camera diagnostic system via its REST API. The beam viewer captures live images from EPICS area detector cameras, performs Gaussian fitting to extract beam parameters (sigma, centroid, amplitude), and supports ROI analysis, background subtraction with persistence, drift tracking, trending, and full display control.

**Repository:** `~/LBL/ML/PyBeamViewer`
**Web panel:** Served at `/panel/` (port 8007 in Docker, 8765 desktop)
**Interactive API docs:** `/docs` (Swagger UI) or `/redoc`

## Architecture

The system runs in two modes — both expose the same REST API and web panel:

| Mode | Entry point | GUI | API port |
|------|------------|-----|----------|
| **Desktop** (PyQt5) | `python main.py` | Qt window + web panel | 8765 |
| **Headless** (container) | Docker | Web panel only | 8007 |

Data flow: `EpicsWorker` → `Controller` → `AnalysisWorker` → `AppState` → REST API / WebSocket / Panel

## How to call the API

All interactions use HTTP requests via curl. Base URL depends on deployment:
- **Desktop:** `http://localhost:8765`
- **Container/prod:** `http://localhost:8007`
- **Client:** `http://appsdev2:8007`

Pattern for reads:
```bash
curl -s http://localhost:8007/analysis
```

Pattern for writes:
```bash
curl -s -X POST http://localhost:8007/camera/exposure \
  -H "Content-Type: application/json" \
  -d '{"value": 0.05}'
```

## REST API — Complete Reference

### Status & Health

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `GET` | `/health` | Server status, streaming state, connection, frame count, WS clients |
| `GET` | `/streaming` | Streaming state: `{streaming, connected, frame_count}` |
| `POST` | `/streaming` | Start/pause: `{"streaming": true}` |

### Camera

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `GET` | `/camera` | Current PV config (prefix, PV names, host, port) |
| `POST` | `/camera/prefix` | Switch camera: `{"prefix": "BL72"}` |
| `POST` | `/camera/exposure` | Set exposure (seconds): `{"value": 0.05}` |
| `POST` | `/camera/gain` | Set gain: `{"value": 5}` |

### Analysis

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `GET` | `/analysis` | Fit results: sigma, centroid, amplitude, residual per axis |
| `POST` | `/analysis/fit-full` | Toggle full-frame fitting: `{"enabled": true}` |
| `POST` | `/analysis/fit-roi` | Toggle ROI fitting: `{"enabled": true}` |

### ROI (Region of Interest)

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `GET` | `/roi` | Current ROI state |
| `POST` | `/roi` | Set ROI rectangle: `{"x0": 100, "y0": 100, "x1": 300, "y1": 300}` |
| `DELETE` | `/roi` | Clear ROI |
| `POST` | `/roi/center` | Center ROI on current centroid |

### Background

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `GET` | `/background` | Status: `{has_background, subtraction_enabled}` |
| `POST` | `/background/acquire` | Capture next frame as background |
| `POST` | `/background/subtraction` | Toggle subtraction: `{"enabled": true}` |
| `POST` | `/background/save` | Save background to `.npy` file |
| `POST` | `/background/load` | Load saved background: `{"path": "..."}` |
| `GET` | `/background/list` | List saved background files |

### Centroid & Drift

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `GET` | `/centroid` | Reference, live position, drift (px and um) |
| `POST` | `/centroid/crosshair` | Toggle crosshair overlay: `{"enabled": true}` |
| `POST` | `/centroid/reference` | Set reference position: `{"x": 150.0, "y": 200.0}` |
| `DELETE` | `/centroid/reference` | Clear centroid reference |

### Display

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `GET` | `/display/theme` | Current theme |
| `POST` | `/display/theme/toggle` | Toggle dark/light |
| `GET` | `/display/colormap` | Current colormap + available options |
| `POST` | `/display/colormap` | Set colormap: `{"name": "viridis"}` |

Available colormaps: `hot`, `viridis`, `inferno`, `plasma`, `magma`, `cividis`, `gray`

### Overlays

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `GET` | `/overlays` | Current projection overlay settings |
| `POST` | `/overlays` | Update (partial): `{"h_enabled": true, "h_side": "bottom", "scale": 0.3}` |

Fields: `h_enabled`, `h_side` (`"bottom"`/`"top"`), `v_enabled`, `v_side` (`"left"`/`"right"`), `scale` (0.05-0.50), `show_full`, `show_roi`.

### Trending

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `GET` | `/trending` | Config: `{visible, depth}` |
| `POST` | `/trending/depth` | Set history depth (50-2000): `{"depth": 500}` |
| `GET` | `/trending/history` | Full buffer: arrays of sigma, centroid, drift per frame |

### Frames

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `GET` | `/frames/metadata` | Frame number, FPS, dimensions, dtype |
| `GET` | `/frames/current` | Current frame as base64 PNG + metadata |
| `GET` | `/frames/projections` | Full-image X/Y projection arrays |
| `GET` | `/frames/roi` | ROI crop: image + projections + fit |

### Config

| Method | Endpoint | What it does |
|--------|----------|-------------|
| `GET` | `/config` | Active prefix, available prefixes, EPICS settings |
| `GET` | `/config/prefix/{prefix}` | PV and calibration info for a specific prefix |
| `GET` | `/config/calibration` | Calibration for active camera |

## WebSocket Streaming

Connect to `ws://<host>:<port>/frames/ws/stream` for real-time frame updates.

Each message is JSON:
```
{
  type: "frame",
  frame_number, timestamp, fps, colormap,
  frame_jpeg_b64,
  projections: {x_projection: [...], y_projection: [...]},
  analysis: {fit_full_enabled, fit_roi_enabled, x_fit, y_fit, roi_x_fit, roi_y_fit},
  roi: {active, roi: {x0,y0,x1,y1}, x_projection, y_projection},
  drift: {has_reference, drift_x, drift_y, ...},
  streaming: true/false,
  background: {has_background, subtraction_enabled}
}
```

Keepalive: `{"type": "keepalive"}` after 30s of silence. Send `"ping"` to get `{"type": "pong"}`.

## Web Panel Controls

Every control on the web panel at `/panel/` maps to a REST endpoint:

### Camera Setup section
| Control | API call |
|---------|----------|
| Camera dropdown | `POST /camera/prefix {"prefix": "BL72"}` |
| Exposure input + Set | `POST /camera/exposure {"value": 0.05}` |
| Gain input + Set | `POST /camera/gain {"value": 5}` |

### Acquire section
| Control | API call |
|---------|----------|
| Streaming toggle | `POST /streaming {"streaming": true/false}` |
| Acquire Background | `POST /background/acquire` |
| Background Sub toggle | `POST /background/subtraction {"enabled": true/false}` |
| Save BG | `POST /background/save` |
| Load BG → file list | `GET /background/list` then `POST /background/load {"path": "..."}` |

### Analysis section
| Control | API call |
|---------|----------|
| Fit Full Image toggle | `POST /analysis/fit-full {"enabled": true/false}` |
| Fit ROI toggle | `POST /analysis/fit-roi {"enabled": true/false}` |
| Clear ROI | `DELETE /roi` |
| Center ROI | `POST /roi/center` |
| Show Centroid Ref toggle | `POST /centroid/crosshair {"enabled": true/false}` |
| Set Reference | `POST /centroid/reference {"x": ..., "y": ...}` |

### Image Settings section
| Control | API call |
|---------|----------|
| Colormap dropdown | `POST /display/colormap {"name": "viridis"}` |

### Status bar
| Control | API call |
|---------|----------|
| Theme toggle | `POST /display/theme/toggle` |

### Canvas
| Interaction | API call |
|-------------|----------|
| Click-drag on image | `POST /roi {"x0":..., "y0":..., "x1":..., "y1":...}` |

## Workflows

### 1. Quick Beam Check

```bash
# Verify connected and streaming
curl -s http://localhost:8007/streaming
# Get beam size and position
curl -s http://localhost:8007/analysis
# Check calibration for micron values
curl -s http://localhost:8007/config/calibration
# Grab snapshot
curl -s http://localhost:8007/frames/current
```

Interpreting `GET /analysis` results:
- **sigma**: beam RMS width. `x_fit.sigma` (px), `x_fit.sigma_um` (microns if calibrated)
- **centroid**: beam center. Large offset from frame center → possible steering error
- **amplitude**: peak intensity. Low amplitude + high offset → poor SNR
- **success=false**: fit failed — beam may be clipped, saturated, or absent

### 2. Camera Setup

```bash
# List available cameras
curl -s http://localhost:8007/config
# Switch to BL72
curl -s -X POST http://localhost:8007/camera/prefix -H "Content-Type: application/json" -d '{"prefix": "BL72"}'
# Set exposure to 20ms
curl -s -X POST http://localhost:8007/camera/exposure -H "Content-Type: application/json" -d '{"value": 0.02}'
# Set gain
curl -s -X POST http://localhost:8007/camera/gain -H "Content-Type: application/json" -d '{"value": 5}'
# Verify image
curl -s http://localhost:8007/frames/current
```

### 3. ROI Optimization + Trending

```bash
# Find current centroid
curl -s http://localhost:8007/analysis
# Place ROI around beam (centroid +/- 50px)
curl -s -X POST http://localhost:8007/roi -H "Content-Type: application/json" -d '{"x0": 600, "y0": 470, "x1": 700, "y1": 570}'
# Fine-tune centering
curl -s -X POST http://localhost:8007/roi/center
# Enable ROI fitting
curl -s -X POST http://localhost:8007/analysis/fit-roi -H "Content-Type: application/json" -d '{"enabled": true}'
# Monitor stability
curl -s http://localhost:8007/trending/history
# Clear when done
curl -s -X DELETE http://localhost:8007/roi
```

ROI sizing: box should be ~3-4x beam sigma. Too tight clips tails; too loose includes noise.

### 4. Background Subtraction (Full Lifecycle)

```bash
# [block beam or close shutter]
# Acquire dark frame
curl -s -X POST http://localhost:8007/background/acquire
# Enable subtraction
curl -s -X POST http://localhost:8007/background/subtraction -H "Content-Type: application/json" -d '{"enabled": true}'
# [restore beam]
# Verify improved fit
curl -s http://localhost:8007/analysis

# Save to disk for later
curl -s -X POST http://localhost:8007/background/save
# List saved files
curl -s http://localhost:8007/background/list
# Load a saved background
curl -s -X POST http://localhost:8007/background/load -H "Content-Type: application/json" -d '{"path": "/path/to/file.npy"}'
```

Always acquire fresh background when changing camera, exposure, or gain.

### 5. Drift Monitoring (Full Lifecycle)

```bash
# Confirm beam at desired position
curl -s http://localhost:8007/analysis
# Set reference (use centroid values from analysis)
curl -s -X POST http://localhost:8007/centroid/reference -H "Content-Type: application/json" -d '{"x": 650.2, "y": 519.0}'
# Show crosshair on panel
curl -s -X POST http://localhost:8007/centroid/crosshair -H "Content-Type: application/json" -d '{"enabled": true}'
# Monitor drift
curl -s http://localhost:8007/centroid
# View drift history
curl -s http://localhost:8007/trending/history
# Clear reference when done
curl -s -X DELETE http://localhost:8007/centroid/reference
```

### 6. Display Configuration

```bash
# Change colormap
curl -s -X POST http://localhost:8007/display/colormap -H "Content-Type: application/json" -d '{"name": "viridis"}'
# Toggle theme
curl -s -X POST http://localhost:8007/display/theme/toggle
# Enable projection overlays
curl -s -X POST http://localhost:8007/overlays -H "Content-Type: application/json" -d '{"h_enabled": true, "h_side": "bottom", "v_enabled": true, "v_side": "left", "scale": 0.25}'
```

### 7. Visual Analysis with Screenshots

Use multimodal reasoning to analyze beam images beyond what Gaussian fitting provides — spot finding, pattern recognition, saturation detection, halo detection.

**Option A: Analyze the raw beam image**

```bash
# Get current frame as base64 PNG
curl -s http://localhost:8007/frames/current
```

The returned `image_b64_png` can be examined visually to identify satellites, halos, saturation, asymmetric profiles, or artifacts.

**Option B: Screenshot the full web panel (Playwright)**

```
1. browser_navigate to http://localhost:8007/panel/
2. browser_wait_for the canvas
3. browser_take_screenshot → full panel with projections, fits, trending
4. Read the screenshot for visual analysis
```

This captures projections with Gaussian fit curves, ROI overlay, trending charts — useful for verifying fit quality visually.

**Option C: Analyze the ROI crop**

```bash
curl -s http://localhost:8007/frames/roi
```

Returns ROI crop as base64 PNG + projections + fit results.

## Response Schema Reference

### GET /analysis
```json
{
  "fit_full_enabled": true,
  "fit_roi_enabled": false,
  "x_fit": {
    "success": true,
    "sigma": 12.3,          "sigma_um": 45.6,
    "centroid": 256.7,      "centroid_um": 950.2,
    "amplitude": 4200.0,    "offset": 120.0,
    "residual": 0.02,       "unit_label": "um"
  },
  "y_fit": { "..." }
}
```

### GET /trending/history
```json
{
  "count": 87,
  "frame_number": [1, 2, "..."],
  "sigma_x": ["..."],       "sigma_y": ["..."],
  "centroid_x": ["..."],    "centroid_y": ["..."],
  "roi_sigma_x": ["..."],   "roi_sigma_y": ["..."],
  "drift_x": ["..."],       "drift_y": ["..."]
}
```

### GET /centroid
```json
{
  "has_reference": true,
  "crosshair_enabled": true,
  "reference": {"x": 256.0, "y": 200.0},
  "live": {"x": 257.2, "y": 199.8},
  "drift_x": 1.2,           "drift_y": -0.2,
  "drift_x_um": 4.44,       "drift_y_um": -0.74
}
```

## Calibration

Two methods configured per camera in `config/config.json`:

| Method | How it works | Example |
|--------|-------------|---------|
| **fixed** | Single um/pixel factor | BL31: 1.8852 um/px |
| **pinhole** | Pinhole camera geometry | BL72 |
| **none** | No calibration — pixels only | — |

When calibrated, fit results include both pixel and micron values (`sigma` + `sigma_um`).

## Error Handling

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request (invalid params, precondition not met) |
| 404 | Not found (unknown prefix) |
| 422 | Validation error |
| 500 | Internal server error |

Success mutations return `{"ok": true, "message": "..."}`. Errors return `{"detail": "..."}`.
