import { test, expect, type APIRequestContext, type BrowserContext, type Page, type Request } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { ProfileData, ResumeFact } from '../src/lib/types';
import { attachProfileReadDiagnostics } from './profile-read-diagnostics';

// Real loopback auth, profile CAS, production Home and SDK. Only the profile
// response boundary is delayed/failed. This proves recovery, not the unique
// historical cause of PR #988's before-network Home Loading failure.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const PROFILE_URL = '**/rest/v1/profiles?**';
const OLD_NAME = 'Original saved student 王';
const CURRENT_NAME = 'Current saved student 王';
const EDITED_INTERESTS = 'My unsaved interest in careful instrument comparisons 王';
const SOURCE = 'Complete original résumé source 王\nI assisted with measurements; I did not lead the project.\nOriginal source tail retained.';
const EXPERIENCE = 'Compared instrument readings and documented uncertainty; I assisted and did not lead.';
const FAILED = "Couldn't load your saved profile. Your edits are kept; retry to continue.";
const fact = (id: string, value: string): ResumeFact => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });

function completeProfile(name = OLD_NAME): ProfileData {
  return {
    name, institution: 'UIUC', college: 'Grainger College of Engineering', major: 'Computer Science',
    grade: 'Sophomore', is_international: false, research_interests: 'instrumentation',
    skills: [{ name: 'Python', level: 'beginner' }], coursework: ['ECE 220'], seeking_types: ['Research'],
    resume_text: SOURCE,
    experience_entries: [{ id: 'recovery-experience', revision: 1, status: 'confirmed',
      source: { kind: 'manual' }, text: EXPERIENCE }],
    resume_master: {
      version: 1, id: 'recovery-master', revision: name === OLD_NAME ? 1 : 2, source_signature: null,
      basics: { name: fact('recovery-name', name), links: [] },
      education: [{ id: 'recovery-education', school: fact('recovery-school', 'Complete Example University'),
        degree: fact('recovery-degree', 'Bachelor of Science'), details: [] }],
      activities: [{ id: 'recovery-project', kind: 'project', title: fact('recovery-title', 'Instrument comparison project'),
        details: [{ id: 'recovery-experience', revision: 1 }] }],
      publications: [], skills: [fact('recovery-skill', 'Beginner Python')], other_sections: [],
      section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [],
    },
  };
}

async function seedProfile(page: Page, request: APIRequestContext) {
  expect(STUB.hostname).toBe('127.0.0.1');
  const signup = await request.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
  expect(signup.status()).toBe(200);
  const session = await signup.json();
  expect(session.user.id).toBeTruthy();
  const headers = { Authorization: `Bearer ${session.access_token}` };
  const value = completeProfile();
  const save = async (profile: ProfileData, expectedRevision: number) => {
    const result = await request.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
      headers, data: { p_expected_device_id: session.user.id, p_expected_revision: expectedRevision, p_patch: profile },
    });
    expect(result.status()).toBe(200);
    expect(await result.json()).toMatchObject({ status: 'applied', revision: expectedRevision + 1, profile });
  };
  await save(value, 0);
  // Auth is seeded once before this page's actual SDK initializes. No fake
  // storage event, owner marker, ready token or profile mirror is injected.
  await page.addInitScript(({ session, localeKey }) => {
    if (!localStorage.getItem('home-load-recovery-seeded')) {
      localStorage.setItem('ofe_auth', JSON.stringify(session));
      localStorage.setItem(localeKey, 'en');
      localStorage.setItem('home-load-recovery-seeded', '1');
    }
  }, { session, localeKey: STORAGE_KEYS.LOCALE });
  const read = async () => {
    const url = new URL('/rest/v1/profiles', STUB);
    url.searchParams.set('select', 'profile_data,revision');
    url.searchParams.set('id', `eq.${session.user.id}`);
    const response = await request.get(url.href, { headers });
    expect(response.status()).toBe(200);
    const rows = await response.json();
    expect(rows).toHaveLength(1);
    return rows[0] as { profile_data: ProfileData; revision: number };
  };
  return { value, save, read };
}

function browserProfileWrites(context: BrowserContext): Request[] {
  const writes: Request[] = [];
  context.on('request', request => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/commit_profile_patch_cas')) writes.push(request);
  });
  return writes;
}

async function assertRecoveredProfile(page: Page, value: ProfileData, interests: string) {
  await expect(page.getByTestId('retry-profile-load')).toHaveCount(0);
  await expect(page.getByTestId('hydration-note')).toHaveCount(0);
  await expect(page.locator('#student_name')).toHaveValue(value.name!);
  await expect(page.locator('#college')).toHaveValue(value.college);
  await expect(page.locator('#major')).toHaveValue(value.major);
  await expect(page.locator('#grade')).toHaveValue(value.grade);
  await expect(page.locator('#research_interests')).toHaveValue(interests);
  const master = page.locator('#resume-master');
  await master.getByText('Open full résumé editor', { exact: true }).click();
  await expect(master.getByRole('textbox', { name: 'Full name', exact: true })).toHaveValue(value.name!);
  await expect(master.getByRole('textbox', { name: 'School', exact: true })).toHaveValue('Complete Example University');
  await expect(master.getByRole('textbox', { name: 'Degree', exact: true })).toHaveValue('Bachelor of Science');
  await expect(master.getByRole('textbox', { name: 'Role / project title', exact: true })).toHaveValue('Instrument comparison project');
  await expect(master.getByRole('group', { name: 'Activity 1', exact: true })
    .getByRole('checkbox', { name: EXPERIENCE, exact: true })).toBeChecked();
}

async function assertServerMaterialsIntact(read: () => Promise<{ profile_data: ProfileData; revision: number }>, value: ProfileData) {
  // After hydration the existing autosave may legitimately send the user's
  // interest edit. Neither retry nor any late response may erase other fields.
  const row = await read();
  expect(row.profile_data).toMatchObject({
    name: value.name, college: value.college, major: value.major, grade: value.grade,
    skills: value.skills, coursework: value.coursework, resume_text: value.resume_text,
    seeking_types: value.seeking_types, experience_entries: value.experience_entries, resume_master: value.resume_master,
  });
}

test.afterEach(async ({ context }, testInfo) => {
  if (testInfo.status === testInfo.expectedStatus) return;
  for (const [index, page] of context.pages().entries()) {
    await attachProfileReadDiagnostics(page, testInfo, `home-load-recovery-page-${index}`);
  }
});

test.describe('Home profile load recovery', () => {
  test('times out a real pending read, preserves an edit through Retry and rejects the old response', async ({ page, context, request }) => {
    const seeded = await seedProfile(page, request);
    const writes = browserProfileWrites(context);
    let allowFresh = false;
    let gatedReads = 0;
    let freshReads = 0;
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const pendingRoutes: Promise<void>[] = [];
    const unexpectedRouteErrors: unknown[] = [];
    await page.route(PROFILE_URL, async route => {
      if (allowFresh) { freshReads += 1; await route.continue(); return; }
      let settled!: () => void;
      pendingRoutes.push(new Promise<void>(resolve => { settled = resolve; }));
      try {
        const response = await route.fetch({ maxRetries: 0 });
        expect(response.status()).toBe(200);
        expect(await response.json()).toMatchObject([{ revision: 1, profile_data: seeded.value }]);
        gatedReads += 1;
        await gate;
        try { await route.fulfill({ response }); }
        catch (error) { if (!route.request().failure()) unexpectedRouteErrors.push(error); }
      } finally { settled(); }
    });
    try {
      await page.goto('/');
      await expect.poll(() => gatedReads, 'the real profile GET must be reached before its response is held').toBeGreaterThan(0);
      const interests = page.locator('#research_interests');
      await interests.fill(EDITED_INTERESTS);
      await expect(page.getByRole('button', { name: /Generate Matches/i })).toBeDisabled();
      await expect(page.getByTestId('retry-profile-load')).toHaveCount(0);
      expect(writes).toHaveLength(0);
      // This assertion waits for the product's real 15-second deadline; the
      // test retains the ordinary 30-second timeout and no test retry override.
      const retry = page.getByRole('button', { name: 'Retry loading profile', exact: true });
      await expect(retry).toBeVisible({ timeout: 17_000 });
      const deadlineTiming = await page.evaluate(() => {
        const marks = performance.getEntriesByType('mark');
        const timeout = marks.filter(mark => /^ofe-profile-read:home:\d+:timed-out$/.test(mark.name)).at(-1);
        const started = timeout && marks.find(mark => mark.name === timeout.name.replace(/timed-out$/, 'started'));
        return timeout && started ? timeout.startTime - started.startTime : null;
      });
      expect(deadlineTiming, 'the real Home read deadline, not an immediate artificial failure').not.toBeNull();
      expect(deadlineTiming!).toBeGreaterThanOrEqual(14_900);
      await expect(page.getByTestId('hydration-note')).toHaveText(FAILED);
      await retry.scrollIntoViewIfNeeded();
      await page.screenshot({ path: test.info().outputPath('home-read-failed.png') });
      await expect(interests).toHaveValue(EDITED_INTERESTS);
      await expect(page.getByRole('button', { name: /Generate Matches/i })).toBeDisabled();
      await expect(page.getByTestId('resume-master-editor')).toHaveCount(0);
      expect(writes, 'unread cloud data must not be overwritten by pre-hydration edits').toHaveLength(0);

      // An independent local server revision makes the obsolete response
      // observably different. This APIRequestContext write is fixture setup,
      // not a page save or a synthetic storage event.
      const current = completeProfile(CURRENT_NAME);
      await seeded.save(current, 1);
      allowFresh = true;
      const fresh = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/profiles'
        && response.request().method() === 'GET');
      await retry.click();
      const response = await fresh;
      expect(response.status()).toBe(200);
      expect(await response.json()).toMatchObject([{ revision: 2, profile_data: current }]);
      expect(freshReads).toBeGreaterThan(0);
      await assertRecoveredProfile(page, current, EDITED_INTERESTS);
      release();
      await Promise.all(pendingRoutes);
      expect(unexpectedRouteErrors).toEqual([]);
      await expect(page.locator('#student_name')).toHaveValue(CURRENT_NAME);
      await expect(page.locator('#research_interests')).toHaveValue(EDITED_INTERESTS);
      await expect(page.locator('#resume-master').getByRole('textbox', { name: 'Full name', exact: true })).toHaveValue(CURRENT_NAME);
      await expect(page.getByTestId('hydration-note')).toHaveCount(0);
      await assertServerMaterialsIntact(seeded.read, current);
    } finally { release(); await Promise.allSettled(pendingRoutes); }
  });

  test('reports a failed read without saving defaults and retries the complete real cloud profile', async ({ page, context, request }) => {
    const seeded = await seedProfile(page, request);
    const writes = browserProfileWrites(context);
    let failRead = true;
    let failures = 0;
    await page.route(PROFILE_URL, route => {
      if (!failRead) return route.continue();
      failures += 1;
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: 'Controlled profile read unavailable' }) });
    });
    await page.goto('/');
    await expect.poll(() => failures).toBeGreaterThan(0);
    // The SDK may retry a 503 internally. The Home deadline still bounds the
    // read; no claim here treats SDK retries as extra user Retry actions.
    const retry = page.getByTestId('retry-profile-load');
    await expect(retry).toBeVisible({ timeout: 17_000 });
    await expect(retry).toHaveText('Retry loading profile');
    await expect(page.getByTestId('hydration-note')).toHaveText(FAILED);
    await retry.scrollIntoViewIfNeeded();
    await page.screenshot({ path: test.info().outputPath('home-read-failed.png') });
    await expect(page.getByRole('button', { name: /Generate Matches/i })).toBeDisabled();
    await expect(page.getByTestId('resume-master-editor')).toHaveCount(0);
    expect(writes).toHaveLength(0);
    failRead = false;
    const read = page.waitForResponse(response => new URL(response.url()).pathname === '/rest/v1/profiles' && response.status() === 200);
    await retry.click();
    expect(await (await read).json()).toMatchObject([{ revision: 1, profile_data: seeded.value }]);
    await assertRecoveredProfile(page, seeded.value, seeded.value.research_interests);
    expect(writes, 'retrying an unchanged profile is a read, not a save').toHaveLength(0);
    await assertServerMaterialsIntact(seeded.read, seeded.value);
  });
});
