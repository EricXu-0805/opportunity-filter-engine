import { test, expect } from '@playwright/test';

/**
 * The tour a first-time visitor cannot get past.
 *
 * OnboardingIntro is a full-viewport modal with no dismiss: Escape routes to
 * the campus step rather than closing, and the last step's CTA is the only way
 * out. From #708 until this spec existed, that CTA was disabled on production
 * for every new browser — the baseline it gates on was discarded by a counter
 * that also advances on same-identity readiness transitions, of which a normal
 * load fires two. Nothing logged, nothing rendered, the button just stayed
 * grey. The free flow began with a locked door.
 *
 * It stayed invisible because BOTH test layers arranged it away: every spec
 * starts from a storageState with ONBOARDING_SEEN already set (global-setup),
 * and the component test calls enterLocalOnlyMode() in beforeEach — the exact
 * precondition that fails in a browser. So this spec opts out of the seeded
 * state, which is what global-setup's own comment says specs exercising the
 * tour should do, and which nothing did until now.
 */
// NOT `storageState: undefined` — which is what global-setup's comment
// recommends, and which Playwright reads as "unspecified" and quietly falls
// back to the project default, seeded flag and all. An explicitly EMPTY state
// is the only way to get the fresh browser this spec is about. The documented
// opt-out never worked, which is part of why nothing ever used it.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe('Onboarding tour', () => {
  test('a first-time visitor can reach the end and get out', async ({ page }) => {
    await page.goto('/');

    const dialog = page.getByTestId('onboarding-intro');
    await expect(dialog).toBeVisible();

    const cta = page.getByTestId('onboarding-primary');
    // Page to the campus step. The count is deliberately not hardcoded: the
    // slide list is release-scoped, so a hidden feature changes it.
    for (let i = 0; i < 10; i += 1) {
      if (await page.getByTestId('onboarding-school-list').count()) break;
      await cta.click();
    }
    await expect(page.getByTestId('onboarding-school-list')).toBeVisible();

    // The whole bug in one assertion: on the only step that can close the
    // tour, the only control that closes it has to work.
    await expect(cta).toBeEnabled();
    await cta.click();

    await expect(dialog).toBeHidden();
    await expect(page.getByTestId('onboarding-error')).toHaveCount(0);
    expect(
      await page.evaluate(() => localStorage.getItem('ofe_onboarding_seen')),
    ).toBe('1');
  });
});
