import { contactReceiptForRequest } from './email-contact-receipt';
import { test, expect, request as apiRequest, type APIRequestContext, type Page } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';

// Local production UI + real loopback auth/profile/CAS and public detail GET.
// Only writing results and controlled changes to that public response are faked.
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const ID = 'uiuc-siebel-ugresearch', NEXT = `wt1:${'b'.repeat(64)}`;
const UNAVAILABLE = 'The opportunity could not be verified. Your draft is kept. Check it again before continuing.';
const CHANGED = 'The opportunity changed. Your draft is kept. Check it again before continuing.';
interface Owner { http: APIRequestContext; session: { access_token: string; user: { id: string } } }
interface WritingCall { path: string; opportunity_id: string; expected_target_version?: string }
const pathOf = (url: string) => new URL(url).pathname;
async function account(): Promise<Owner> {
  expect(new URL(STUB).hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const signup = await http.post(`${STUB}/auth/v1/signup`, { data: {} }); expect(signup.status()).toBe(200);
    const session = await signup.json(), headers = { Authorization: `Bearer ${session.access_token}` };
    const created = await http.post(`${STUB}/rest/v1/rpc/commit_profile_patch_cas`, { headers, data: {
      p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: {
        name: 'Email version student 王', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
        major: 'Computer Science', grade: 'Sophomore', is_international: false, skills: [], coursework: ['ECE 220'],
        research_interests: 'sensors', seeking_types: ['research'],
      },
    } }); expect(created.status()).toBe(200); expect(await created.json()).toMatchObject({ status: 'applied', revision: 1 });
    const favorite = await http.post(`${STUB}/rest/v1/favorites`, { headers, data: { device_id: session.user.id, opportunity_id: ID } });
    expect(favorite.status()).toBe(201); return { http, session };
  } catch (error) { await http.dispose(); throw error; }
}
async function seed(page: Page, owner: Owner) {
  await page.addInitScript(({ session, keys }) => {
    if (localStorage.getItem('email-version-seeded')) return;
    localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, 'en');
    localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('email-version-seeded', '1');
  }, { session: owner.session, keys: STORAGE_KEYS });
}
async function open(page: Page) {
  const read = page.waitForResponse(response => pathOf(response.url()) === '/rest/v1/profiles' && response.status() === 200);
  await page.goto('/favorites'); await read;
  await page.getByRole('button', { name: 'Draft Email', exact: true }).click();
}
function fields(page: Page) {
  const editor = page.getByTestId('cold-email-editor-fields');
  return { subject: editor.locator('#cold-email-subject'), body: editor.locator('#cold-email-body'), recipient: editor.locator('#cold-email-to') };
}
async function edit(page: Page) {
  await fields(page).subject.fill('Manual subject 王'); await fields(page).body.fill('My manual research message 王'); await fields(page).recipient.fill('manual@example.edu');
}
async function kept(page: Page) {
  await expect(fields(page).subject).toHaveValue('Manual subject 王'); await expect(fields(page).body).toHaveValue('My manual research message 王');
  await expect(fields(page).recipient).toHaveValue('manual@example.edu');
}
function profileWrites(page: Page) {
  const requests: string[] = []; page.on('request', request => {
    if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(request.method()) && /\/profiles$|\/commit_profile_patch_cas$/.test(pathOf(request.url()))) requests.push(request.url());
  }); return requests;
}
async function writing(page: Page) {
  const state = { calls: [] as WritingCall[], wrongRefine: false, holdStream: false, changed: false, streamStarted: false };
  let release!: () => void; const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/cold-email**', async route => {
    const path = pathOf(route.request().url()), body = route.request().postDataJSON() as WritingCall;
    state.calls.push({ ...body, path }); expect(body.opportunity_id).toBe(ID); expect(body.expected_target_version).toMatch(/^wt1:[0-9a-f]{64}$/);
    const receipt = { opportunity_id: ID, target_version: body.expected_target_version, contact_context_receipt: contactReceiptForRequest(body) };
    const draft = { ...receipt, subject: 'Checked subject', body: 'Checked body', recipient_email: 'lab@example.edu',
      recipient_status: 'revealed', mailto_link: '', method: 'template', pipeline_version: 'w12.6', corpus_version: 'email-version-test' };
    if (path === '/api/cold-email/variants') { await route.fulfill({ json: { ...draft, variants: [{ id: 'checked', label: 'Checked template', ...draft }] } }); return; }
    if (path === '/api/cold-email/stream') {
      state.streamStarted = true;
      if (state.holdStream) { await gate; state.holdStream = false; state.changed = true;
        await route.fulfill({ status: 409, json: { detail: { code: 'WRITING_TARGET_CHANGED', message: 'PRIVATE SOURCE DETAIL', retryable: false } } }); return; }
      await route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ ...draft, stage: 'done' })}\n\n` }); return;
    }
    if (path === '/api/cold-email/refine') {
      await route.fulfill({ json: { ...receipt, ...(state.wrongRefine ? { target_version: NEXT } : {}), body: 'Unverified replacement', method: 'llm' } }); return;
    }
    await route.fulfill({ status: 503, json: { detail: 'No unexpected writing endpoint is allowed in this test' } });
  });
  return { state, release };
}

test('a missing server target version stops the initial email before any generation request', async ({ page }) => {
  const owner = await account();
  try {
    await seed(page, owner); const { state } = await writing(page), writes = profileWrites(page);
    await page.route(`**/api/opportunities/${ID}**`, async route => {
      const response = await route.fetch({ maxRetries: 0 }); expect(response.status()).toBe(200); const target = await response.json();
      delete target.writing_target_version; await route.fulfill({ response, json: target });
    });
    await open(page); await expect(page.getByText(UNAVAILABLE, { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Check opportunity again', exact: true })).toBeEnabled();
    expect(state.calls).toEqual([]); expect(writes).toEqual([]); await expect(page.getByTestId('cold-email-footer')).toHaveCount(0);
  } finally { await owner.http.dispose(); }
});

test('a refinement for another target version preserves all manually edited fields', async ({ page }) => {
  const owner = await account();
  try {
    await seed(page, owner); const { state } = await writing(page), writes = profileWrites(page);
    await open(page); await expect(fields(page).body).toHaveValue('Checked body'); await expect(page.getByRole('button', { name: 'Shorter', exact: true })).toBeEnabled();
    await edit(page); state.wrongRefine = true; await page.getByRole('button', { name: 'Shorter', exact: true }).click();
    await expect(page.getByText(UNAVAILABLE, { exact: true })).toBeVisible(); await kept(page);
    expect(state.calls.filter(call => call.path === '/api/cold-email/refine')).toHaveLength(1);
    expect(state.calls.filter(call => call.path === '/api/cold-email')).toEqual([]); expect(writes).toEqual([]);
    await expect(page.getByText('Unverified replacement', { exact: true })).toHaveCount(0);
  } finally { await owner.http.dispose(); }
});

test('a streaming target 409 preserves the draft and checks the new target before explicit regeneration', async ({ page }, info) => {
  const owner = await account(); let release = () => {};
  try {
    await seed(page, owner); const model = await writing(page), writes = profileWrites(page); release = model.release; model.state.holdStream = true;
    await page.route(`**/api/opportunities/${ID}**`, async route => {
      const response = await route.fetch({ maxRetries: 0 }); expect(response.status()).toBe(200); const target = await response.json();
      if (model.state.changed) { target.description_clean += '\nUpdated requirements.'; target.writing_target_version = NEXT; }
      await route.fulfill({ response, json: target });
    });
    await open(page); await expect.poll(() => model.state.streamStarted).toBe(true); await edit(page); release();
    await expect(page.getByText(CHANGED, { exact: true })).toBeVisible(); await kept(page);
    expect(model.state.calls.filter(call => call.path === '/api/cold-email/stream')).toHaveLength(1);
    expect(model.state.calls.filter(call => call.path === '/api/cold-email')).toEqual([]);
    await expect(page.getByText('PRIVATE SOURCE DETAIL', { exact: true })).toHaveCount(0);
    await page.screenshot({ path: info.outputPath('email-target-changed-manual-draft.png'), fullPage: true });
    await page.getByRole('button', { name: 'Check opportunity again', exact: true }).click();
    const regenerate = page.getByRole('button', { name: 'Regenerate from updated materials', exact: true });
    await expect(regenerate).toBeEnabled(); await kept(page);
    expect(model.state.calls.filter(call => call.path === '/api/cold-email/variants')).toHaveLength(1);
    await regenerate.click(); await expect(fields(page).body).toHaveValue('Checked body');
    await expect.poll(() => model.state.calls.filter(call => call.path === '/api/cold-email/stream').length).toBe(2);
    expect(model.state.calls.at(-1)?.expected_target_version).toBe(NEXT); await expect(fields(page).recipient).toHaveValue('manual@example.edu');
    expect(writes).toEqual([]); await page.screenshot({ path: info.outputPath('email-target-regenerated.png'), fullPage: true });
  } finally { release(); await owner.http.dispose(); }
});
