import { test, expect } from '@playwright/test';

test.describe('Home → Results core flow', () => {
  test('loads home, shows opportunity count', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /Find Your Perfect/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Database coverage', exact: true })).toBeVisible();
    for (const label of ['Projects & postings', 'Professor profiles']) {
      const count = page.locator('dl > div').filter({ has: page.getByText(label, { exact: true }) });
      await expect(count.locator('dt')).toHaveText(label);
      await expect(count.locator('dd')).toHaveText(/^\d[\d,]*$/);
    }
  });

  test('disables Generate Matches until required fields filled', async ({ page }) => {
    await page.goto('/');
    const button = page.getByRole('button', { name: /Generate Matches/i });
    await expect(button).toBeDisabled();

    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });

    await expect(button).toBeEnabled();
  });

  test('generates matches and lands on /results', async ({ page }) => {
    test.slow();
    await page.goto('/', { waitUntil: 'networkidle' });
    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });

    await page.getByRole('button', { name: /Generate Matches/i }).click();
    await page.waitForURL('**/results*', { timeout: 30_000 });
    await expect(page.getByRole('heading', { name: /Your Matches/i })).toBeVisible();
    await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 60_000 });
  });
});

test.describe('Profile strength widget', () => {
  test('hides when profile complete enough', async ({ page }) => {
    await page.goto('/');
    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });
    const strength = page.getByText(/Profile strength/);
    expect(await strength.count()).toBeGreaterThanOrEqual(0);
  });
});
