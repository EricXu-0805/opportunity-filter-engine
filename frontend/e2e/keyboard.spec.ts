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

test.describe('Keyboard shortcuts', () => {
  test('/ focuses the search box', async ({ page }) => {
    await goToResults(page);
    await page.keyboard.press('/');
    const searchInput = page.locator('#results-search-input');
    await expect(searchInput).toBeFocused();
  });

  test('? opens help dialog, Escape closes it', async ({ page }) => {
    await goToResults(page);
    await page.keyboard.press('Shift+Slash');
    const dialog = page.getByRole('dialog', { name: /Keyboard shortcuts/i });
    await expect(dialog).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
  });

  test('j/k navigate focus ring across cards', async ({ page }) => {
    await goToResults(page);
    await page.locator('body').click();
    await page.keyboard.press('j');
    const firstCard = page.locator('[id^="match-card-"]').first();
    await expect(firstCard).toHaveClass(/ring-2/);
    await page.keyboard.press('j');
    const secondCard = page.locator('[id^="match-card-"]').nth(1);
    await expect(secondCard).toHaveClass(/ring-2/);
    await page.keyboard.press('k');
    await expect(firstCard).toHaveClass(/ring-2/);
  });

  test('s stars the focused card', async ({ page }) => {
    await goToResults(page);
    await page.locator('body').click();
    await page.keyboard.press('j');
    const firstCard = page.locator('[id^="match-card-"]').first();
    const star = firstCard.locator('button[aria-label*="favorite" i]').first();
    await page.keyboard.press('s');
    await expect(star.locator('svg.fill-amber-400')).toBeVisible({ timeout: 3_000 });
  });
});

test.describe('Skip link & focus management', () => {
  test('Tab on home page shows skip-to-content', async ({ page }) => {
    await page.goto('/');
    await page.keyboard.press('Tab');
    const skipLink = page.getByText('Skip to main content');
    await expect(skipLink).toBeFocused();
  });

  test('skip link jumps focus to main', async ({ page }) => {
    await page.goto('/');
    await page.keyboard.press('Tab');
    await page.keyboard.press('Enter');
    await expect(page.locator('#main-content')).toBeFocused();
  });
});
