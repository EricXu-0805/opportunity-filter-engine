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
  await page.getByRole('button', { name: 'Edit résumé bullets', exact: true }).click();
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

  test('cancelled exits retain unsaved bullet edits before an explicit switch', async ({ page }) => {
    await stubRenovate(page);
    await openRenovation(page);
    await page.getByRole('button', { name: 'Renovate with AI' }).click();
    await expect(page.getByText(REWRITTEN)).toBeVisible({ timeout: 30_000 });
    await page.getByRole('button', { name: 'Edit this bullet', exact: true }).first().click();
    const draft = page.getByRole('textbox', { name: 'Edit this bullet', exact: true });
    await draft.fill('Manual changes that have not been saved');
    let confirmations = 0;
    const cancelExit = async (dialog: import('@playwright/test').Dialog) => {
      expect(dialog.type()).toBe('confirm');
      confirmations += 1;
      await dialog.dismiss();
    };
    page.on('dialog', cancelExit);
    await draft.press('Escape');
    await expect(draft).toHaveValue('Manual changes that have not been saved');
    await page.getByRole('button', { name: 'Close renovation dialog', exact: true }).click();
    await expect(draft).toHaveValue('Manual changes that have not been saved');
    await page.getByRole('button', { name: 'Open full target résumé', exact: true }).click();
    await expect(draft).toHaveValue('Manual changes that have not been saved');
    expect(confirmations).toBe(3);
    page.off('dialog', cancelExit);
    page.once('dialog', async dialog => { await dialog.accept(); });
    await page.getByRole('button', { name: 'Open full target résumé', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'Target résumé', exact: true })).toBeVisible();
    await expect(draft).toHaveCount(0);
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

      await page.getByRole('button', { name: 'Edit résumé bullets', exact: true }).click();
      await expect(page.getByText(/Save a résumé to your profile first/)).toBeVisible();
      await expect(page.getByRole('button', { name: 'Renovate with AI' })).toHaveCount(0);
    });
});


// M37: complete master editing uses the real browser/profile coordinator and
// loopback Supabase stub. No model, email or hosted storage is involved.
test.describe('Complete résumé master', () => {
  test.describe.configure({ timeout: 60_000 });
  const source = 'Alex 王\nEducation: Example University, 2026–expected\n' + '完整原文🧪 '.repeat(500);
  const confirmedDetail = 'Built and documented a reproducible instrument. ' + '实验记录🧪 '.repeat(400);
  async function openMaster(page: Page) {
    await page.addInitScript(({ profileKey, localeKey, data }) => {
      if (!localStorage.getItem('master-browser-seeded')) {
        localStorage.setItem(profileKey, JSON.stringify(data));
        localStorage.setItem(localeKey, 'en');
        localStorage.setItem('master-browser-seeded', '1');
      }
    }, { profileKey: STORAGE_KEYS.PROFILE, localeKey: STORAGE_KEYS.LOCALE, data: {
      ...PROFILE, search_weight: 50, skills: [], resume_text: source,
      experience_entries: [
        { id: 'confirmed-project', revision: 3, status: 'confirmed', text: confirmedDetail, source: { kind: 'manual' } },
        { id: 'candidate-project', revision: 1, status: 'candidate', text: 'Unconfirmed experience must not appear', source: { kind: 'manual' } },
      ],
    } });
    await page.goto('/');
    const card = page.locator('#resume-master');
    await card.getByText('Open full résumé editor', { exact: true }).click();
    await expect(card.getByRole('textbox', { name: 'Full name', exact: true })).toBeEnabled();
    return card;
  }

  test('edits exact identity, education and publication fields, then restores them after saving', async ({ page }, testInfo) => {
    const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
    const card = await openMaster(page);
    const fillConfirmed = async (label: string, value: string) => {
      await card.getByRole('textbox', { name: label, exact: true }).fill(value);
      await card.getByRole('button', { name: `Confirm ${label}`, exact: true }).click();
    };
    await expect(card.getByRole('textbox', { name: 'Full name', exact: true })).toHaveValue('');
    await fillConfirmed('Full name', 'Alex 王');
    await fillConfirmed('Email', 'synthetic-student@example.edu');
    await card.getByRole('button', { name: 'Add education', exact: true }).click();
    await fillConfirmed('School', 'Example University');
    await fillConfirmed('Degree', 'B.S. (in progress)');
    await fillConfirmed('End date / expected date', 'Expected 2027');
    await card.getByRole('button', { name: 'Add publication', exact: true }).click();
    await fillConfirmed('Publication title', 'Instrument study');
    await fillConfirmed('Authors in exact order', 'J. Lee; Alex 王; M. Doe');
    await fillConfirmed('Publication status', 'Submitted, not accepted');
    await card.getByRole('button', { name: 'Add experience or project', exact: true }).click();
    await fillConfirmed('Role / project title', 'Instrument project');
    const activity = card.getByRole('group', { name: 'Activity 1', exact: true });
    await activity.getByRole('checkbox').check();
    const preview = card.getByRole('region', { name: 'Résumé preview' });
    await expect(preview).toContainText(confirmedDetail);
    await expect(preview).not.toContainText('Unconfirmed experience must not appear');
    await expect(preview).toContainText('Expected 2027');
    const saved = page.waitForResponse(r => r.url().includes('/rest/v1/rpc/commit_profile_patch_cas')
      && r.request().postDataJSON()?.p_patch?.resume_master?.basics?.name?.value === 'Alex 王');
    await card.getByRole('button', { name: 'Apply changes', exact: true }).click();
    const receipt = await (await saved).json();
    expect(['applied', 'unchanged']).toContain(receipt.status);
    expect(receipt.profile.resume_master.publications[0].authors.value).toBe('J. Lee; Alex 王; M. Doe');
    expect(receipt.profile.resume_text).toBe(source);
    expect(receipt.profile.experience_entries[0].text).toBe(confirmedDetail);
    await page.reload();
    await card.getByText('Open full résumé editor', { exact: true }).click();
    await expect(card.getByRole('textbox', { name: 'Full name', exact: true })).toHaveValue('Alex 王');
    await expect(card.getByRole('textbox', { name: 'Authors in exact order', exact: true })).toHaveValue('J. Lee; Alex 王; M. Doe');
    await expect(preview).toContainText(confirmedDetail);
    await expect(preview).toContainText('Submitted, not accepted');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
    await preview.screenshot({ path: testInfo.outputPath('complete-master-preview.png') });
    expect(errors).toEqual([]);
  });

  test('keeps source and long text intact; unfinished fields do not crash or enter the preview', async ({ page }) => {
    const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
    const card = await openMaster(page);
    await card.getByText('View complete current résumé source', { exact: true }).click();
    expect(await card.locator('pre').textContent()).toBe(source);
    await card.getByRole('button', { name: 'Add link', exact: true }).click();
    await expect(card.getByRole('button', { name: 'Apply changes', exact: true })).toBeVisible();
    await card.getByRole('button', { name: 'Remove link', exact: true }).click();
    await card.getByRole('button', { name: 'Add another section', exact: true }).click();
    await card.getByRole('textbox', { name: 'Section heading', exact: true }).fill('Additional contributions');
    await card.getByRole('button', { name: 'Add detail', exact: true }).click();
    const long = '完整内容🧪'.repeat(1201);
    await card.getByRole('textbox', { name: 'Additional detail 1', exact: true }).fill(long);
    const preview = card.getByRole('region', { name: 'Résumé preview' });
    await expect(preview).not.toContainText(long);
    await card.getByRole('button', { name: 'Confirm Additional detail 1', exact: true }).click();
    await expect(preview).toContainText(long);
    const saved = page.waitForResponse(r => r.url().includes('/rest/v1/rpc/commit_profile_patch_cas')
      && r.request().postDataJSON()?.p_patch?.resume_master?.other_sections?.[0]?.items?.[0]?.value === long);
    await card.getByRole('button', { name: 'Apply changes', exact: true }).click();
    expect((await (await saved).json()).profile.resume_master.other_sections[0].items[0].value).toBe(long);
    await page.reload();
    await card.getByText('Open full résumé editor', { exact: true }).click();
    await expect(card.getByRole('textbox', { name: 'Additional detail 1', exact: true })).toHaveValue(long);
    await expect(preview).toContainText(long);
    await card.getByRole('textbox', { name: 'Additional detail 1', exact: true }).fill(`${long} edited`);
    await expect(preview).not.toContainText(long);
    expect(errors).toEqual([]);
  });
});

// Complete target drafts use the real modal, source binding, Supabase client and
// owner lifecycle. The loopback storage server stands in for hosted persistence;
// SQL tests separately prove CAS/RLS/merge semantics against PostgreSQL.
test.describe('Complete target résumé', () => {
  test.describe.configure({ timeout: 90_000 });
  const raw = 'Full original résumé source 王🧪\n' + 'Source material beyond old truncation limits. '.repeat(250);
  const fullDetail = 'Complete project evidence 王🧪 '.repeat(120);
  const longField = 'L'.repeat(6_004) + '终';
  const fact = (id: string, value: string) => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
  const master = {
    version: 1, id: 'target-browser-master', revision: 7, source_signature: null,
    basics: { name: fact('name', 'Alex 王'), email: fact('email', 'synthetic-student@example.edu'), links: [] },
    education: [{ id: 'education-1', school: fact('school', 'Example University'), degree: fact('degree', 'B.S. (in progress)'), end: fact('end', 'Expected 2027'), details: [] }],
    activities: [{ id: 'project-1', kind: 'project', title: fact('project-title', 'Instrument project'), details: [{ id: 'project-evidence', revision: 2 }] }],
    publications: [{ id: 'publication-1', title: fact('paper-title', 'Instrument study'), authors: fact('authors', 'J. Lee; Alex 王; M. Doe'), publication_status: fact('paper-status', 'Submitted, not accepted'), details: [] }],
    skills: [fact('python', 'Python')],
    other_sections: [{ id: 'extended', heading: 'Extended note', items: [fact('long-note', longField)] }],
    section_order: ['basics', 'education', 'activities', 'publications', 'skills', 'extended'], unmapped_ranges: [],
  };
  async function seed(page: Page) {
    await page.addInitScript(({ profileKey, localeKey, data }) => {
      if (!localStorage.getItem('target-browser-seeded')) {
        localStorage.setItem(profileKey, JSON.stringify(data));
        localStorage.setItem(localeKey, 'en');
        localStorage.setItem('target-browser-seeded', '1');
      }
    }, { profileKey: STORAGE_KEYS.PROFILE, localeKey: STORAGE_KEYS.LOCALE, data: {
      ...PROFILE, search_weight: 50, resume_text: raw, resume_master: master,
      experience_entries: [
        { id: 'project-evidence', revision: 2, status: 'confirmed', text: fullDetail, source: { kind: 'manual' } },
        { id: 'not-confirmed', revision: 1, status: 'candidate', text: 'UNCONFIRMED MUST NOT APPEAR IN DRAFT', source: { kind: 'manual' } },
      ],
    } });
  }
  async function open(page: Page) {
    await page.goto(`/opportunities/${KNOWN_ID}`);
    await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'Target résumé' })).toBeVisible();
  }
  async function create(page: Page) {
    await seed(page); await open(page);
    await page.getByRole('button', { name: 'Create from confirmed master', exact: true }).click();
    await expect(page.getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue('Alex 王');
  }
  async function save(page: Page, expectedRevision: number) {
    return test.step(`Save from expected revision ${expectedRevision}`, async () => {
      const button = page.getByRole('button', { name: 'Save target draft', exact: true });
      await expect(button).toBeEnabled();
      const [response] = await Promise.all([
        page.waitForResponse(r => r.url().includes('/rest/v1/rpc/commit_target_resume_cas')
          && r.request().postDataJSON()?.p_expected_revision === expectedRevision, { timeout: 15_000 }),
        button.click(),
      ]);
      return response.json();
    });
  }
  async function unchangedMaster(page: Page) {
    const saved = await page.evaluate(key => JSON.parse(localStorage.getItem(key) ?? '{}'), STORAGE_KEYS.PROFILE);
    expect(saved.resume_text).toBe(raw);
    expect(saved.resume_master).toEqual(master);
    expect(saved.experience_entries[0].text).toBe(fullDetail);
  }

  test('keeps full confirmed content, saves independent edits and reloads them without changing the master', async ({ page }, testInfo) => {
    const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
    await create(page);
    const preview = page.getByRole('region', { name: 'Current target draft preview' });
    await expect(preview).toContainText(fullDetail);
    await expect(preview).toContainText('J. Lee; Alex 王; M. Doe');
    await expect(preview).toContainText('Submitted, not accepted');
    await expect(preview).not.toContainText('UNCONFIRMED MUST NOT APPEAR IN DRAFT');
    await expect(page.getByRole('textbox', { name: 'Edit Extended note', exact: true })).toHaveValue(longField);
    const name = page.getByRole('textbox', { name: 'Edit Full name', exact: true });
    await name.fill('Alex 王'); await name.press('End'); await name.pressSequentially(' — targeted');
    await expect(name).toHaveValue('Alex 王 — targeted');
    await expect(name).toBeFocused();
    const receipt = await save(page, 0);
    expect(receipt.status).toBe('saved'); expect(receipt.revision).toBe(1);
    expect(receipt.doc.base_snapshot.resume_text).toBe(raw);
    expect(receipt.doc.base_snapshot.resume_master).toEqual(master);
    await expect(page.getByText('Saved version 1', { exact: true })).toBeVisible();
    await unchangedMaster(page);
    await page.getByRole('button', { name: 'Close target résumé', exact: true }).click();
    await page.reload();
    await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
    await expect(name).toHaveValue('Alex 王 — targeted');
    await expect(page.getByRole('textbox', { name: 'Edit Extended note', exact: true })).toHaveValue(longField);
    await expect(preview).toContainText(fullDetail);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
    await preview.screenshot({ path: testInfo.outputPath('full-target-preview.png') });
    await page.getByRole('button', { name: 'Save target draft', exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath('full-target-workspace.png'), fullPage: false });
    await unchangedMaster(page); expect(errors).toEqual([]);
  });

  test('restores a full historical version as a new save', async ({ page }) => {
    await create(page); expect((await save(page, 0)).revision).toBe(1);
    await page.getByRole('textbox', { name: 'Edit Full name', exact: true }).fill('Manual version two');
    expect((await save(page, 1)).revision).toBe(2);
    await page.getByText('Version history', { exact: true }).click();
    await page.getByRole('button', { name: 'Load latest 20 versions', exact: true }).click();
    await page.getByRole('button', { name: /^View version 1 ·/ }).click();
    const old = page.getByRole('region', { name: 'Selected historical version preview' });
    await expect(old).toContainText('Alex 王'); await expect(old).toContainText(longField);
    const response = page.waitForResponse(r => r.url().includes('/rest/v1/rpc/commit_target_resume_cas')
      && r.request().postDataJSON()?.p_expected_revision === 2);
    await page.getByRole('button', { name: 'Restore selected version as a new save', exact: true }).click();
    const receipt = await (await response).json();
    expect(receipt.status).toBe('saved'); expect(receipt.revision).toBe(3);
    await expect(page.getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue('Alex 王');
    await page.getByRole('button', { name: 'Load latest 20 versions', exact: true }).click();
    await expect(page.getByRole('button', { name: /^View version 1 ·/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /^View version 2 ·/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /^View version 3 ·/ })).toBeVisible();
    await unchangedMaster(page);
  });

  test('keeps edits when another tab saves first', async ({ page, context }) => {
    let targetReads = 0;
    context.on('request', request => {
      if (request.method() === 'GET' && request.url().includes('/rest/v1/target_resumes?')) targetReads += 1;
    });
    await create(page); expect((await save(page, 0)).revision).toBe(1);
    const other = await context.newPage();
    await test.step('Open saved target in second tab', async () => { await open(other); });
    await expect(other.getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue('Alex 王');
    await test.step('Edit first tab', async () => {
      await page.getByRole('textbox', { name: 'Edit Full name', exact: true }).fill('First tab accepted');
      await expect(page.getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue('First tab accepted');
    });
    expect((await save(page, 1)).revision).toBe(2);
    await other.getByRole('textbox', { name: 'Edit Full name', exact: true }).fill('Second tab unsaved');
    expect((await save(other, 1)).status).toBe('conflict');
    await expect(other.getByText(/A newer server version exists/)).toBeVisible();
    await expect(other.getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue('Second tab unsaved');
    await other.getByRole('button', { name: 'Discard local edits and load server version', exact: true }).click();
    await expect(other.getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue('First tab accepted');
    await unchangedMaster(page);
    // Two opening reads and one explicit conflict reload should remain bounded.
    // The former same-owner marker loop made over 10,000 reads in 90 seconds.
    expect(targetReads).toBeLessThanOrEqual(6);
    await other.close();
  });

  test('read failure pauses creation and retry loads safely', async ({ page }) => {
    await seed(page);
    let fail = true;
    await page.route('**/rest/v1/target_resumes?*', async route => {
      if (fail) await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: 'synthetic unavailable' }) });
      else await route.continue();
    });
    await open(page);
    // The client retries GET 503 after 1s, 2s and 4s before surfacing failure.
    await expect(page.getByText(/The saved résumé could not be read/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: 'Create from confirmed master', exact: true })).toHaveCount(0);
    fail = false;
    await page.getByRole('button', { name: 'Retry reading saved résumé', exact: true }).click();
    await page.getByRole('button', { name: 'Create from confirmed master', exact: true }).click();
    await expect(page.getByRole('textbox', { name: 'Edit Full name', exact: true })).toHaveValue('Alex 王');
  });
});
