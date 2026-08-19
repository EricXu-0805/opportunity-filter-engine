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

// AI refine stays fail-closed until the match-view API performs and attests a
// bounded paid rerank. A stale bookmark or local preference must not resurrect
// a control whose current result path is deterministic.
test.describe('AI refine release boundary', () => {
  test('the refine toggle and AI URL state are absent', async ({ page }) => {
    await goToResults(page);
    await expect(page.getByTestId('semantic-toggle')).toHaveCount(0);
    await expect(page).not.toHaveURL(/(?:\?|&)ai=/);
  });

  test('stale URL and storage requests are removed and stay deterministic', async ({ page }) => {
    await goToResults(page);
    await page.evaluate(() => {
      localStorage.setItem('ofe_semantic_rerank', '1');
      localStorage.setItem('ofe_semantic_rerank_opt_in_v1', '1');
    });
    await page.goto('/results?ai=1');
    await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('semantic-toggle')).toHaveCount(0);
    await expect(page).not.toHaveURL(/(?:\?|&)ai=/);
  });
});
