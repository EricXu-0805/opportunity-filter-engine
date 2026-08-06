import { test, expect } from '@playwright/test';

/**
 * The first thing a visitor does must not be thrown away.
 *
 * Anonymous sign-in reaches the app as TWO auth observations — INITIAL_SESSION
 * carrying no user, then SIGNED_IN carrying the browser's first uid — while the
 * school catalog enables the college dropdown before either of them lands. The
 * second observation used to run the full account-switch reset, so a college
 * picked the instant the page became interactive vanished ~300ms later, and the
 * same pick three seconds on stuck. 2,892 green unit tests did not see it; only
 * a browser did, because only a browser produces that observation sequence.
 *
 * Covered in jsdom by FV-0/FV-4/FV-5 in use-profile-form.test.tsx. This is the
 * end-to-end half: a real supabase-js client, its real event sequence, and a
 * real controlled <select>.
 */
test.describe('First visit', () => {
  test('a college picked the moment the page is interactive survives sign-in', async ({ page }) => {
    // The window is REAL but latency-shaped: against hosted Supabase the
    // sign-in round trip is ~300ms and the catalog beats it, which is how a
    // student hits this. Against the loopback stub it resolves in about a
    // millisecond and the window never opens — a version of this test without
    // the delay below passes against the defect, proving nothing. Holding the
    // auth response makes the ordering deterministic instead of hoping for it.
    await page.route('**/auth/v1/**', async (route) => {
      await new Promise((r) => setTimeout(r, 1_500));
      await route.continue();
    });

    await page.goto('/');

    const college = page.locator('#college');
    // Playwright waits for actionability, which for this control means exactly
    // "the catalog landed and the dropdown enabled" — the opening edge of the
    // window the defect lived in. Racing it by hand would be flakier, not
    // sharper.
    await expect(college).toBeEnabled({ timeout: 30_000 });

    const options = await college.locator('option').allTextContents();
    if (options.length < 2) {
      // No catalog served (backend or corpus unavailable): the free-text input
      // renders instead and this scenario cannot exist. Fail rather than skip —
      // a silent skip here is what let the defect ship in the first place.
      throw new Error(`college catalog empty; got options ${JSON.stringify(options)}`);
    }

    await college.selectOption({ index: 1 });
    const picked = await college.inputValue();
    expect(picked, 'accepted on the spot').not.toBe('');

    // Well past the sign-in round trip that used to wipe it. A poll would pass
    // against a value that has not been reset YET, so wait the whole window out
    // and read once.
    await page.waitForTimeout(4_000);

    expect(
      await college.inputValue(),
      'the first thing a visitor typed is still there after sign-in resolved',
    ).toBe(picked);

    // A reset would also have cleared the rest of the form, so prove the value
    // is genuinely held rather than repainted by a late catalog render.
    // The delay above has done its job. Left in place it also throttles the
    // session restore after the reload below, which is not the thing under
    // test.
    await page.unroute('**/auth/v1/**');
    await page.reload();
    // Polled, unlike the check above: the catalog enables the control before
    // the saved row hydrates, so reading once here races the load. The
    // assertion above must NOT poll — there the value has to survive the whole
    // window, and a poll would pass on a value that has not been reset yet.
    await expect(
      page.locator('#college'),
      'and it was actually persisted, not just left on screen',
    ).toHaveValue(picked, { timeout: 30_000 });
  });
});
