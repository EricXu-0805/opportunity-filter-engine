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

// This file asserted the opposite for the whole MVP route freeze: no toggle, no
// AI badge, no `ai=` in the URL. match_ai_refine is accepted now, so what has
// to hold is that the control exists AND that the URL is the authority over a
// stored preference — a share link must reproduce what the sender saw rather
// than what the recipient last chose.
test.describe('AI refine, now part of the accepted release', () => {
  test('the refine toggle is present and the URL carries its state', async ({ page }) => {
    await goToResults(page);
    await expect(page.getByTestId('semantic-toggle')).toHaveCount(1);
    // Written in both directions, unlike every other facet: omitting `ai=0`
    // would let a recipient's stored preference turn refine on in a link
    // shared with it off.
    await expect(page).toHaveURL(/ai=(0|1)/);
  });

  test('an explicit ?ai=1 wins over a stored off preference', async ({ page }) => {
    await goToResults(page);
    await page.evaluate(() => {
      localStorage.setItem('ofe_semantic_rerank', '0');
    });
    await page.goto('/results?ai=1');
    await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('semantic-toggle')).toHaveCount(1);
    await expect(page).toHaveURL(/ai=1/);
  });

  test('an explicit ?ai=0 wins over a stored on preference', async ({ page }) => {
    await goToResults(page);
    await page.evaluate(() => {
      localStorage.setItem('ofe_semantic_rerank', '1');
      localStorage.setItem('ofe_semantic_rerank_opt_in_v1', '1');
    });
    await page.goto('/results?ai=0');
    await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 30_000 });
    await expect(page).toHaveURL(/ai=0/);
  });
});
