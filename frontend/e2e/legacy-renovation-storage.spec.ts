import { test, expect, request as apiRequest, type APIRequestContext, type Browser, type Locator, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import type { ProfileData, RenovationDoc, ResumeSectionInput } from '../src/lib/types';

// Production UI + real browser SDK against only the loopback wire stub. These
// cases prove interaction/receipt handling, not PostgreSQL ACLs or concurrency.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const TARGET = 'uiuc-siebel-ugresearch';
const ORIGINAL = 'Compared sensor readings with the team; I did not lead.';
const PROFILE: ProfileData = { name: 'Legacy storage student 王', institution: 'UIUC', home_school: 'uiuc',
  college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Sophomore', is_international: false,
  research_interests: 'research instrumentation', skills: [{ name: 'Python', level: 'beginner' }],
  coursework: ['CS 225'], seeking_types: ['research'], resume_text: `EXPERIENCE\n- ${ORIGINAL}` };
interface Payload { doc: RenovationDoc; base_snapshot: { sections?: ResumeSectionInput[] }; method: string | null; warnings: string[] }
interface Current { owner_id: string; opportunity_id: string; revision: number; updated_at: string; payload: Payload }
interface Receipt { status: 'saved' | 'unchanged' | 'conflict'; current: Current }
interface Session { access_token: string; user: { id: string }; [key: string]: unknown }
interface Owner { session: Session; uid: string; http: APIRequestContext }
const pathOf = (url: string) => new URL(url).pathname;
const RPC = '/rest/v1/rpc/';

async function owner(): Promise<Owner> {
  expect(STUB.hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
    expect(signup.status()).toBe(200);
    const session = await signup.json() as Session;
    const seeded = await http.post(new URL(`${RPC}commit_profile_patch_cas`, STUB).href, {
      headers: { Authorization: `Bearer ${session.access_token}` }, data: {
        p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: PROFILE,
      },
    });
    expect(seeded.status()).toBe(200); expect(await seeded.json()).toMatchObject({ status: 'applied', revision: 1 });
    return { session, uid: session.user.id, http };
  } catch (error) { await http.dispose(); throw error; }
}
async function setup(page: Page, account: Owner) {
  await page.addInitScript(({ session, keys }) => {
    if (!localStorage.getItem('legacy-storage-seeded')) {
      localStorage.setItem('ofe_auth', JSON.stringify(session));
      localStorage.setItem(keys.LOCALE, 'en'); localStorage.setItem(keys.ONBOARDING_SEEN, '1');
      localStorage.setItem(keys.SCHOOL_CONFIRMED, JSON.stringify({ slug: 'uiuc', ts: '2026-09-25T00:00:00Z' }));
      localStorage.setItem('legacy-storage-seeded', '1');
    }
  }, { session: account.session, keys: STORAGE_KEYS });
  const modelRequests: string[] = [];
  await page.route('**/api/tailor**', async route => {
    const path = pathOf(route.request().url()); modelRequests.push(path);
    const body = route.request().postDataJSON() as { resume_text?: string; sections?: ResumeSectionInput[] };
    if (path === '/api/tailor/structure') {
      expect(body.resume_text).toBe(PROFILE.resume_text);
      await route.fulfill({ json: { sections: [{ id: 'experience', heading: 'Experience', kind: 'experience',
        bullets: [{ id: 'sensor', text: ORIGINAL }] }], method: 'heuristic', warnings: [] } });
    } else if (path === '/api/tailor/renovate') {
      expect(body.sections).toHaveLength(1);
      await route.fulfill({ json: { opportunity_id: TARGET, target_version: route.request().postDataJSON().expected_target_version, method: 'fallback', warnings: [],
        sections: body.sections!.map(section => ({ ...section, bullets: section.bullets.map(bullet => ({
          id: bullet.id, base_text: bullet.text, variants: [], current: -1, action: 'keep',
        })) })) } });
    } else await route.fulfill({ status: 503, json: { detail: { code: 'unexpected_test_model_request' } } });
  });
  return modelRequests;
}
async function enter(page: Page) {
  const read = page.waitForResponse(response => pathOf(response.url()) === '/rest/v1/profiles' && response.status() === 200);
  await page.goto(`/opportunities/${TARGET}`); await read;
  await page.getByRole('button', { name: 'Renovate Resume', exact: true }).click();
  await page.getByRole('button', { name: 'Edit résumé bullets', exact: true }).click();
}
async function generate(page: Page): Promise<Receipt> {
  const receipt = page.waitForResponse(response => pathOf(response.url()) === `${RPC}save_renovation_cas`);
  await page.getByRole('button', { name: 'Renovate with AI', exact: true }).click();
  const body = await (await receipt).json() as Receipt;
  expect(body).toMatchObject({ status: 'saved', current: { revision: 1, opportunity_id: TARGET } });
  await expect(page.getByRole('dialog').getByText('Saved', { exact: true })).toBeVisible();
  await expect(page.getByText(ORIGINAL, { exact: true })).toBeVisible();
  return body;
}
async function edit(page: Page, text: string) {
  await page.getByRole('button', { name: 'Edit this bullet', exact: true }).first().click();
  await page.getByRole('textbox', { name: 'Edit this bullet', exact: true }).fill(text);
}
async function editAndSave(page: Page, text: string, revision: number): Promise<Receipt> {
  await edit(page, text);
  const receipt = page.waitForResponse(response => pathOf(response.url()) === `${RPC}save_renovation_cas`
    && response.request().postDataJSON()?.p_expected_revision === revision);
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  return await (await receipt).json() as Receipt;
}
async function rpc(account: Owner, name: string, extra: Record<string, unknown> = {}) {
  const response = await account.http.post(new URL(`${RPC}${name}`, STUB).href, { headers: { Authorization: `Bearer ${account.session.access_token}` },
    data: { p_expected_owner: account.uid, p_opportunity_id: TARGET, ...extra } });
  expect(response.status()).toBe(200); return response.json();
}
async function visualEvidence(page: Page, action: Locator, name: string) {
  // A trial click checks the actual viewport hit target (including overlays),
  // scrolls naturally, and never invokes a save/restore or changes draft data.
  await action.click({ trial: true });
  await expect(action).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  const dialog = page.getByRole('dialog');
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath(`${name}-${test.info().project.name}.png`), fullPage: false });
}
async function otherDevice(browser: Browser, page: Page, account: Owner) {
  const context = await browser.newContext({ viewport: page.viewportSize() ?? undefined, baseURL: test.info().project.use.baseURL });
  const other = await context.newPage(); await setup(other, account);
  return { context, page: other };
}

test.describe('Legacy draft storage RPCs', () => {
  test.describe.configure({ timeout: 90_000 });

  test('two independent devices preserve the losing manual draft until explicit conflict resolution', async ({ page, browser }) => {
    const account = await owner(); let second: Awaited<ReturnType<typeof otherDevice>> | undefined;
    try {
      await setup(page, account); await enter(page); const initial = await generate(page);
      second = await otherDevice(browser, page, account); await enter(second.page);
      await expect(second.page.getByText(ORIGINAL, { exact: true })).toBeVisible();
      const local = 'My second-device wording 王 must survive the conflict.';
      await edit(second.page, local);
      const winner = 'First device saved its own careful instrument wording.';
      expect(await editAndSave(page, winner, 1)).toMatchObject({ status: 'saved', current: { revision: 2 } });
      const conflict = second.page.waitForResponse(response => pathOf(response.url()) === `${RPC}save_renovation_cas`);
      await second.page.getByRole('button', { name: 'Save', exact: true }).click();
      expect(await (await conflict).json()).toMatchObject({ status: 'conflict', current: { revision: 2 } });
      const notice = second.page.getByTestId('renovation-save-conflict');
      await expect(notice).toBeVisible();
      await notice.getByText('View saved version', { exact: true }).click();
      await expect(second.page.getByTestId('renovation-conflict-preview')).toBeVisible();
      await expect(second.page.getByTestId('renovation-conflict-preview')).toContainText(winner);
      await expect(second.page.getByText(local, { exact: true })).toBeVisible();
      await visualEvidence(second.page, notice.getByRole('button', { name: 'Save my draft over this version', exact: true }), 'legacy-conflict');
      expect((await rpc(account, 'read_renovation')).current.payload.doc).not.toEqual(initial.current.payload.doc);
      await expect(second.page.getByRole('dialog').getByText('Saved', { exact: true })).toHaveCount(0);
      const resolved = second.page.waitForResponse(response => pathOf(response.url()) === `${RPC}save_renovation_cas`
        && response.request().postDataJSON()?.p_expected_revision === 2);
      await notice.getByRole('button', { name: 'Save my draft over this version', exact: true }).click();
      const third = await (await resolved).json() as Receipt;
      expect(third).toMatchObject({ status: 'saved', current: { revision: 3 } });
      expect(third.current.payload.base_snapshot).toEqual(initial.current.payload.base_snapshot);
      expect(third.current.payload.doc.target_sig).toBe(initial.current.payload.doc.target_sig);
      await expect(notice).toHaveCount(0); await expect(second.page.getByText(local, { exact: true })).toBeVisible();
      expect((await rpc(account, 'read_renovation')).current).toEqual(third.current);
    } finally { await second?.context.close(); await account.http.dispose(); }
  });

  test('a committed save with a lost response retries unchanged without duplicating history', async ({ page }) => {
    const account = await owner();
    try {
      const models = await setup(page, account); await enter(page); await generate(page);
      let committed: Receipt | null = null;
      await page.route('**/rest/v1/rpc/save_renovation_cas', async route => {
        const response = await route.fetch({ maxRetries: 0 });
        expect(response.status()).toBe(200); committed = await response.json() as Receipt;
        expect(committed).toMatchObject({ status: 'saved', current: { revision: 2 } });
        await route.abort('failed');
      }, { times: 1 });
      const text = 'I kept the measurement notebook; this response was lost. 王';
      await edit(page, text); await page.getByRole('button', { name: 'Save', exact: true }).click();
      const failed = page.getByTestId('renovation-save-failed'); await expect(failed).toBeVisible();
      await expect(page.getByText(text, { exact: true })).toBeVisible();
      expect((await rpc(account, 'read_renovation')).current.revision).toBe(2);
      const retried = page.waitForResponse(response => pathOf(response.url()) === `${RPC}save_renovation_cas`
        && response.request().postDataJSON()?.p_expected_revision === 1);
      await failed.getByRole('button').click();
      const receipt = await (await retried).json() as Receipt;
      expect(receipt.status).toBe('unchanged'); expect(receipt.current).toEqual(committed!.current);
      await expect(failed).toHaveCount(0); await expect(page.getByRole('dialog').getByText('Saved', { exact: true })).toBeVisible();
      const history = await rpc(account, 'list_renovation_versions', { p_before_created_at: null, p_before_id: null, p_limit: 20 });
      expect(history.items).toHaveLength(2); expect(history.items.map((item: { revision: number }) => item.revision).sort()).toEqual([1, 2]);
      expect(models.filter(path => path === '/api/tailor/renovate')).toHaveLength(1);
    } finally { await account.http.dispose(); }
  });

  test('complete history restores as a new save, while legacy history stays read-only', async ({ page }) => {
    const account = await owner();
    try {
      const models = await setup(page, account); await enter(page); const first = await generate(page);
      const later = await editAndSave(page, 'Later wording from the same source.', 1);
      expect(later).toMatchObject({ status: 'saved', current: { revision: 2 } });
      await expect(page.getByRole('dialog').getByText('Saved', { exact: true })).toBeVisible();
      await page.getByRole('button', { name: 'Version history', exact: true }).click();
      const history = page.getByTestId('renovation-history'); await expect(history).toBeVisible();
      await history.getByRole('button', { name: /^Version 1 ·/ }).click();
      await expect(page.getByTestId('renovation-history-preview')).toContainText(ORIGINAL);
      await visualEvidence(page, history.getByRole('button', { name: 'Restore as new version', exact: true }), 'legacy-history-restore');
      const restore = page.waitForResponse(response => pathOf(response.url()) === `${RPC}save_renovation_cas`
        && response.request().postDataJSON()?.p_expected_revision === 2);
      await history.getByRole('button', { name: 'Restore as new version', exact: true }).click();
      const third = await (await restore).json() as Receipt;
      expect(third).toMatchObject({ status: 'saved', current: { revision: 3, payload: first.current.payload } });
      expect((await rpc(account, 'list_renovation_versions', { p_limit: 20 })).items).toHaveLength(3);
      await expect(page.getByText(ORIGINAL, { exact: true }).first()).toBeVisible();
      await visualEvidence(page, page.getByRole('button', { name: 'Close renovation dialog', exact: true }), 'legacy-history-restored');
      // Only this old pre-migration row is synthetic at the RPC boundary. It
      // cannot be created by normal save RPCs; real migration preservation is
      // tested separately against PostgreSQL, with no permissive table API.
      const legacyId = '77777777-7777-4777-8777-777777777724';
      const summary = { id: legacyId, created_at: '2026-01-01T00:00:00.000Z', revision: null,
        snapshot_kind: 'legacy_doc', source_revision: null, source_updated_at: null };
      await page.route('**/rest/v1/rpc/list_renovation_versions', route => route.fulfill({ json: { items: [summary], next_cursor: null } }));
      await page.route('**/rest/v1/rpc/get_renovation_version', route => route.fulfill({ json: { status: 'found', version: {
        ...summary, owner_id: account.uid, opportunity_id: TARGET,
        payload: { doc: first.current.payload.doc, base_snapshot: null, method: null, warnings: null },
      } } }));
      if (await history.isVisible()) await history.getByRole('button', { name: 'Close history', exact: true }).click();
      await page.getByRole('button', { name: 'Version history', exact: true }).click();
      await history.getByRole('button', { name: /^Imported version ·.*source unavailable/ }).click();
      await expect(page.getByTestId('renovation-history-preview')).toContainText(ORIGINAL);
      await expect(history.getByRole('button', { name: 'Restore as new version', exact: true })).toHaveCount(0);
      await visualEvidence(page, history.getByRole('button', { name: 'Close history', exact: true }), 'legacy-history-read-only');
      expect((await rpc(account, 'read_renovation')).current).toEqual(third.current);
      expect(models.filter(path => path === '/api/tailor/renovate')).toHaveLength(1);
    } finally { await account.http.dispose(); }
  });

  test('permission-denied initial reads cannot become an absent draft or trigger generation', async ({ page }) => {
    const account = await owner();
    try {
      const models = await setup(page, account);
      const saves: string[] = []; page.on('request', request => { if (pathOf(request.url()) === `${RPC}save_renovation_cas`) saves.push(request.url()); });
      await page.route('**/rest/v1/rpc/read_renovation', route => route.fulfill({ status: 403,
        json: { code: '42501', message: 'Synthetic permission denied' } }), { times: 1 });
      await enter(page);
      await expect(page.getByText('Could not load the saved draft. Retry before generating a replacement.', { exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Renovate with AI', exact: true })).toHaveCount(0);
      expect(saves).toEqual([]); expect(models).toEqual([]);
      await page.getByRole('button', { name: 'Retry loading', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Renovate with AI', exact: true })).toBeEnabled();
      expect(saves).toEqual([]); expect(models).toEqual([]);
      for (const table of ['resume_renovations', 'resume_renovation_versions']) {
        const denied = await account.http.get(new URL(`/rest/v1/${table}`, STUB).href, {
          headers: { Authorization: `Bearer ${account.session.access_token}` },
        });
        expect(denied.status()).toBe(403); expect(await denied.json()).toMatchObject({ code: '42501' });
      }
    } finally { await account.http.dispose(); }
  });
});
