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

    await page.getByPlaceholder(/Search by title/i).fill('machine learning');

    const saveButton = page.getByRole('button', { name: /Save to account/i });
    await expect(saveButton).toBeVisible({ timeout: 5_000 });

    const testName = `e2e-r22-${Date.now()}`;
    page.once('dialog', (dialog) => dialog.accept(testName));

    const savePromise = page
      .waitForResponse(
        (resp) =>
          resp.url().includes('saved_searches') && resp.request().method() === 'POST',
        { timeout: 10_000 },
      )
      .catch(() => null);

    await saveButton.click();
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

    const allIds = await page
      .locator('[id^="match-card-"]')
      .evaluateAll((els) => els.map((el) => el.id));
    expect(allIds.length).toBeGreaterThan(0);

    const targetWrapperId = allIds[0];
    const oppId = targetWrapperId.slice('match-card-'.length);
    const otherWrapperId = allIds.find((id) => id !== targetWrapperId);

    await page.goto(`/results?highlight=${encodeURIComponent(oppId)}`);

    const wrapper = page.locator(`[id="${targetWrapperId}"]`);
    await expect(wrapper).toBeVisible({ timeout: 30_000 });
    await expect(wrapper).toHaveClass(/ring-amber-400/);
    await expect(wrapper.getByText(/New match/i)).toBeVisible();

    if (otherWrapperId) {
      await expect(page.locator(`[id="${otherWrapperId}"]`)).not.toHaveClass(/ring-amber-400/);
    }
  });
});
