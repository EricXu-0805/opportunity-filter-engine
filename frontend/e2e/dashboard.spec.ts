import { test, expect } from '@playwright/test';

test.describe('Dashboard', () => {
  test('shows the personal activity summary instead of database-wide stats', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Your activity' })).toBeVisible();
    await expect(page.getByTestId('saved-summary')).toBeVisible();
    // The whole-database vanity metrics are gone.
    await expect(page.getByText(/Total Opps/i)).toHaveCount(0);
    await expect(page.getByText(/Next 30 days/i)).toHaveCount(0);
  });

  // M51: the Saved tile counted an import saved in this browser that the
  // saved-deadline list never showed. Its date came from the import, so the
  // row asks the student to verify it and opens the saved copy.
  test('an import saved in this browser is counted and its date listed to verify', async ({ page }) => {
    await page.route('**/api/import-url', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          llm_enriched: true,
          opportunity: {
            source: 'url_parser',
            source_url: 'https://lab.example/summer-reu',
            url: 'https://lab.example/summer-reu',
            title: 'Summer REU, Optics Lab',
            organization: 'Optics Lab',
            deadline: '2027-01-15',
            description_raw: 'Paid summer research for undergraduates in optics.',
            extra_fields: { llm_enriched: true, description_source: 'page_text' },
          },
        }),
      }),
    );
    await page.goto('/import');
    await page.getByPlaceholder('https://...').fill('https://lab.example/summer-reu');
    await page.getByRole('button', { name: /Fetch & parse/i }).click();
    const card = page.getByRole('article');
    await card.getByRole('button', { name: /Save in this browser/i }).click();
    await expect(card.getByText(/^Saved$/i)).toBeVisible();

    await page.goto('/dashboard');
    const saved = page.getByTestId('saved-summary');
    await expect(saved).toHaveAttribute('data-state', 'ready', { timeout: 20_000 });
    await expect(saved).toContainText('1');
    const row = page.getByRole('link', { name: /Summer REU, Optics Lab/ });
    await expect(row).toContainText('Verify date');
    await expect(row).toContainText('2027-01-15');
    await expect(row).toContainText('Imported in this browser. Check this date on the posting.');
    await expect(row).toHaveAttribute('href', '/favorites');
    await expect(page.getByText('No deadlines among your saved opportunities')).toHaveCount(0);
  });

  test('a fresh visitor sees honest empty states, not fabricated activity', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: 'Saved deadlines' })).toBeVisible();
    await expect(page.getByText('No saved opportunities yet')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText('Nothing tracked yet')).toBeVisible();
    await expect(page.getByText('No reminders set')).toBeVisible();
  });
});

test.describe('Deep-link URL filters', () => {
  test('opening /results with filter params in URL applies them', async ({ page }) => {
    await page.goto('/');
    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });
    await page.getByRole('button', { name: /Generate Matches/i }).click();
    await page.waitForURL('**/results*');
    await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 30_000 });

    await page.goto('/results?tab=high_priority&paid=yes');
    const paidSelect = page.locator('select').first();
    await expect(paidSelect).toHaveValue('yes');
  });
});
