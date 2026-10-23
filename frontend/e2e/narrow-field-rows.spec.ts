import { test, expect, type Page } from '@playwright/test';

// Checklist M144. A flex-1 text field keeps its automatic minimum width unless
// it also has min-w-0, so on a narrow phone the button beside it was pushed
// past its row. Measured on production 2026-10-23 at 360 px: the GitHub Import
// button 20 px out in Chromium; in WebKit 66 px out with the whole page
// scrolling sideways, and the import page's Fetch button 14 px out. CI runs
// Chromium, which shows both rows over only at 320 px (60 px and 8 px).
test.use({ viewport: { width: 320, height: 760 } });

function rowsPastTheirEdge(page: Page) {
  return page.evaluate(() => [...document.querySelectorAll('input, textarea, select')]
    .filter((field) => field.getClientRects().length > 0 && getComputedStyle(field.parentElement!).display.includes('flex'))
    .map((field) => {
      const row = field.parentElement!;
      const right = Math.max(...[...row.children].map((child) => child.getBoundingClientRect().right));
      return { field: field.id || field.getAttribute('placeholder') || field.tagName, over: Math.round(right - row.getBoundingClientRect().right) };
    })
    .filter((row) => row.over > 1));
}

for (const [name, path, field] of [['home', '/', '#github_url'], ['import', '/resources?tab=import', 'input[type="url"]']] as const) {
  test(`320 px ${name}: no field row reaches past its edge`, async ({ page }) => {
    await page.goto(path);
    await expect(page.locator(field)).toBeVisible();
    expect(await rowsPastTheirEdge(page)).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  });
}
