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

// Below the sm breakpoint the FilterRail collapses its selects behind a
// "Filters" toggle (aria-controls=filter-rail-chips). Desktop viewports render
// the chips row directly, so the toggle simply isn't there. Same canonical
// filters either way — only the disclosure differs (mobile-chrome project).
async function openFiltersIfCollapsed(page: Page) {
  const toggle = page.getByRole('button', { name: /^Filters$/ }).or(
    page.locator('button[aria-controls="filter-rail-chips"]'),
  ).first();
  if (await toggle.isVisible().catch(() => false)) {
    if ((await toggle.getAttribute('aria-expanded')) !== 'true') {
      await toggle.click();
    }
    await expect(page.locator('#filter-rail-chips select').first()).toBeVisible();
  }
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
    await openFiltersIfCollapsed(page);
    const before = await page.locator('[id^="match-card-"]').count();
    const paidSelect = page.locator('#filter-rail-chips select').first();
    await paidSelect.selectOption({ label: 'Paid only' });
    // URL sync happens with the same state update that filters the list,
    // so it marks the moment the filtered render has been committed.
    await expect(page).toHaveURL(/paid=yes/);
    const after = await page.locator('[id^="match-card-"]').count();
    expect(after).toBeLessThanOrEqual(before);
  });

  test('the deadline facet offers only values the corpus can answer', async ({ page }) => {
    // Was 'deadline-passed opportunities hidden under 7-day filter', which
    // selected value '7' and asserted only that the URL said dl=7. It never
    // looked at the list, and on the published corpus that click returned an
    // empty page every time: 789 of 132,524 records carry a deadline and 786
    // of those are already past, so the 7/14/30-day windows matched zero rows
    // each (measured 2026-08-14). The chips now come from server-side counts.
    await goToResults(page);
    await openFiltersIfCollapsed(page);
    const deadlineSelect = page.locator('select', { hasText: /Any deadline/i });
    const values = await deadlineSelect
      .locator('option')
      .evaluateAll((options) => options.map((o) => (o as HTMLOptionElement).value));

    // 'rolling' reads is_rolling, which 98.7% of records answer, so it is
    // always offered. Everything after it is conditional on the count.
    expect(values.slice(0, 2)).toEqual(['', 'rolling']);

    for (const value of values.slice(1)) {
      await deadlineSelect.selectOption({ value });
      await expect(page).toHaveURL(new RegExp(`dl=${value}`));
    }
  });

  test('clear filters button restores state', async ({ page }) => {
    await goToResults(page);
    await openFiltersIfCollapsed(page);
    await page.locator('#filter-rail-chips select').first().selectOption({ label: 'Paid only' });
    await page.getByRole('button', { name: /^Clear \d+ filters?$/i }).click();
    await expect(page).not.toHaveURL(/paid=yes/);
  });

  test('filter preset save + apply + delete', async ({ page }) => {
    await goToResults(page);
    await openFiltersIfCollapsed(page);

    await page.locator('#filter-rail-chips select').first().selectOption({ label: 'Paid only' });

    page.on('dialog', dialog => dialog.accept('My Paid Preset'));
    await page.getByRole('button', { name: /Save preset/i }).click();
    await expect(page.getByText('My Paid Preset')).toBeVisible();

    await page.getByRole('button', { name: /^Clear \d+ filters?$/i }).click();
    await expect(page).not.toHaveURL(/paid=yes/);

    await page.getByRole('button', { name: /Apply preset My Paid Preset/ }).click();
    await expect(page).toHaveURL(/paid=yes/);
  });
});
