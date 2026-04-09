# Beam Viewer Deploy & Test

Deploy the beam viewer headless container to appsdev2, validate it against live EPICS cameras, debug failures, and iterate until everything works.

**Source of truth:** ALS GitLab — `https://git.als.lbl.gov/physics/production/beam-viewer`
**GitHub (`origin`) is no longer used for deployment. Ignore it.**

All code changes must be pushed to the `gitlab` remote before deploying:
```bash
git push gitlab <branch>
```

## Why Host Networking Matters

The beam viewer uses caproto in "native mode" (empty `host` field in config.json) which relies on UDP broadcast for Channel Access PV discovery. Standard container networking (bridge/NAT) isolates UDP broadcasts — the container would never find the IOCs. `network_mode: host` puts the container directly on appsdev2's network where CA discovery works natively.

## Action Routing

Match the user's intent to one of these actions:

| Intent | Action |
|--------|--------|
| First-time deploy or full redeploy | **Deploy** (push → pull → build → run → validate) |
| Code changed, need to test again | **Rebuild** (push → pull → rebuild image → run → validate) |
| Container is running, check if it works | **Validate** (run checks against running container) |
| Something isn't working | **Debug** (inspect logs, check EPICS, targeted fixes) |
| Check web panel matches PyQt layout | **Layout Parity** → read `references/layout-parity.md` |
| Done testing | **Cleanup** (stop container, optionally remove image) |

---

## Deploy (Full)

### Prerequisites

- SSH access to appsdev2 (`ssh appsdev2` works)
- podman available on appsdev2
- Changes pushed to GitLab (`git push gitlab <branch>`)
- No other process using port 8007 on appsdev2

### Step 1: Push local changes to GitLab

Always push first — appsdev2 pulls from GitLab, so unpushed commits won't be there.

```bash
git push gitlab web-panel
```

### Step 2: Pull on appsdev2

First time (fresh clone):
```bash
ssh appsdev2 "git clone https://oauth2:${ALS_GITLAB_TOKEN}@git.als.lbl.gov/physics/production/beam-viewer.git ~/projects/beam-viewer"
```

Subsequent pulls (repo already exists):
```bash
ssh appsdev2 "cd ~/projects/beam-viewer && git fetch origin && git checkout web-panel && git pull"
```

Note: Inside the cloned repo on appsdev2, the GitLab remote is called `origin` (it's a plain clone).

### Step 3: Build the container image

```bash
ssh appsdev2 "cd ~/projects/beam-viewer && podman build -f docker/Dockerfile.beam-viewer -t beam-viewer-test ."
```

Watch for: pip install failures (network/proxy issues), missing source files, or Python version mismatches.

### Step 4: Run the container

```bash
ssh appsdev2 "podman run -d --name beam-viewer-test \
  --network host \
  beam-viewer-test \
  --host 0.0.0.0 --port 8007"
```

The Dockerfile bakes in the ALS EPICS CA environment (`EPICS_CA_ADDR_LIST` with all ALS broadcast subnets, `EPICS_CA_AUTO_ADDR_LIST=NO`, `EPICS_CA_SERVER_PORT=5064`). Combined with `--network host` and `"host": ""` in config.json, caproto can discover IOCs across all ALS subnets via UDP broadcast. No manual `-e` flags needed.

### Step 5: Validate

Run the validation script (see **Validate** below) or step through checks manually.

---

## Rebuild (After Code Changes)

When you've fixed something locally and want to test again:

```bash
# 1. Push changes to GitLab
git push gitlab web-panel

# 2. Stop and remove the old container on appsdev2
ssh appsdev2 "podman stop beam-viewer-test 2>/dev/null; podman rm beam-viewer-test 2>/dev/null"

# 3. Pull latest from GitLab on appsdev2
ssh appsdev2 "cd ~/projects/beam-viewer && git pull"

# 4. Rebuild (podman caches layers, so unchanged deps are fast)
ssh appsdev2 "cd ~/projects/beam-viewer && podman build -f docker/Dockerfile.beam-viewer -t beam-viewer-test ."

# 5. Run again
ssh appsdev2 "podman run -d --name beam-viewer-test \
  --network host \
  beam-viewer-test \
  --host 0.0.0.0 --port 8007"
```

EPICS CA env vars are baked into the image — no manual `-e` flags needed.

---

## Validate

Validation has four tiers. Each tier assumes the previous one passed.

### Tier 1: Container alive

```bash
ssh appsdev2 "podman ps --filter name=beam-viewer-test --format '{{.Status}}'"
```
Expected: `Up X seconds` or similar. If not running, check `podman logs beam-viewer-test`.

### Tier 2: API responding

```bash
ssh appsdev2 "curl -sf http://localhost:8007/health | python3 -m json.tool"
```
Expected: JSON with `status`, `connected`, `streaming`, `frame_count`, `ws_clients`.

- `"status": "ok"` — EPICS connected and streaming. Everything works.
- `"status": "degraded"` — Server is up but EPICS isn't connected. Move to **Debug**.

### Tier 3: EPICS data flowing

```bash
# Camera info (PV config loaded correctly)
ssh appsdev2 "curl -sf http://localhost:8007/camera | python3 -m json.tool"

# Current frame (EPICS data → image pipeline works)
ssh appsdev2 "curl -sf http://localhost:8007/frames/current -o /tmp/beam_frame.png && echo 'OK: frame captured' || echo 'FAIL: no frame'"

# Analysis (Gaussian fitting running)
ssh appsdev2 "curl -sf http://localhost:8007/analysis | python3 -m json.tool"
```

### Tier 4: Real-time features

Read `references/validation-checks.md` for WebSocket frame-rate testing, camera switching, web panel visual verification via SSH tunnel, and the full automated validation script.

---

## Layout Parity (Web Panel vs PyQt)

The PyQt desktop app (`gui/*.py`) is the source of truth. The web panel must converge to match it exactly.

### First-Principles Feedback Loop (MANDATORY)

This is a closed-loop process. Every iteration has exactly 4 steps. Never skip a step. Never batch multiple fixes without verifying each one.

**Step 1: READ the PyQt source code.**
The specification lives in these files — not in a reference doc, not in memory:
- `gui/window.py` — overall structure, splitter layout, status bar
- `gui/control_panel.py` — all 5 control groups, every widget
- `gui/projection_plot.py` — projection plots (titles, stats, curves, fit overlays)
- `gui/trending_panel.py` — 3 dual-trace sub-plots
- `gui/image_pane.py` — image display, ROI overlay
- `gui/theme.py` — color tokens for both themes

Read the relevant section of PyQt source for the specific element you're checking. Extract the exact specification: dimensions, labels, ordering, colors, hierarchy.

**Step 2: INSPECT the deployed panel.**
Use Playwright MCP tools against the live container on appsdev2:
```
browser_navigate → http://localhost:8007/panel
browser_take_screenshot → capture full panel
browser_snapshot → get DOM structure
browser_console_messages → check for JS errors
```
If the SSH tunnel isn't open:
```bash
ssh -L 8007:localhost:8007 -N -f appsdev2
```
Compare what you see in the screenshot against what the PyQt source says. Identify ONE specific mismatch.

**Step 3: FIX the mismatch.**
Make the minimal local change (HTML, CSS, or JS) to close that one gap. Then push and redeploy:
```bash
# Push changes to GitLab
git push gitlab web-panel

# Stop old container
ssh appsdev2 "podman stop beam-viewer-test 2>/dev/null; podman rm beam-viewer-test 2>/dev/null"

# Pull latest on appsdev2
ssh appsdev2 "cd ~/projects/beam-viewer && git pull"

# Rebuild and run
ssh appsdev2 "cd ~/projects/beam-viewer && podman build -f docker/Dockerfile.beam-viewer -t beam-viewer-test . 2>&1 | tail -3"
ssh appsdev2 "podman run -d --name beam-viewer-test --network host beam-viewer-test --host 0.0.0.0 --port 8007"
```
IMPORTANT: Bump the `?v=N` cache-bust version on changed static files in `index.html` so browsers don't serve stale assets.

**Step 4: VERIFY the fix on the deployed panel.**
Take a new Playwright screenshot. Confirm the mismatch is resolved. If it isn't, debug (check container logs, console errors, verify files inside container). Do NOT proceed to the next mismatch until this one is confirmed fixed.

```
Loop: Step 1 → 2 → 3 → 4 → back to Step 1 for the next mismatch
```

### What to compare (checklist)

Work through these areas in order. For each, read the PyQt source, screenshot the panel, and close gaps:

1. **Overall structure** — splitter columns, proportions, no extra header/toolbar rows
2. **Status bar** — theme toggle left, frame counter right, format matches
3. **Image area** — canvas fills column, aspect-locked, ROI overlay behavior
4. **Projections** — column to the right, titles, stats labels, curve colors, fit overlay
5. **Control panel sections** — 5 groups matching PyQt names and ordering
6. **Each widget in each group** — labels, types, ranges, defaults, enabled/disabled states
7. **Trending panel** — 3 dual-trace sub-plots as a column, colors match, stats legend
8. **Theme colors** — both dark and light themes, every token matches `gui/theme.py`

### Known gaps tracker

See `references/layout-parity.md` for the gap table. Update it as gaps are resolved or new ones are discovered.

### Playwright E2E tests

Structural tests live in `tests/e2e/layout-parity.spec.js`. Run against the live container:
```bash
npx playwright test tests/e2e/layout-parity.spec.js --reporter=list
```

---

## Debug

When something fails, work through this decision tree:

```
Container not running?
  → podman logs beam-viewer-test
  → Usually: import error, missing dep, config parse failure

Health returns "degraded" / EPICS disconnected?
  → First: verify PVs exist on the network
    ssh appsdev2 "caget BL72:image1:ArraySize0_RBV"
  → If caget fails: camera IOC is down, or wrong PV prefix. Try BL31.
  → If caget works but container can't connect:
    - Verify host networking: podman inspect beam-viewer-test | grep NetworkMode
    - Check container logs for caproto errors

Frames endpoint returns error?
  → Health says connected but frames fail: check analysis pipeline
    ssh appsdev2 "podman logs beam-viewer-test 2>&1 | tail -30"
  → Look for reshape errors (wrong width/height), numpy issues

WebSocket not streaming?
  → Check ws_manager logs, verify /health shows ws_clients incrementing
```

Read `references/troubleshooting.md` for the full symptom → cause → fix table.

### Useful diagnostic commands

```bash
# Container logs (last 50 lines)
ssh appsdev2 "podman logs --tail 50 beam-viewer-test"

# Follow logs in real-time
ssh appsdev2 "podman logs -f beam-viewer-test"

# Shell into the container
ssh appsdev2 "podman exec -it beam-viewer-test /bin/bash"

# Check what config.json the container is using
ssh appsdev2 "podman exec beam-viewer-test cat /app/config/config.json | python3 -m json.tool"

# Test EPICS from inside the container
ssh appsdev2 "podman exec beam-viewer-test python3 -c \"
from caproto.threading.client import Context
ctx = Context()
pv, = ctx.get_pvs('BL72:image1:ArraySize0_RBV')
pv.wait_for_connection(timeout=5)
print('Connected:', pv.read().data)
\""

# Check if port 8007 is in use by something else
ssh appsdev2 "ss -tlnp | grep 8007"

# Verify repo state on appsdev2
ssh appsdev2 "cd ~/projects/beam-viewer && git log --oneline -5 && git status"
```

---

## Cleanup

```bash
ssh appsdev2 "podman stop beam-viewer-test && podman rm beam-viewer-test"

# Optionally remove the image too
ssh appsdev2 "podman rmi beam-viewer-test"

# Remove cloned source (if you don't need it anymore)
ssh appsdev2 "rm -rf ~/projects/beam-viewer"
```

---

## Web Panel (Visual Verification)

The web panel is the most complete test — it exercises the frame pipeline, WebSocket streaming, Canvas rendering, and all UI controls.

From your Mac, open an SSH tunnel:
```bash
ssh -L 8007:localhost:8007 -N appsdev2
```

Then open `http://localhost:8007/panel` in your browser.

**What to check:**
- Live image updating (should refresh at ≥5 Hz)
- Beam parameter readouts (centroid, sigma) in the overlay
- Projection plots (enable via overlay controls)
- ROI selection (click and drag on the image)
- Camera switching (dropdown should list BL31, BL72)
- Colormap controls

---

## Config Customization

The default config.json is baked into the image. To override it at runtime (e.g., to test a different camera or change EPICS settings):

```bash
# Create a local config on appsdev2
ssh appsdev2 "mkdir -p ~/projects/beam-viewer-data"
# Edit the config as needed, then mount it:
ssh appsdev2 "podman run -d --name beam-viewer-test \
  --network host \
  -v ~/projects/beam-viewer-data:/app/config \
  beam-viewer-test \
  --host 0.0.0.0 --port 8007"
```

The entrypoint.sh will copy the default config into the mounted volume if config.json doesn't exist yet, then you can edit it in place and restart.

### Available camera prefixes

| Prefix | Camera | Typical availability |
|--------|--------|---------------------|
| BL72 | 7.2 beamline camera | Usually available during operations |
| BL31 | 3.1 beamline camera | Usually available during operations |

To switch at runtime without restarting:
```bash
ssh appsdev2 "curl -s -X POST http://localhost:8007/camera/prefix \
  -H 'Content-Type: application/json' \
  -d '{\"prefix\": \"BL31\"}'"
```
