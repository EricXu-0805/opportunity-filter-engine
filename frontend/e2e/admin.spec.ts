import { test, expect, type Page } from '@playwright/test';

// In the e2e webServer env the backend has no ADMIN_TOKEN, so every
// /api/admin/* call returns 503. With a real ADMIN_TOKEN the mismatch
// path returns 401 (frontend then clears state and returns to login).
// The two test.describes below cover both branches.

const ADMIN_HEADING = /Admin · Data Quality/i;
const ADMIN_DISABLED_MSG = /Admin endpoints disabled/i;

async function gotoAdmin(page: Page) {
  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: ADMIN_HEADING })).toBeVisible();
}

test.describe('Admin login + error paths (no ADMIN_TOKEN required)', () => {
  test('renders login form when no session token is set', async ({ page }) => {
    await gotoAdmin(page);

    await expect(page.getByText(/Paste your ADMIN_TOKEN/i)).toBeVisible();
    await expect(page.getByPlaceholder(/Admin token/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /^Load$/i })).toBeVisible();

    const backLink = page.getByRole('link', { name: /Back/i });
    await expect(backLink).toBeVisible();
    await expect(backLink).toHaveAttribute('href', '/');
  });

  test('password field masks the token + Load button starts disabled', async ({ page }) => {
    await gotoAdmin(page);

    const input = page.getByPlaceholder(/Admin token/i);
    const submit = page.getByRole('button', { name: /^Load$/i });

    await expect(input).toHaveAttribute('type', 'password');
    await expect(input).toHaveAttribute('autocomplete', 'off');

    await expect(submit).toBeDisabled();
    await input.fill('any-non-empty');
    await expect(submit).toBeEnabled();
    await input.fill('');
    await expect(submit).toBeDisabled();
  });

  test('submitting any token surfaces the 503 disabled-error banner', async ({ page }) => {
    await gotoAdmin(page);

    await page.getByPlaceholder(/Admin token/i).fill('e2e-fake-token');
    await page.getByRole('button', { name: /^Load$/i }).click();

    await expect(page.getByText(ADMIN_DISABLED_MSG)).toBeVisible({ timeout: 10_000 });

    await expect(page.getByRole('button', { name: /^Lock$/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /^Refresh$/i })).not.toBeVisible();
  });

  test('Lock button after a failed submit returns to the login form', async ({ page }) => {
    await gotoAdmin(page);

    await page.getByPlaceholder(/Admin token/i).fill('e2e-fake-token');
    await page.getByRole('button', { name: /^Load$/i }).click();
    await expect(page.getByText(ADMIN_DISABLED_MSG)).toBeVisible({ timeout: 10_000 });

    await page.getByRole('button', { name: /^Lock$/i }).click();

    await expect(page.getByPlaceholder(/Admin token/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /^Load$/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /^Lock$/i })).not.toBeVisible();

    const stored = await page.evaluate(() => sessionStorage.getItem('ofe_admin_token'));
    expect(stored).toBeNull();
  });

  test('?token=<value> on mount is stripped from the URL (no leak via history / Referer)', async ({ page }) => {
    await page.goto('/admin?token=e2e-token-from-url&keep=this');

    await expect(page.getByRole('heading', { name: ADMIN_HEADING })).toBeVisible();

    await expect.poll(() => new URL(page.url()).searchParams.get('token')).toBeNull();
    expect(new URL(page.url()).searchParams.get('keep')).toBe('this');

    const stored = await page.evaluate(() => sessionStorage.getItem('ofe_admin_token'));
    expect(stored).toBe('e2e-token-from-url');

    await expect(page.getByText(ADMIN_DISABLED_MSG)).toBeVisible({ timeout: 10_000 });
  });

  test('login form is i18n-aware: Chinese locale renders the zh strings', async ({ context, page }) => {
    await context.addCookies([
      { name: 'ofe_lang', value: 'zh', url: 'http://127.0.0.1:3100' },
    ]);
    await page.goto('/admin');

    await expect(page.getByRole('heading', { name: /管理 · 数据质量/ })).toBeVisible();
    await expect(page.getByText(/粘贴你的 ADMIN_TOKEN/)).toBeVisible();
  });
});

test.describe('Admin authenticated dashboard (requires ADMIN_TOKEN env)', () => {
  test.beforeEach(() => {
    test.skip(
      !process.env.ADMIN_TOKEN,
      'ADMIN_TOKEN not set in webServer env — skip authenticated dashboard checks',
    );
  });

  test('valid ?token=<ADMIN_TOKEN> loads the dashboard widgets', async ({ page }) => {
    const token = process.env.ADMIN_TOKEN!;
    await page.goto(`/admin?token=${encodeURIComponent(token)}`);

    await expect(page.getByRole('heading', { name: ADMIN_HEADING })).toBeVisible();
    await expect(page.getByRole('button', { name: /^Refresh$/i })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: /^Lock$/i })).toBeVisible();

    await expect(page.getByRole('heading', { name: /Distribution by source/i })).toBeVisible();
  });

  test('Lock after a valid login clears state and returns to the login form', async ({ page }) => {
    const token = process.env.ADMIN_TOKEN!;
    await page.goto(`/admin?token=${encodeURIComponent(token)}`);
    await expect(page.getByRole('button', { name: /^Refresh$/i })).toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: /^Lock$/i }).click();
    await expect(page.getByPlaceholder(/Admin token/i)).toBeVisible();
    const stored = await page.evaluate(() => sessionStorage.getItem('ofe_admin_token'));
    expect(stored).toBeNull();
  });
});
