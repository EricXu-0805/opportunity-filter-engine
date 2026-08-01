import { test, expect, type Page } from '@playwright/test';

// uiuc-siebel-ugresearch: hand-curated umbrella seed — survives refreshes, unlike
// scraped ids (hash of name/url) or the fabricated prototype record this replaced.
// Pinned by test_e2e_detail_fixture_present (backend DQ) so a data PR that drops
// it fails fast there, not with a 404-cascade here. Update both if this changes.
const KNOWN_ID = 'uiuc-siebel-ugresearch';

async function goToResults(page: Page) {
  await page.goto('/');
  await page.selectOption('#college', 'Grainger College of Engineering');
  await page.selectOption('#major', { index: 1 });
  await page.selectOption('#grade', { index: 1 });
  await page.getByRole('button', { name: /Generate Matches/i }).click();
  await page.waitForURL('**/results*');
  await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 30_000 });
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

test.describe('Opportunity detail page', () => {
  test('renders full page SSR with title and meta', async ({ page }) => {
    const response = await page.goto(`/opportunities/${KNOWN_ID}`);
    expect(response?.status()).toBe(200);

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const title = await page.title();
    expect(title).toContain('JoinALab');

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

  test('shows not-found UI (and noindex) for an unknown id — the route\'s loading.tsx streams a shell, so the top-level nav status is not a reliable signal here', async ({ page }) => {
    // Per Next.js's own loading.js docs: once a route has a loading
    // boundary, the initial shell streams with its headers (status 200)
    // already committed before the async Server Component resolves —
    // notFound() deep inside it can still swap in the not-found UI and an
    // injected robots=noindex meta, but cannot retroactively change the
    // status code already sent. Accept either status; the honest,
    // framework-accurate contract is the rendered UI + noindex.
    const response = await page.goto('/opportunities/this-does-not-exist-abc123');
    expect([200, 404]).toContain(response?.status());
    await expect(page.getByRole('heading', { name: /Opportunity not found/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Browse matches/i })).toBeVisible();
    // The page can carry more than one robots meta tag (e.g. a root-layout
    // default alongside the not-found-injected one) — assert at least one
    // is the noindex Next injects, not that it's the only tag present.
    const noindexCount = await page.locator('meta[name="robots"][content*="noindex" i]').count();
    expect(noindexCount).toBeGreaterThan(0);
  });

  test('Back to matches link navigates toward results', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    const backLink = page.getByRole('link', { name: /Back to matches/i });
    await expect(backLink).toHaveAttribute('href', '/results');
  });
});

test.describe('Detail page linked from MatchCard', () => {
  test('clicking match title goes to detail page', async ({ page }) => {
    await goToResults(page);

    const firstCard = page.locator('[id^="match-card-"]').first();
    const titleLink = firstCard.locator('h3 a').first();
    const href = await titleLink.getAttribute('href');
    expect(href).toMatch(/^\/opportunities\//);

    await titleLink.click();
    await expect(page).toHaveURL(/\/opportunities\//);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });
});

test.describe('Target-A journey: Match -> Detail -> Shortlist -> reopen -> reload', () => {
  test('the same opportunity id is preserved through Match, star, favorites reopen, and reload', async ({ page }) => {
    // 1. Deterministic Match result A — the real product flow: submit the
    // default profile and take the first ranked card exactly as rendered,
    // capturing its own href/title rather than assuming any fixed id.
    await goToResults(page);
    const firstCard = page.locator('[id^="match-card-"]').first();
    const titleLink = firstCard.locator('h3 a').first();
    const hrefA = await titleLink.getAttribute('href');
    expect(hrefA).toMatch(/^\/opportunities\//);
    const titleA = await titleLink.innerText();
    const urlPatternA = new RegExp(`${escapeRegExp(hrefA!)}$`);

    // 2. Open Detail A.
    await titleLink.click();
    await expect(page).toHaveURL(urlPatternA);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(titleA);

    // 3. Shortlist A.
    const star = page.getByRole('button', { name: /Add to favorites/i });
    await star.click();
    await expect(page.getByRole('button', { name: /Remove from favorites/i })).toBeVisible();

    // 4. Reopen A from the shortlist (Favorites), by its own exact href/title
    // — never by list position, which could silently land on a different record.
    await page.goto('/favorites');
    const cardLink = page.getByRole('link', { name: titleA });
    await expect(cardLink).toBeVisible({ timeout: 15_000 });
    await expect(cardLink).toHaveAttribute('href', hrefA!);
    await cardLink.click();
    await expect(page).toHaveURL(urlPatternA);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(titleA);
    await expect(page.getByRole('button', { name: /Remove from favorites/i })).toBeVisible();

    // 5. Reload and still see A — on the detail page itself...
    await page.reload();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(titleA);
    await expect(page.getByRole('button', { name: /Remove from favorites/i })).toBeVisible();

    // ...and on the shortlist it was reopened from.
    await page.goto('/favorites');
    await page.reload();
    const reloadedLink = page.getByRole('link', { name: titleA });
    await expect(reloadedLink).toBeVisible({ timeout: 15_000 });
    await expect(reloadedLink).toHaveAttribute('href', hrefA!);
  });
});
