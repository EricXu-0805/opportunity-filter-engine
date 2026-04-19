import { test, expect } from '@playwright/test';

const KNOWN_ID = 'uiuc-ece-cv-lab';

test.describe('Opportunity detail page', () => {
  test('renders full page SSR with title and meta', async ({ page }) => {
    const response = await page.goto(`/opportunities/${KNOWN_ID}`);
    expect(response?.status()).toBe(200);

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const title = await page.title();
    expect(title).toContain('OpportunityEngine');

    const ogTitle = await page.locator('meta[property="og:title"]').getAttribute('content');
    expect(ogTitle).toBeTruthy();
    expect(ogTitle!.length).toBeGreaterThan(0);
  });

  test('includes JSON-LD JobPosting schema', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    const ld = await page.locator('script[type="application/ld+json"]').textContent();
    expect(ld).toBeTruthy();
    const parsed = JSON.parse(ld!);
    expect(parsed['@type']).toBe('JobPosting');
    expect(parsed.title).toBeTruthy();
    expect(parsed.hiringOrganization?.name).toBeTruthy();
  });

  test('shows apply/share/star action buttons', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);

    const applyButton = page.getByRole('link', { name: /Apply now/i });
    if (await applyButton.count() > 0) {
      await expect(applyButton).toBeVisible();
      await expect(applyButton).toHaveAttribute('target', '_blank');
      await expect(applyButton).toHaveAttribute('rel', /noopener/);
    }

    await expect(page.getByRole('button', { name: /Share/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /favorite|favorites/i })).toBeVisible();
  });

  test('star toggle works', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    const star = page.getByRole('button', { name: /Add to favorites/i });
    await star.click();
    await expect(page.getByRole('button', { name: /Remove from favorites/i })).toBeVisible();
  });

  test('interaction tracking toggles status', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    const applied = page.getByRole('button', { name: 'Applied' });
    await applied.click();
    await expect(applied).toHaveAttribute('aria-pressed', 'true');
    await applied.click();
    await expect(applied).toHaveAttribute('aria-pressed', 'false');
  });

  test('shows 404 page for unknown id', async ({ page }) => {
    const response = await page.goto('/opportunities/this-does-not-exist-abc123');
    expect(response?.status()).toBe(404);
    await expect(page.getByRole('heading', { name: /Opportunity not found/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Browse matches/i })).toBeVisible();
  });

  test('Back to matches link navigates toward results', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    const backLink = page.getByRole('link', { name: /Back to matches/i });
    await expect(backLink).toHaveAttribute('href', '/results');
  });
});

test.describe('Detail page linked from MatchCard', () => {
  test('clicking match title goes to detail page', async ({ page }) => {
    await page.goto('/');
    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });
    await page.getByRole('button', { name: /Generate Matches/i }).click();
    await page.waitForURL('**/results*');

    const firstCard = page.locator('[id^="match-card-"]').first();
    await expect(firstCard).toBeVisible({ timeout: 30_000 });
    const titleLink = firstCard.locator('h3 a').first();
    const href = await titleLink.getAttribute('href');
    expect(href).toMatch(/^\/opportunities\//);

    await titleLink.click();
    await expect(page).toHaveURL(/\/opportunities\//);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });
});
