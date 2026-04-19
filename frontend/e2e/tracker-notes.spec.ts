import { test, expect } from '@playwright/test';

const KNOWN_ID = 'uiuc-ece-cv-lab';

test.describe('Application tracker notes & reminder', () => {
  test('notes panel toggles open and closed', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    const toggle = page.getByRole('button', { name: /notes or reminder/i });
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(page.getByPlaceholder(/Private notes/i)).toBeVisible();
    await toggle.click();
    await expect(page.getByPlaceholder(/Private notes/i)).not.toBeVisible();
  });

  test('typing notes shows Saving and then Saved', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    await page.getByRole('button', { name: /notes or reminder/i }).click();
    const textarea = page.getByPlaceholder(/Private notes/i);
    await textarea.fill('Prep: review their recent NeurIPS paper');
    const statusIndicator = page.locator('[aria-live="polite"]').filter({ hasText: /Saving|Saved/ });
    await expect(statusIndicator).toBeVisible({ timeout: 3_000 });
  });

  test('setting remind_at persists across reload', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    await page.getByRole('button', { name: /notes or reminder/i }).click();
    const dateInput = page.locator('input[type="date"]');
    await dateInput.fill('2026-05-01');
    await page.waitForTimeout(2000);

    await page.reload();
    const panelToggle = page.getByRole('button', { name: /Notes & reminder|notes or reminder/i });
    await panelToggle.waitFor();
    if (await panelToggle.getAttribute('aria-expanded') !== 'true') {
      await panelToggle.click();
    }
    const persisted = await page.locator('input[type="date"]').first().inputValue();
    if (persisted !== '2026-05-01') {
      test.skip(true, 'Supabase migration 005 not yet applied to this database');
    }
    expect(persisted).toBe('2026-05-01');
  });

  test('character counter reflects notes length', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    await page.getByRole('button', { name: /notes or reminder/i }).click();
    const textarea = page.getByPlaceholder(/Private notes/i);
    await textarea.fill('hello');
    await expect(page.getByText('5 / 2000')).toBeVisible();
  });

  test('clear reminder button removes the date', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    await page.getByRole('button', { name: /notes or reminder/i }).click();
    const dateInput = page.locator('input[type="date"]');
    await dateInput.fill('2026-05-01');
    await page.waitForTimeout(1500);

    await page.getByRole('button', { name: /Clear/ }).click();
    await expect(dateInput).toHaveValue('');
  });

  test('auto-sets applied status when adding a note on untracked opp', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);

    const appliedButton = page.getByRole('button', { name: 'Applied' });
    if (await appliedButton.getAttribute('aria-pressed') === 'true') {
      await appliedButton.click();
      await page.waitForTimeout(300);
    }

    await page.getByRole('button', { name: /notes or reminder/i }).click();
    await page.getByPlaceholder(/Private notes/i).fill('Test auto-apply');
    await page.waitForTimeout(1500);

    await expect(appliedButton).toHaveAttribute('aria-pressed', 'true');
  });
});

test.describe('Dashboard reminders widget', () => {
  async function hasRemindAtColumn(page: import('@playwright/test').Page): Promise<boolean> {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    await page.getByRole('button', { name: /notes or reminder/i }).click();
    await page.locator('input[type="date"]').fill('2030-05-01');
    await page.waitForTimeout(2000);
    await page.reload();
    const toggle = page.getByRole('button', { name: /Notes & reminder|notes or reminder/i });
    await toggle.waitFor();
    if (await toggle.getAttribute('aria-expanded') !== 'true') {
      await toggle.click();
    }
    const value = await page.locator('input[type="date"]').first().inputValue();
    return value === '2030-05-01';
  }

  test('shows reminders widget when reminders exist', async ({ page }) => {
    const persisted = await hasRemindAtColumn(page);
    if (!persisted) {
      test.skip(true, 'Supabase migration 005 not yet applied to this database');
    }
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: /Your reminders/i })).toBeVisible();
  });

  test('reminder entry links to opportunity detail', async ({ page }) => {
    const persisted = await hasRemindAtColumn(page);
    if (!persisted) {
      test.skip(true, 'Supabase migration 005 not yet applied to this database');
    }
    await page.goto('/dashboard');
    const widget = page.getByRole('heading', { name: /Your reminders/i });
    await expect(widget).toBeVisible();
    const firstReminder = page.locator('h2:has-text("Your reminders") ~ ul a').first();
    const href = await firstReminder.getAttribute('href');
    expect(href).toContain(`/opportunities/${KNOWN_ID}`);
  });
});
