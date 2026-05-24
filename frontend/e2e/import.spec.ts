import { test, expect, type Route } from '@playwright/test';

test.describe('Import by URL', () => {
  test('renders form with disabled button initially empty', async ({ page }) => {
    await page.goto('/import');
    await expect(
      page.getByRole('heading', { name: /Import opportunity by URL/i }),
    ).toBeVisible();
    await expect(page.getByPlaceholder('https://...')).toBeVisible();
    await expect(page.getByRole('button', { name: /Fetch & parse/i })).toBeVisible();
  });

  test('shows error message when fetch fails', async ({ page }) => {
    await page.route('**/api/import-url', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: false,
          error: 'failed to fetch or parse the URL',
          llm_enriched: false,
        }),
      }),
    );
    await page.goto('/import');
    await page.getByPlaceholder('https://...').fill('https://broken.example.com/x');
    await page.getByRole('button', { name: /Fetch & parse/i }).click();
    await expect(page.getByText(/Could not fetch or parse/i)).toBeVisible();
  });

  test('surfaces specific "not allowed" message when backend rejects 400', async ({ page }) => {
    await page.route('**/api/import-url', (route: Route) =>
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'unsafe url: literal IP not allowed' }),
      }),
    );
    await page.goto('/import');
    await page.getByPlaceholder('https://...').fill('http://192.168.1.1/x');
    await page.getByRole('button', { name: /Fetch & parse/i }).click();
    await expect(page.getByText(/not allowed|public http\/https/i)).toBeVisible();
  });

  test('renders extracted opportunity card on success', async ({ page }) => {
    await page.route('**/api/import-url', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          llm_enriched: true,
          opportunity: {
            source: 'url_parser',
            source_url: 'https://example.com/intern',
            title: 'Software Engineering Intern',
            description_raw: 'Build distributed systems with us.',
            url: 'https://example.com/intern',
            organization: 'Acme Corp',
            deadline: '2026-04-15',
            location: 'San Francisco, CA',
            extra_fields: {
              opportunity_type: 'internship',
              on_campus: false,
              paid: 'stipend',
              skills_required: ['Python', 'React'],
              skills_preferred: ['Rust'],
              preferred_year: ['junior', 'senior'],
              international_friendly: 'yes',
              llm_enriched: true,
            },
          },
        }),
      }),
    );
    await page.goto('/import');
    await page.getByPlaceholder('https://...').fill('https://example.com/intern');
    await page.getByRole('button', { name: /Fetch & parse/i }).click();

    await expect(
      page.getByRole('heading', { name: 'Software Engineering Intern' }),
    ).toBeVisible();
    await expect(page.getByText('Acme Corp')).toBeVisible();
    await expect(page.getByText(/AI-extracted/i)).toBeVisible();
    await expect(page.getByText('2026-04-15')).toBeVisible();
    await expect(page.getByText('Python').first()).toBeVisible();
    await expect(page.getByText('Rust').first()).toBeVisible();
  });

  test('reset button clears the form and result', async ({ page }) => {
    await page.route('**/api/import-url', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          llm_enriched: false,
          opportunity: {
            source: 'url_parser',
            source_url: 'https://x.com/y',
            title: 'Some Opportunity',
            description_raw: '',
            url: 'https://x.com/y',
            extra_fields: {},
          },
        }),
      }),
    );
    await page.goto('/import');
    await page.getByPlaceholder('https://...').fill('https://x.com/y');
    await page.getByRole('button', { name: /Fetch & parse/i }).click();
    await expect(page.getByRole('heading', { name: 'Some Opportunity' })).toBeVisible();

    await page.getByRole('button', { name: /Try another URL/i }).click();
    await expect(
      page.getByRole('heading', { name: 'Some Opportunity' }),
    ).not.toBeVisible();
    await expect(page.getByPlaceholder('https://...')).toHaveValue('');
  });

  test('basic-extraction badge shows when LLM not configured', async ({ page }) => {
    await page.route('**/api/import-url', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          llm_enriched: false,
          opportunity: {
            source: 'url_parser',
            source_url: 'https://example.com/x',
            title: 'OG-only Opportunity',
            description_raw: 'from og:description',
            url: 'https://example.com/x',
            organization: 'example.com',
            extra_fields: { needs_manual_review: true },
          },
        }),
      }),
    );
    await page.goto('/import');
    await page.getByPlaceholder('https://...').fill('https://example.com/x');
    await page.getByRole('button', { name: /Fetch & parse/i }).click();
    await expect(page.getByText(/Basic extraction/i)).toBeVisible();
  });
});
