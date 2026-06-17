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

// The toggle's visible copy has been reworded across iterations ("AI semantic
// ranking" → "AI smart match", #226). Locate it by a stable data-testid rather
// than its accessible name so a future copy change can't break these specs; the
// underlying state (URL ?ai param, localStorage 'ofe_semantic_rerank') is
// unchanged.
test.describe('AI smart-match (semantic rerank) toggle', () => {
  test('toggle is visible and defaults to off', async ({ page }) => {
    await goToResults(page);
    const toggle = page.getByTestId('semantic-toggle');
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
    await page.getByTestId('semantic-toggle').click();
    await expect(page).not.toHaveURL(/ai=0/);
    await expect(page.getByTestId('semantic-toggle'))
      .toHaveAttribute('aria-checked', 'true');
    const stored = await page.evaluate(() => localStorage.getItem('ofe_semantic_rerank'));
    expect(stored).toBe('1');
  });

  test('AI badge appears once smart match is enabled', async ({ page }) => {
    await goToResults(page);
    // Off by default → no badge next to the result count.
    await expect(page.locator('main').getByText(/^AI$/)).toHaveCount(0);
    await page.getByTestId('semantic-toggle').click();
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
    await expect(page.getByTestId('semantic-toggle'))
      .toHaveAttribute('aria-checked', 'false');
  });
});
