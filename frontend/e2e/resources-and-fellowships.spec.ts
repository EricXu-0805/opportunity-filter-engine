import { test, expect, type Page } from '@playwright/test';

async function openMobileNavIfVisible(page: Page) {
  const toggle = page.getByTestId('mobile-nav-toggle');
  if (await toggle.isVisible()) {
    await toggle.click();
  }
}

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
    await openMobileNavIfVisible(page);
    await page.getByRole('link', { name: /Find Matches|^Match$/ }).first().click();
    await page.waitForURL('**/');
    await expect(page.getByRole('heading', { name: /Find Your Perfect/i })).toBeVisible();
  });
});

test.describe('dormant release routes', () => {
  for (const path of ['/fellowships', '/roadmap', '/compare?ids=one,two']) {
    test(`${path} fails closed with 404`, async ({ page }) => {
      const response = await page.goto(path);
      expect(response?.status()).toBe(404);
    });
  }

  test('home and header do not advertise dormant product areas', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('link', { name: /^Fellowships$|^Funding$/ })).toHaveCount(0);
    await expect(page.getByRole('link', { name: /^Roadmap$/ })).toHaveCount(0);
    await expect(page.getByTestId('featured-fellowships')).toHaveCount(0);
    await expect(page.getByText(/^Fellowship$/)).toHaveCount(0);
  });
});

test.describe('cross-route navigation from header', () => {
  test('Resources remains reachable from the accepted header', async ({ page }) => {
    await page.goto('/');
    await openMobileNavIfVisible(page);
    await page.getByRole('link', { name: /^Resources$|^Tips$/ }).click();
    await page.waitForURL('**/resources');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  });
});
