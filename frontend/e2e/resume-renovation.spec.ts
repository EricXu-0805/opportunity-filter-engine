import { test, expect, type Page, type Route } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';

/**
 * Résumé renovation — the acceptance run, in a real browser.
 *
 * tests/test_resume_renovation.py proves the staged routes and
 * ResumeRenovationModal.test.tsx proves the component's logic. This proves the
 * shipped thing: the release switch really opens the door, the production React
 * build mounts the modal, and the one product invariant a student's trust rests
 * on survives the whole chain — **their own sentence is always still there.**
 *
 * Only the renovate call is stubbed, and only at its outermost edge, so the run
 * does not depend on an LLM being configured or on which bullets a model
 * happens to foreground. Everything between the click and that edge is shipped
 * code: the release gate, the real /api/tailor/structure, the modal, the
 * variant chain, and the rollback pointer.
 */
const KNOWN_ID = 'uiuc-siebel-ugresearch';

const OWN_WORDS = 'Built a Python script that parsed 3,000 rows of lab sensor data';
const REWRITTEN = 'Processed 3,000 rows of lab sensor data in Python, charting daily trends';

const PROFILE = {
  name: 'Alex Chen',
  institution: 'UIUC',
  college: 'Grainger College of Engineering',
  major: 'Computer Science',
  grade: 'Sophomore',
  is_international: false,
  research_interests: 'machine learning',
  skills: ['Python'],
  coursework: ['CS 225'],
  resume_text: [
    'EXPERIENCE',
    `- ${OWN_WORDS}`,
    '- Teaching assistant for CS 225; ran weekly office hours for 25 students',
  ].join('\n'),
};

/** Answer /api/tailor/renovate as a model that foregrounded the first bullet
 *  and left the second alone, echoing the section ids /tailor/structure just
 *  produced. Returns the bullet the stub rewrote so assertions cannot drift
 *  from what the server was told. */
async function stubRenovate(page: Page) {
  await page.route('**/api/tailor/renovate', async (route: Route) => {
    const body = route.request().postDataJSON() as {
      sections: { id: string; heading: string; kind: string;
                  bullets: { id: string; text: string }[] }[];
    };
    const sections = body.sections.map((section) => ({
      id: section.id,
      heading: section.heading,
      kind: section.kind,
      bullets: section.bullets.map((bullet, index) => ({
        id: bullet.id,
        base_text: bullet.text,
        action: index === 0 ? 'foreground' : 'keep',
        variants: index === 0
          ? [{ source: 'macro', text: REWRITTEN, source_evidence: OWN_WORDS }]
          : [],
        current: index === 0 ? 0 : -1,
      })),
    }));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        sections, method: 'ai', warnings: [], opportunity_id: KNOWN_ID,
      }),
    });
  });
}

async function openRenovation(page: Page) {
  await page.addInitScript(
    ([key, value]) => { window.localStorage.setItem(key, value); },
    [STORAGE_KEYS.PROFILE, JSON.stringify(PROFILE)] as const,
  );
  await page.goto(`/opportunities/${KNOWN_ID}`);
  await page.getByRole('button', { name: 'Renovate Resume' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
}

test.describe('Résumé renovation (real browser)', () => {
  // The detail route is one of the heaviest in the app and this file loads it
  // four times. Under `next dev` a cold compile alone can eat the default
  // budget, which is a property of the harness rather than of the feature.
  test.describe.configure({ timeout: 60_000 });

  test('the release switch actually opens the door', async ({ page }) => {
    // The whole point of the acceptance: with resumeRenovate closed the header
    // renders no opener at all, so this button existing IS the flip, observed
    // from outside the process that decides it.
    await page.addInitScript(
      ([key, value]) => { window.localStorage.setItem(key, value); },
      [STORAGE_KEYS.PROFILE, JSON.stringify(PROFILE)] as const,
    );
    await page.goto(`/opportunities/${KNOWN_ID}`);
    await expect(page.getByRole('button', { name: 'Renovate Resume' })).toBeVisible();
  });

  test('renovating keeps the student\'s own sentence one click away', async ({ page }) => {
    await stubRenovate(page);
    await openRenovation(page);

    await page.getByRole('button', { name: 'Renovate with AI' }).click();

    // The AI version is what the student is shown…
    await expect(page.getByText(REWRITTEN)).toBeVisible({ timeout: 30_000 });

    // …and one click puts their own words back. A rollback is a pointer move
    // over a chain that still holds base_text, so this can never be a second
    // generation that happens to look like the original.
    await page.getByRole('button', { name: 'Roll back to the previous version of this bullet' })
      .first().click();
    await expect(page.getByText(OWN_WORDS)).toBeVisible();
    await expect(page.getByText(REWRITTEN)).toHaveCount(0);
  });

  test('an unavailable model leaves the résumé intact rather than empty', async ({ page }) => {
    // The degraded path a real student can hit — provider down, budget spent.
    // The contract is that renovation falls back to a passthrough document, so
    // what they see is still their own résumé, never a blank or an invention.
    await page.route('**/api/tailor/renovate', async (route: Route) => {
      const body = route.request().postDataJSON() as {
        sections: { id: string; heading: string; kind: string;
                    bullets: { id: string; text: string }[] }[];
      };
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sections: body.sections.map((section) => ({
            id: section.id,
            heading: section.heading,
            kind: section.kind,
            bullets: section.bullets.map((bullet) => ({
              id: bullet.id, base_text: bullet.text,
              action: 'keep', variants: [], current: -1,
            })),
          })),
          method: 'fallback',
          warnings: ['llm_not_configured'],
        }),
      });
    });
    await openRenovation(page);

    await page.getByRole('button', { name: 'Renovate with AI' }).click();

    await expect(page.getByText(OWN_WORDS)).toBeVisible({ timeout: 30_000 });
  });

  test('a student with no saved résumé is told what to do, not shown a broken pipeline',
    async ({ page }) => {
      const { resume_text: _dropped, ...noResume } = PROFILE;
      await page.addInitScript(
        ([key, value]) => { window.localStorage.setItem(key, value); },
        [STORAGE_KEYS.PROFILE, JSON.stringify(noResume)] as const,
      );
      await page.goto(`/opportunities/${KNOWN_ID}`);
      await page.getByRole('button', { name: 'Renovate Resume' }).click();

      await expect(page.getByText(/Save a résumé to your profile first/)).toBeVisible();
      await expect(page.getByRole('button', { name: 'Renovate with AI' })).toHaveCount(0);
    });
});
