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
  test('toggle is visible and starts off', async ({ page }) => {
    await goToResults(page);
    const toggle = page.getByRole('switch', { name: /AI semantic ranking/i });
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
  });

  test('turning on adds ?ai=1 to URL and refetches', async ({ page }) => {
    await goToResults(page);
    const matchesRequest = page.waitForRequest(req =>
      req.url().includes('/api/matches') && req.url().includes('semantic=true'),
    );
    await page.getByRole('switch', { name: /AI semantic ranking/i }).click();
    await matchesRequest;
    await expect(page).toHaveURL(/ai=1/);
    await expect(page.getByRole('switch', { name: /AI semantic ranking/i }))
      .toHaveAttribute('aria-checked', 'true');
  });

  test('AI badge appears in subheader when on', async ({ page }) => {
    await goToResults(page);
    await page.getByRole('switch', { name: /AI semantic ranking/i }).click();
    await expect(page.locator('main').getByText(/^AI$/).first()).toBeVisible({ timeout: 15_000 });
  });

  test('preference persists in localStorage', async ({ page }) => {
    await goToResults(page);
    await page.getByRole('switch', { name: /AI semantic ranking/i }).click();
    await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 30_000 });

    const stored = await page.evaluate(() => localStorage.getItem('ofe_semantic_rerank'));
    expect(stored).toBe('1');
  });

  test('deep link with ?ai=1 activates ranking on first load', async ({ page }) => {
    await page.goto('/');
    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });

    const matchesRequest = page.waitForRequest(req =>
      req.url().includes('/api/matches') && req.url().includes('semantic=true'),
    );
    await page.getByRole('button', { name: /Generate Matches/i }).click();
    await page.waitForURL('**/results*');
    await page.goto('/results?ai=1');
    await matchesRequest;
    await expect(page.getByRole('switch', { name: /AI semantic ranking/i }))
      .toHaveAttribute('aria-checked', 'true');
  });
});
