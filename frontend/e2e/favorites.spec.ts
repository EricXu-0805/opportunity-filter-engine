import { test, expect, type Page } from '@playwright/test';

// Matches STORAGE_KEYS.FAVORITES_FALLBACK in src/lib/storage-keys.ts.
const FAVORITES_FALLBACK_KEY = 'ofe_favs_fallback';
// Matches STORAGE_KEYS.CUSTOM_IMPORTS in src/lib/storage-keys.ts.
const CUSTOM_IMPORTS_KEY = 'ofe_custom_imports';
const MISSING_ID = 'e2e-nonexistent-opportunity-id';
const CUSTOM_IMPORT_TITLE = 'E2E Custom Import';

async function seedExtraFavoriteId(page: Page, id: string) {
  await page.evaluate(
    ({ key, id }) => {
      const raw = localStorage.getItem(key);
      const ids: string[] = raw ? JSON.parse(raw) : [];
      if (!ids.includes(id)) ids.push(id);
      localStorage.setItem(key, JSON.stringify(ids));
    },
    { key: FAVORITES_FALLBACK_KEY, id },
  );
}

// A local custom import needs no server fetch at all — seeding one makes
// opportunities.length > 0 independently of whatever the shortlist fetch
// does, which is what turns "Email is hidden during an error" into a real
// counterfactual instead of a tautology (an empty list hides Email either way).
async function seedCustomImport(page: Page, title: string) {
  await page.evaluate(
    ({ key, title }) => {
      const entry = {
        id: 'e2e-custom-import-1',
        imported_at: new Date(0).toISOString(),
        opportunity: {
          source: 'manual',
          source_url: 'https://example.edu/e2e-custom',
          title,
          description_raw: 'seeded for an e2e header-gating counterfactual',
          url: 'https://example.edu/e2e-custom',
          extra_fields: {},
        },
      };
      localStorage.setItem(key, JSON.stringify([entry]));
    },
    { key: CUSTOM_IMPORTS_KEY, title },
  );
}

async function goToResults(page: Page) {
  await page.goto('/');
  await page.selectOption('#college', 'Grainger College of Engineering');
  await page.selectOption('#major', { index: 1 });
  await page.selectOption('#grade', { index: 1 });
  await page.getByRole('button', { name: /Generate Matches/i }).click();
  await page.waitForURL('**/results*');
  await expect(page.locator('[id^="match-card-"]').first()).toBeVisible({ timeout: 30_000 });
}

test.describe('Favorites', () => {
  test('star toggles a card into the starred tab', async ({ page }) => {
    await goToResults(page);

    const firstCard = page.locator('[id^="match-card-"]').first();
    const title = await firstCard.locator('h3').innerText();

    const star = firstCard.locator('button[aria-label*="favorite" i]').first();
    await star.click();

    await page.getByRole('tab', { name: /Starred/i }).click();
    await expect(page.locator('h3', { hasText: title })).toBeVisible();

    await expect(
      page.getByRole('button', { name: /Export.*CSV/i }),
    ).toBeVisible();
  });

  test('CSV export download has expected shape', async ({ page }) => {
    await goToResults(page);
    const firstCard = page.locator('[id^="match-card-"]').first();
    await firstCard.locator('button[aria-label*="favorite" i]').first().click();

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /Export.*CSV/i }).click();
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toMatch(/opportunities-\d{4}-\d{2}-\d{2}\.csv/);
    const path = await download.path();
    expect(path).toBeTruthy();
  });
});

test.describe('Interaction tracking (dismiss)', () => {
  test('dismiss hides card and toggle shows it again', async ({ page }) => {
    await goToResults(page);
    const firstCard = page.locator('[id^="match-card-"]').first();
    const title = await firstCard.locator('h3').innerText();

    // R69-C (#63): the inline "Not interested" pill row was replaced by the
    // "Mark status" disclosure menu (portaled to <body>, hence not scoped
    // to the card). It is a NON-modal disclosure dialog — role="dialog"
    // with plain buttons, deliberately not role="menu"/menuitemradio (see
    // InteractionStatusMenu.tsx's doc comment for the ARIA reasoning).
    await firstCard.getByRole('button', { name: /^Set application status for/ }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Not interested' }).click();
    await expect(page.locator('h3', { hasText: title }).first()).not.toBeVisible();

    const showDismissed = page.getByRole('button', { name: /Show.*dismissed/i });
    const showFilters = page.getByRole('button', { name: /Show filters/i });
    // Dismissing changes the canonical server view, so both controls briefly
    // disappear behind the loading state. Wait for the responsive UI to settle
    // before deciding whether the filter rail is collapsed.
    await expect(showDismissed.or(showFilters)).toBeVisible({ timeout: 30_000 });
    if (await showFilters.isVisible()) {
      // On mobile the dismissed toggle lives in the collapsed filter rail.
      await showFilters.click();
    }
    await showDismissed.click();
    await expect(page.locator('h3', { hasText: title })).toBeVisible();
  });
});

test.describe('Shortlist accounting (error / partial / all-unavailable)', () => {
  test('a shortlist fetch failure shows error + Retry, never the empty-favorites copy, and hides Email even though a local item alone would make the old header show it — Retry recovers', async ({ page }) => {
    await goToResults(page);
    const firstCard = page.locator('[id^="match-card-"]').first();
    const title = await firstCard.locator('h3').innerText();
    await firstCard.locator('button[aria-label*="favorite" i]').first().click();

    // A local custom import needs no server fetch — it alone makes
    // opportunities.length > 0 even while the shortlist fetch is failing.
    // Under the OLD header that would be enough to show Email; the safe
    // error header must still hide it. Without this, "Email is hidden"
    // during an error would be tautological (an empty list hides it too).
    await seedCustomImport(page, CUSTOM_IMPORT_TITLE);

    let blockBatch = true;
    await page.route('**/api/opportunities/batch', async (route) => {
      if (blockBatch) {
        await route.fulfill({ status: 500, contentType: 'application/json', body: '{}' });
      } else {
        await route.continue();
      }
    });

    await page.goto('/favorites');
    await expect(page.getByText(/Couldn.t load your favorites/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/haven.t starred any/i)).not.toBeVisible();
    await expect(page.locator('h3', { hasText: CUSTOM_IMPORT_TITLE })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Email favorites' })).not.toBeVisible();

    blockBatch = false;
    await page.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByText(/Couldn.t load your favorites/i)).not.toBeVisible({ timeout: 15_000 });
    await expect(page.locator('h3', { hasText: title })).toBeVisible();
    // Recovery restores the real header and its actions, now backed by a
    // complete, clean accounting (the real resolved favorite + the custom import).
    await expect(page.getByRole('button', { name: 'Email favorites' })).toBeVisible();
  });

  test('a partial shortlist (one id missing) shows the found card, an unavailable warning, and the correct total — never the empty-favorites copy, and still hides Email despite a real found row', async ({ page }) => {
    await goToResults(page);
    const firstCard = page.locator('[id^="match-card-"]').first();
    const title = await firstCard.locator('h3').innerText();
    await firstCard.locator('button[aria-label*="favorite" i]').first().click();

    // Seed a second, non-existent favorite id directly into the local
    // fallback store — the real backend legitimately skips it, producing a
    // genuine partial (found=1, unavailable=1) without any network mocking.
    await seedExtraFavoriteId(page, MISSING_ID);

    await page.goto('/favorites');
    await expect(page.locator('h3', { hasText: title })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/1 saved item.s. could not be loaded right now/i)).toBeVisible();
    await expect(page.getByText(/haven.t starred any/i)).not.toBeVisible();
    await expect(page.getByText(/Couldn.t load your favorites/i)).not.toBeVisible();
    // Total = 1 found + 1 unavailable = 2 — the header must not undercount
    // by only reflecting the successfully-resolved rows.
    await expect(page.getByText('2 saved', { exact: true })).toBeVisible();
    // Genuine gating proof: found=1 means opportunities.length > 0, so an
    // old-header check would show Email; the safe header must still hide
    // it while unavailableCount > 0.
    await expect(page.getByRole('button', { name: 'Email favorites' })).not.toBeVisible();
  });

  test('all favorited ids unavailable: reports the count, never claims "you have no favorites"', async ({ page }) => {
    await page.goto('/');
    await seedExtraFavoriteId(page, MISSING_ID);

    await page.goto('/favorites');
    await expect(page.getByText(/1 saved item.s. could not be loaded right now/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/haven.t starred any/i)).not.toBeVisible();
    // Note: with zero resolved cards here, an Email/Compare-hidden
    // assertion would be tautological (an empty list hides them under the
    // old header too) — the partial (found=1) case above is what actually
    // proves the degraded-state header gating.
  });
});
