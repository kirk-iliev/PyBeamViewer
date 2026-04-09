# Side-by-Side Validation: Qt Desktop vs Web Panel

Validation checklist for comparing the original Qt desktop application against the
headless web frontend. Both interfaces should be connected to the same live EPICS
camera so that frames, analysis results, and controls can be compared in real time.

## Prerequisites

| Item | Detail |
|------|--------|
| Qt app | `python main.py --prefix <CAM_PV>` |
| Web panel | `python -m mcp_servers.beam_viewer --prefix <CAM_PV>` then open `http://localhost:8989/panel/` |
| EPICS IOC | Live camera IOC broadcasting Array/Image PVs |
| Browser | Chrome or Firefox with DevTools open for console errors |

---

## 1. Live Beam Image Display

| Aspect | Qt Reference | Web Reference | How to Test | Pass |
|--------|-------------|---------------|-------------|------|
| Image renders | `gui/image_pane.py` `ImagePane` (pyqtgraph `ImageItem`) | `static/js/renderer.js` `Renderer.renderFrame()` (canvas + JPEG decode) | Start streaming on both; verify image appears and updates at comparable rate | [ ] |
| Frame number | `gui/window.py` status bar frame counter | `static/js/app.js` `#frameNum` DOM element | Compare displayed frame numbers; should be close (web may lag 1-2 frames) | [ ] |
| FPS display | `gui/window.py` FPS calculation in `update_display()` | `static/js/app.js` `#fpsVal` DOM element | Both show a non-zero FPS during streaming | [ ] |
| Image dimensions | `gui/window.py` header labels on `ImagePane` | `static/js/app.js` `#dimLabel` | Both report same width x height | [ ] |
| No-signal state | `gui/image_pane.py` blank/black canvas when no frame | `static/js/app.js` `#noSignal` overlay shown when no frame received | Stop the IOC; both should show an empty/no-signal state | [ ] |

---

## 2. Colormap Selection

All 7 colormaps must produce visually matching false-colour images.

| Colormap | Qt (`gui/control_panel.py` `colormap_combo` QComboBox) | Web (`static/js/colormaps.js` LUT + `static/js/app.js` `#cmapSelect`) | Match | Pass |
|----------|------|------|-------|------|
| hot | Default on startup | Default on startup | Warm black-red-yellow-white gradient | [ ] |
| viridis | Select in combo | Select in `<select>` | Blue-green-yellow perceptual map | [ ] |
| inferno | Select in combo | Select in `<select>` | Black-purple-orange-yellow | [ ] |
| plasma | Select in combo | Select in `<select>` | Blue-magenta-orange-yellow | [ ] |
| magma | Select in combo | Select in `<select>` | Black-purple-pink-white | [ ] |
| cividis | Select in combo | Select in `<select>` | Blue-grey-yellow | [ ] |
| gray | Select in combo | Select in `<select>` | Linear grayscale | [ ] |

---

## 3. H/V Projection Plots with Gaussian Fit

| Aspect | Qt Reference | Web Reference | How to Test | Pass |
|--------|-------------|---------------|-------------|------|
| H projection (full) | `gui/projection_plot.py` `ProjectionPlot("h")` in `window.py:h_proj_1` | `static/js/projections.js` `Projections` — H canvas | Both show a smooth horizontal intensity profile | [ ] |
| V projection (full) | `gui/projection_plot.py` `ProjectionPlot("v")` in `window.py:v_proj_1` | `static/js/projections.js` `Projections` — V canvas | Both show a smooth vertical intensity profile | [ ] |
| H projection (ROI) | `gui/projection_plot.py` in `window.py:h_proj_2` | `static/js/projections.js` ROI H canvas | Draw ROI first; profile updates to cropped region | [ ] |
| V projection (ROI) | `gui/projection_plot.py` in `window.py:v_proj_2` | `static/js/projections.js` ROI V canvas | Draw ROI first; profile updates to cropped region | [ ] |
| Gaussian fit overlay | `gui/projection_plot.py` `fit_curve` (dashed line) | `static/js/projections.js` dashed fit line (`FIT_DASH = [6, 4]`) | Enable Fit Full; dashed yellow curve tracks the beam | [ ] |
| Stats label (centroid, sigma) | `gui/projection_plot.py` `stats_label` QLabel | `static/js/projections.js` stats text above each canvas | Compare centroid and sigma values; should agree within rounding | [ ] |
| Fit fails gracefully | Stats show "---" when fit diverges | `static/js/errors.js` `ErrorStates.checkAnalysis()` | Block the beam or use a flat field; both show failure indication | [ ] |

---

## 4. Interactive ROI (Draw, Clear, Center)

| Aspect | Qt Reference | Web Reference | How to Test | Pass |
|--------|-------------|---------------|-------------|------|
| Click-drag to draw | `gui/image_pane.py` `ImagePane(enable_roi=True)` mouse events | `static/js/roi.js` `BeamROI` canvas mouse handlers | Click-drag on the full image in both; rectangle appears | [ ] |
| ROI crop pane updates | `gui/window.py` `image_pane_2` (ROI ImagePane) | `static/js/roi.js` secondary cropped canvas | Cropped sub-image appears matching the selected rectangle | [ ] |
| Clear ROI | `gui/control_panel.py` `clear_roi_btn` ("Clear ROI") | `static/js/roi.js` Clear button (calls `DELETE /roi`) | Press clear; ROI rectangle and crop pane both reset | [ ] |
| Center ROI on centroid | `gui/control_panel.py` `center_roi_btn` ("Center ROI") | `static/js/roi.js` Center button (calls `POST /roi/center`) | Press center; ROI repositions as a square around centroid | [ ] |
| ROI persists across frames | ROI stays until cleared or redrawn | ROI overlay stays until cleared or redrawn | Stream 50+ frames; ROI remains stable | [ ] |

---

## 5. Control Panel (Camera, Exposure, Gain, Streaming)

| Aspect | Qt Reference | Web Reference | How to Test | Pass |
|--------|-------------|---------------|-------------|------|
| Camera selector | `gui/control_panel.py` `prefix_combo` QComboBox | `static/js/controls.js` `prefixSelect` `<select>` | Both list available camera prefixes from config | [ ] |
| Change camera | `window.py` `prefix_change_requested` signal | `controls.js` `POST /camera/prefix` | Select a different camera; both switch to the new PV | [ ] |
| Exposure input + Set | `gui/control_panel.py` `exposure_input` QDoubleSpinBox + `exposure_set_btn` | `static/js/controls.js` `exposureInput` + `exposureBtn` | Enter 0.05 s and press Set; verify PV updates (confirm via `caget`) | [ ] |
| Gain input + Set | `gui/control_panel.py` `gain_input` QSpinBox + `gain_set_btn` | `static/js/controls.js` `gainInput` + `gainBtn` | Enter gain 5 and press Set; verify PV updates | [ ] |
| Streaming toggle | `gui/control_panel.py` `stream_btn` (green when on) | `static/js/controls.js` `streamBtn` toggle | Press to stop streaming; image freezes in both; press again to resume | [ ] |
| Readback sync | `window.py` `update_display()` syncs widgets from `FrameState` | `controls.js` WS frame readback updates inputs | Change exposure via `caput`; both UIs reflect the new value | [ ] |

---

## 6. Background Subtraction (Acquire, Toggle, Save, Load)

| Aspect | Qt Reference | Web Reference | How to Test | Pass |
|--------|-------------|---------------|-------------|------|
| Acquire background | `gui/control_panel.py` `acquire_bg_btn` | `static/js/controls.js` `acquireBgBtn` (calls `POST /background/acquire`) | Press acquire; BG status changes from "BG: none" | [ ] |
| Toggle subtraction | `gui/control_panel.py` `bg_subtract_btn` (checkable) | `static/js/controls.js` `bgSubBtn` toggle | Enable; image contrast changes as background is removed | [ ] |
| BG status label | `gui/control_panel.py` `bg_status_label` | `static/js/controls.js` `bgStatus` div | Shows "BG: acquired" or frame shape after acquire | [ ] |
| Save background | `gui/control_panel.py` `save_bg_btn` | `static/js/controls.js` `saveBgBtn` (calls `POST /background/save`) | Save; file appears in backgrounds directory | [ ] |
| Load background | `gui/control_panel.py` `load_bg_btn` + `gui/dialogs.py` `LoadBackgroundDialog` | `static/js/controls.js` `loadBgBtn` + file list select | Load a previously saved .npy; BG status updates | [ ] |
| Subtract + ROI | Both apply subtraction before ROI crop | Both apply subtraction before ROI crop | Draw ROI with BG sub on; cropped image shows subtracted data | [ ] |

---

## 7. Trending Panel (8 Charts, Depth Control)

| Aspect | Qt Reference | Web Reference | How to Test | Pass |
|--------|-------------|---------------|-------------|------|
| Panel visibility | `gui/trending_panel.py` `TrendingPanel` (hidden by default) | `static/js/trending.js` `Trending` (collapsed by default) | Toggle "Trending" button; panel appears/disappears | [ ] |
| Full-image sigma_x / sigma_y | `trending_panel.py` `full_sigma_plot` (`_TrendSubPlot`) | `trending.js` charts for `sigma_x`, `sigma_y` | Enable Fit Full + Trending; both show sigma traces | [ ] |
| ROI sigma_x / sigma_y | `trending_panel.py` `roi_sigma_plot` | `trending.js` charts for `roi_sigma_x`, `roi_sigma_y` | Enable Fit ROI + Trending; both show ROI sigma traces | [ ] |
| Centroid X / Y | (Qt trending derives from `analysis.trending_buffer`) | `trending.js` charts for `centroid_x`, `centroid_y` | Enable trending; centroid position tracks over time | [ ] |
| Drift X / Y | `trending_panel.py` `drift_plot` | `trending.js` charts for `drift_x`, `drift_y` | Set centroid reference + enable trending; drift traces appear | [ ] |
| Auto-scroll X axis | `trending_panel.py` `_TrendSubPlot.update_data()` sets X range | `trending.js` auto-scrolls canvas X axis | Let run for 100+ frames; old data scrolls off the left edge | [ ] |
| Depth control | `gui/control_panel.py` `trending_depth_input` QSpinBox (50-2000) | `static/js/controls.js` depth input (calls `POST /trending/depth`) | Change depth to 100; charts show only last 100 frames | [ ] |
| NaN handling | `_TrendSubPlot.update_data()` filters NaN with `~np.isnan()` | `trending.js` skips null/NaN data points | Disable Fit ROI while trending is on; ROI sigma lines disappear cleanly | [ ] |

---

## 8. Projection Overlays on Image (H/V, Side, Scale)

| Aspect | Qt Reference | Web Reference | How to Test | Pass |
|--------|-------------|---------------|-------------|------|
| H overlay toggle | `gui/control_panel.py` `h_overlay_btn` | `static/js/overlays.js` `Overlays` — H toggle in CP section | Enable H overlay; projection curve drawn on image | [ ] |
| V overlay toggle | `gui/control_panel.py` `v_overlay_btn` | `static/js/overlays.js` `Overlays` — V toggle in CP section | Enable V overlay; projection curve drawn on image | [ ] |
| H side selector (Bottom/Top) | `gui/control_panel.py` `h_overlay_side` QComboBox | `static/js/overlays.js` H side `<select>` | Switch to "Top"; overlay moves to top edge of image | [ ] |
| V side selector (Left/Right) | `gui/control_panel.py` `v_overlay_side` QComboBox | `static/js/overlays.js` V side `<select>` | Switch to "Right"; overlay moves to right edge of image | [ ] |
| Scale slider (5%-50%) | `gui/control_panel.py` `overlay_scale_slider` QSlider + `overlay_scale_label` | `static/js/overlays.js` scale range input | Drag to 40%; overlay height grows proportionally | [ ] |
| Show on Full pane | `gui/control_panel.py` `overlay_show_full_btn` | `static/js/overlays.js` "Show Full" toggle | Toggle off; overlay disappears from full image only | [ ] |
| Show on ROI pane | `gui/control_panel.py` `overlay_show_roi_btn` | `static/js/overlays.js` "Show ROI" toggle | Toggle on; overlay appears on ROI crop pane | [ ] |

---

## 9. Crosshair and Drift Tracking (dx/dy in px and um)

| Aspect | Qt Reference | Web Reference | How to Test | Pass |
|--------|-------------|---------------|-------------|------|
| Set centroid reference | `gui/control_panel.py` `center_roi_btn` -> `window.py` `centroid_reference_changed` signal | `static/js/roi.js` Center button -> `static/js/overlays.js` stores reference | Press "Center ROI"; reference crosshair appears at centroid | [ ] |
| Crosshair visibility | `gui/control_panel.py` `show_crosshair_btn` (checkable) | `static/js/overlays.js` crosshair toggle in Overlays section | Toggle on; crosshair lines drawn on image at reference position | [ ] |
| Live crosshair | `gui/window.py` draws live centroid crosshair each frame | `static/js/overlays.js` draws live centroid position | Both show a second crosshair tracking the current beam center | [ ] |
| Drift label (px) | `gui/window.py` `drift_label` QLabel shows "dx: ... dy: ... px" | `static/js/overlays.js` drift text overlay on canvas | Move the beam; both show pixel drift values and they agree | [ ] |
| Drift label (um) | `gui/window.py` drift_label shows um when calibrated (`analysis/calibration.py`) | `static/js/overlays.js` shows um when `calibration.is_calibrated` | Load a calibration; drift label includes um values | [ ] |
| Drift resets on re-center | `gui/window.py` resets `_centroid_reference` and drift | `static/js/overlays.js` resets reference on center | Press "Center ROI" again; drift resets to zero | [ ] |

---

## 10. Error States (EPICS Disconnect, Fit Failure, No Camera)

| Aspect | Qt Reference | Web Reference | How to Test | Pass |
|--------|-------------|---------------|-------------|------|
| EPICS disconnect banner | `gui/window.py` connection status handling | `static/js/errors.js` `ErrorStates.showDisconnected()` — polls `GET /health` | Kill the IOC; disconnection banner appears in both | [ ] |
| Reconnect recovery | Qt reconnects via `core/epics_layer.py` auto-retry | Web banner clears when `/health` returns OK | Restart the IOC; both recover without manual intervention | [ ] |
| Fit failure indication | `gui/projection_plot.py` stats show "---" when fit is None | `static/js/errors.js` `ErrorStates.showFitFailed("x"/"y")` | Block the beam (flat field); fit failure shown in both | [ ] |
| No camera state | `gui/window.py` empty state before first frame | `static/js/errors.js` `ErrorStates.showNoCameraState()` | Start with an invalid prefix; no-camera message appears | [ ] |
| WebSocket reconnect | (N/A for Qt — uses EPICS directly) | `static/js/connection.js` exponential backoff reconnect | Kill the headless server; web shows "Reconnecting..." then recovers | [ ] |

---

## 11. Dark/Light Theme Toggle

| Aspect | Qt Reference | Web Reference | How to Test | Pass |
|--------|-------------|---------------|-------------|------|
| Default theme | `gui/theme.py` `DARK` dataclass — dark background | `static/js/theme.js` `ThemeManager.init()` — `data-theme="dark"` | Both start in dark mode | [ ] |
| Toggle to light | `gui/theme.py` `LIGHT` dataclass + `window.py` `_toggle_theme()` | `static/js/theme.js` `toggle()` sets `data-theme="light"` | Press theme button; background, text, plot chrome all switch to light | [ ] |
| Toggle back to dark | Press again in Qt | Press again in web | Colours revert to dark theme | [ ] |
| Plot backgrounds update | `gui/projection_plot.py` `apply_theme()` updates pyqtgraph bg | CSS custom properties update canvas/chart backgrounds | Projection plot and trending chart backgrounds match the theme | [ ] |
| Curve colours update | `gui/trending_panel.py` `apply_theme()` re-pens curves | `static/js/projections.js` / `trending.js` use CSS vars | Data curves remain visible and match expected colours in both themes | [ ] |
| Persistence | Qt: not persisted (defaults to dark on restart) | Web: `localStorage` key `pybeamviewer-theme` | Reload web page; theme is remembered. Restart Qt app; defaults to dark | [ ] |

---

## Summary

| Category | Items | Passed | Failed | Notes |
|----------|-------|--------|--------|-------|
| 1. Live beam image | 5 | | | |
| 2. Colormap selection | 7 | | | |
| 3. Projection plots | 7 | | | |
| 4. Interactive ROI | 5 | | | |
| 5. Control panel | 6 | | | |
| 6. Background subtraction | 6 | | | |
| 7. Trending panel | 8 | | | |
| 8. Projection overlays | 7 | | | |
| 9. Crosshair / drift | 6 | | | |
| 10. Error states | 5 | | | |
| 11. Theme toggle | 6 | | | |
| **Total** | **68** | | | |

---

## How to Run

1. Start the EPICS camera IOC.
2. Launch the Qt app: `python main.py --prefix <CAM_PV>`.
3. Launch the headless web server: `python -m mcp_servers.beam_viewer --prefix <CAM_PV>`.
4. Open `http://localhost:8989/panel/` in a browser.
5. Walk through each section above, checking items as they pass.
6. Record any discrepancies in the **Notes** column of the summary table.
