# Layout Parity: PyQt Desktop App vs Web Panel

The web panel must match the PyQt desktop application layout. The PyQt GUI code (`gui/*.py`) is the source of truth.

## Evaluation Strategy

1. **Playwright structural tests** (`tests/e2e/layout-parity.spec.js`) — 48 tests asserting every widget, section, and control exists in the correct position
2. **Run against live container** via SSH tunnel:
   ```bash
   ssh -L 8007:localhost:8007 -N -f appsdev2
   npx playwright test tests/e2e/layout-parity.spec.js --reporter=list
   ```

## PyQt Layout Source of Truth

### Overall Structure
- Main window: 1500x920px default
- Horizontal splitter: image/projections (left, 5x weight) + control panel (right, 1x weight)
- Status bar at bottom: theme toggle (left), frame counter (right)

### Image Area (Left)
- **Full Image pane** — pyqtgraph PlotWidget, aspect-locked, Y-inverted
- **ROI pane** — hidden until ROI drawn, same as full image but cropped
- **Drift label** — hidden until crosshair enabled, monospace, green

### Projections (Center Column)
- **H Projection (Full)** — title, stats label (sigma/centroid/amp), plot with cyan curve + red dashed fit
- **V Projection (Full)** — same layout, lavender curve
- **H Projection (ROI)** — hidden until ROI, same as full
- **V Projection (ROI)** — hidden until ROI, same as full

### Trending Panel (Optional Column)
- Hidden by default, shown via "Trending" button
- Sub-plots: ROI Beam Size, Full Image Beam Size, Centroid Drift
- Each has title, stats label, two curves (A/B)

### Control Panel (Right, 320px fixed)
Scrollable, 5 groups with 8px spacing:

#### Group 1: Camera Setup
| Widget | Type | Details |
|--------|------|---------|
| Camera | QComboBox | Prefix dropdown, dynamically populated |
| Exposure (s) | QDoubleSpinBox + "Set" | Range 0.0001-30, decimals 4 |
| Gain | QSpinBox + "Set" | Range 0-40 |

#### Group 2: Acquire
| Widget | Type | Details |
|--------|------|---------|
| Streaming/Paused | Toggle button | Green when streaming, red when paused |
| Acquire Background | Button | Captures current frame as BG |
| Background Sub | Toggle button | Disabled until BG acquired |
| BG status | Label | "BG: none" / "BG: acquired \| Sub: ON" |
| Save BG / Load BG | Two buttons | Save disabled until BG acquired |

#### Group 3: Analysis
| Widget | Type | Details |
|--------|------|---------|
| Fit Full Image | Toggle button | Checked by default |
| Fit ROI | Toggle button | Unchecked by default |
| Clear ROI | Button | Disabled until ROI drawn |
| Center ROI | Button | Disabled until ROI drawn |
| Show Centroid Ref | Toggle button | Shows crosshair + drift |
| Trending | Toggle button | Shows/hides trending panel |
| History depth | SpinBox | 50-2000, default 300, suffix " frames" |

#### Group 4: Image Settings
| Widget | Type | Details |
|--------|------|---------|
| Colormap | QComboBox | hot, viridis, inferno, plasma, magma, cividis, gray |

#### Group 5: Projection Overlays
| Widget | Type | Details |
|--------|------|---------|
| H Overlay | Toggle button | Horizontal projection overlay |
| H side | QComboBox | Bottom / Top |
| V Overlay | Toggle button | Vertical projection overlay |
| V side | QComboBox | Left / Right |
| Scale | Slider | 5%-50%, default 25% |
| Show on: Full / ROI | Two toggle buttons | Scope of overlays |

### Status Bar
- Left: Theme toggle ("Light" / "Dark")
- Right: "Frame: {n} | {fps} Hz"

### Theme Colors
| Token | Dark | Light |
|-------|------|-------|
| bg | #141423 | #f0f2f5 |
| surface | #16213e | #ffffff |
| border | #1a3a5c | #c8ccd8 |
| accent | #00adb5 | #0077b6 |
| text | #e0e0e0 | #1a1a2e |
| text-dim | #7a7a9a | #6b6b85 |
| h-curve | #00e5ff | #0077b6 |
| v-curve | #ce93d8 | #7b2d8b |
| fit-curve | #ff5555 | #c0392b |

## Known Gaps (Web vs PyQt)

Track these here as they're discovered. When all are resolved, the web panel achieves 100% parity.

| Gap | PyQt | Web | Status |
|-----|------|-----|--------|
| Projections layout | 4 plots in separate column | 2 canvases in right column (H + V stacked) | Partial — column layout done, ROI projection canvases not yet added |
| Control panel width | 320px | 320px | Resolved |
| Header/toolbar | No separate header; all in status bar | Theme + frame counter in status bar, no header/toolbar | Resolved |
| Trending layout | Column in splitter, 3 sub-plots | Column in viewer area, 3 dual-trace sub-plots | Resolved |
| Control panel groups | 5 groups: Camera Setup, Acquire, Analysis, Image Settings, Projection Overlays | 6 sections: Camera Setup, Acquisition, Background, Display, ROI, Overlays | Open — web splits Acquire into Acquisition+Background, Analysis controls split across sections |
| ROI image pane | Separate image pane below full image | Preview inside ROI control panel section | Open — structural difference |
