import { test, expect, request as apiRequest, type APIRequestContext, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { ProfileData } from '../src/lib/types';

// Real production UI/auth/profile reads + loopback CAS. Only model/status and
// the changed public target response are controlled; no hosted/model calls.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const TARGET = 'uiuc-siebel-ugresearch';
const BULLET = 'I compared sensor readings with the team; I did not lead. 王';
const MANUAL = 'My retained manual wording: I reviewed the readings, not led the team. 王';
const UNKNOWN = 'Check that these bullets are accurate before tailoring.';
const STALE = 'Your profile, opportunity requirements, or tailoring rules changed. Review these bullets before continuing.';
const pathOf = (url: string) => new URL(url).pathname;
const profile = (): ProfileData => ({ name: 'Tailor provenance student 王', institution: 'UIUC', home_school: 'uiuc',
  college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Sophomore', is_international: false,
  research_interests: 'instrumentation', skills: [{ name: 'Python', level: 'beginner' }], coursework: ['ECE 220'], seeking_types: ['research'],
  resume_text: `EXPERIENCE\n- ${BULLET}`, experience_entries: [{ id: 'sensor', revision: 1, status: 'confirmed', text: BULLET, source: { kind: 'manual' } }] });
interface Session { access_token: string; user: { id: string }; [key: string]: unknown }
interface Owner { http: APIRequestContext; session: Session; uid: string; revision: number }
interface Binding { profile_sig: string; target_sig: string; resume_sig: string; pipeline_version: string; rule_version: string }
interface SavedDraft { version: 2 | 3; owner_id: string; opportunity_id: string; text: string;
  origin: { kind: string; binding: Binding | null }; review: null | { text_sig: string; binding: Binding } }
interface ModelRequest { path: string; original_bullets?: string[]; expected_pipeline_version?: string; expected_target_version?: string; resume_text?: string; profile?: unknown }
async function commit(owner: Owner, patch: Partial<ProfileData>) {
  const response = await owner.http.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
    headers: { Authorization: `Bearer ${owner.session.access_token}` },
    data: { p_expected_device_id: owner.uid, p_expected_revision: owner.revision, p_patch: patch },
  });
  expect(response.status()).toBe(200); const body = await response.json();
  expect(body).toMatchObject({ status: 'applied', revision: owner.revision + 1, profile: patch }); owner.revision = body.revision;
}
async function account() {
  expect(STUB.hostname).toBe('127.0.0.1'); const http = await apiRequest.newContext();
  try {
    const response = await http.post(new URL('/auth/v1/signup', STUB).href, { data: {} }); expect(response.status()).toBe(200);
    const session = await response.json() as Session; const owner = { http, session, uid: session.user.id, revision: 0 };
    await commit(owner, profile());
    const favorite = await http.post(new URL('/rest/v1/favorites', STUB).href, {
      headers: { Authorization: `Bearer ${session.access_token}` }, data: { device_id: owner.uid, opportunity_id: TARGET },
    }); expect(favorite.status()).toBe(201); return owner;
  } catch (error) { await http.dispose(); throw error; }
}
async function seed(page: Page, owner: Owner) {
  await page.addInitScript(({ session, keys }) => {
    if (localStorage.getItem('tailor-provenance-seeded')) return;
    localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, 'en');
    localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('tailor-provenance-seeded', '1');
  }, { session: owner.session, keys: STORAGE_KEYS });
}
async function open(page: Page) {
  const read = page.waitForResponse(response => pathOf(response.url()) === '/rest/v1/profiles' && response.status() === 200);
  await page.goto('/favorites'); await read;
  await page.getByRole('button', { name: 'Tailor Resume', exact: true }).click();
  await expect(page.locator('#tailor-bullets-input')).toBeEditable();
}
const generate = (page: Page) => page.getByRole('button', { name: /^(Tailor with AI|Re-tailor)$/ });
async function models(page: Page) {
  const state = { version: 'w13.3', rejectNext: false, rejectTargetNext: false, targetChanged: false, requests: [] as ModelRequest[], statusReads: 0 };
  await page.route('**/api/tailor**', async route => {
    const path = pathOf(route.request().url());
    if (path === '/api/tailor/status') { state.statusReads += 1; await route.fulfill({ json: { ai_available: true, pipeline_version: state.version } }); return; }
    const body = route.request().postDataJSON() as Omit<ModelRequest, 'path'>; state.requests.push({ path, ...body });
    if (path === '/api/tailor') expect(body.expected_target_version).toMatch(/^wt1:[0-9a-f]{64}$/);
    if (state.rejectTargetNext) {
      state.rejectTargetNext = false; state.targetChanged = true;
      await route.fulfill({ status: 409, json: { detail: { code: 'WRITING_TARGET_CHANGED', message: 'The opportunity changed.', retryable: false } } }); return;
    }
    if (state.rejectNext) {
      state.rejectNext = false; state.version = 'w13.4-fixture';
      await route.fulfill({ status: 409, json: { detail: { code: 'TAILOR_PIPELINE_CHANGED', message: 'Tailoring rules changed. Check again before continuing.', retryable: false, pipeline_version: state.version } } }); return;
    }
    expect(body.expected_pipeline_version).toBe(state.version);
    if (path === '/api/tailor') await route.fulfill({ json: { opportunity_id: TARGET, target_version: body.expected_target_version, method: 'ai', warnings: [],
      pipeline_version: state.version, generated_at: new Date().toISOString(),
      tailored_bullets: body.original_bullets!.map((text, source_index) => ({ text, source_evidence: text, source_index })) } });
    else if (path === '/api/tailor/extract-bullets') await route.fulfill({ json: { bullets: [BULLET], method: 'heuristic', warnings: [],
      pipeline_version: state.version, generated_at: new Date().toISOString() } });
    else await route.fulfill({ status: 503, json: { error: 'Unexpected synthetic model endpoint' } });
  }); return state;
}
function writes(page: Page) {
  const calls: string[] = []; page.on('request', request => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method()) && /\/profiles$|\/commit_profile_patch_cas$/.test(pathOf(request.url()))) calls.push(request.url());
  }); return calls;
}
async function saved(page: Page, owner: Owner): Promise<{ key: string; value: SavedDraft } | null> {
  return page.evaluate(({ prefix, uid, target }) => {
    for (const [key, raw] of Object.entries(localStorage)) {
      if (!key.endsWith(`${prefix}${uid}:${target}`)) continue;
      try { const value = JSON.parse(raw); if ((value.version === 2 || value.version === 3) && value.owner_id === uid && value.opportunity_id === target) return { key, value }; } catch { /* another draft format */ }
    } return null;
  }, { prefix: STORAGE_KEYS.TAILOR_DRAFT_PREFIX, uid: owner.uid, target: TARGET });
}
async function establish(page: Page, owner: Owner, state: Awaited<ReturnType<typeof models>>) {
  await open(page); await page.locator('#tailor-bullets-input').fill(BULLET);
  await generate(page).click(); await expect.poll(() => state.requests.filter(item => item.path === '/api/tailor').length).toBe(1);
  await expect(page.getByRole('button', { name: 'Re-tailor', exact: true })).toBeEnabled();
  await expect.poll(async () => (await saved(page, owner))?.value.text).toBe(BULLET);
  const initial = (await saved(page, owner))!;
  expect(initial.value.origin.binding).not.toBeNull(); return initial;
}
async function review(page: Page) {
  await page.getByRole('button', { name: 'I reviewed these bullets', exact: true }).click();
  await expect(page.getByText(UNKNOWN, { exact: true })).toHaveCount(0);
  await expect(page.getByText(STALE, { exact: true })).toHaveCount(0);
  await expect(generate(page)).toBeEnabled();
}
async function blocked(page: Page, state: Awaited<ReturnType<typeof models>>, expected: number, message: string) {
  await generate(page).click(); await expect(page.getByText(message, { exact: true })).toBeVisible();
  await expect(generate(page)).toBeEnabled(); expect(state.requests.filter(item => item.path === '/api/tailor')).toHaveLength(expected);
  await expect(page.locator('#tailor-bullets-input')).toBeEditable();
}

test.describe('Saved Tailor draft provenance', () => {
  test.describe.configure({ timeout: 90_000 });
  for (const change of ['withdrawn experience', 'deleted raw résumé'] as const) test(`reopened draft requires review after ${change} without rewriting personal materials`, async ({ page }, testInfo) => {
    const owner = await account();
    try {
      await seed(page, owner); const state = await models(page), writesSeen = writes(page); const initial = await establish(page, owner, state);
      await page.getByRole('button', { name: 'Close tailor panel', exact: true }).click();
      const patch = change === 'withdrawn experience' ? { experience_entries: [{ ...profile().experience_entries![0], revision: 2, status: 'withdrawn' as const }] } : { resume_text: '' };
      await commit(owner, patch); await open(page);
      await expect(page.locator('#tailor-bullets-input')).toHaveValue(BULLET); await blocked(page, state, 1, STALE);
      await page.locator('#tailor-bullets-input').fill(MANUAL); await blocked(page, state, 1, STALE);
      if (change === 'withdrawn experience') {
        const image = testInfo.outputPath('tailor-stale.png'); await page.screenshot({ path: image, fullPage: true });
        await testInfo.attach('Tailor stale draft', { path: image, contentType: 'image/png' });
      }
      expect((await saved(page, owner))!.value.origin).toEqual(initial.value.origin);
      await review(page);
      if (change === 'withdrawn experience') {
        const image = testInfo.outputPath('tailor-reviewed.png'); await page.screenshot({ path: image, fullPage: true });
        await testInfo.attach('Tailor reviewed draft', { path: image, contentType: 'image/png' });
      }
      await generate(page).click(); await expect.poll(() => state.requests.filter(item => item.path === '/api/tailor').length).toBe(2);
      expect(state.requests.at(-1)).toMatchObject({ original_bullets: [MANUAL], expected_pipeline_version: state.version });
      const final = (await saved(page, owner))!.value; expect(final.origin).toEqual(initial.value.origin);
      expect(final.review?.binding.profile_sig).not.toBe(initial.value.origin.binding!.profile_sig);
      if (change === 'deleted raw résumé') expect(final.review?.binding.resume_sig).not.toBe(initial.value.origin.binding!.resume_sig);
      expect(writesSeen).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('same-ID changed requirements retain the text and old origin until explicit review', async ({ page }) => {
    const owner = await account(); let changed = false;
    try {
      await seed(page, owner); const state = await models(page), writesSeen = writes(page);
      await page.route(`**/api/opportunities/${TARGET}**`, async route => {
        const response = await route.fetch({ maxRetries: 0 }); expect(response.status()).toBe(200); const value = await response.json();
        if (changed) {
          const previous = value.eligibility.preferred_year;
          const next = JSON.stringify(previous) === JSON.stringify(['Senior']) ? ['Junior'] : ['Senior'];
          expect(next).not.toEqual(previous); value.eligibility = { ...value.eligibility, preferred_year: next };
          value.writing_target_version = `wt1:${'b'.repeat(64)}`;
        }
        await route.fulfill({ response, json: value });
      });
      const initial = await establish(page, owner, state); await page.getByRole('button', { name: 'Close tailor panel', exact: true }).click();
      changed = true; await open(page); await blocked(page, state, 1, STALE);
      await expect(page.locator('#tailor-bullets-input')).toHaveValue(BULLET);
      expect((await saved(page, owner))!.value.origin).toEqual(initial.value.origin);
      await review(page); const reviewed = (await saved(page, owner))!.value;
      expect(reviewed.review?.binding.target_sig).not.toBe(initial.value.origin.binding!.target_sig);
      await generate(page).click(); await expect.poll(() => state.requests.length).toBe(2); expect(writesSeen).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('a new rules version and a later 409 require new review, never automatic generation retry', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const state = await models(page), writesSeen = writes(page); const initial = await establish(page, owner, state);
      await page.getByRole('button', { name: 'Close tailor panel', exact: true }).click(); state.version = 'w13.3-next-fixture';
      await open(page); await blocked(page, state, 1, STALE); await review(page);
      expect((await saved(page, owner))!.value.review?.binding.pipeline_version).toBe(state.version);
      state.rejectNext = true; await generate(page).click();
      await expect.poll(() => state.requests.length).toBe(2); await expect(generate(page)).toBeEnabled();
      await expect(page.locator('#tailor-bullets-input')).toHaveValue(BULLET);
      await blocked(page, state, 2, STALE); // fresh status may run, but no automatic POST at the new version
      await review(page); await generate(page).click(); await expect.poll(() => state.requests.length).toBe(3);
      expect(state.requests.at(-1)?.expected_pipeline_version).toBe('w13.4-fixture');
      expect((await saved(page, owner))!.value.origin).toEqual(initial.value.origin); expect(writesSeen).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  for (const format of ['plain text', 'old t-s envelope'] as const) test(`${format} stays unknown after editing and can only proceed after review`, async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const state = await models(page), writesSeen = writes(page); const initial = await establish(page, owner, state);
      await page.getByRole('button', { name: 'Close tailor panel', exact: true }).click();
      await page.evaluate(({ key, text, format }) => localStorage.setItem(key, format === 'plain text' ? text : JSON.stringify({ t: text, s: 'legacy-weak-signature' })), { key: initial.key, text: BULLET, format });
      await open(page); await expect(page.locator('#tailor-bullets-input')).toHaveValue(BULLET); await blocked(page, state, 1, UNKNOWN);
      await page.locator('#tailor-bullets-input').fill(MANUAL); await blocked(page, state, 1, UNKNOWN);
      expect((await saved(page, owner))!.value.origin).toEqual({ kind: 'unknown', binding: null });
      await review(page); await generate(page).click(); await expect.poll(() => state.requests.length).toBe(2);
      expect(state.requests.at(-1)?.original_bullets).toEqual([MANUAL]);
      expect((await saved(page, owner))!.value.origin).toEqual({ kind: 'unknown', binding: null }); expect(writesSeen).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('manual review cannot supply a missing server target version', async ({ page }) => {
    const owner = await account(); let missing = false;
    try {
      await seed(page, owner); const state = await models(page), writesSeen = writes(page);
      await page.route(`**/api/opportunities/${TARGET}**`, async route => {
        const response = await route.fetch({ maxRetries: 0 }); expect(response.status()).toBe(200); const value = await response.json();
        if (missing) delete value.writing_target_version;
        await route.fulfill({ response, json: value });
      });
      const initial = await establish(page, owner, state); await page.getByRole('button', { name: 'Close tailor panel', exact: true }).click();
      missing = true; await open(page); await expect(page.locator('#tailor-bullets-input')).toHaveValue(BULLET);
      await expect(page.getByRole('button', { name: 'I reviewed these bullets', exact: true })).toBeVisible();
      await review(page); await generate(page).click();
      await expect(page.getByText('The opportunity could not be verified. Your text is kept. Check again before tailoring.', { exact: true })).toBeVisible();
      expect(state.requests).toHaveLength(1); expect((await saved(page, owner))!.value.origin).toEqual(initial.value.origin);
      await expect(page.locator('#tailor-bullets-input')).toHaveValue(BULLET); expect(writesSeen).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('a server target-version conflict keeps the draft and waits for review of the new target', async ({ page }) => {
    const owner = await account(); const nextVersion = `wt1:${'c'.repeat(64)}`;
    try {
      await seed(page, owner); const state = await models(page), writesSeen = writes(page);
      await page.route(`**/api/opportunities/${TARGET}**`, async route => {
        const response = await route.fetch({ maxRetries: 0 }); expect(response.status()).toBe(200); const value = await response.json();
        if (state.targetChanged) { value.writing_target_version = nextVersion; value.description_clean += '\nUpdated public research requirements.'; }
        await route.fulfill({ response, json: value });
      });
      const initial = await establish(page, owner, state); await page.locator('#tailor-bullets-input').fill(MANUAL);
      state.rejectTargetNext = true; await generate(page).click();
      await expect(page.getByText('The opportunity changed. Your text is kept. Check it again before tailoring.', { exact: true })).toBeVisible();
      await expect(generate(page)).toBeEnabled(); expect(state.requests).toHaveLength(2);
      await expect(page.locator('#tailor-bullets-input')).toHaveValue(MANUAL);
      await generate(page).click(); // fresh GET discovers a different complete target and retires this intent
      await expect(page.getByText(STALE, { exact: true })).toBeVisible(); expect(state.requests).toHaveLength(2);
      await review(page); await generate(page).click(); await expect.poll(() => state.requests.length).toBe(3);
      expect(state.requests[2]).toMatchObject({ original_bullets: [MANUAL], expected_target_version: nextVersion });
      expect((await saved(page, owner))!.value.origin).toEqual(initial.value.origin); expect(writesSeen).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('a real account switch cannot restore or copy the previous owner draft', async ({ page }) => {
    const first = await account(), second = await account();
    try {
      await seed(page, first); const state = await models(page), writesSeen = writes(page); await establish(page, first, state);
      await page.locator('#tailor-bullets-input').fill('PRIVATE first-owner manual text');
      await expect.poll(async () => (await saved(page, first))?.value.text).toBe('PRIVATE first-owner manual text');
      const secondProfile = page.waitForResponse(response => {
        const url = new URL(response.url());
        return url.pathname === '/rest/v1/profiles' && url.searchParams.get('id') === `eq.${second.uid}` && response.status() === 200;
      });
      await page.evaluate(session => {
        localStorage.setItem('ofe_auth', JSON.stringify(session));
        const channel = new BroadcastChannel('ofe_auth'); channel.postMessage({ event: 'SIGNED_IN', session }); channel.close();
      }, second.session);
      await expect(page.getByRole('dialog', { name: 'Tailor My Resume', exact: true })).toHaveCount(0);
      await secondProfile;
      // A real owner switch clears the old school confirmation. Defer the new
      // owner's gate through its normal UI, without writing a profile or
      // reloading away the same-page owner-isolation boundary.
      const school = page.getByRole('dialog', { name: 'Confirm your school', exact: true });
      await expect(school).toBeVisible(); await school.getByRole('button', { name: 'Close', exact: true }).click();
      await expect(school).toHaveCount(0);
      const openTailor = page.getByRole('button', { name: 'Tailor Resume', exact: true });
      await expect(openTailor).toBeEnabled(); await openTailor.click();
      await expect(page.locator('#tailor-bullets-input')).toBeEditable();
      await expect(page.locator('#tailor-bullets-input')).not.toHaveValue('PRIVATE first-owner manual text');
      await expect(page.getByText('PRIVATE first-owner manual text', { exact: true })).toHaveCount(0);
      await page.locator('#tailor-bullets-input').fill('Second owner independently typed this.');
      await expect.poll(async () => (await saved(page, second))?.value.text).toBe('Second owner independently typed this.');
      expect(state.requests).toHaveLength(1); expect(writesSeen).toEqual([]);
    } finally { await first.http.dispose(); await second.http.dispose(); }
  });
});
