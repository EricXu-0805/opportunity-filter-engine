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

test.describe('deterministic Match release contract', () => {
  test('AI refine controls and badges are absent from the accepted release', async ({ page }) => {
    await goToResults(page);
    await expect(page.getByTestId('semantic-toggle')).toHaveCount(0);
    await expect(page.locator('main').getByText(/^AI$/)).toHaveCount(0);
    await expect(page).not.toHaveURL(/ai=/);
  });

  test('stale URL and localStorage opt-ins cannot re-enable AI refine', async ({ page }) => {
    await goToResults(page);
    await page.evaluate(() => {
      localStorage.setItem('ofe_semantic_rerank', '1');
      localStorage.setItem('ofe_semantic_rerank_opt_in_v1', '1');
    });
    await page.goto('/results?ai=1');
    await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('semantic-toggle')).toHaveCount(0);
    await expect(page.locator('main').getByText(/^AI$/)).toHaveCount(0);
    await expect(page).not.toHaveURL(/ai=/);
  });
});
