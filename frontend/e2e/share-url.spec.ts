import { test, expect, type Page } from '@playwright/test';
import { attachProfileReadDiagnostics } from './profile-read-diagnostics';

// Observations only: no wait, event dispatch, retry or profile mutation. Keep
// source and imported fields separate so a missing clipboard value cannot be
// mistaken for the destination losing an otherwise correct shared profile.
async function shareSnapshot(page: Page, phase: string, shareUrl?: string) {
  let decoded: unknown = undefined;
  if (shareUrl !== undefined) {
    try {
      const encoded = new URL(shareUrl).searchParams.get('share');
      decoded = encoded === null ? { error: 'missing-share-parameter' }
        : JSON.parse(Buffer.from(encoded, 'base64url').toString('utf8'));
    } catch { decoded = { error: 'invalid-share-payload' }; }
  }
  const form = await page.evaluate(() => ({
    college: (document.querySelector('#college') as HTMLSelectElement | null)?.value ?? null,
    major: (document.querySelector('#major') as HTMLSelectElement | null)?.value ?? null,
    grade: (document.querySelector('#grade') as HTMLSelectElement | null)?.value ?? null,
    interests: (document.querySelector('#research_interests') as HTMLTextAreaElement | null)?.value ?? null,
    hydration: document.querySelector('[data-testid="hydration-note"]')?.textContent ?? null,
    freshness: document.querySelector('[data-testid="home-profile-refresh-status"]')?.textContent ?? null,
    saveStatus: document.querySelector('#profile-save-status')?.textContent ?? null,
    profileReadMarks: performance.getEntriesByType('mark')
      .filter(mark => mark.name.startsWith('ofe-profile-read:')).slice(-64)
      .map(mark => ({ name: mark.name, startTime: mark.startTime })),
  })).catch(() => ({ error: 'page-unavailable' }));
  return { phase, form, ...(shareUrl !== undefined ? { decodedShare: decoded } : {}) };
}

test.describe('Profile share URL', () => {
  test('generates a copyable share URL with encoded profile', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.goto('/');
    await page.selectOption('#college', 'Grainger College of Engineering');
    await page.selectOption('#major', { index: 1 });
    await page.selectOption('#grade', { index: 1 });
    await page.getByRole('textbox', { name: /Research Interests/i }).fill('signed-profile-marker-abc123');

    const shareBtn = page.getByRole('button', { name: /Share profile/i });
    await expect(shareBtn).toBeVisible();
    await shareBtn.click();

    await expect(page.getByText(/Copied!/)).toBeVisible();

    const clipboard = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboard).toContain('?share=');
    expect(clipboard.split('?share=')[1].length).toBeGreaterThan(20);
  });

  test('loading a share URL pre-fills the form and shows banner', async ({ page }, testInfo) => {
    const observations: Awaited<ReturnType<typeof shareSnapshot>>[] = [];
    let victim: Page | undefined;
    let shareUrl: string | undefined;
    let completed = false;
    try {
      await page.goto('/');
      await page.selectOption('#college', 'Grainger College of Engineering');
      await page.selectOption('#major', { index: 1 });
      await page.selectOption('#grade', { index: 1 });
      await page.getByRole('textbox', { name: /Research Interests/i })
        .fill('MARKER_SHARED_E2E_ZZZ');
      observations.push(await shareSnapshot(page, 'source-after-fill'));

      await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
      observations.push(await shareSnapshot(page, 'source-before-copy'));
      await page.getByRole('button', { name: /Share profile/i }).click();
      await expect(page.getByText(/Copied!/)).toBeVisible();
      shareUrl = await page.evaluate(() => navigator.clipboard.readText());
      observations.push(await shareSnapshot(page, 'source-after-clipboard-read', shareUrl));

      victim = await page.context().newPage();
      await victim.goto(shareUrl);
      observations.push(await shareSnapshot(page, 'source-after-victim-open', shareUrl));
      observations.push(await shareSnapshot(victim, 'victim-after-open', shareUrl));

      await expect(victim.getByText(/Loaded a shared profile/i)).toBeVisible();
      await expect(victim.locator('#research_interests'))
        .toHaveValue(/MARKER_SHARED_E2E_ZZZ/);
      completed = true;
    } finally {
      if (!completed) {
        observations.push(await shareSnapshot(page, 'source-at-failure', shareUrl));
        if (victim) observations.push(await shareSnapshot(victim, 'victim-at-failure', shareUrl));
        await testInfo.attach('share-url-form-and-payload-observations', {
          body: JSON.stringify(observations, null, 2), contentType: 'application/json',
        });
        await attachProfileReadDiagnostics(page, testInfo, 'share-source');
        if (victim) await attachProfileReadDiagnostics(victim, testInfo, 'share-victim');
      }
    }
  });

  test('rejects malformed share payload gracefully', async ({ page }) => {
    await page.goto('/?share=not-a-valid-payload!!!');
    await expect(page.getByText(/Loaded a shared profile/i)).not.toBeVisible();
    await expect(page.getByRole('heading', { name: /Find Your Perfect/i })).toBeVisible();
  });
});
