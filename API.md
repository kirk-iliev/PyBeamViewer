# PyBeamViewer REST API

PyBeamViewer includes a built-in FastAPI server that exposes 100% of the viewer's
functionality over HTTP and WebSocket. The API starts automatically alongside the
GUI on `http://127.0.0.1:8765`.

Interactive docs are available at `http://127.0.0.1:8765/docs` (Swagger UI) and
`http://127.0.0.1:8765/redoc` (ReDoc).

---

## Architecture

```
 FastAPI thread (daemon)                Qt main thread
        |                                     |
    API routes --> ApiBridge ---------> Signals / QMetaObject.invokeMethod
        |              |                      |
    reads <----- AppState (RLock) <---- Controller / State / Window
        |
    WebSocket <-- schedule_ws_broadcast <-- controller._on_analysis_done
```

The API server runs in a **daemon thread** with its own asyncio event loop,
completely independent of the Qt event loop on the main thread.

### Thread safety model

| Operation | Mechanism |
|-----------|-----------|
| **Reads** (frame data, fit results, config) | Direct access to `AppState`, which protects all mutable fields with an `RLock` |
| **Mutations** (set exposure, change colormap, toggle streaming) | Dispatched to the Qt main thread via `QMetaObject.invokeMethod` with `Qt.QueuedConnection`, or by emitting Qt signals (which are automatically queued across threads) |
| **WebSocket broadcast** | Controller calls `schedule_ws_broadcast()` on the main thread, which posts a `loop.create_task` to the API event loop via `call_soon_threadsafe` |

### Key files

| File | Role |
|------|------|
| `api/bridge.py` | `ApiBridge` -- single adapter between routes and Qt. All thread-crossing logic lives here. |
| `api/server.py` | FastAPI app factory, uvicorn daemon thread launcher, WebSocket broadcast scheduler |
| `api/ws_manager.py` | WebSocket connection manager with broadcast and dead-client cleanup |
| `api/dependencies.py` | FastAPI dependency injection for the `ApiBridge` singleton |
| `api/schemas/` | Pydantic request/response models for all endpoints |
| `api/routes/` | Route handlers organized by domain (camera, streaming, analysis, etc.) |

---

## Endpoints

### Health

```
GET /health
```

Returns server status, streaming state, connection state, frame count, and
number of connected WebSocket clients.

---

### Camera

```
GET  /camera                Get current camera PV configuration
POST /camera/prefix         Switch to a different camera prefix
POST /camera/exposure       Set camera exposure time (seconds)
POST /camera/gain           Set camera gain
```

**Switch camera:**
```bash
curl -X POST http://localhost:8765/camera/prefix \
  -H "Content-Type: application/json" \
  -d '{"prefix": "BL72"}'
```

**Set exposure:**
```bash
curl -X POST http://localhost:8765/camera/exposure \
  -H "Content-Type: application/json" \
  -d '{"value": 0.05}'
```

**Set gain:**
```bash
curl -X POST http://localhost:8765/camera/gain \
  -H "Content-Type: application/json" \
  -d '{"value": 5}'
```

---

### Streaming

```
GET  /streaming             Get streaming status (streaming, connected, frame_count)
POST /streaming             Start or pause frame streaming
```

**Pause streaming:**
```bash
curl -X POST http://localhost:8765/streaming \
  -H "Content-Type: application/json" \
  -d '{"streaming": false}'
```

---

### Background Subtraction

```
GET  /background            Get background status (has_background, subtraction_enabled)
POST /background/acquire    Capture next frame as background reference
POST /background/subtraction Enable/disable background subtraction
POST /background/save       Save current background to disk (.npy)
POST /background/load       Load a saved background file
GET  /background/list       List all saved background files for the active prefix
```

**Acquire and enable subtraction:**
```bash
curl -X POST http://localhost:8765/background/acquire
curl -X POST http://localhost:8765/background/subtraction \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

**List and load a saved background:**
```bash
# List available backgrounds
curl http://localhost:8765/background/list

# Load one (path must be inside the backgrounds/ directory)
curl -X POST http://localhost:8765/background/load \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/config/backgrounds/BL72_20240101_120000.npy"}'
```

---

### Analysis

```
GET  /analysis              Get fit status and results (sigma, centroid, amplitude per axis)
POST /analysis/fit-full     Enable/disable Gaussian fitting on the full image
POST /analysis/fit-roi      Enable/disable Gaussian fitting on the ROI
```

**Get current fit results:**
```bash
curl http://localhost:8765/analysis
```

Response:
```json
{
  "fit_full_enabled": true,
  "fit_roi_enabled": false,
  "x_fit": {
    "success": true,
    "sigma": 12.34,
    "sigma_um": 23.27,
    "centroid": 150.2,
    "centroid_um": 283.1,
    "amplitude": 4500.0,
    "offset": 100.0,
    "residual": 0.45,
    "unit_label": "\u00b5m"
  },
  "y_fit": { ... }
}
```

---

### ROI (Region of Interest)

```
GET    /roi                 Get current ROI state
POST   /roi                 Set ROI rectangle (x0, y0, x1, y1 in pixels)
DELETE /roi                 Clear the ROI
POST   /roi/center          Re-center ROI as a square around the intensity centroid
```

**Set ROI:**
```bash
curl -X POST http://localhost:8765/roi \
  -H "Content-Type: application/json" \
  -d '{"x0": 100, "y0": 100, "x1": 300, "y1": 300}'
```

---

### Centroid and Drift Tracking

```
GET  /centroid              Get centroid reference, live position, and drift values
POST /centroid/crosshair    Enable/disable the centroid crosshair overlay
```

**Read drift:**
```bash
curl http://localhost:8765/centroid
```

Response:
```json
{
  "has_reference": true,
  "crosshair_enabled": true,
  "reference": {"x": 150.0, "y": 150.0},
  "live": {"x": 151.5, "y": 149.2},
  "drift_x": 1.5,
  "drift_y": -0.8,
  "drift_x_um": 2.83,
  "drift_y_um": -1.51
}
```

---

### Display

```
GET  /display/theme         Get current theme ("dark" or "light")
POST /display/theme/toggle  Toggle between dark and light mode
GET  /display/colormap      Get current colormap and list of available options
POST /display/colormap      Set the image colormap
```

Available colormaps: `hot`, `viridis`, `inferno`, `plasma`, `magma`, `cividis`, `gray`.

```bash
curl -X POST http://localhost:8765/display/colormap \
  -H "Content-Type: application/json" \
  -d '{"name": "viridis"}'
```

---

### Projection Overlays

```
GET  /overlays              Get current overlay settings
POST /overlays              Update overlay settings (partial update supported)
```

**Enable horizontal overlay on bottom:**
```bash
curl -X POST http://localhost:8765/overlays \
  -H "Content-Type: application/json" \
  -d '{"h_enabled": true, "h_side": "bottom", "scale": 0.3}'
```

Fields: `h_enabled`, `h_side` (`"bottom"` | `"top"`), `v_enabled`,
`v_side` (`"left"` | `"right"`), `scale` (0.05--0.50), `show_full`, `show_roi`.
Only include fields you want to change.

---

### Trending

```
GET  /trending              Get trending panel config (visible, depth)
POST /trending/visible      Show/hide the trending panel
POST /trending/depth        Set the history depth (50--2000 frames)
GET  /trending/history      Get the full trending history buffer
```

**Get trending data:**
```bash
curl http://localhost:8765/trending/history
```

Response contains arrays of per-frame values:
`frame_number`, `sigma_x`, `sigma_y`, `centroid_x`, `centroid_y`,
`roi_sigma_x`, `roi_sigma_y`, `drift_x`, `drift_y`.

---

### Frame Data

```
GET /frames/metadata        Frame number, FPS, dimensions, dtype
GET /frames/current         Current frame as base64-encoded PNG + metadata
GET /frames/projections     Full-image X and Y projections (1-D arrays)
GET /frames/roi             ROI crop: image (base64 PNG), projections, metadata
WS  /frames/ws/stream       Real-time WebSocket stream (see below)
```

**Get current frame:**
```bash
curl http://localhost:8765/frames/current
```

Response:
```json
{
  "metadata": {
    "frame_number": 1042,
    "fps": 10.3,
    "height": 1038,
    "width": 1300,
    "dtype": "uint16"
  },
  "image_b64_png": "iVBORw0KGgo..."
}
```

---

### Configuration

```
GET /config                     Overview: active prefix, available prefixes, EPICS settings
GET /config/prefix/{prefix}     Detailed PV and calibration info for a specific prefix
GET /config/calibration         Calibration for the active camera
```

---

## WebSocket Streaming

Connect to `ws://127.0.0.1:8765/frames/ws/stream` to receive real-time frame
updates. The server pushes a JSON message every time a new frame is analyzed.

### Payload structure

```json
{
  "type": "frame",
  "frame_number": 1042,
  "timestamp": 1712345678.123,
  "fps": 10.3,
  "frame_png_b64": "iVBORw0KGgo...",
  "projections": {
    "x_projection": [100.2, 101.5, ...],
    "y_projection": [98.3, 99.1, ...]
  },
  "analysis": {
    "fit_full_enabled": true,
    "fit_roi_enabled": false,
    "x_fit": { "success": true, "sigma": 12.3, ... },
    "y_fit": { "success": true, "sigma": 11.8, ... }
  },
  "roi": {
    "active": true,
    "roi": { "x0": 100, "y0": 100, "x1": 300, "y1": 300 }
  },
  "drift": {
    "has_reference": true,
    "drift_x": 1.5,
    "drift_y": -0.8
  }
}
```

### Keepalive

The server sends `{"type": "keepalive"}` if no data arrives within 30 seconds.
Send `"ping"` as a text message to receive `{"type": "pong"}`.

### Python client example

```python
import asyncio
import json
import websockets

async def stream():
    async with websockets.connect("ws://127.0.0.1:8765/frames/ws/stream") as ws:
        async for message in ws:
            data = json.loads(message)
            if data["type"] == "frame":
                print(f"Frame {data['frame_number']}  FPS={data['fps']}")
                if data["analysis"]["x_fit"]:
                    print(f"  sigma_x = {data['analysis']['x_fit']['sigma']}")

asyncio.run(stream())
```

---

## Python Client Examples

### Read beam size in a loop

```python
import requests, time

while True:
    r = requests.get("http://localhost:8765/analysis")
    data = r.json()
    xf = data.get("x_fit")
    yf = data.get("y_fit")
    if xf and xf["success"]:
        print(f"sigma_x = {xf['sigma_um']:.2f} um")
    if yf and yf["success"]:
        print(f"sigma_y = {yf['sigma_um']:.2f} um")
    time.sleep(1)
```

### Switch camera and set exposure

```python
import requests

base = "http://localhost:8765"

# Switch to BL31
requests.post(f"{base}/camera/prefix", json={"prefix": "BL31"})

# Set exposure to 50 ms
requests.post(f"{base}/camera/exposure", json={"value": 0.05})

# Enable fitting
requests.post(f"{base}/analysis/fit-full", json={"enabled": True})
```

### Acquire background and enable subtraction

```python
import requests, time

base = "http://localhost:8765"

requests.post(f"{base}/background/acquire")
time.sleep(0.5)  # wait for next frame to be captured

requests.post(f"{base}/background/subtraction", json={"enabled": True})
print(requests.get(f"{base}/background").json())
```

### Set ROI and read fit results

```python
import requests

base = "http://localhost:8765"

# Draw ROI
requests.post(f"{base}/roi", json={"x0": 200, "y0": 150, "x1": 500, "y1": 450})

# Enable ROI fitting
requests.post(f"{base}/analysis/fit-roi", json={"enabled": True})

# Read ROI fit results (part of /analysis response)
print(requests.get(f"{base}/analysis").json())

# Center ROI on beam centroid
requests.post(f"{base}/roi/center")
```

---

## Error Handling

All endpoints return standard HTTP status codes:

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request (invalid parameters, precondition not met) |
| 404 | Resource not found (e.g. unknown prefix) |
| 422 | Validation error (Pydantic rejected the request body) |
| 500 | Internal server error |

Mutation endpoints return `{"ok": true, "message": "..."}` on success.
Error responses include `{"detail": "..."}` with a human-readable description.

---

## Security Notes

- The API binds to `127.0.0.1` by default (localhost only). To expose it on the
  network, change the `host` parameter in `main.py`.
- Background file loading validates that the path is inside the `config/backgrounds/`
  directory to prevent path traversal.
- No authentication is implemented. If the API is exposed on a network, add
  authentication middleware before deployment.
- CORS is configured to allow all origins for local development. Restrict
  `allow_origins` in `api/server.py` for production use.
