# Troubleshooting Reference

Symptom → likely cause → fix for common beam viewer deployment failures.

## Container Won't Start

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ImportError: No module named 'beam_viewer'` | PYTHONPATH wrong in Dockerfile | Verify `ENV PYTHONPATH=/app:/app/mcp_servers` in Dockerfile |
| `ImportError: No module named 'analysis'` | Top-level `analysis/` not copied | Check `COPY analysis/ /app/analysis/` in Dockerfile |
| `FileNotFoundError: config.json` | entrypoint.sh didn't copy default config | Check `COPY mcp_servers/beam_viewer/config/config.json /app/config.default/config.json` |
| `JSONDecodeError` in config | Malformed config.json (maybe from a bad edit) | Rebuild image to reset to default, or mount a corrected config |
| `Address already in use: 8007` | Another process on port 8007 | `ssh appsdev2 "ss -tlnp \| grep 8007"` — kill the conflicting process or use a different port |
| Container exits immediately (exit code 1) | Python crash on startup | `podman logs beam-viewer-test` for the traceback |

## EPICS Not Connecting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Health: `"degraded"`, `"reason": "EPICS disconnected"` | PVs not reachable | Verify with `caget BL72:image1:ArraySize0_RBV` on appsdev2 |
| `caget` works on host but not in container | Container not using host networking | Check `--network host` flag. Verify: `podman inspect beam-viewer-test \| grep NetworkMode` should show `host` |
| `caget` times out on host too | Camera IOC is down, or wrong PV name | Try a different prefix (BL31 vs BL72). Check with accelerator operations if IOCs are running. |
| caproto `SearchRequest timed out` in logs | CA search can't find the IOC via UDP broadcast | `EPICS_CA_ADDR_LIST` is baked into the Dockerfile with ALS subnets. If overridden at runtime, verify the addr list covers the IOC's subnet. |
| Connected briefly then disconnected | IOC restarted or network blip | Check logs for reconnection attempts. The worker has automatic retry with backoff. |
| Config has `"host": "some-ip"` | Tunnel mode active — wrong for appsdev2 | Set `"host": ""` (empty string) in config.json for native CA mode |

### Verifying EPICS connectivity step by step

```bash
# 1. Can the host reach the PV?
ssh appsdev2 "caget BL72:image1:ArraySize0_RBV"

# 2. Can Python/caproto reach it?
ssh appsdev2 "python3 -c \"
from caproto.threading.client import Context
ctx = Context()
pv, = ctx.get_pvs('BL72:image1:ArraySize0_RBV')
pv.wait_for_connection(timeout=5)
print('Value:', pv.read().data)
ctx.disconnect()
\""

# 3. Can the container reach it?
ssh appsdev2 "podman exec beam-viewer-test python3 -c \"
from caproto.threading.client import Context
ctx = Context()
pv, = ctx.get_pvs('BL72:image1:ArraySize0_RBV')
pv.wait_for_connection(timeout=5)
print('Value:', pv.read().data)
ctx.disconnect()
\""
```

If step 2 works but step 3 fails, the container networking is the issue.

## Frames Not Working

| Symptom | Cause | Fix |
|---------|-------|-----|
| `/frames/current` returns 503 | No frames received yet | Wait a few seconds after startup. Check health — EPICS may not be connected. |
| Frame captured but image is garbled | Wrong width/height PVs or fallback_shape | Check `config.json` — verify `fallback_shape` matches the camera resolution |
| `ValueError: cannot reshape` in logs | Image array size doesn't match dimensions | The width/height PVs may not have responded yet. Check fallback_shape in config. |
| Frame is all black | Camera shutter closed or exposure too low | Not a container issue — check camera settings via `caget BL72:cam1:AcquireTime_RBV` |
| Frame is saturated (all white) | Exposure too high or gain too high | Adjust via API: `curl -X POST .../camera/exposure -d '{"value": 0.01}'` |

## WebSocket Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| WebSocket connection refused | FastAPI not running or wrong endpoint | Use `ws://localhost:8007/ws/frames` (not `/ws` or `/websocket`) |
| Connected but no frames | EPICS not connected (no data to stream) | Fix EPICS connectivity first |
| Frames received but < 5 Hz | IOC update rate is slow, or analysis pipeline is bottleneck | Check IOC rate with `camonitor`. If IOC is fast but WS is slow, check CPU usage in container. |
| `websockets` ImportError | Package not installed on appsdev2 | `pip3 install websockets` or use browser-based test instead |

## Web Panel Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `/panel/` returns 404 | Static files not in image | Check `_STATIC_DIR` path in `server.py` resolves inside container |
| Panel loads but no image | WebSocket not connecting from browser | Check browser console for WS errors. Ensure SSH tunnel is forwarding 8007. |
| Panel loads, image shows, but no overlays | Overlay settings disabled in config | Enable via API: `curl -X POST .../overlays/settings -d '{"h_enabled":true,"v_enabled":true}'` |

## Build/Podman Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `podman build` fails downloading pip packages | Proxy required on ALS network | May need `--build-arg HTTP_PROXY=http://squid-ctrl.als.lbl.gov:3128` |
| `podman: command not found` | podman not installed or not in PATH | On appsdev2, podman should be available. Check with `which podman`. |
| `Error: container name beam-viewer-test already in use` | Forgot to remove old container | `podman rm -f beam-viewer-test` |
| Image builds but is very large | Docker cache not being used | Normal for first build (~500MB). Subsequent builds use layer cache. |

## Performance

| Symptom | Cause | Fix |
|---------|-------|-----|
| High CPU usage in container | Analysis pipeline running on every frame | Expected for Gaussian fitting. If too high, check if multiple subscriptions are active. |
| Memory growing over time | Frame buffer or trending buffer not bounded | Check trending buffer size. Should be capped at ~1000 entries. |
| Slow response times on REST endpoints | Analysis blocking the event loop | The analysis runs in a separate thread — if REST is slow, check for lock contention in logs. |
