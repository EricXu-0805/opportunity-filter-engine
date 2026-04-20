import { test, expect, type Page } from '@playwright/test';

async function goToResults(page: Page) {
  await page.goto('/');
  await page.selectOption('#college', 'Grainger College of Engineering');
  await page.selectOption('#major', { index: 1 });
  await page.selectOption('#grade', { index: 1 });
  await page.getByRole('button', { name: /Generate Matches/i }).click();
  await page.waitForURL('**/results*');
  await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 30_000 });
}

test.describe('Semantic AI ranking toggle', () => {
  test('toggle is visible and defaults to on', async ({ page }) => {
    await goToResults(page);
    const toggle = page.getByRole('switch', { name: /AI semantic ranking/i });
    await expect(toggle).toBeVisible();
    // Default changed to on (session 17): semantic rerank is the better UX
    // for most users, including humanities majors with sparse matches
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
  });

  test('turning off adds ?ai=0 to URL and persists', async ({ page }) => {
    await goToResults(page);
    await page.getByRole('switch', { name: /AI semantic ranking/i }).click();
    await expect(page).toHaveURL(/ai=0/);
    await expect(page.getByRole('switch', { name: /AI semantic ranking/i }))
      .toHaveAttribute('aria-checked', 'false');
    const stored = await page.evaluate(() => localStorage.getItem('ofe_semantic_rerank'));
    expect(stored).toBe('0');
  });

  test('AI badge is present by default', async ({ page }) => {
    await goToResults(page);
    await expect(page.locator('main').getByText(/^AI$/).first()).toBeVisible({ timeout: 15_000 });
  });

  test('deep link with ?ai=0 disables ranking on first load', async ({ page }) => {
    await page.goto('/');
    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });

    await page.getByRole('button', { name: /Generate Matches/i }).click();
    await page.waitForURL('**/results*');
    await page.goto('/results?ai=0');
    await expect(page.getByRole('switch', { name: /AI semantic ranking/i }))
      .toHaveAttribute('aria-checked', 'false');
  });
});
