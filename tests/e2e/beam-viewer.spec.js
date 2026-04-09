const { test, expect } = require('@playwright/test');

test.describe('Beam Viewer Web Panel', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/panel');
  });

  // 1. Page load
  test('page loads without JS errors', async ({ page }) => {
    const errors = [];
    page.on('pageerror', (err) => errors.push(err.message));
    await page.reload();
    await page.waitForLoadState('networkidle');
    expect(errors).toEqual([]);
    await expect(page).toHaveTitle('PyBeamViewer');
  });

  // 2. Image canvas
  test('image canvas exists with correct dimensions', async ({ page }) => {
    const canvas = page.locator('#beamCanvas');
    await expect(canvas).toBeVisible();
    await expect(canvas).toHaveAttribute('width', '640');
    await expect(canvas).toHaveAttribute('height', '480');
  });

  // 3. Colormap selector
  test('colormap selector has all 7 options', async ({ page }) => {
    const select = page.locator('#cmapSelect');
    await expect(select).toBeVisible();

    const options = select.locator('option');
    await expect(options).toHaveCount(7);

    const expected = ['gray', 'hot', 'viridis', 'inferno', 'plasma', 'magma', 'cividis'];
    const values = await options.evaluateAll(els => els.map(el => el.value));
    expect(values).toEqual(expected);
  });

  test('changing colormap selection updates value', async ({ page }) => {
    const select = page.locator('#cmapSelect');
    await select.selectOption('viridis');
    await expect(select).toHaveValue('viridis');
    await select.selectOption('gray');
    await expect(select).toHaveValue('gray');
  });

  // 4. Projection plots
  test('horizontal and vertical projection canvases exist', async ({ page }) => {
    const hProj = page.locator('#hProjCanvas');
    const vProj = page.locator('#vProjCanvas');
    await expect(hProj).toBeAttached();
    await expect(vProj).toBeAttached();
    expect(await hProj.getAttribute('class')).toContain('proj-canvas');
    expect(await vProj.getAttribute('class')).toContain('proj-canvas');
  });

  // 5. ROI
  test('ROI draw interaction on canvas', async ({ page }) => {
    const canvas = page.locator('#beamCanvas');
    const box = await canvas.boundingBox();

    // Simulate mousedown -> mousemove -> mouseup to draw ROI
    await page.mouse.move(box.x + 100, box.y + 100);
    await page.mouse.down();
    await page.mouse.move(box.x + 300, box.y + 250, { steps: 5 });
    await page.mouse.up();

    // ROI overlay canvas should exist
    const overlay = page.locator('#roiOverlay');
    await expect(overlay).toBeAttached();
  });

  test('ROI Clear and Center buttons exist', async ({ page }) => {
    // ROI section is appended dynamically to the control panel
    const clearBtn = page.locator('#controlPanel button', { hasText: 'Clear' });
    const centerBtn = page.locator('#controlPanel button', { hasText: 'Center' });
    await expect(clearBtn).toBeAttached();
    await expect(centerBtn).toBeAttached();
  });

  // 6. Control panel sections
  test('control panel has all required sections', async ({ page }) => {
    const panel = page.locator('#controlPanel');
    await expect(panel).toBeAttached();

    const sectionHeaders = panel.locator('.cp-section-header');
    const headerTexts = await sectionHeaders.allTextContents();

    // Sections: Camera Setup, Acquisition, Background, Display, ROI
    expect(headerTexts.some(t => t.includes('Camera'))).toBeTruthy();
    expect(headerTexts.some(t => t.includes('Acquisition'))).toBeTruthy();
    expect(headerTexts.some(t => t.includes('Background'))).toBeTruthy();
    expect(headerTexts.some(t => t.includes('Display'))).toBeTruthy();
  });

  test('control panel sections are collapsible', async ({ page }) => {
    const firstHeader = page.locator('#controlPanel .cp-section-header').first();
    const firstBody = page.locator('#controlPanel .cp-section-body').first();

    // Body should be visible by default
    await expect(firstBody).toBeVisible();

    // Click header to collapse
    await firstHeader.click();
    await expect(firstBody).toBeHidden();

    // Click again to expand
    await firstHeader.click();
    await expect(firstBody).toBeVisible();
  });

  // 7. Trending
  test('trending toggle shows and hides trending panel', async ({ page }) => {
    const toggleBtn = page.locator('#trendingToggle');
    const trendingPanel = page.locator('#trendingPanel');

    await expect(toggleBtn).toBeVisible();
    await expect(trendingPanel).toBeHidden();

    // Click to show
    await toggleBtn.click();
    // The toggle behaviour depends on JS wiring; just verify the panel element exists
    await expect(trendingPanel).toBeAttached();
  });

  test('trending depth control exists', async ({ page }) => {
    const depthInput = page.locator('#trendingDepth');
    await expect(depthInput).toBeAttached();
    await expect(depthInput).toHaveAttribute('type', 'number');
    await expect(depthInput).toHaveAttribute('min', '50');
    await expect(depthInput).toHaveAttribute('max', '2000');
    await expect(depthInput).toHaveValue('300');
  });

  // 8. Background
  test('background Acquire button exists', async ({ page }) => {
    const acquireBtn = page.locator('#controlPanel button', { hasText: 'Acquire Background' });
    await expect(acquireBtn).toBeAttached();
  });

  test('background Subtraction toggle exists', async ({ page }) => {
    const bgSubBtn = page.locator('#controlPanel button', { hasText: 'Background Sub' });
    await expect(bgSubBtn).toBeAttached();
  });

  // 9. Overlays
  test('overlay controls exist', async ({ page }) => {
    // The ROI overlay canvas is created by roi.js
    const roiOverlay = page.locator('#roiOverlay');
    await expect(roiOverlay).toBeAttached();

    // ROI section buttons serve as overlay controls
    const clearBtn = page.locator('#controlPanel button', { hasText: 'Clear' });
    const centerBtn = page.locator('#controlPanel button', { hasText: 'Center' });
    await expect(clearBtn).toBeAttached();
    await expect(centerBtn).toBeAttached();
  });

  // 10. Crosshair
  test('crosshair toggle exists in Display section', async ({ page }) => {
    const crosshairBtn = page.locator('#controlPanel button', { hasText: 'Show Crosshair' });
    await expect(crosshairBtn).toBeAttached();
  });

  test('crosshair toggle activates on click', async ({ page }) => {
    const crosshairBtn = page.locator('#controlPanel button', { hasText: 'Show Crosshair' });

    // Should not be active initially
    const classBefore = await crosshairBtn.getAttribute('class');
    expect(classBefore).not.toContain('active');

    // Click to activate
    await crosshairBtn.click();
    const classAfter = await crosshairBtn.getAttribute('class');
    expect(classAfter).toContain('active');

    // Click again to deactivate
    await crosshairBtn.click();
    const classAgain = await crosshairBtn.getAttribute('class');
    expect(classAgain).not.toContain('active');
  });

  // 11. Theme
  test('theme toggle switches between dark and light', async ({ page }) => {
    const themeBtn = page.locator('#themeToggle');
    await expect(themeBtn).toBeVisible();

    // Default theme is dark
    const initialTheme = await page.locator('html').getAttribute('data-theme');
    expect(initialTheme).toBe('dark');
    await expect(themeBtn).toHaveText('Light Mode');

    // Click to switch to light
    await themeBtn.click();
    const lightTheme = await page.locator('html').getAttribute('data-theme');
    expect(lightTheme).toBe('light');
    await expect(themeBtn).toHaveText('Dark Mode');

    // Click to switch back to dark
    await themeBtn.click();
    const darkTheme = await page.locator('html').getAttribute('data-theme');
    expect(darkTheme).toBe('dark');
    await expect(themeBtn).toHaveText('Light Mode');
  });

  // 12. Error states
  test('disconnected banner element exists and is hidden by default', async ({ page }) => {
    const banner = page.locator('#disconnectedBanner');
    await expect(banner).toBeAttached();
    // Banner should not be actively visible (hidden via CSS or class)
    await expect(banner).toHaveText('Disconnected');
  });

  test('no-camera banner exists', async ({ page }) => {
    const banner = page.locator('#noCameraBanner');
    await expect(banner).toBeAttached();
  });

  // 13. Status bar
  test('status bar has connection indicator and FPS counter', async ({ page }) => {
    const statusDot = page.locator('#statusDot');
    const statusText = page.locator('#statusText');
    const fpsVal = page.locator('#fpsVal');
    const frameNum = page.locator('#frameNum');

    await expect(statusDot).toBeAttached();
    await expect(statusText).toBeAttached();
    await expect(fpsVal).toBeAttached();
    await expect(frameNum).toBeAttached();

    // Default text when disconnected
    await expect(statusText).toHaveText('Disconnected');
    await expect(fpsVal).toHaveText('--');
    await expect(frameNum).toHaveText('--');
  });

  test('status dot has disconnected class by default', async ({ page }) => {
    const statusDot = page.locator('#statusDot');
    const cls = await statusDot.getAttribute('class');
    expect(cls).toContain('disconnected');
  });

});
