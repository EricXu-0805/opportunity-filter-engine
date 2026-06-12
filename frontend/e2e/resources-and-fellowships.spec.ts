import { test, expect } from '@playwright/test';

test.describe('/resources page', () => {
  test('renders the main heading and both sections', async ({ page }) => {
    await page.goto('/resources');
    await expect(
      page.getByRole('heading', { level: 1 }),
    ).toBeVisible();
    await expect(page.locator('section[aria-labelledby="contact-tips-heading"]')).toBeVisible();
    await expect(page.locator('section[aria-labelledby="databases-heading"]')).toBeVisible();
  });

  test('shows 3 lab-type contact-tips cards (wet, dry, humanities)', async ({ page }) => {
    await page.goto('/resources');
    const section = page.locator('section[aria-labelledby="contact-tips-heading"]');
    const cards = section.locator('article[aria-labelledby^="tips-"]');
    await expect(cards).toHaveCount(3);
    await expect(section.locator('article[aria-labelledby="tips-wet-heading"]')).toBeVisible();
    await expect(section.locator('article[aria-labelledby="tips-dry-heading"]')).toBeVisible();
    await expect(section.locator('article[aria-labelledby="tips-humanities-heading"]')).toBeVisible();
  });

  test('shows at least 4 database link cards with external link semantics', async ({ page }) => {
    await page.goto('/resources');
    const section = page.locator('section[aria-labelledby="databases-heading"]');
    const externals = section.locator('a[target="_blank"]');
    await expect(externals.first()).toBeVisible();
    const count = await externals.count();
    expect(count).toBeGreaterThanOrEqual(4);
    for (let i = 0; i < count; i++) {
      const rel = await externals.nth(i).getAttribute('rel');
      expect(rel ?? '').toMatch(/noopener/);
      expect(rel ?? '').toMatch(/noreferrer/);
    }
  });

  test('navigates from /resources back to home via the header', async ({ page }) => {
    await page.goto('/resources');
    await page.getByRole('link', { name: /Find Matches|^Match$/ }).first().click();
    await page.waitForURL('**/');
    await expect(page.getByRole('heading', { name: /Find Your Perfect/i })).toBeVisible();
  });
});

test.describe('/fellowships page', () => {
  test('renders the heading, filter controls, and the count label', async ({ page }) => {
    await page.goto('/fellowships');
    await expect(
      page.getByRole('heading', { level: 1, name: /Research fellowships|Fellowships/i }),
    ).toBeVisible();
    await expect(page.getByText(/Showing \d+ of \d+/)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole('group', { name: /year/i }).first()).toBeVisible();
  });

  test('changing the year filter changes the visible count', async ({ page }) => {
    await page.goto('/fellowships');
    // The count label renders "Showing 0 of 0" while the fetch is in flight
    // (FellowshipFilters sits above the loading gate) — wait for a non-zero
    // total so the captured baseline is the loaded state, not the transient.
    await expect(page.getByText(/Showing \d+ of [1-9]\d*/)).toBeVisible({ timeout: 20_000 });
    const before = (await page.getByText(/Showing \d+ of \d+/).first().textContent()) ?? '';

    await page.getByRole('button', { name: 'Freshman', exact: true }).click();

    await expect.poll(async () => {
      const txt = (await page.getByText(/Showing \d+ of \d+/).first().textContent()) ?? '';
      return txt;
    }, { timeout: 5_000 }).not.toBe(before);

    await expect(page.getByRole('button', { name: 'Freshman', exact: true })).toHaveAttribute('aria-pressed', 'true');
  });

  test('clear-filters button resets the state', async ({ page }) => {
    await page.goto('/fellowships');
    // Same loaded-state gate as above: capturing during the "0 of 0"
    // in-flight render made the reset comparison flaky.
    await expect(page.getByText(/Showing \d+ of [1-9]\d*/)).toBeVisible({ timeout: 20_000 });
    const cleanCount = (await page.getByText(/Showing \d+ of \d+/).first().textContent()) ?? '';

    await page.getByRole('button', { name: 'Senior', exact: true }).click();
    await page.getByRole('button', { name: /Clear filters/i }).click();

    await expect.poll(async () => {
      const txt = (await page.getByText(/Showing \d+ of \d+/).first().textContent()) ?? '';
      return txt;
    }, { timeout: 5_000 }).toBe(cleanCount);
  });

  test('selecting a college pill toggles aria-pressed', async ({ page }) => {
    await page.goto('/fellowships');
    await expect(page.getByText(/Showing \d+ of \d+/)).toBeVisible({ timeout: 20_000 });

    const beckman = page.getByRole('button', { name: 'Beckman', exact: true });
    await expect(beckman).toBeVisible();
    await expect(beckman).toHaveAttribute('aria-pressed', 'false');

    await beckman.click();
    await expect(beckman).toHaveAttribute('aria-pressed', 'true');
  });

  test('navigates from /fellowships back to / via "Match by profile instead"', async ({ page }) => {
    await page.goto('/fellowships');
    await page.getByRole('link', { name: /Match by profile instead/i }).click();
    await page.waitForURL('**/');
    await expect(page.getByRole('heading', { name: /Find Your Perfect/i })).toBeVisible();
  });
});

test.describe('cross-route navigation from header', () => {
  test('Resources and Fellowships nav items both link to their routes', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: /^Resources$|^Tips$/ }).click();
    await page.waitForURL('**/resources');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    await page.getByRole('link', { name: /^Fellowships$|^Funding$/ }).click();
    await page.waitForURL('**/fellowships');
    await expect(page.getByRole('heading', { level: 1, name: /Research fellowships|Fellowships/i })).toBeVisible();
  });
});
