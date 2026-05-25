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

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

test.describe('Saved searches end-to-end', () => {
  test('save current filters via /results button and see them on /favorites', async ({ page }) => {
    await goToResults(page);

    const testName = `e2e-r22-${Date.now()}`;
    page.once('dialog', (dialog) => dialog.accept(testName));

    const savePromise = page
      .waitForResponse(
        (resp) =>
          resp.url().includes('saved_searches') && resp.request().method() === 'POST',
        { timeout: 10_000 },
      )
      .catch(() => null);

    await page.getByRole('button', { name: /Save to account/i }).click();
    await savePromise;

    await page.goto('/favorites');

    await expect(
      page.getByRole('link', {
        name: new RegExp(`Apply saved search "${escapeRegExp(testName)}"`),
      }),
    ).toBeVisible({ timeout: 15_000 });

    await expect(page.getByText(/pending first sync|checked/i).first()).toBeVisible();
  });

  test('highlight ring renders on /results when ?highlight=<id> is set', async ({ page }) => {
    await goToResults(page);

    const firstCardIdAttr = await page
      .locator('[id^="match-card-"]')
      .first()
      .getAttribute('id');
    expect(firstCardIdAttr).toBeTruthy();
    const oppId = firstCardIdAttr!.slice('match-card-'.length);

    await page.goto(`/results?highlight=${encodeURIComponent(oppId)}`);

    const wrapper = page.locator(`[id="match-card-${oppId}"]`);
    await expect(wrapper).toBeVisible({ timeout: 30_000 });
    await expect(wrapper).toHaveClass(/ring-amber-400/);
    await expect(wrapper.getByText(/New match/i)).toBeVisible();

    const otherCards = page.locator('[id^="match-card-"]').filter({
      hasNot: page.locator(`[id="match-card-${oppId}"]`),
    });
    const otherCount = await otherCards.count();
    if (otherCount > 0) {
      await expect(otherCards.first()).not.toHaveClass(/ring-amber-400/);
    }
  });
});
