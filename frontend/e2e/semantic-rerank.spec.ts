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
  test('toggle is visible and defaults to ON', async ({ page }) => {
    await goToResults(page);
    const toggle = page.getByTestId('semantic-toggle');
    await expect(toggle).toBeVisible();
    // Default flipped to ON (2026-07 matching rework): the LLM rerank fixes
    // the rule ranking's tie walls and writes each card's concrete lead
    // reason; without a server key it is a strict no-op, so the default is
    // safe everywhere. '?ai=0' / stored '0' still opt out.
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
    // The URL writer marks the state symmetrically (use-results-url.ts).
    await expect(page).toHaveURL(/ai=1/);
  });

  test('turning off writes ?ai=0 to the URL and persists', async ({ page }) => {
    await goToResults(page);
    await expect(page).toHaveURL(/ai=1/);
    await page.getByTestId('semantic-toggle').click();
    await expect(page).toHaveURL(/ai=0/);
    await expect(page.getByTestId('semantic-toggle'))
      .toHaveAttribute('aria-checked', 'false');
    const stored = await page.evaluate(() => localStorage.getItem('ofe_semantic_rerank'));
    expect(stored).toBe('0');
  });

  test('AI badge shows by default and disappears when toggled off', async ({ page }) => {
    await goToResults(page);
    // On by default → the badge sits next to the result count.
    await expect(page.locator('main').getByText(/^AI$/).first()).toBeVisible({ timeout: 15_000 });
    await page.getByTestId('semantic-toggle').click();
    // The toggle triggers a re-rank (cache miss). Wait on the badge, not on
    // match cards: the tab distribution can legitimately shift between modes.
    await expect(page.locator('main').getByText(/^AI$/)).toHaveCount(0, { timeout: 15_000 });
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
