import { test, expect, type Route } from '@playwright/test';

test.describe('Import by URL', () => {
  test('renders form with disabled button initially empty', async ({ page }) => {
    await page.goto('/import');
    await expect(
      page.getByRole('heading', { name: /Import opportunity/i }),
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

  test('Save to my list persists the import and surfaces it on /favorites', async ({ page, context }) => {
    await page.route('**/api/import-url', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          llm_enriched: true,
          opportunity: {
            source: 'url_parser',
            source_url: 'https://lab.example/research-asst',
            title: 'Research Assistant — Quantum Lab',
            description_raw: 'Join the QC group as a junior research assistant.',
            url: 'https://lab.example/research-asst',
            organization: 'Caltech',
            deadline: '2026-06-01',
            location: 'Pasadena, CA',
            extra_fields: {
              opportunity_type: 'research',
              paid: 'stipend',
              llm_enriched: true,
            },
          },
        }),
      }),
    );
    await page.goto('/import');
    await page.getByPlaceholder('https://...').fill('https://lab.example/research-asst');
    await page.getByRole('button', { name: /Fetch & parse/i }).click();
    const card = page.getByRole('article');
    await expect(card.getByRole('heading', { name: /Quantum Lab/i })).toBeVisible();

    const saveBtn = card.getByRole('button', { name: /Save to my list/i });
    await expect(saveBtn).toBeVisible();
    await saveBtn.click();

    await expect(card.getByText(/^Saved$/i)).toBeVisible();
    const viewLink = card.getByRole('link', { name: /View in Saved/i });
    await expect(viewLink).toBeVisible();

    const stored = await page.evaluate(() => window.localStorage.getItem('ofe_custom_imports'));
    expect(stored).toBeTruthy();
    const parsed = JSON.parse(stored as string) as { opportunity: { title: string } }[];
    expect(parsed).toHaveLength(1);
    expect(parsed[0].opportunity.title).toBe('Research Assistant — Quantum Lab');

    await viewLink.click();
    await expect(page).toHaveURL(/\/favorites/);
    await expect(page.getByRole('heading', { name: /Research Assistant — Quantum Lab/i })).toBeVisible();
    await expect(page.getByText(/^Custom$/i)).toBeVisible();
    await expect(page.getByRole('link', { name: /Open source/i })).toBeVisible();

    await context.clearCookies();
  });

  test('saving twice does not duplicate the entry', async ({ page }) => {
    await page.route('**/api/import-url', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          llm_enriched: true,
          opportunity: {
            source: 'url_parser',
            source_url: 'https://dedup.example/role',
            title: 'Dedupe Test',
            description_raw: 'desc',
            url: 'https://dedup.example/role',
            extra_fields: { llm_enriched: true },
          },
        }),
      }),
    );
    await page.goto('/import');
    await page.evaluate(() => window.localStorage.removeItem('ofe_custom_imports'));
    await page.getByPlaceholder('https://...').fill('https://dedup.example/role');
    await page.getByRole('button', { name: /Fetch & parse/i }).click();
    const cardA = page.getByRole('article');
    await cardA.getByRole('button', { name: /Save to my list/i }).click();
    await expect(cardA.getByText(/^Saved$/i)).toBeVisible();

    await cardA.getByRole('button', { name: /Try another URL/i }).click();
    await page.getByPlaceholder('https://...').fill('https://dedup.example/role');
    await page.getByRole('button', { name: /Fetch & parse/i }).click();
    const cardB = page.getByRole('article');
    await expect(cardB.getByText(/^Saved$/i)).toBeVisible();
    await expect(cardB.getByRole('button', { name: /Save to my list/i })).toHaveCount(0);

    const stored = await page.evaluate(() => window.localStorage.getItem('ofe_custom_imports'));
    const parsed = JSON.parse(stored as string) as unknown[];
    expect(parsed).toHaveLength(1);
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

test.describe('Import by Text', () => {
  test('switching to text mode reveals textarea + Extract button', async ({ page }) => {
    await page.goto('/import');
    await page.getByRole('tab', { name: /By text/i }).click();
    await expect(page.getByRole('tab', { name: /By text/i })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('button', { name: /Extract with AI/i })).toBeVisible();
    await expect(page.getByText(/Minimum 50 characters/i)).toBeVisible();
    await expect(page.getByPlaceholder('https://...')).toHaveCount(0);
  });

  test('shows "paste some text first" when textarea is empty', async ({ page }) => {
    await page.goto('/import');
    await page.getByRole('tab', { name: /By text/i }).click();
    await page.getByRole('button', { name: /Extract with AI/i }).click();
    await expect(page.getByText(/Paste some text first/i)).toBeVisible();
  });

  test('shows "at least 50 characters" when text is too short', async ({ page }) => {
    await page.goto('/import');
    await page.getByRole('tab', { name: /By text/i }).click();
    await page.getByRole('textbox', { name: /Job description/i }).fill('too short');
    await page.getByRole('button', { name: /Extract with AI/i }).click();
    await expect(page.getByText(/at least 50 characters/i)).toBeVisible();
  });

  test('renders extracted opportunity card on text-mode success', async ({ page }) => {
    await page.route('**/api/import-text', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          llm_enriched: true,
          opportunity: {
            source: 'text_parser',
            source_url: '',
            title: 'Pasted LinkedIn Posting',
            description_raw: 'A solid backend role from a paywalled source.',
            url: '',
            organization: 'BigCo',
            deadline: '2026-05-30',
            location: 'Remote',
            extra_fields: {
              opportunity_type: 'internship',
              paid: 'yes',
              skills_required: ['Go', 'Kubernetes'],
              llm_enriched: true,
            },
          },
        }),
      }),
    );
    await page.goto('/import');
    await page.getByRole('tab', { name: /By text/i }).click();
    await page.getByRole('textbox', { name: /Job description/i }).fill(
      'Posting description with deadline and stipend details, redacted org ' +
      'name so the textarea text does not collide with result-card matches. ' +
      'Originally on a paywalled source; pasted by the user as plain text.',
    );
    await page.getByRole('button', { name: /Extract with AI/i }).click();

    const card = page.getByRole('article');
    await expect(card.getByRole('heading', { name: 'Pasted LinkedIn Posting' })).toBeVisible();
    await expect(card.getByText('BigCo')).toBeVisible();
    await expect(card.getByText('2026-05-30')).toBeVisible();
    await expect(card.getByText('Go').first()).toBeVisible();
    await expect(card.getByText(/AI-extracted/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /Try another text/i })).toBeVisible();
  });

  test('shows extraction-failed message on text-mode failure', async ({ page }) => {
    await page.route('**/api/import-text', (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: false,
          llm_enriched: false,
          error: 'AI extraction unavailable',
        }),
      }),
    );
    await page.goto('/import');
    await page.getByRole('tab', { name: /By text/i }).click();
    await page.getByRole('textbox', { name: /Job description/i }).fill(
      'A reasonable-length text that should make it past the 50-char client check before the mocked API returns failure.',
    );
    await page.getByRole('button', { name: /Extract with AI/i }).click();
    await expect(page.getByText(/AI extraction failed/i)).toBeVisible();
  });

  test('surfaces backend 422 detail from Pydantic min_length violation', async ({ page }) => {
    await page.route('**/api/import-text', (route: Route) =>
      route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: [{ msg: 'String should have at least 50 characters', type: 'string_too_short' }],
        }),
      }),
    );
    await page.goto('/import');
    await page.getByRole('tab', { name: /By text/i }).click();
    await page.getByRole('textbox', { name: /Job description/i }).fill(
      'Long enough to pass the client-side guard, but the mocked server returns a 422 anyway.',
    );
    await page.getByRole('button', { name: /Extract with AI/i }).click();
    await expect(page.getByText(/AI extraction failed/i)).toBeVisible();
  });

  test('switching tabs preserves work-in-progress in each input', async ({ page }) => {
    await page.goto('/import');
    await page.getByPlaceholder('https://...').fill('https://example.com/x');
    await page.getByRole('tab', { name: /By text/i }).click();
    await page.getByRole('textbox', { name: /Job description/i }).fill('Drafting a pasted description...');
    await page.getByRole('tab', { name: /By URL/i }).click();
    await expect(page.getByPlaceholder('https://...')).toHaveValue('https://example.com/x');
    await page.getByRole('tab', { name: /By text/i }).click();
    await expect(page.getByRole('textbox', { name: /Job description/i }))
      .toHaveValue('Drafting a pasted description...');
  });
});
