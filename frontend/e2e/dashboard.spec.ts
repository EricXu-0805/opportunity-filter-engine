import { test, expect } from '@playwright/test';

test.describe('Dashboard', () => {
  test('shows the personal activity summary instead of database-wide stats', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Your activity' })).toBeVisible();
    await expect(page.getByTestId('saved-summary')).toBeVisible();
    // The whole-database vanity metrics are gone.
    await expect(page.getByText(/Total Opps/i)).toHaveCount(0);
    await expect(page.getByText(/Next 30 days/i)).toHaveCount(0);
  });

  test('a fresh visitor sees honest empty states, not fabricated activity', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: 'Saved deadlines' })).toBeVisible();
    await expect(page.getByText('No saved opportunities yet')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText('Nothing tracked yet')).toBeVisible();
    await expect(page.getByText('No reminders set')).toBeVisible();
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
