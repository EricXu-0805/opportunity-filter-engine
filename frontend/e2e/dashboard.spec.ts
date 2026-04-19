import { test, expect } from '@playwright/test';

test.describe('Dashboard', () => {
  test('loads stats without errors', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByText(/Total Opps/i)).toBeVisible();
  });

  test('upcoming deadlines widget appears when data available', async ({ page }) => {
    await page.goto('/dashboard');

    const widget = page.getByRole('heading', { name: /Upcoming deadlines/i });
    const count = await widget.count();
    if (count === 0) {
      test.skip(true, 'No upcoming deadlines in current dataset');
    }
    await expect(widget).toBeVisible();
    await expect(page.getByText(/Next 30 days/i)).toBeVisible();
  });
});

test.describe('Deep-link URL filters', () => {
  test('opening /results with filter params in URL applies them', async ({ page }) => {
    await page.goto('/');
    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });
    await page.getByRole('button', { name: /Generate Matches/i }).click();
    await page.waitForURL('**/results*');
    await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 30_000 });

    await page.goto('/results?tab=high_priority&paid=yes');
    const paidSelect = page.locator('select').first();
    await expect(paidSelect).toHaveValue('yes');
  });
});
