/**
 * Layout Parity Tests — PyQt Desktop App vs Web Panel
 *
 * These tests enforce that the web panel matches the PyQt desktop
 * application layout. The PyQt GUI code (gui/*.py) is the source of truth.
 *
 * Reference: gui/window.py, gui/control_panel.py, gui/image_pane.py,
 *            gui/projection_plot.py, gui/trending_panel.py
 *
 * Run: npx playwright test tests/e2e/layout-parity.spec.js --reporter=list
 * Requires: SSH tunnel to appsdev2 (ssh -L 8007:localhost:8007 -N appsdev2)
 */

const { test, expect } = require('@playwright/test');

test.describe('Layout Parity: PyQt ↔ Web Panel', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/panel');
    await page.waitForLoadState('networkidle');
  });

  // ===================================================================
  // OVERALL STRUCTURE
  // PyQt: QMainWindow with outer QSplitter (images+projs | control panel)
  //        + QStatusBar (theme toggle left, frame counter right)
  //        No separate header or toolbar row.
  // ===================================================================

  test.describe('Overall Structure', () => {

    test('main layout has viewer area and right-side control panel', async ({ page }) => {
      // PyQt: outer_splitter with inner content (left) + ControlPanel (right)
      const main = page.locator('.main');
      await expect(main).toBeVisible();

      const viewer = page.locator('.viewer-area');
      await expect(viewer).toBeVisible();

      const controlPanel = page.locator('.control-panel, #controlPanel');
      await expect(controlPanel).toBeVisible();
    });

    test('control panel is on the right side of the viewer area', async ({ page }) => {
      const viewer = await page.locator('.viewer-area').boundingBox();
      const panel = await page.locator('.control-panel, #controlPanel').boundingBox();
      expect(panel.x).toBeGreaterThan(viewer.x);
    });

    test('no separate header or toolbar rows exist', async ({ page }) => {
      // PyQt has no header/toolbar — all status in the status bar
      const header = page.locator('.header');
      await expect(header).toHaveCount(0);
      const toolbar = page.locator('.toolbar');
      await expect(toolbar).toHaveCount(0);
    });

    test('status bar exists at the bottom', async ({ page }) => {
      const statusBar = page.locator('.status-bar');
      await expect(statusBar).toBeVisible();
    });

    test('status bar has frame counter', async ({ page }) => {
      // PyQt: frame_label with "Frame: {n} | {fps} Hz" in status bar
      const frameNum = page.locator('#frameNum');
      const fpsVal = page.locator('#fpsVal');
      await expect(frameNum).toBeAttached();
      await expect(fpsVal).toBeAttached();
    });

    test('theme toggle is in the status bar', async ({ page }) => {
      // PyQt: _theme_btn in status bar (left side), text "Light"/"Dark"
      const statusBar = page.locator('.status-bar');
      const themeBtn = statusBar.locator('#themeToggle');
      await expect(themeBtn).toBeVisible();
      const text = await themeBtn.textContent();
      expect(text).toMatch(/light|dark/i);
    });
  });

  // ===================================================================
  // IMAGE AREA
  // PyQt: ImagePane with pg.PlotWidget, header "Full Image"
  // ===================================================================

  test.describe('Image Display', () => {

    test('beam image canvas exists', async ({ page }) => {
      const canvas = page.locator('#beamCanvas');
      await expect(canvas).toBeVisible();
    });

    test('"waiting for frames" message shown when no data', async ({ page }) => {
      // PyQt: image is black until EPICS connects; web shows explicit message
      const msg = page.locator('.no-signal');
      await expect(msg).toBeAttached();
    });

    test('image is in the left column of the viewer area', async ({ page }) => {
      // PyQt: images column is leftmost in the inner splitter
      const viewer = await page.locator('.viewer-area').boundingBox();
      const imageCol = await page.locator('.image-column').boundingBox();
      if (viewer && imageCol) {
        expect(imageCol.x).toBe(viewer.x);
      }
    });
  });

  // ===================================================================
  // PROJECTION PLOTS
  // PyQt: 4 ProjectionPlots in a separate column to the RIGHT of images
  //        H full, V full (stacked), H ROI + V ROI (hidden until ROI)
  // ===================================================================

  test.describe('Projection Plots', () => {

    test('horizontal projection canvas exists', async ({ page }) => {
      // PyQt: h_proj_1 "Horizontal Projection (Full Image)"
      const hProj = page.locator('#hProjCanvas');
      await expect(hProj).toBeAttached();
    });

    test('vertical projection canvas exists', async ({ page }) => {
      // PyQt: v_proj_1 "Vertical Projection (Full Image)"
      const vProj = page.locator('#vProjCanvas');
      await expect(vProj).toBeAttached();
    });

    test('projections are in a column to the right of the image', async ({ page }) => {
      // PyQt: proj_col is the second widget in the inner splitter
      const imageCol = await page.locator('.image-column').boundingBox();
      const projCol = await page.locator('.proj-column').boundingBox();
      if (imageCol && projCol) {
        expect(projCol.x).toBeGreaterThanOrEqual(imageCol.x + imageCol.width - 2);
      }
    });

    test('H and V projections are stacked vertically', async ({ page }) => {
      // PyQt: h_proj_1 and v_proj_1 are stacked in proj_col
      const projAreas = page.locator('.proj-area');
      const count = await projAreas.count();
      expect(count).toBeGreaterThanOrEqual(2);

      const first = await projAreas.nth(0).boundingBox();
      const second = await projAreas.nth(1).boundingBox();
      if (first && second) {
        // V projection should be below H projection
        expect(second.y).toBeGreaterThanOrEqual(first.y + first.height - 2);
        // Both should have the same x position (same column)
        expect(Math.abs(second.x - first.x)).toBeLessThan(2);
      }
    });
  });

  // ===================================================================
  // CONTROL PANEL — GROUP 1: Camera Setup
  // PyQt: QGroupBox "Camera Setup" with prefix_combo, exposure_input,
  //        exposure_set_btn, gain_input, gain_set_btn
  // ===================================================================

  test.describe('Control Panel — Camera Setup', () => {

    test('Camera Setup section exists', async ({ page }) => {
      const header = page.locator('.cp-section-header', { hasText: /camera/i });
      await expect(header).toBeVisible();
    });

    test('camera prefix dropdown exists', async ({ page }) => {
      // PyQt: prefix_combo (QComboBox) labeled "Camera:"
      const cameraSection = page.locator('.cp-section', { hasText: /camera/i }).first();
      const selects = cameraSection.locator('select');
      await expect(selects.first()).toBeVisible();
    });

    test('exposure input and Set button exist', async ({ page }) => {
      // PyQt: exposure_input (QDoubleSpinBox) + exposure_set_btn ("Set")
      const section = page.locator('.cp-section', { hasText: /camera/i }).first();
      const expInput = section.locator('input[type="number"]').first();
      await expect(expInput).toBeVisible();
      const setBtn = section.locator('button', { hasText: /set/i }).first();
      await expect(setBtn).toBeVisible();
    });

    test('gain input and Set button exist', async ({ page }) => {
      // PyQt: gain_input (QSpinBox) + gain_set_btn ("Set")
      const section = page.locator('.cp-section', { hasText: /camera/i }).first();
      const inputs = section.locator('input[type="number"]');
      // Should have at least 2 numeric inputs: exposure and gain
      expect(await inputs.count()).toBeGreaterThanOrEqual(2);
      const setBtns = section.locator('button', { hasText: /set/i });
      expect(await setBtns.count()).toBeGreaterThanOrEqual(2);
    });
  });

  // ===================================================================
  // CONTROL PANEL — GROUP 2: Acquire
  // PyQt: QGroupBox "Acquire" with stream_btn, acquire_bg_btn,
  //        bg_subtract_btn, bg_status_label, save_bg_btn, load_bg_btn
  // ===================================================================

  test.describe('Control Panel — Acquire / Streaming', () => {

    test('streaming toggle button exists', async ({ page }) => {
      // PyQt: stream_btn — checkable, "Streaming"/"Paused"
      const btn = page.locator('button', { hasText: /stream/i });
      await expect(btn).toBeVisible();
    });

    test('acquire background button exists', async ({ page }) => {
      // PyQt: acquire_bg_btn — "Acquire Background"
      const btn = page.locator('button', { hasText: /acquire.*background/i });
      await expect(btn).toBeVisible();
    });

    test('background subtraction toggle exists', async ({ page }) => {
      // PyQt: bg_subtract_btn — checkable, "Background Sub"
      const btn = page.locator('button', { hasText: /background sub/i });
      await expect(btn).toBeVisible();
    });

    test('background status label exists', async ({ page }) => {
      // PyQt: bg_status_label — "BG: none" / "BG: acquired | Sub: ON"
      const status = page.locator(':text("BG:")');
      await expect(status).toBeVisible();
    });

    test('save and load background buttons exist', async ({ page }) => {
      // PyQt: save_bg_btn ("Save BG") + load_bg_btn ("Load BG")
      const saveBtn = page.locator('button', { hasText: /save.*bg/i });
      const loadBtn = page.locator('button', { hasText: /load.*bg/i });
      await expect(saveBtn).toBeVisible();
      await expect(loadBtn).toBeVisible();
    });
  });

  // ===================================================================
  // CONTROL PANEL — GROUP 3: Analysis
  // PyQt: QGroupBox "Analysis" with fit_full_btn, fit_roi_btn,
  //        clear_roi_btn, center_roi_btn, show_crosshair_btn,
  //        trending_btn, trending_depth_input
  // ===================================================================

  test.describe('Control Panel — Analysis', () => {

    test('fit full image toggle exists', async ({ page }) => {
      // PyQt: fit_full_btn — checkable, "Fit Full Image" / "Fit Full"
      const btn = page.locator('button', { hasText: /fit.*full/i });
      await expect(btn).toBeVisible();
    });

    test('fit ROI toggle exists', async ({ page }) => {
      // PyQt: fit_roi_btn — checkable, "Fit ROI"
      const btn = page.locator('button', { hasText: /fit.*roi/i });
      await expect(btn).toBeVisible();
    });

    test('clear ROI button exists', async ({ page }) => {
      // PyQt: clear_roi_btn — "Clear ROI" (with x symbol)
      const btn = page.locator('button', { hasText: /clear/i });
      await expect(btn).toBeVisible();
    });

    test('center ROI button exists', async ({ page }) => {
      // PyQt: center_roi_btn — "Center ROI" (with crosshair symbol)
      const btn = page.locator('button', { hasText: /center/i });
      await expect(btn).toBeVisible();
    });

    test('show crosshair / centroid reference toggle exists', async ({ page }) => {
      // PyQt: show_crosshair_btn — "Show Centroid Ref"
      const btn = page.locator('button', { hasText: /crosshair|centroid/i });
      await expect(btn).toBeVisible();
    });

    test('trending toggle button exists in control panel', async ({ page }) => {
      // PyQt: trending_btn — checkable, "Trending" (in Analysis group)
      const panel = page.locator('#controlPanel');
      const btn = panel.locator('button', { hasText: /trending/i });
      await expect(btn).toBeVisible();
    });

    test('trending history depth input exists', async ({ page }) => {
      // PyQt: trending_depth_input — QSpinBox, range 50-2000, default 300
      const input = page.locator('#trendingDepth');
      await expect(input).toBeAttached();
      const val = await input.inputValue();
      expect(parseInt(val)).toBe(300);
    });
  });

  // ===================================================================
  // CONTROL PANEL — GROUP 4: Image Settings
  // PyQt: QGroupBox "Image Settings" with colormap_combo
  // ===================================================================

  test.describe('Control Panel — Image Settings / Display', () => {

    test('colormap dropdown exists with all 7 options', async ({ page }) => {
      // PyQt: colormap_combo — ["hot","viridis","inferno","plasma","magma","cividis","gray"]
      // Colormap is in the control panel Display section (not toolbar)
      const panel = page.locator('#controlPanel');
      const selects = panel.locator('select');
      // Find the colormap select by checking for 'hot' option
      let cmapSelect = null;
      for (let i = 0; i < await selects.count(); i++) {
        const options = await selects.nth(i).locator('option').evaluateAll(
          els => els.map(el => el.value)
        );
        if (options.includes('hot') && options.includes('viridis')) {
          cmapSelect = selects.nth(i);
          break;
        }
      }
      expect(cmapSelect).not.toBeNull();
      const values = await cmapSelect.locator('option').evaluateAll(
        els => els.map(el => el.value)
      );
      expect(values).toContain('hot');
      expect(values).toContain('viridis');
      expect(values).toContain('inferno');
      expect(values).toContain('plasma');
      expect(values).toContain('magma');
      expect(values).toContain('cividis');
      expect(values).toContain('gray');
      expect(values).toHaveLength(7);
    });
  });

  // ===================================================================
  // CONTROL PANEL — GROUP 5: Projection Overlays
  // PyQt: QGroupBox "Projection Overlays" with h_overlay_btn,
  //        h_overlay_side, v_overlay_btn, v_overlay_side,
  //        overlay_scale_slider, overlay_show_full_btn, overlay_show_roi_btn
  // ===================================================================

  test.describe('Control Panel — Projection Overlays', () => {

    test('H overlay toggle exists', async ({ page }) => {
      // PyQt: h_overlay_btn — checkable, "H Overlay"
      const btn = page.locator('button', { hasText: /h.*overlay/i });
      await expect(btn).toBeVisible();
    });

    test('V overlay toggle exists', async ({ page }) => {
      // PyQt: v_overlay_btn — checkable, "V Overlay"
      const btn = page.locator('button', { hasText: /v.*overlay/i });
      await expect(btn).toBeVisible();
    });

    test('H overlay side selector exists with bottom/top options', async ({ page }) => {
      // PyQt: h_overlay_side — QComboBox ["Bottom","Top"]
      const select = page.locator('select').filter({ hasText: /bottom|top/i });
      await expect(select).toBeVisible();
    });

    test('V overlay side selector exists with left/right options', async ({ page }) => {
      // PyQt: v_overlay_side — QComboBox ["Left","Right"]
      const select = page.locator('select').filter({ hasText: /left|right/i });
      await expect(select).toBeVisible();
    });

    test('overlay scale slider exists', async ({ page }) => {
      // PyQt: overlay_scale_slider — QSlider, range 5-50 (5%-50%)
      const slider = page.locator('input[type="range"]');
      await expect(slider).toBeVisible();
    });

    test('show-on-full and show-on-ROI toggles exist', async ({ page }) => {
      // PyQt: overlay_show_full_btn ("Full") + overlay_show_roi_btn ("ROI")
      // These are scope toggles for where overlays display
      const fullBtn = page.locator('button', { hasText: /^full$/i });
      const roiBtn = page.locator('button', { hasText: /^roi$/i });
      await expect(fullBtn).toBeVisible();
      await expect(roiBtn).toBeVisible();
    });
  });

  // ===================================================================
  // CONTROL PANEL — All 5 groups present
  // PyQt groups: Camera Setup, Acquire, Analysis, Image Settings,
  //              Projection Overlays
  // Web groups: Camera Setup, Acquisition, Background, Display, ROI, Overlays
  // ===================================================================

  test.describe('Control Panel — Section Completeness', () => {

    test('has Camera Setup section', async ({ page }) => {
      const section = page.locator('.cp-section-header', { hasText: /camera/i });
      await expect(section).toBeVisible();
    });

    test('has Acquisition section', async ({ page }) => {
      const section = page.locator('.cp-section-header', { hasText: /acqui/i });
      await expect(section).toBeVisible();
    });

    test('has Background section', async ({ page }) => {
      // PyQt groups bg controls under "Acquire"; web separates them
      const section = page.locator('.cp-section-header', { hasText: /background/i });
      await expect(section).toBeVisible();
    });

    test('has Display / Image Settings section', async ({ page }) => {
      const section = page.locator('.cp-section-header', { hasText: /display|image.*settings/i });
      await expect(section).toBeVisible();
    });

    test('has ROI section', async ({ page }) => {
      const section = page.locator('.cp-section-header', { hasText: /roi/i });
      await expect(section).toBeVisible();
    });

    test('has Overlays section', async ({ page }) => {
      const section = page.locator('.cp-section-header', { hasText: /overlay/i });
      await expect(section).toBeVisible();
    });
  });

  // ===================================================================
  // TRENDING PANEL
  // PyQt: TrendingPanel in inner splitter (column), 3 dual-trace sub-plots
  //        ROI Beam Size, Full Image Beam Size, Centroid Drift
  // ===================================================================

  test.describe('Trending Panel', () => {

    test('trending panel exists (hidden by default)', async ({ page }) => {
      // PyQt: trending_panel hidden by default, shown via trending_btn
      const panel = page.locator('#trendingPanel');
      await expect(panel).toBeAttached();
      // Should be hidden initially
      await expect(panel).not.toBeVisible();
    });

    test('clicking trending toggle shows the panel', async ({ page }) => {
      // Trending toggle is in the control panel (not toolbar)
      const panel = page.locator('#controlPanel');
      const toggle = panel.locator('button', { hasText: /trending/i }).first();
      await toggle.click();
      const trendingPanel = page.locator('#trendingPanel');
      await expect(trendingPanel).toBeVisible();
    });

    test('trending panel has 3 sub-plot cells', async ({ page }) => {
      // PyQt: 3 stacked sub-plots (Full σ, ROI σ, Drift)
      const panel = page.locator('#controlPanel');
      const toggle = panel.locator('button', { hasText: /trending/i }).first();
      await toggle.click();
      const cells = page.locator('.trending-cell');
      expect(await cells.count()).toBe(3);
    });

    test('trending panel is a column in the viewer area', async ({ page }) => {
      // PyQt: trending is the 3rd column in the inner splitter
      const panel = page.locator('#controlPanel');
      const toggle = panel.locator('button', { hasText: /trending/i }).first();
      await toggle.click();
      const trendingCol = page.locator('.trending-column');
      await expect(trendingCol).toBeVisible();
      // Should be inside the viewer area
      const viewer = page.locator('.viewer-area');
      await expect(viewer.locator('.trending-column')).toBeAttached();
    });
  });

  // ===================================================================
  // THEME SYSTEM
  // PyQt: DARK and LIGHT themes with matching color tokens
  // ===================================================================

  test.describe('Theme System', () => {

    test('starts in dark theme', async ({ page }) => {
      // PyQt: dark theme is default
      const theme = await page.locator('html').getAttribute('data-theme');
      expect(theme).toBe('dark');
    });

    test('theme toggle switches to light', async ({ page }) => {
      const btn = page.locator('#themeToggle');
      await btn.click();
      const theme = await page.locator('html').getAttribute('data-theme');
      expect(theme).toBe('light');
    });

    test('dark theme uses correct accent color', async ({ page }) => {
      // PyQt dark: accent=#00adb5
      const accent = await page.evaluate(() =>
        getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()
      );
      expect(accent).toBe('#00adb5');
    });
  });

  // ===================================================================
  // CONNECTION STATUS
  // PyQt: health endpoint, status bar
  // ===================================================================

  test.describe('Connection Status', () => {

    test('status dot indicator exists in status bar', async ({ page }) => {
      const statusBar = page.locator('.status-bar');
      const dot = statusBar.locator('.status-dot, #statusDot');
      await expect(dot).toBeVisible();
    });

    test('status text exists in status bar', async ({ page }) => {
      const statusBar = page.locator('.status-bar');
      const text = statusBar.locator('#statusText');
      await expect(text).toBeAttached();
    });
  });
});
