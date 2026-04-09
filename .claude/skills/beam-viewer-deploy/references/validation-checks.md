# Validation Checks Reference

Complete validation commands with expected outputs. These are the checks that `scripts/validate.sh` runs automatically — this reference is for understanding what each check does and for running them manually.

## Tier 1: Container Health

### 1.1 Container Running

```bash
ssh appsdev2 "podman ps --filter name=beam-viewer-test --format '{{.Names}} {{.Status}}'"
```

**Pass**: Output contains `beam-viewer-test Up`
**Fail**: Empty output or `Exited`. Check: `podman logs beam-viewer-test`

### 1.2 Process Healthy

```bash
ssh appsdev2 "podman inspect beam-viewer-test --format '{{.State.Status}}'"
```

**Pass**: `running`
**Fail**: `exited`, `dead`, or `created` (container started but process crashed)

---

## Tier 2: API & Health

### 2.1 Health Endpoint

```bash
ssh appsdev2 "curl -sf --max-time 5 http://localhost:8007/health"
```

**Pass**: Returns JSON. Check `status` field:
- `"ok"` — fully operational, EPICS connected and streaming
- `"degraded"` — server up but EPICS issue (check `reason` field)

**Fail**: Connection refused or timeout. Container may have crashed after starting — check logs.

Example good response:
```json
{
  "status": "ok",
  "connected": true,
  "streaming": true,
  "frame_count": 142,
  "ws_clients": 0
}
```

Example degraded response:
```json
{
  "status": "degraded",
  "connected": false,
  "streaming": false,
  "frame_count": 0,
  "ws_clients": 0,
  "reason": "EPICS disconnected"
}
```

### 2.2 OpenAPI Schema (FastAPI routes registered)

```bash
ssh appsdev2 "curl -sf http://localhost:8007/openapi.json | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d[\"paths\"]),\"routes\")'"
```

**Pass**: Reports a route count (should be >10 — there are 11 route modules).
**Fail**: Parse error or 0 routes — routes not registered, check import errors in logs.

---

## Tier 3: EPICS Data Pipeline

### 3.1 Camera Info

```bash
ssh appsdev2 "curl -sf http://localhost:8007/camera/info"
```

**Pass**: Returns JSON with `active_prefix`, `available_prefixes`, and PV names.
**Fail**: 500 error — config.json not loaded or malformed. Check `BEAMVIEWER_CONFIG` env var.

### 3.2 Current Frame (PNG)

```bash
ssh appsdev2 "curl -sf http://localhost:8007/frames/current -o /tmp/beam_test.png -w '%{http_code} %{size_download}'"
```

**Pass**: HTTP 200, size > 1000 bytes (a real PNG frame). The file at `/tmp/beam_test.png` is a valid PNG.
**Fail**: 
- HTTP 503 — EPICS not connected, no frames available
- HTTP 200 but tiny file — empty/placeholder frame

Verify the PNG is valid:
```bash
ssh appsdev2 "python3 -c \"from PIL import Image; img=Image.open('/tmp/beam_test.png'); print(f'{img.size[0]}x{img.size[1]} {img.mode}')\""
```

### 3.3 Beam Analysis

```bash
ssh appsdev2 "curl -sf http://localhost:8007/analysis/beam"
```

**Pass**: JSON with beam parameters — `centroid_x`, `centroid_y`, `sigma_x`, `sigma_y`, `amplitude`, `fit_valid`.
**Fail**:
- 503 — no frames flowing, can't analyze
- 200 but `fit_valid: false` — frames are flowing but the Gaussian fit failed (could be normal if the beam is off or saturated)

### 3.4 Camera Switch

```bash
# Switch to BL31
ssh appsdev2 "curl -sf -X POST http://localhost:8007/camera/switch \
  -H 'Content-Type: application/json' \
  -d '{\"prefix\": \"BL31\"}'"

# Verify it took effect
sleep 2
ssh appsdev2 "curl -sf http://localhost:8007/camera/info | python3 -c 'import sys,json; print(json.load(sys.stdin)[\"active_prefix\"])'"

# Switch back
ssh appsdev2 "curl -sf -X POST http://localhost:8007/camera/switch \
  -H 'Content-Type: application/json' \
  -d '{\"prefix\": \"BL72\"}'"
```

**Pass**: Active prefix changes to BL31, then back to BL72.
**Fail**: 422 (unknown prefix) or 500 (reconnection error).

---

## Tier 4: Real-Time Features

### 4.1 WebSocket Frame Rate

This test connects to the WebSocket endpoint and counts frames over 5 seconds. Requires `websockets` Python package on appsdev2 (or install it: `pip3 install websockets`).

```bash
ssh appsdev2 "python3 -c \"
import asyncio, json, time
try:
    import websockets
except ImportError:
    print('SKIP: websockets not installed (pip3 install websockets)')
    exit(0)

async def test():
    async with websockets.connect('ws://localhost:8007/ws/frames') as ws:
        start = time.time()
        count = 0
        while time.time() - start < 5:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(msg)
                if 'frame_jpeg_b64' in data:
                    count += 1
            except asyncio.TimeoutError:
                break
        elapsed = time.time() - start
        fps = count / elapsed if elapsed > 0 else 0
        print(f'{count} frames in {elapsed:.1f}s = {fps:.1f} Hz')
        if fps >= 5:
            print('PASS: >= 5 Hz')
        elif fps > 0:
            print(f'WARN: {fps:.1f} Hz (below 5 Hz target)')
        else:
            print('FAIL: no frames received')

asyncio.run(test())
\""
```

**Pass**: ≥5 Hz frame rate
**Warn**: >0 but <5 Hz — may indicate slow IOC update rate or processing bottleneck
**Fail**: 0 frames — WebSocket connected but no data flowing

### 4.2 Static Files (Web Panel)

```bash
ssh appsdev2 "curl -sf -o /dev/null -w '%{http_code}' http://localhost:8007/panel/"
```

**Pass**: HTTP 200
**Fail**: HTTP 404 — static files not mounted. Check that `/app/mcp_servers/beam_viewer/static/` exists in the container:
```bash
ssh appsdev2 "podman exec beam-viewer-test ls /app/mcp_servers/beam_viewer/static/"
```

### 4.3 Web Panel Visual (Manual)

Open SSH tunnel: `ssh -L 8007:localhost:8007 -N appsdev2`
Browse to: `http://localhost:8007/panel`

Checklist:
- [ ] Live image updating in real-time
- [ ] Beam parameter overlays visible
- [ ] Projection plots render when enabled
- [ ] ROI selection works (click-drag)
- [ ] Camera dropdown lists all prefixes
- [ ] Colormap selector changes the display

---

## Tier 5: MCP Tools (Optional)

If testing MCP integration:

```bash
# List available tools
ssh appsdev2 "curl -sf http://localhost:8007/mcp/tools | python3 -m json.tool"
```

This tier is only relevant when integrating with the als-profiles MCP pipeline.
