import { randomUUID } from 'node:crypto';
import { test, expect, type Page } from '@playwright/test';

const ACCOUNT_SERVER = `http://127.0.0.1:${process.env.E2E_SUPABASE_PORT ?? 54321}`;

async function goToResults(page: Page) {
  await page.goto('/');
  await page.selectOption('#college', 'Grainger College of Engineering');
  await page.selectOption('#major', { index: 1 });
  await page.selectOption('#grade', { index: 1 });
  await page.getByRole('button', { name: /Generate Matches/i }).click();
  await page.waitForURL('**/results*');
  await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 30_000 });
}

test.describe('Saved searches end-to-end', () => {
  test('save current filters via /results button and see them on /favorites', async ({ page, request }) => {
    const email = `saved-search-${randomUUID()}@example.test`;
    const signup = await request.post(`${ACCOUNT_SERVER}/auth/v1/signup`, { data: { email } });
    expect(signup.status()).toBe(200);
    const session = await signup.json();
    expect(session.user).toMatchObject({ email, is_anonymous: false });
    await page.addInitScript((session) => {
      if (!localStorage.getItem('ofe_auth')) {
        localStorage.setItem('ofe_auth', JSON.stringify(session));
      }
    }, session);
    await goToResults(page);

    await page.getByPlaceholder(/Search by title/i).fill('machine learning');

    const saveButton = page.getByRole('button', { name: /Save to account/i });
    await expect(saveButton).toBeVisible({ timeout: 5_000 });

    const testName = `e2e-r22-${Date.now()}`;
    await saveButton.click();

    // The save dialog replaces the old window.prompt flow.
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 5_000 });
    await dialog.getByLabel(/^Name$/).fill(testName);

    const insert = page.waitForResponse(resp =>
      new URL(resp.url()).pathname === '/rest/v1/saved_searches' && resp.request().method() === 'POST');
    await dialog.getByRole('button', { name: /^Save search$/i }).click();
    const response = await insert;
    expect(response.ok()).toBe(true);
    expect(response.request().postDataJSON()).toMatchObject({
      device_id: session.user.id, name: testName, query: 'machine learning',
    });
    const saved = await response.json();
    expect(saved).toMatchObject({ id: expect.any(String), name: testName, query: 'machine learning' });

    await page.goto('/favorites');
    const apply = page.getByRole('link', { name: `Apply saved search "${testName}"`, exact: true });
    await expect(apply).toBeVisible();
    await expect(page.getByText(/pending first sync/i).first()).toBeVisible();
    await apply.click();
    await expect(page.getByPlaceholder(/Search by title/i)).toHaveValue('machine learning');
  });

  test('highlight ring renders on /results when ?highlight=<id> is set', async ({ page }) => {
    await goToResults(page);

    const allIds = await page
      .locator('[id^="match-card-"]')
      .evaluateAll((els) => els.map((el) => el.id));
    expect(allIds.length).toBeGreaterThan(0);

    const targetWrapperId = allIds[0];
    const oppId = targetWrapperId.slice('match-card-'.length);
    const otherWrapperId = allIds.find((id) => id !== targetWrapperId);

    await page.goto(`/results?highlight=${encodeURIComponent(oppId)}`);

    const wrapper = page.locator(`[id="${targetWrapperId}"]`);
    await expect(wrapper).toBeVisible({ timeout: 30_000 });
    await expect(wrapper).toHaveClass(/ring-amber-400/);
    await expect(wrapper.getByText(/New match/i)).toBeVisible();

    if (otherWrapperId) {
      await expect(page.locator(`[id="${otherWrapperId}"]`)).not.toHaveClass(/ring-amber-400/);
    }
  });
});
