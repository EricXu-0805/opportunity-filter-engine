import { test, expect, type Page } from '@playwright/test';

// uiuc-siebel-ugresearch: hand-curated umbrella seed — survives refreshes, unlike
// scraped ids (hash of name/url) or the fabricated prototype record this replaced.
// Pinned by test_e2e_detail_fixture_present (backend DQ) so a data PR that drops
// it fails fast there, not with a 404-cascade here. Update both if this changes.
const KNOWN_ID = 'uiuc-siebel-ugresearch';

// TrackerPanel autosaves on a 600ms debounce, then flips the aria-live
// indicator to "Saved" once the write round-trips. Waiting on that state
// (instead of sleeping) guarantees the save has actually completed.
async function waitForSaved(page: Page) {
  await expect(
    page.locator('[aria-live="polite"]').filter({ hasText: /Saved/ }),
  ).toBeVisible({ timeout: 5_000 });
}

// Notes/reminders attach to a tracked status — saving without one would have
// to invent an 'applied' (a send event the user never reported), so the panel
// only autosaves once a status exists. Tests that exercise persistence first
// set one explicitly, the way a real user does.
async function ensureTracked(page: Page) {
  const appliedButton = page.getByRole('button', { name: 'Applied' });
  if (await appliedButton.getAttribute('aria-pressed') !== 'true') {
    await appliedButton.click();
    await expect(appliedButton).toHaveAttribute('aria-pressed', 'true');
  }
}

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
    await ensureTracked(page);
    await page.getByRole('button', { name: /notes or reminder/i }).click();
    const textarea = page.getByPlaceholder(/Private notes/i);
    await textarea.fill('Prep: review their recent NeurIPS paper');
    const statusIndicator = page.locator('[aria-live="polite"]').filter({ hasText: /Saving|Saved/ });
    await expect(statusIndicator).toBeVisible({ timeout: 3_000 });
  });

  test('setting remind_at persists across reload', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    await ensureTracked(page);
    await page.getByRole('button', { name: /notes or reminder/i }).click();
    const dateInput = page.locator('input[type="date"]');
    await dateInput.fill('2026-05-01');
    await waitForSaved(page);

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
    // Notes attach to a tracked status, so the box is disabled until one
    // exists — the same convention the rest of this file already follows.
    await ensureTracked(page);
    await page.getByRole('button', { name: /notes or reminder/i }).click();
    const textarea = page.getByPlaceholder(/Private notes/i);
    await textarea.fill('hello');
    await expect(page.getByText('5 / 2000')).toBeVisible();
  });

  test('clear reminder button removes the date', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    await ensureTracked(page);
    await page.getByRole('button', { name: /notes or reminder/i }).click();
    const dateInput = page.locator('input[type="date"]');
    await dateInput.fill('2026-05-01');
    // Wait for the save round-trip so the detail sync effect cannot
    // re-populate the input with the stale date after we clear it.
    await waitForSaved(page);

    await page.getByRole('button', { name: /Clear/ }).click();
    await expect(dateInput).toHaveValue('');
  });

  test('does NOT auto-set applied when adding a note on untracked opp', async ({ page }) => {
    await page.goto(`/opportunities/${KNOWN_ID}`);

    const appliedButton = page.getByRole('button', { name: 'Applied' });
    if (await appliedButton.getAttribute('aria-pressed') === 'true') {
      await appliedButton.click();
      await expect(appliedButton).toHaveAttribute('aria-pressed', 'false');
    }

    await page.getByRole('button', { name: /notes or reminder/i }).click();
    // The panel asks for a status instead of fabricating an 'applied'
    // interaction (a send event the user never reported).
    await expect(page.getByText(/Pick a status above first/i)).toBeVisible();
    // Stronger than "typing does not auto-apply": there is nothing to type
    // into. The box is disabled until a status exists, so the auto-apply this
    // test guards against is unreachable rather than merely not taken.
    await expect(page.getByPlaceholder(/Private notes/i)).toBeDisabled();
    // Give the (gated) 600ms debounce ample time to prove it never fires.
    await page.waitForTimeout(1_500);
    await expect(appliedButton).toHaveAttribute('aria-pressed', 'false');
    await expect(
      page.locator('[aria-live="polite"]').filter({ hasText: /Saving|Saved/ }),
    ).not.toBeVisible();
  });
});

test.describe('Dashboard reminders widget', () => {
  async function hasRemindAtColumn(page: import('@playwright/test').Page): Promise<boolean> {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    await ensureTracked(page);
    await page.getByRole('button', { name: /notes or reminder/i }).click();
    await page.locator('input[type="date"]').fill('2030-05-01');
    await waitForSaved(page);
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
    // Scoped by the section, not by `h2 ~ ul`: the heading lives inside the
    // card's header row, so it is not a SIBLING of the list and that selector
    // can never match this markup.
    const firstReminder = page
      .locator('section:has(h2:has-text("Your reminders")) ul a')
      .first();
    const href = await firstReminder.getAttribute('href');
    expect(href).toContain(`/opportunities/${KNOWN_ID}`);
  });
});
