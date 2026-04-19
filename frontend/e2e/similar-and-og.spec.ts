import { test, expect } from '@playwright/test';

const KNOWN_ID = 'uiuc-ece-cv-lab';

test.describe('Similar opportunities on detail page', () => {
  test('renders similar section when matches exist', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    const heading = page.getByRole('heading', { name: /Similar opportunities/i });
    if (await heading.count() === 0) {
      test.skip(true, 'No similar opportunities for this source in dataset');
    }
    await expect(heading).toBeVisible();
  });

  test('each similar card links to its own detail page', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    const heading = page.getByRole('heading', { name: /Similar opportunities/i });
    if (await heading.count() === 0) test.skip(true, 'No similar matches');

    const firstLink = page.locator('section[aria-labelledby="similar-heading"] a').first();
    const href = await firstLink.getAttribute('href');
    expect(href).toMatch(/^\/opportunities\//);

    await firstLink.click();
    await expect(page).toHaveURL(/\/opportunities\//);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });

  test('does not include the source opportunity in its own similar list', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    const similarLinks = page.locator('section[aria-labelledby="similar-heading"] a');
    const hrefs = await similarLinks.evaluateAll(els =>
      els.map(e => (e as HTMLAnchorElement).getAttribute('href') ?? ''),
    );
    for (const href of hrefs) {
      expect(href).not.toContain(KNOWN_ID);
    }
  });
});

test.describe('Dynamic OG image endpoint', () => {
  test('/api/og/opportunity/[id] returns a PNG', async ({ request }) => {
    const response = await request.get(`/api/og/opportunity/${KNOWN_ID}`);
    expect(response.status()).toBe(200);
    expect(response.headers()['content-type']).toContain('image/png');
    const buf = await response.body();
    expect(buf.length).toBeGreaterThan(10_000);
  });

  test('OG route has cache-control header', async ({ request }) => {
    const response = await request.get(`/api/og/opportunity/${KNOWN_ID}`);
    const cc = response.headers()['cache-control'];
    expect(cc).toBeTruthy();
    expect(cc).toMatch(/max-age/);
  });

  test('unknown id still returns a valid fallback PNG', async ({ request }) => {
    const response = await request.get('/api/og/opportunity/bogus-id-123');
    expect(response.status()).toBe(200);
    expect(response.headers()['content-type']).toContain('image/png');
  });

  test('detail page metadata references the OG image URL', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    const ogImage = await page.locator('meta[property="og:image"]').first().getAttribute('content');
    expect(ogImage).toBeTruthy();
    expect(ogImage!).toMatch(/\/api\/og\/opportunity\//);
    const twitterImage = await page.locator('meta[name="twitter:image"]').first().getAttribute('content');
    expect(twitterImage).toBeTruthy();
  });

  test('Twitter card uses summary_large_image', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    const card = await page.locator('meta[name="twitter:card"]').getAttribute('content');
    expect(card).toBe('summary_large_image');
  });
});
