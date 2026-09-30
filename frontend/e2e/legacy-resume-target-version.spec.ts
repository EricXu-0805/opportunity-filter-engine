import { test, expect, request as apiRequest, type APIRequestContext, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { ProfileData, ResumeSectionInput } from '../src/lib/types';
import { attachProfileReadDiagnostics } from './profile-read-diagnostics';

// Real browser SDK and loopback profile/renovation RPCs. Only public-target
// GET and model response boundaries are controlled; no provider is contacted.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const TARGET = 'uiuc-siebel-ugresearch';
const ORIGINAL = 'Compared instrument readings with the team; I did not lead.';
const SECOND = 'Recorded measurement uncertainty in a shared notebook.';
const MANUAL = 'Keep my complete unsaved wording 王; I assisted, never led.';
const PROFILE: ProfileData = { name: 'Target receipt student 王', institution: 'UIUC', home_school: 'uiuc',
  college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Sophomore', is_international: false,
  research_interests: 'instrumentation', skills: [{ name: 'Python', level: 'beginner' }], coursework: ['CS 225'],
  seeking_types: ['research'], resume_text: `EXPERIENCE\n- ${ORIGINAL}\n- ${SECOND}` };
const RPC = '/rest/v1/rpc/';
const pathOf = (url: string) => new URL(url).pathname;
interface Owner { http: APIRequestContext; uid: string; token: string }
interface ModelRequest { path: string; opportunity_id?: string; expected_target_version?: string; resume_text?: string; sections?: ResumeSectionInput[]; current_text?: string }
async function seed(page: Page): Promise<Owner> {
  expect(STUB.hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
    expect(signup.status()).toBe(200); const session = await signup.json();
    const owner = { http, uid: session.user.id as string, token: session.access_token as string };
    const saved = await http.post(new URL(`${RPC}commit_profile_patch_cas`, STUB).href, {
      headers: { Authorization: `Bearer ${owner.token}` },
      data: { p_expected_device_id: owner.uid, p_expected_revision: 0, p_patch: PROFILE },
    });
    expect(saved.status()).toBe(200); expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1 });
    await page.addInitScript(({ session, keys }) => {
      if (!localStorage.getItem('legacy-version-seeded')) {
        localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, 'en');
        localStorage.setItem(keys.ONBOARDING_SEEN, '1');
        localStorage.setItem(keys.SCHOOL_CONFIRMED, JSON.stringify({ slug: 'uiuc', ts: '2026-09-25T00:00:00Z' }));
        localStorage.setItem('legacy-version-seeded', '1');
      }
    }, { session, keys: STORAGE_KEYS });
    return owner;
  } catch (error) { await http.dispose(); throw error; }
}
async function installBoundaries(page: Page) {
  const state = { omitVersion: false, failure: null as null | 'whole-409' | 'bullet-wrong', targetReads: 0,
    targetVersions: [] as string[], requests: [] as ModelRequest[], saves: [] as unknown[], profileWrites: [] as string[] };
  page.on('request', request => {
    const path = pathOf(request.url());
    if (path === `${RPC}save_renovation_cas`) state.saves.push(request.postDataJSON());
    if (request.method() !== 'GET' && /\/profiles$|\/commit_profile_patch_cas$/.test(path)) state.profileWrites.push(path);
  });
  await page.route(url => url.pathname === `/api/opportunities/${TARGET}`, async route => {
    const response = await route.fetch({ maxRetries: 0 }); expect(response.status()).toBe(200);
    const target = await response.json(); expect(target.writing_target_version).toMatch(/^wt1:[a-f0-9]{64}$/);
    state.targetReads += 1; state.targetVersions.push(target.writing_target_version);
    if (state.omitVersion) delete target.writing_target_version;
    await route.fulfill({ response, json: target });
  });
  await page.route('**/api/tailor**', async route => {
    const path = pathOf(route.request().url());
    if (path === '/api/tailor/status') { await route.fulfill({ json: { ai_available: true, pipeline_version: 'w13.4' } }); return; }
    const body = route.request().postDataJSON() as ModelRequest;
    state.requests.push({ ...body, path });
    if (path === '/api/tailor/structure') {
      expect(body.resume_text).toBe(PROFILE.resume_text);
      await route.fulfill({ json: { sections: [{ id: 'experience', heading: 'Experience', kind: 'experience', bullets: [
        { id: 'first', text: ORIGINAL }, { id: 'second', text: SECOND },
      ] }], method: 'heuristic', warnings: [] } });
      return;
    }
    expect(body.opportunity_id).toBe(TARGET);
    expect(body.expected_target_version).toBe(state.targetVersions.at(-1));
    if (path === '/api/tailor/renovate') {
      if (state.failure === 'whole-409') { await route.fulfill({ status: 409, json: { detail: { code: 'WRITING_TARGET_CHANGED', message: 'Synthetic stale target' } } }); return; }
      await route.fulfill({ json: { opportunity_id: TARGET, target_version: body.expected_target_version, pipeline_version: 'w13.4', generated_at: '2026-09-25T00:00:00Z',
        sections: body.sections!.map(section => ({ ...section, bullets: section.bullets.map(bullet => ({ id: bullet.id, base_text: bullet.text,
          variants: [], current: -1, action: 'keep' })) })), method: 'fallback', warnings: [] } });
    } else if (path === '/api/tailor/bullet') {
      await route.fulfill({ json: { opportunity_id: TARGET, target_version: state.failure === 'bullet-wrong' ? `wt1:${'0'.repeat(64)}` : body.expected_target_version,
        text: 'Rejected target-specific rewrite', source_evidence: SECOND, changed: true, method: 'ai', warnings: [] } });
    } else await route.fulfill({ status: 503, json: { detail: { code: 'unexpected_test_model_request' } } });
  });
  return state;
}
async function enter(page: Page) {
  const read = page.waitForResponse(response => pathOf(response.url()) === '/rest/v1/profiles' && response.status() === 200);
  await page.goto(`/opportunities/${TARGET}`); await read;
  await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
  await page.getByRole('button', { name: 'Edit résumé bullets', exact: true }).click();
}
async function generate(page: Page) {
  const save = page.waitForResponse(response => pathOf(response.url()) === `${RPC}save_renovation_cas`);
  await page.getByRole('button', { name: 'Renovate with AI', exact: true }).click();
  expect(await (await save).json()).toMatchObject({ status: 'saved', current: { revision: 1, opportunity_id: TARGET } });
  await expect(page.getByRole('dialog').getByText('Saved', { exact: true })).toBeVisible();
  await expect(page.getByText(ORIGINAL, { exact: true })).toBeVisible();
}
async function rpc(owner: Owner, name: string) {
  const response = await owner.http.post(new URL(`${RPC}${name}`, STUB).href, { headers: { Authorization: `Bearer ${owner.token}` },
    data: { p_expected_owner: owner.uid, p_opportunity_id: TARGET, ...(name === 'list_renovation_versions' ? { p_limit: 20 } : {}) } });
  expect(response.status()).toBe(200); return response.json();
}
test.afterEach(async ({ context }, info) => {
  if (info.status !== info.expectedStatus) for (const [index, page] of context.pages().entries()) await attachProfileReadDiagnostics(page, info, `legacy-target-version-${index}`);
});

test.describe('Legacy résumé target version', () => {
  test('missing verified version blocks all model work; explicit recheck does not start it automatically', async ({ page }) => {
    const owner = await seed(page), state = await installBoundaries(page); state.omitVersion = true;
    try {
      await enter(page);
      const notice = page.getByTestId('renovation-target-version');
      await expect(notice).toContainText('The opportunity could not be verified. Your draft is kept.');
      await expect(page.getByRole('button', { name: 'Renovate with AI', exact: true })).toBeDisabled();
      expect(state.requests).toEqual([]); expect(state.saves).toEqual([]);
      const reads = state.targetReads; state.omitVersion = false;
      await notice.getByRole('button', { name: 'Check opportunity again', exact: true }).click();
      await expect.poll(() => state.targetReads).toBe(reads + 1);
      await expect(page.getByRole('button', { name: 'Renovate with AI', exact: true })).toBeEnabled();
      expect(state.requests).toEqual([]); expect(state.saves).toEqual([]);
      await generate(page);
      expect(state.requests.map(item => item.path)).toEqual(['/api/tailor/structure', '/api/tailor/renovate']);
      expect(state.saves).toHaveLength(1); expect(state.profileWrites).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  for (const failure of ['whole-409', 'bullet-wrong'] as const) test(`${failure} preserves saved history and unsaved text, and rechecking never replays the request`, async ({ page }, info) => {
    const owner = await seed(page), state = await installBoundaries(page);
    try {
      await enter(page); await generate(page);
      const saved = await rpc(owner, 'read_renovation'); const history = await rpc(owner, 'list_renovation_versions');
      await page.getByRole('button', { name: 'Edit this bullet', exact: true }).first().click();
      const editor = page.getByRole('textbox', { name: 'Edit this bullet', exact: true }); await editor.fill(MANUAL);
      state.failure = failure;
      if (failure === 'whole-409') await page.getByRole('button', { name: 'Re-renovate', exact: true }).click();
      else await page.getByRole('button', { name: 'Ask AI to re-optimize this bullet', exact: true }).click();
      const notice = page.getByTestId('renovation-target-version');
      await expect(notice).toContainText(failure === 'whole-409' ? 'The opportunity changed. Your draft is kept.' : 'The opportunity could not be verified. Your draft is kept.');
      await expect(editor).toHaveValue(MANUAL); await expect(page.getByText(SECOND, { exact: true })).toBeVisible();
      await expect(page.getByText('Rejected target-specific rewrite', { exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Re-renovate', exact: true })).toBeDisabled();
      expect(state.saves).toHaveLength(1);
      expect(await rpc(owner, 'read_renovation')).toEqual(saved); expect(await rpc(owner, 'list_renovation_versions')).toEqual(history);
      const count = state.requests.length, reads = state.targetReads;
      await notice.getByRole('button', { name: 'Check opportunity again', exact: true }).click();
      await expect.poll(() => state.targetReads).toBe(reads + 1);
      await expect(notice).toHaveCount(0); await expect(page.getByRole('button', { name: 'Re-renovate', exact: true })).toBeEnabled();
      await expect(editor).toHaveValue(MANUAL); expect(state.requests).toHaveLength(count); expect(state.saves).toHaveLength(1);
      expect(state.profileWrites).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
      await editor.scrollIntoViewIfNeeded();
      await page.screenshot({ path: info.outputPath(`legacy-${failure}-draft-kept.png`), fullPage: false });
    } finally { await owner.http.dispose(); }
  });
});
