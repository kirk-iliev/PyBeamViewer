# Beam Viewer Deploy & Test

Deploy the beam viewer headless container to appsdev2 via GitLab CI/CD, validate it against live EPICS cameras, debug failures, and iterate until everything works.

**Source of truth:** ALS GitLab — `https://git.als.lbl.gov/physics/production/beam-viewer`
**GitHub (`origin`) is no longer used for deployment. Ignore it.**

## CI/CD Pipeline

Beam-viewer has its own 3-stage GitLab CI pipeline (`.gitlab-ci.yml`):

| Stage | Jobs | Purpose |
|-------|------|---------|
| checks | lint, test | Ruff linting + pytest unit tests (advisory, `allow_failure: true`) |
| docker-build | build-beam-viewer | Builds container image, tags with `$CI_COMMIT_SHORT_SHA` |
| release | release | Re-tags as `:latest` (web-panel branch only, manual trigger) |

The image is pushed to the GitLab Container Registry at `git.als.lbl.gov:5050/physics/production/beam-viewer/beam-viewer:latest`.

On appsdev2, als-profiles' `docker-compose.yml` references this image directly (hardcoded path, no env var). The `deploy.sh` script pulls it alongside all other MCP server images.

## Why Host Networking Matters

The beam viewer uses caproto in "native mode" (empty `host` field in config.json) which relies on UDP broadcast for Channel Access PV discovery. Standard container networking (bridge/NAT) isolates UDP broadcasts — the container would never find the IOCs. `docker-compose.host.yml` adds `network_mode: host` so CA discovery works natively.

## Action Routing

Match the user's intent to one of these actions:

| Intent | Action |
|--------|--------|
| First-time deploy or full redeploy | **Deploy** (push → CI → release → deploy.sh → validate) |
| Code changed, need to test again | **Rebuild** (push → CI → release → deploy.sh → validate) |
| Container is running, check if it works | **Validate** (run checks against running container) |
| Something isn't working | **Debug** (inspect logs, check EPICS, targeted fixes) |
| Check web panel matches PyQt layout | **Layout Parity** → read `references/layout-parity.md` |

---

## Deploy (Full)

### Prerequisites

- SSH access to appsdev2 (`ssh appsdev2` works)
- als-profiles cloned on appsdev2 at `~/projects/als-profiles`
- No other process using port 8007 on appsdev2

### Step 1: Push to GitLab (triggers CI)

```bash
NO_PROXY=git.als.lbl.gov git push gitlab web-panel
```

### Step 2: Monitor CI pipeline

```bash
curl -s --header "PRIVATE-TOKEN: $ALS_GITLAB_TOKEN" \
  "https://git.als.lbl.gov/api/v4/projects/physics%2Fproduction%2Fbeam-viewer/pipelines?per_page=1" \
  | python3 -m json.tool
```

Wait until status shows `manual` (checks and docker-build stages passed, release job waiting).

### Step 3: Trigger manual release

Via GitLab web UI or API. This re-tags the image as `:latest`.

### Step 4: Deploy on appsdev2

```bash
ssh appsdev2 "cd ~/projects/als-profiles && ./scripts/deploy.sh"
```

This single command pulls all images (including beam-viewer) and starts everything.

### Step 5: Validate

Run the validation checks below or step through manually.

---

## Rebuild (After Code Changes)

Same flow as Deploy — push, CI, release, deploy.sh:

```bash
# 1. Push changes to GitLab
NO_PROXY=git.als.lbl.gov git push gitlab web-panel

# 2. Wait for CI pipeline to reach "manual" status (checks + build pass)

# 3. Trigger manual release job (GitLab UI or API)

# 4. Pull and restart on appsdev2
ssh appsdev2 "cd ~/projects/als-profiles && ./scripts/deploy.sh"
```

For a clean restart (stops all containers first):
```bash
ssh appsdev2 "cd ~/projects/als-profiles && ./scripts/deploy.sh --clean"
```

---

## Validate

Validation has four tiers. Each tier assumes the previous one passed.

### Tier 1: Container alive

```bash
ssh appsdev2 "podman ps --filter name=als-beam-viewer --format '{{.Status}}'"
```
Expected: `Up X seconds` or similar. If not running, check `podman logs als-beam-viewer`.

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
Make the minimal local change (HTML, CSS, or JS). Then push and redeploy:
```bash
# Push changes to GitLab
NO_PROXY=git.als.lbl.gov git push gitlab web-panel

# Wait for CI → trigger release → deploy
ssh appsdev2 "cd ~/projects/als-profiles && ./scripts/deploy.sh"
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
  → podman logs als-beam-viewer
  → Usually: import error, missing dep, config parse failure

Health returns "degraded" / EPICS disconnected?
  → First: verify PVs exist on the network
    ssh appsdev2 "caget BL72:image1:ArraySize0_RBV"
  → If caget fails: camera IOC is down, or wrong PV prefix. Try BL31.
  → If caget works but container can't connect:
    - Verify host networking: podman inspect als-beam-viewer | grep NetworkMode
    - Check container logs for caproto errors

Frames endpoint returns error?
  → Health says connected but frames fail: check analysis pipeline
    ssh appsdev2 "podman logs als-beam-viewer 2>&1 | tail -30"
  → Look for reshape errors (wrong width/height), numpy issues

WebSocket not streaming?
  → Check ws_manager logs, verify /health shows ws_clients incrementing
```

Read `references/troubleshooting.md` for the full symptom → cause → fix table.

### Useful diagnostic commands

```bash
# Container logs (last 50 lines)
ssh appsdev2 "podman logs --tail 50 als-beam-viewer"

# Follow logs in real-time
ssh appsdev2 "podman logs -f als-beam-viewer"

# Shell into the container
ssh appsdev2 "podman exec -it als-beam-viewer /bin/bash"

# Check what config.json the container is using
ssh appsdev2 "podman exec als-beam-viewer cat /app/config/config.json | python3 -m json.tool"

# Test EPICS from inside the container
ssh appsdev2 "podman exec als-beam-viewer python3 -c \"
from caproto.threading.client import Context
ctx = Context()
pv, = ctx.get_pvs('BL72:image1:ArraySize0_RBV')
pv.wait_for_connection(timeout=5)
print('Connected:', pv.read().data)
\""

# Check if port 8007 is in use by something else
ssh appsdev2 "ss -tlnp | grep 8007"

# Check all als-profiles containers
ssh appsdev2 "cd ~/projects/als-profiles && podman-compose ps"
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

The default config.json is baked into the image. To override at runtime, add a volume mount in als-profiles' `docker-compose.yml`:

```yaml
beam-viewer:
  volumes:
    - /path/to/custom/config.json:/app/config/config.json:ro
```

Then redeploy: `ssh appsdev2 "cd ~/projects/als-profiles && ./scripts/deploy.sh --clean"`

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
