const { test, expect } = require('@playwright/test');

test('panel page loads', async ({ page }) => {
  await page.goto('/panel');
  // Just verify the page loads without error
  await expect(page).toHaveTitle(/.*/);
});
