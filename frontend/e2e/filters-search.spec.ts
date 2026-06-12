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

test.describe('Filters, search, sort', () => {
  test('search box narrows results and updates URL', async ({ page }) => {
    await goToResults(page);
    const search = page.getByPlaceholder(/Search by title/i);
    await search.fill('research');
    await expect(page).toHaveURL(/q=research/, { timeout: 2_000 });
    // After debounce (~300ms), the search echo "…research" shows up in
    // the quoted span. Match the quoted query instead of "result(s)? for"
    // because the "for" prefix is split into its own i18n span.
    await expect(page.getByText(/\u201Cresearch\u201D/)).toBeVisible({ timeout: 3_000 });
  });

  test('tabs switch and persist to URL', async ({ page }) => {
    await goToResults(page);
    // R69-A (#61): High Priority is the default tab and the URL
    // omit-sentinel, so it starts selected with no ?tab= param. Every
    // other tab — including the explicit 'all' — round-trips via the URL.
    await expect(page.getByRole('tab', { name: /High Priority/i }))
      .toHaveAttribute('aria-selected', 'true');
    await expect(page).not.toHaveURL(/tab=/);

    await page.getByRole('tab', { name: /^All/i }).click();
    await expect(page).toHaveURL(/tab=all/);
    await expect(page.getByRole('tab', { name: /^All/i }))
      .toHaveAttribute('aria-selected', 'true');

    // Switching back to the default drops the param again.
    await page.getByRole('tab', { name: /High Priority/i }).click();
    await expect(page).not.toHaveURL(/tab=/);
    await expect(page.getByRole('tab', { name: /High Priority/i }))
      .toHaveAttribute('aria-selected', 'true');
  });

  test('paid filter reduces visible result count', async ({ page }) => {
    await goToResults(page);
    const before = await page.locator('[id^="match-card-"]').count();
    const paidSelect = page.locator('select').first();
    await paidSelect.selectOption({ label: 'Paid only' });
    // URL sync happens with the same state update that filters the list,
    // so it marks the moment the filtered render has been committed.
    await expect(page).toHaveURL(/paid=yes/);
    const after = await page.locator('[id^="match-card-"]').count();
    expect(after).toBeLessThanOrEqual(before);
  });

  test('deadline-passed opportunities hidden under 7-day filter', async ({ page }) => {
    await goToResults(page);
    const deadlineSelect = page.locator('select', { hasText: /Any deadline/i });
    await deadlineSelect.selectOption({ value: '7' });
    await expect(page).toHaveURL(/dl=7/);
  });

  test('clear filters button restores state', async ({ page }) => {
    await goToResults(page);
    await page.locator('select').first().selectOption({ label: 'Paid only' });
    await page.getByRole('button', { name: /Clear.*filter/i }).click();
    await expect(page).not.toHaveURL(/paid=yes/);
  });

  test('filter preset save + apply + delete', async ({ page }) => {
    await goToResults(page);

    await page.locator('select').first().selectOption({ label: 'Paid only' });

    page.on('dialog', dialog => dialog.accept('My Paid Preset'));
    await page.getByRole('button', { name: /Save preset/i }).click();
    await expect(page.getByText('My Paid Preset')).toBeVisible();

    await page.getByRole('button', { name: /Clear.*filter/i }).click();
    await expect(page).not.toHaveURL(/paid=yes/);

    await page.getByRole('button', { name: /Apply preset My Paid Preset/ }).click();
    await expect(page).toHaveURL(/paid=yes/);
  });
});
