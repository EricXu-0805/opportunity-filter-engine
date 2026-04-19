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

test.describe('Favorites', () => {
  test('star toggles a card into the starred tab', async ({ page }) => {
    await goToResults(page);

    const firstCard = page.locator('[id^="match-card-"]').first();
    const title = await firstCard.locator('h3').innerText();

    const star = firstCard.locator('button[aria-label*="favorite" i]').first();
    await star.click();

    await page.getByRole('tab', { name: /Starred/i }).click();
    await expect(page.locator('h3', { hasText: title })).toBeVisible();

    await expect(
      page.getByRole('button', { name: /Export.*CSV/i }),
    ).toBeVisible();
  });

  test('CSV export download has expected shape', async ({ page }) => {
    await goToResults(page);
    const firstCard = page.locator('[id^="match-card-"]').first();
    await firstCard.locator('button[aria-label*="favorite" i]').first().click();

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /Export.*CSV/i }).click();
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toMatch(/opportunities-\d{4}-\d{2}-\d{2}\.csv/);
    const path = await download.path();
    expect(path).toBeTruthy();
  });
});

test.describe('Interaction tracking (dismiss)', () => {
  test('dismiss hides card and toggle shows it again', async ({ page }) => {
    await goToResults(page);
    const firstCard = page.locator('[id^="match-card-"]').first();
    const title = await firstCard.locator('h3').innerText();

    await firstCard.getByRole('button', { name: 'Not interested' }).click();
    await expect(page.locator('h3', { hasText: title }).first()).not.toBeVisible();

    await page.getByRole('button', { name: /Show.*dismissed/i }).click();
    await expect(page.locator('h3', { hasText: title })).toBeVisible();
  });
});
