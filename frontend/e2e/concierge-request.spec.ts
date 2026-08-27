import { test, expect, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';

/**
 * "Have JoinALab handle this one" — bound to the opportunity, in a real
 * browser.
 *
 * The jsdom fixture proves the component's states. This proves the thing the
 * funnel actually depends on: the request SURVIVES. A student who asks and
 * then reloads must still see that they asked, because the row is what an
 * operator later works from — a state that lived only in React would look
 * identical on the screen and be worth nothing in the queue.
 *
 * Nothing is stubbed. The write goes through the real supabase-js client to
 * the loopback stand-in, so the round trip under test is the shipped one.
 */
const KNOWN_ID = 'uiuc-siebel-ugresearch';

const PROFILE = {
  name: 'Alex Chen',
  institution: 'UIUC',
  college: 'Grainger College of Engineering',
  major: 'Computer Science',
  grade: 'Sophomore',
  is_international: false,
  research_interests: 'machine learning',
  skills: ['Python'],
};

async function openDetail(page: Page) {
  await page.addInitScript(
    ([key, value]) => { window.localStorage.setItem(key, value); },
    [STORAGE_KEYS.PROFILE, JSON.stringify(PROFILE)] as const,
  );
  await page.goto(`/opportunities/${KNOWN_ID}`);
}

test.describe('Concierge request (real browser)', () => {
  test.describe.configure({ timeout: 60_000 });

  test('asking is remembered across a reload, not just on the screen',
    async ({ page }) => {
      await openDetail(page);

      const submit = page.getByTestId('concierge-request-submit');
      await expect(submit).toBeVisible({ timeout: 30_000 });
      // Anonymous session: the form asks where to reach them first.
      await page.getByLabel('Where should we reach you?').fill('alex@illinois.edu');
      await submit.click();

      await expect(page.getByTestId('concierge-requested')).toBeVisible();

      // The reload is the assertion. Local state does not survive it; a row
      // does.
      await page.reload();
      await expect(page.getByTestId('concierge-requested')).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId('concierge-request-submit')).toHaveCount(0);
    });

  test('asking about one professor does not answer for another', async ({ page }) => {
    // The whole point of migration 033: the request names a target. If the
    // stored state were per-student rather than per-(student, target), the
    // second page would open already answered.
    await openDetail(page);
    await page.getByLabel('Where should we reach you?').fill('alex@illinois.edu');
    await page.getByTestId('concierge-request-submit').click();
    await expect(page.getByTestId('concierge-requested')).toBeVisible();

    await page.goto('/opportunities/uiuc-career-center-ugr');
    await expect(page.getByTestId('concierge-request-submit')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('concierge-requested')).toHaveCount(0);
  });
});
