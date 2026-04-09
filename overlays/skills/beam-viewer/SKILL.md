---
name: beam-viewer
description: Beam viewer MCP tool workflows for camera diagnostics — beam capture and analysis, camera setup, ROI-based beam optimization with trending, background subtraction, drift monitoring, and configuration. Use when the user asks to view a beam profile, check beam size, optimize beam, monitor drift, set up a camera, acquire backgrounds, or any beam diagnostic task.
trigger: beam viewer, beam profile, beam size, beam capture, sigma, centroid, ROI, drift, background subtraction, camera, exposure, gain, beam diagnostic, beam optimization, trending
user_invocable: true
---

# Beam Viewer

Operate the beam viewer camera diagnostic system through MCP tools. The beam viewer captures live images from EPICS area detector cameras, performs Gaussian fitting to extract beam parameters (sigma, centroid, amplitude), and supports ROI analysis, background subtraction, drift tracking, and trending.

## Available Tools

| Tool | Description | Key Parameters |
|---|---|---|
| `beam_status` | Connection state, streaming, camera info, frame metadata | — |
| `beam_capture` | Capture current frame as base64 PNG | — |
| `beam_set_camera` | Switch active camera | `prefix` (EPICS PV prefix) |
| `beam_set_exposure` | Set exposure time | `value` (float, seconds) |
| `beam_set_gain` | Set camera gain | `value` (int) |
| `beam_analysis` | Gaussian fit results: sigma, centroid, amplitude (full + ROI) | — |
| `beam_roi_set` | Define region of interest | `x0, y0, x1, y1` (int, pixels) |
| `beam_roi_clear` | Remove ROI | — |
| `beam_roi_center` | Center ROI on current centroid | — |
| `beam_background_acquire` | Capture background frame | — |
| `beam_background_toggle` | Enable/disable background subtraction | `enabled` (bool) |
| `beam_trending` | Sigma, centroid, drift history over recent frames | — |
| `beam_calibration` | Pixel-to-micron calibration info | — |
| `beam_drift` | Centroid drift from reference (px and um) | — |
| `beam_config` | Read or update configuration | `updates` (optional dict) |

## Workflows

### 1. Beam Diagnostic (most common)

Quick check of the current beam state — size, position, and shape.

```
1. beam_status          → verify connected and streaming
2. beam_analysis        → read sigma_x, sigma_y, centroid_x, centroid_y
3. beam_calibration     → check if um_per_pixel is available
4. beam_capture         → grab a snapshot for visual inspection
```

Interpret the results:
- **sigma**: beam size (RMS width of Gaussian fit). Check `x_fit.sigma` and `y_fit.sigma`. If `sigma_um` is available, report in microns.
- **centroid**: beam center position. Large shifts from frame center may indicate steering errors.
- **amplitude**: peak intensity. Low amplitude with high offset suggests poor signal-to-noise.
- **success**: if `false`, the Gaussian fit failed — beam may be clipped, saturated, or absent.

### 2. Camera Setup

Connect to a camera and configure acquisition parameters.

```
1. beam_config          → list available_prefixes
2. beam_set_camera      → select the desired prefix
3. beam_status          → confirm connected=true, streaming=true
4. beam_set_exposure    → adjust exposure (increase if image is dark, decrease if saturated)
5. beam_set_gain        → adjust gain if needed
6. beam_capture         → verify image looks correct
```

**Exposure tuning heuristic**: If `beam_analysis` returns `success: false` and the captured image appears dark (low amplitude), increase exposure. If the image appears saturated (amplitude near max dtype value, e.g., 255 for uint8 or 65535 for uint16), decrease exposure.

### 3. Beam Optimization with ROI + Trending

Focus analysis on a region and monitor beam parameters over time.

```
1. beam_analysis        → get current centroid to know where the beam is
2. beam_roi_set         → place ROI around the beam (e.g., centroid +/- 50 pixels)
3. beam_roi_center      → fine-tune ROI centering on fitted centroid
4. beam_analysis        → check fit_roi results for the ROI region
5. beam_trending        → monitor sigma/centroid stability over recent frames
```

**ROI sizing guidance**: Start with a box ~3-4x the beam sigma around the centroid. Too tight clips the tails and biases the fit; too loose includes noise. After setting the ROI, check that `beam_analysis` still returns `success: true`.

To monitor optimization progress:
- Call `beam_trending` periodically to see if sigma is decreasing (beam getting smaller = better focus)
- Check `centroid_x`/`centroid_y` trending for stability (should be flat when well-steered)
- Use `drift_x`/`drift_y` trending to detect systematic movement

When done: `beam_roi_clear` to return to full-frame analysis.

### 4. Background Subtraction

Remove static background (dark current, stray light) for cleaner analysis.

```
1. [block the beam or close the shutter]
2. beam_background_acquire   → capture background frame
3. beam_background_toggle    → enabled=true
4. [restore beam]
5. beam_analysis             → verify improved fit quality (lower offset, better residual)
```

Check `beam_status` → `background.has_background` to confirm a background was acquired. The `subtraction_enabled` flag shows current state.

**When to use**: Always acquire a fresh background when changing cameras, exposure, or gain. Background frames are specific to the current acquisition settings.

### 5. Drift Monitoring

Track beam position stability over time relative to a reference point.

```
1. beam_analysis        → confirm beam is at desired position
2. beam_drift           → check current drift state
3. [wait / make adjustments]
4. beam_drift           → read drift_x, drift_y (and drift_x_um, drift_y_um if calibrated)
5. beam_trending        → view drift_x/drift_y history for systematic trends
```

Interpret drift results:
- `reference`: the saved centroid reference position
- `live`: current centroid position
- `drift_x`, `drift_y`: delta in pixels
- `drift_x_um`, `drift_y_um`: delta in microns (only if calibrated)
- If `has_reference` is `false`, no reference has been set yet

### 6. Configuration Management

Read or bulk-update settings.

```
# Read all config
beam_config

# Update multiple settings at once
beam_config(updates={"exposure": 0.01, "gain": 5, "colormap": "viridis", "trending_depth": 500})

# Switch camera via config
beam_config(updates={"prefix": "13SIM1:"})
```

Available update keys: `prefix`, `exposure`, `gain`, `colormap`, `trending_depth`, `overlays`.

## Response Schema Reference

### beam_analysis response
```
{
  "fit_full_enabled": true,
  "fit_roi_enabled": false,
  "x_fit": {
    "success": true,
    "sigma": 12.3,           # pixels
    "sigma_um": 45.6,        # microns (null if uncalibrated)
    "centroid": 256.7,        # pixels
    "centroid_um": 950.2,     # microns (null if uncalibrated)
    "amplitude": 4200.0,
    "offset": 120.0,
    "residual": 0.02,
    "unit_label": "um"
  },
  "y_fit": { ... }           # same structure
}
```

### beam_trending response
```
{
  "config": {"visible": true, "depth": 100},
  "history": {
    "count": 87,
    "frame_number": [1, 2, ...],
    "sigma_x": [12.1, 12.3, ...],
    "sigma_y": [10.5, 10.4, ...],
    "centroid_x": [256.7, 256.8, ...],
    "centroid_y": [200.1, 200.0, ...],
    "roi_sigma_x": [...],
    "roi_sigma_y": [...],
    "drift_x": [...],
    "drift_y": [...]
  }
}
```

### beam_drift response
```
{
  "has_reference": true,
  "crosshair_enabled": true,
  "reference": {"x": 256.0, "y": 200.0},
  "live": {"x": 257.2, "y": 199.8},
  "drift_x": 1.2,
  "drift_y": -0.2,
  "drift_x_um": 4.44,
  "drift_y_um": -0.74
}
```
