import { test, expect } from '@playwright/test';
import { en } from '../src/i18n/dictionaries';

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

  test('a favorites read outage keeps account totals and deadlines unknown until a successful retry on each page', async ({ page }) => {
    let fail = true;
    let cursorReads = 0;
    await page.route('**/rest/v1/favorites?**', route => {
      expect(route.request().method()).toBe('GET');
      if (fail) return route.fulfill({
        status: 503,
        // Exercise all SDK retries before the assertion deadline.
        headers: { 'Retry-After': '0', 'Access-Control-Expose-Headers': 'Retry-After' },
        json: { message: 'controlled read failure' },
      });
      // The count header is absent. After the only ID, the service has no remaining favorites.
      const cursor = new URL(route.request().url()).searchParams.get('opportunity_id');
      if (cursor !== null) {
        expect(cursor).toBe('gt.saved-target');
        cursorReads++;
        return route.fulfill({ json: [] });
      }
      return route.fulfill({ json: [{ opportunity_id: 'saved-target' }] });
    });
    await page.route('**/api/opportunities/batch', route => route.fulfill({
      json: { requested: 1, found: 0, opportunities: [] },
    }));
    await page.goto('/dashboard');
    const saved = page.getByTestId('saved-summary');
    await expect(saved).toHaveAttribute('data-state', 'error');
    await expect(saved).not.toHaveText(/0/);
    await expect(page.getByText(en.dashboard.deadlines.errorTitle)).toBeVisible();
    await expect(page.getByText(en.dashboard.deadlines.noSavesTitle)).toHaveCount(0);
    await expect(page.getByTestId('applied-summary')).toHaveAttribute('data-state', 'ready');
    fail = false;
    await page.getByText(en.dashboard.saved.errorTitle).locator('..').getByRole('button').click();
    await expect(saved).toHaveAttribute('data-state', 'ready');
    await expect(saved).toContainText('1');
    await expect(page.getByTestId('dashboard-unavailable-note')).toBeVisible();

    expect(cursorReads).toBeGreaterThan(0);
    const dashboardCursorReads = cursorReads;
    fail = true;
    await page.goto('/favorites');
    await expect(page.getByText(en.favorites.loadError)).toBeVisible();
    fail = false;
    await page.getByRole('alert').filter({ hasText: en.favorites.loadError }).getByRole('button').click();
    await expect(page.getByText(en.favorites.count.replace('{count}', '1'), { exact: true })).toBeVisible();
    expect(cursorReads).toBeGreaterThan(dashboardCursorReads);
  });

  test('a failed continuation of a large tracker stays unknown until retry loads the final status', async ({ page }) => {
    const old = Array.from({ length: 1000 }, (_, n) => ({
      opportunity_id: String(n).padStart(4, '0'), interaction_type: 'dismissed',
    }));
    let fail = true;
    let recovered = false;
    await page.route('**/rest/v1/interactions?**', route => {
      const params = new URL(route.request().url()).searchParams;
      const cursor = params.get('opportunity_id');
      if (!cursor) return route.fulfill({
        json: old, headers: { 'Content-Range': '0-999/1001', 'Access-Control-Expose-Headers': 'Content-Range' },
      });
      expect(params.get('order')).toBe('opportunity_id.asc');
      expect(cursor).toBe('gt.0999');
      if (fail) return route.fulfill({
        status: 503, json: { message: 'tracker continuation unavailable' },
        headers: { 'Retry-After': '0', 'Access-Control-Expose-Headers': 'Retry-After' },
      });
      recovered = true;
      return route.fulfill({
        json: [{ opportunity_id: '1000', interaction_type: 'applied', notes: 'Existing application' }],
        headers: { 'Content-Range': '0-0/1', 'Access-Control-Expose-Headers': 'Content-Range' },
      });
    });
    await page.route('**/api/opportunities/batch', route => route.fulfill({
      json: { requested: 1, found: 0, opportunities: [] },
    }));
    await page.goto('/dashboard');
    const applied = page.getByTestId('applied-summary');
    await expect(applied).toHaveAttribute('data-state', 'error');
    fail = false;
    await page.locator('p').filter({ hasText: en.dashboard.trackerSection.errorTitle }).getByRole('button').click();
    await expect(applied).toHaveAttribute('data-state', 'ready');
    await expect(applied).toContainText('1');
    expect(recovered).toBe(true);
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
    const disclosure = page.locator('button[aria-controls="filter-rail-chips"]');
    if (await disclosure.isVisible() && await disclosure.getAttribute('aria-expanded') === 'false') {
      await disclosure.click();
    }
    const paidSelect = page.getByRole('combobox', { name: 'Pay', exact: true });
    await expect(paidSelect).toHaveValue('yes');
  });
});
