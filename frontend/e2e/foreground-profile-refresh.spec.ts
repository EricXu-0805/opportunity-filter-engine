import { contactReceiptForRequest } from './email-contact-receipt';
import { test, expect, request as apiRequest, type APIRequestContext, type Page } from '@playwright/test';
import type { ExperienceEntry, ProfileData, ProfileRequest } from '../src/lib/types';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { attachProfileReadDiagnostics } from './profile-read-diagnostics';

// Real loopback SDK/auth/profile reads. An independent HTTP client changes the
// server row; no test dispatches focus, online or storage events. Playwright's
// clock advances the shipped foreground timer, never a replacement constant.
// All writing responses are synthetic at the HTTP boundary; no provider runs.
const STUB = new URL(`http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`);
const TARGET = 'uiuc-siebel-ugresearch';
const NAME = 'Foreground student 王';
const NEXT_NAME = 'Updated foreground student 王';
const FACT = 'Compared instrument readings; I assisted and did not lead the project.';
const NEXT_FACT = 'Recorded calibration notes; I assisted and did not lead the project.';
const MANUAL = { subject: 'My careful subject 王', body: 'Dear Professor,\n\nKeep my exact wording. I assisted; I did not lead. 王',
  recipient: 'reviewed-recipient@example.edu', instruction: 'Keep this unsent request exactly as entered.' };
const CHANGED = 'Your profile or target details changed. Your subject, message and recipient are kept. Regenerate when you are ready to replace this draft.';
const MISSING = 'Your profile is no longer available. Your draft is kept; generation and outreach are paused.';
const FAILED = 'Could not check for profile updates. Your draft is kept.';
const isProfile = (url: string) => new URL(url).pathname === '/rest/v1/profiles';
const dialog = (page: Page) => page.getByRole('dialog', { name: 'Email Editor', exact: true });
const fields = (page: Page) => {
  const editor = page.getByTestId('cold-email-editor-fields');
  return { subject: editor.locator('#cold-email-subject'), body: editor.locator('#cold-email-body'), recipient: editor.locator('#cold-email-to'),
    instruction: page.getByRole('textbox', { name: 'Request an edit', exact: true }) };
};
const entry = (text: string): ExperienceEntry => ({ id: 'foreground-experience', revision: 1, status: 'confirmed', text, source: { kind: 'manual' } });
const profile = (): ProfileData => ({ name: NAME, institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
  major: 'Computer Science', grade: 'Sophomore', is_international: false, research_interests: 'instrumentation',
  skills: [{ name: 'Python', level: 'beginner' }], coursework: ['ECE 220'], seeking_types: ['research'],
  resume_text: FACT, experience_entries: [entry(FACT)] });
interface Owner { http: APIRequestContext; uid: string; token: string; revision: number }
async function commit(owner: Owner, patch: Partial<ProfileData>) {
  const response = await owner.http.post(new URL('/rest/v1/rpc/commit_profile_patch_cas', STUB).href, {
    headers: { Authorization: `Bearer ${owner.token}` },
    data: { p_expected_device_id: owner.uid, p_expected_revision: owner.revision, p_patch: patch },
  });
  expect(response.status()).toBe(200);
  const receipt = await response.json();
  expect(receipt).toMatchObject({ status: 'applied', revision: owner.revision + 1, profile: patch });
  owner.revision = receipt.revision;
}
async function seed(page: Page): Promise<Owner> {
  expect(STUB.hostname).toBe('127.0.0.1');
  await page.clock.install();
  const http = await apiRequest.newContext();
  try {
    const response = await http.post(new URL('/auth/v1/signup', STUB).href, { data: {} });
    expect(response.status()).toBe(200);
    const session = await response.json();
    const owner = { http, uid: session.user.id as string, token: session.access_token as string, revision: 0 };
    await commit(owner, profile());
    await page.addInitScript(({ session, locale }) => {
      // Auth bootstrap only. The complete profile is obtained through the SDK.
      if (!localStorage.getItem('foreground-profile-seeded')) {
        localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(locale, 'en');
        localStorage.setItem('foreground-profile-seeded', '1');
      }
    }, { session, locale: STORAGE_KEYS.LOCALE });
    const read = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
    await page.goto('/');
    expect(await (await read).json()).toMatchObject([{ revision: 1, profile_data: { name: NAME } }]);
    await expect(page.locator('#student_name')).toHaveValue(NAME);
    await expect(page.getByRole('button', { name: 'Generate Matches', exact: true })).toBeEnabled();
    return owner;
  } catch (error) { await http.dispose(); throw error; }
}
function monitor(page: Page) {
  const state = { profileReads: 0, profileWrites: [] as string[] };
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (isProfile(request.url()) && request.method() === 'GET') state.profileReads += 1;
    if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method()) && /\/profiles$|\/commit_profile_patch_cas$/.test(path)) state.profileWrites.push(path);
  });
  return state;
}
function deferred() {
  let release!: () => void;
  const promise = new Promise<void>(resolve => { release = resolve; });
  return { promise, release };
}
interface WritingRequest { path: string; opportunity_id: string; expected_target_version: string; style?: string; profile: ProfileRequest; experience_evidence: { entries: ExperienceEntry[] } }
async function installWriting(page: Page, holdStream: (request: WritingRequest) => Promise<void> = async () => {}) {
  const requests: WritingRequest[] = [];
  for (const pattern of ['**/api/cold-email**', '**/api/tailor**', '**/api/resume/**']) await page.route(pattern, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/tailor/status') { await route.fulfill({ json: { ai_available: true } }); return; }
    const body = route.request().postDataJSON() as Omit<WritingRequest, 'path'>;
    const request = { ...body, path }; requests.push(request);
    if (path !== '/api/cold-email/variants' && path !== '/api/cold-email/stream') {
      await route.fulfill({ status: 503, json: { error: 'Unrequested synthetic writing route' } }); return;
    }
    const stream = path.endsWith('/stream');
    if (stream) await holdStream(request);
    const draft = { opportunity_id: body.opportunity_id, target_version: body.expected_target_version, contact_context_receipt: contactReceiptForRequest(body), subject: stream ? `AI ${body.style ?? 'professional'} subject` : 'Template subject',
      body: stream ? `AI ${body.style ?? 'professional'} draft for ${body.profile.name}\n${FACT}` : `Template for ${body.profile.name}`,
      recipient_email: 'professor@example.edu', recipient_status: 'revealed', mailto_link: '', method: 'ai',
      pipeline_version: 'foreground-fixture', corpus_version: 'foreground-fixture' };
    try {
      if (stream) await route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ stage: 'done', ...draft })}\n\n` });
      else await route.fulfill({ json: { ...draft, variants: [{ id: 'template', label: 'Template', ...draft }] } });
    } catch (error) { if (!route.request().failure()) throw error; }
  });
  return requests;
}
async function openEmail(page: Page) {
  const read = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
  await page.goto(`/opportunities/${TARGET}`); await read;
  await expect(page.getByRole('button', { name: 'Draft email', exact: true })).toBeEnabled();
  await expect(page.getByTestId('profile-refresh-status')).toHaveCount(0);
  await page.getByRole('button', { name: 'Draft email', exact: true }).click();
  await expect(dialog(page)).toBeVisible();
}
async function editManual(page: Page) {
  const input = fields(page);
  await input.subject.fill(MANUAL.subject); await input.body.fill(MANUAL.body);
  await input.recipient.fill(MANUAL.recipient); await input.instruction.fill(MANUAL.instruction);
}
async function expectManual(page: Page) {
  const input = fields(page);
  await expect(input.subject).toHaveValue(MANUAL.subject); await expect(input.body).toHaveValue(MANUAL.body);
  await expect(input.recipient).toHaveValue(MANUAL.recipient); await expect(input.instruction).toHaveValue(MANUAL.instruction);
  await expect(input.body).toBeEditable();
}
async function observeTriggers(page: Page) {
  expect(await page.evaluate(() => document.visibilityState)).toBe('visible');
  await page.evaluate(() => {
    const state = { focus: 0, online: 0, visibilitychange: 0 };
    Object.assign(window, { foregroundTestTriggers: state });
    window.addEventListener('focus', () => { state.focus += 1; });
    window.addEventListener('online', () => { state.online += 1; });
    document.addEventListener('visibilitychange', () => { state.visibilitychange += 1; });
  });
}
async function expectNoTriggers(page: Page) {
  expect(await page.evaluate(() => (window as typeof window & { foregroundTestTriggers: unknown }).foregroundTestTriggers))
    .toEqual({ focus: 0, online: 0, visibilitychange: 0 });
  expect(await page.evaluate(() => document.visibilityState)).toBe('visible');
}
async function advancePeriod(page: Page, status = 200) {
  const response = page.waitForResponse(response => isProfile(response.url()) && response.status() === status);
  await page.clock.fastForward(60_001);
  return response;
}

test.afterEach(async ({ context }, info) => {
  if (info.status !== info.expectedStatus) for (const [index, page] of context.pages().entries()) await attachProfileReadDiagnostics(page, info, `foreground-page-${index}`);
});

test.describe('Foreground profile refresh', () => {
  test('visible periodic reads discover silent changes and deletion while retaining every manual email field', async ({ page }, info) => {
    const owner = await seed(page), traffic = monitor(page), requests = await installWriting(page);
    try {
      await openEmail(page);
      await expect(fields(page).body).toHaveValue(`Template for ${NAME}`);
      await expect(page.getByRole('button', { name: 'Generate AI draft', exact: true })).toBeEnabled();
      // Give a request that opening starts a moment late the chance to show up.
      await page.waitForTimeout(500);
      expect(requests.some(request => request.path.endsWith('/stream'))).toBe(false);
      await editManual(page); await observeTriggers(page);
      const node = await dialog(page).elementHandle(), count = requests.length, reads = traffic.profileReads;
      await commit(owner, { name: NEXT_NAME, experience_entries: [{ ...entry(NEXT_FACT), revision: 2 }] });
      const changed = await advancePeriod(page);
      expect(await changed.json()).toMatchObject([{ revision: 2, profile_data: { name: NEXT_NAME } }]);
      await expect(dialog(page).getByText(CHANGED, { exact: true })).toBeVisible();
      await expectManual(page); expect(await node!.evaluate(element => element.isConnected)).toBe(true);
      await expect(page.getByRole('button', { name: 'Submit request', exact: true })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Warm', exact: true })).toBeDisabled();
      expect(traffic.profileReads).toBe(reads + 1); expect(requests).toHaveLength(count);
      const url = new URL('/rest/v1/profiles', STUB); url.searchParams.set('id', `eq.${owner.uid}`);
      expect((await owner.http.delete(url.href, { headers: { Authorization: `Bearer ${owner.token}` } })).status()).toBe(204);
      const deleted = await advancePeriod(page); expect(await deleted.json()).toEqual([]);
      await expect(dialog(page).getByTestId('profile-refresh-status')).toContainText(MISSING);
      await expectManual(page); expect(await node!.evaluate(element => element.isConnected)).toBe(true);
      await expect(page.getByRole('button', { name: 'Open in Email', exact: true })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Copy', exact: true })).toBeEnabled();
      expect(traffic.profileReads).toBe(reads + 2); expect(requests).toHaveLength(count); expect(traffic.profileWrites).toEqual([]);
      expect(await (await owner.http.get(url.href, { headers: { Authorization: `Bearer ${owner.token}` } })).json()).toEqual([]);
      await expectNoTriggers(page);
      await page.screenshot({ path: info.outputPath('foreground-deletion-keeps-manual-email.png') });
    } finally { await owner.http.dispose(); }
  });

  test('an unchanged periodic read in flight does not discard an already running AI draft', async ({ page }, info) => {
    const owner = await seed(page), traffic = monitor(page), streamGate = deferred(), profileGate = deferred();
    let profileStarted = false;
    const requests = await installWriting(page, () => streamGate.promise);
    try {
      await openEmail(page);
      await expect(fields(page).body).toHaveValue(`Template for ${NAME}`);
      await expect(page.getByRole('button', { name: 'Generate AI draft', exact: true })).toBeEnabled();
      await page.waitForTimeout(500);
      expect(requests.some(request => request.path.endsWith('/stream'))).toBe(false);
      await page.getByRole('button', { name: 'Generate AI draft', exact: true }).click();
      await expect.poll(() => requests.some(request => request.path.endsWith('/stream'))).toBe(true);
      await expect(fields(page).body).toHaveValue(`Template for ${NAME}`);
      await observeTriggers(page);
      const reads = traffic.profileReads, count = requests.length;
      await page.route('**/rest/v1/profiles?**', async route => {
        const response = await route.fetch({ maxRetries: 0 });
        expect(response.status()).toBe(200);
        expect(await response.json()).toMatchObject([{ revision: 1, profile_data: { name: NAME } }]);
        profileStarted = true; await profileGate.promise; await route.fulfill({ response });
      }, { times: 1 });
      await page.clock.fastForward(60_001);
      await expect.poll(() => profileStarted).toBe(true);
      expect(traffic.profileReads).toBe(reads + 1);
      await expect(dialog(page).getByTestId('profile-refresh-status')).toHaveCount(0);
      streamGate.release();
      await expect(fields(page).body).toHaveValue(`AI professional draft for ${NAME}\n${FACT}`);
      const read = page.waitForResponse(response => isProfile(response.url()) && response.status() === 200);
      profileGate.release(); expect(await (await read).json()).toMatchObject([{ revision: 1 }]);
      await expect(fields(page).body).toHaveValue(`AI professional draft for ${NAME}\n${FACT}`);
      expect(requests).toHaveLength(count); expect(traffic.profileWrites).toEqual([]); await expectNoTriggers(page);
      await page.screenshot({ path: info.outputPath('foreground-unchanged-read-keeps-generation.png') });
    } finally { streamGate.release(); profileGate.release(); await owner.http.dispose(); }
  });

  test('a periodic read failure keeps the manual draft and rejects a later in-flight AI result', async ({ page }, info) => {
    const owner = await seed(page), traffic = monitor(page), late = deferred();
    const requests = await installWriting(page, request => request.style === 'warm' ? late.promise : Promise.resolve());
    try {
      await openEmail(page);
      await expect(fields(page).body).toHaveValue(`Template for ${NAME}`);
      await editManual(page);
      await page.getByRole('button', { name: 'Warm', exact: true }).click();
      expect(requests.some(request => request.path.endsWith('/stream'))).toBe(false);
      await page.getByRole('button', { name: 'Generate AI draft', exact: true }).click();
      await expect.poll(() => requests.some(request => request.path.endsWith('/stream') && request.style === 'warm')).toBe(true);
      await expectManual(page); await observeTriggers(page);
      const reads = traffic.profileReads, count = requests.length;
      // A failed permission/read response cannot masquerade as cloud absence.
      await page.route('**/rest/v1/profiles?**', route => route.fulfill({ status: 403,
        json: { message: 'Controlled foreground read failure' } }), { times: 1 });
      await advancePeriod(page, 403);
      await expect(dialog(page).getByTestId('profile-refresh-status')).toContainText(FAILED);
      await expectManual(page);
      const done = page.waitForResponse(response => new URL(response.url()).pathname === '/api/cold-email/stream'
        && response.request().postDataJSON().style === 'warm');
      late.release(); await (await done).finished();
      // Let the genuine fetch/SSE consumer and React commit run after transport completion.
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await expectManual(page);
      await expect(page.getByRole('button', { name: 'Submit request', exact: true })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Open in Email', exact: true })).toBeDisabled();
      expect(traffic.profileReads).toBe(reads + 1); expect(requests).toHaveLength(count); expect(traffic.profileWrites).toEqual([]);
      const url = new URL('/rest/v1/profiles', STUB); url.searchParams.set('id', `eq.${owner.uid}`);
      expect(await (await owner.http.get(url.href, { headers: { Authorization: `Bearer ${owner.token}` } })).json())
        .toMatchObject([{ revision: 1, profile_data: { name: NAME } }]);
      await expectNoTriggers(page);
      await page.screenshot({ path: info.outputPath('foreground-read-failure-keeps-manual-email.png') });
    } finally { late.release(); await owner.http.dispose(); }
  });
});
