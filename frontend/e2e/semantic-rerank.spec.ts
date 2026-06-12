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
  test('toggle is visible and defaults to off', async ({ page }) => {
    await goToResults(page);
    const toggle = page.getByRole('switch', { name: /AI semantic ranking/i });
    await expect(toggle).toBeVisible();
    // Default flipped to off in #109: the semantic blend compressed rule
    // scores and buried topically-specific matches, so the accurate rule
    // ranking is the default and AI rerank is opt-in.
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    // The URL writer marks the off state explicitly (use-results-url.ts).
    await expect(page).toHaveURL(/ai=0/);
  });

  test('turning on removes ?ai=0 from URL and persists', async ({ page }) => {
    await goToResults(page);
    await expect(page).toHaveURL(/ai=0/);
    await page.getByRole('switch', { name: /AI semantic ranking/i }).click();
    await expect(page).not.toHaveURL(/ai=0/);
    await expect(page.getByRole('switch', { name: /AI semantic ranking/i }))
      .toHaveAttribute('aria-checked', 'true');
    const stored = await page.evaluate(() => localStorage.getItem('ofe_semantic_rerank'));
    expect(stored).toBe('1');
  });

  test('AI badge appears once semantic ranking is enabled', async ({ page }) => {
    await goToResults(page);
    // Off by default → no badge next to the result count.
    await expect(page.locator('main').getByText(/^AI$/)).toHaveCount(0);
    await page.getByRole('switch', { name: /AI semantic ranking/i }).click();
    // The toggle triggers a re-rank (cache miss). Wait on the badge, not on
    // match cards: semantic blending compresses scores, so the default
    // High Priority tab can legitimately end up empty under AI ranking.
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
