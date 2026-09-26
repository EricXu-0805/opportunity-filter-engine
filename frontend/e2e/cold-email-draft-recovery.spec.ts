import { test, expect, request as apiRequest, type APIRequestContext, type Page, type TestInfo } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { en, zh } from '../src/i18n/dictionaries';
import { contactReceiptForRequest } from './email-contact-receipt';

// Production UI with loopback auth/profile state. Generation/source responses
// are controlled; window.open is inert and no email or model call is made.
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const ID = 'uiuc-siebel-ugresearch';
const V1 = `wt1:${'d'.repeat(64)}`, V2 = `wt1:${'e'.repeat(64)}`;
const BODY = 'Original fixture email 王';
const EDIT = { subject: 'My own subject 王', body: 'My full manual draft.\n本人负责采样，团队设计实验。', to: 'chosen@example.edu', request: '保留我的贡献，不要改成团队负责人。' };
interface Fixture { http: APIRequestContext; session: { access_token: string; refresh_token: string; user: { id: string; is_anonymous: boolean; email: string; app_metadata: Record<string, unknown> } } }
const fact = (id: string, value: string) => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
async function account(): Promise<Fixture> {
  expect(new URL(STUB).hostname).toBe('127.0.0.1'); const http = await apiRequest.newContext();
  try {
    const result = await http.post(`${STUB}/auth/v1/signup`, { data: {} }); expect(result.status()).toBe(200); const session = await result.json();
    // Formal SDK state is required for the independent address-reveal read.
    session.user = { ...session.user, is_anonymous: false, email: 'draft-recovery@fixture.invalid', app_metadata: { provider: 'email', providers: ['email'] } };
    const token = session.access_token.split('.'); const claims = JSON.parse(Buffer.from(token[1], 'base64url').toString());
    token[1] = Buffer.from(JSON.stringify({ ...claims, is_anonymous: false })).toString('base64url'); session.access_token = token.join('.');
    const headers = { Authorization: `Bearer ${session.access_token}` };
    const saved = await http.post(`${STUB}/rest/v1/rpc/commit_profile_patch_cas`, { headers, data: { p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: {
      name: 'Recovery student 王', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Sophomore',
      is_international: false, research_interests: 'sensors', seeking_types: ['research'], skills: [], coursework: [], resume_text: 'Original complete source 王', experience_entries: [],
      resume_master: { version: 1, id: 'email-master', revision: 1, source_signature: null,
        basics: { name: fact('name', 'Recovery student 王'), links: [] }, education: [],
        activities: [{ id: 'project-1', kind: 'project', title: fact('project-title', 'Instrument project'), details: [] }],
        publications: [], skills: [], other_sections: [], section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [] },
    } } }); expect(saved.status()).toBe(200); expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1 });
    const favorite = await http.post(`${STUB}/rest/v1/favorites`, { headers, data: { device_id: session.user.id, opportunity_id: ID } }); expect(favorite.status()).toBe(201);
    return { http, session };
  } catch (error) { await http.dispose(); throw error; }
}

async function setup(page: Page, info: TestInfo) {
  const owner = await account(), owners = [owner]; const locale = info.project.name === 'mobile-chrome' ? 'zh' : 'en';
  const copy = (locale === 'zh' ? zh : en).coldEmail;
  if (locale === 'zh') await page.setViewportSize({ width: 320, height: 640 });
  const state = { owner, version: V1, calls: [] as string[], mutations: [] as string[], detailReads: 0, review: false };
  const audit = { pageErrors: [] as string[], console: [] as string[], unexpected5xx: [] as string[], external: [] as string[], storageFailureInjected: false };
  page.on('pageerror', error => audit.pageErrors.push(error.message));
  page.on('console', entry => { if (entry.type() === 'error') audit.console.push(entry.text()); });
  page.on('response', response => { if (response.status() >= 500) audit.unexpected5xx.push(`${response.status()} ${response.url()}`); });
  page.on('request', request => { if (request.method() !== 'GET' && /confirm_contact_event|commit_profile_patch_cas/.test(request.url())) state.mutations.push(new URL(request.url()).pathname); });
  await page.context().route('**/*', route => {
    const url = new URL(route.request().url());
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) { audit.external.push(url.origin); return route.abort('blockedbyclient'); }
    return route.continue();
  });
  await page.context().addCookies([{ name: STORAGE_KEYS.LOCALE, value: locale, url: `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3100)}` }]);
  await page.addInitScript(({ session, keys, locale }) => {
    if (!localStorage.getItem('draft-recovery-seeded')) {
      localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, locale);
      localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('draft-recovery-seeded', '1');
    }
    const compose = { opens: 0 };
    (window as unknown as { __recoveryCompose: typeof compose }).__recoveryCompose = compose;
    window.open = (() => { compose.opens++; const popup = { closed: false, opener: null, location: { href: 'about:blank' }, close() { popup.closed = true; } }; return popup as unknown as Window; });
  }, { session: owner.session, keys: STORAGE_KEYS, locale });
  await page.route('**/auth/v1/user', route => route.fulfill({ json: state.owner.session.user }));
  await page.route('**/auth/v1/token?grant_type=refresh_token', route => {
    const match = owners.find(item => item.session.refresh_token === route.request().postDataJSON().refresh_token);
    expect(match, 'The SDK must refresh the account owning this token').toBeTruthy();
    return route.fulfill({ json: match!.session });
  });
  await page.route(`**/api/opportunities/${ID}**`, async route => {
    state.detailReads++; const response = await route.fetch({ maxRetries: 0 }); expect(response.status()).toBe(200);
    const value = await response.json(); value.writing_target_version = state.version;
    value.contact_instructions = { version: 1, status: 'unknown', email_policy: 'unknown', rules: [] };
    if (route.request().headers().authorization) { value.contact_email_status = 'revealed'; value.contact_email = 'lab@example.edu'; }
    await route.fulfill({ response, json: value });
  });
  await page.route('**/api/cold-email**', async route => {
    const path = new URL(route.request().url()).pathname, payload = route.request().postDataJSON(); state.calls.push(path);
    expect(payload.opportunity_id).toBe(ID); expect(payload.expected_target_version).toBe(state.version);
    const draft = { opportunity_id: ID, target_version: payload.expected_target_version, contact_context_receipt: contactReceiptForRequest(payload),
      subject: 'Original subject', body: BODY, recipient_email: 'lab@example.edu', recipient_status: 'revealed', mailto_link: '', method: 'template', pipeline_version: 'b40-controlled', corpus_version: 'b40-controlled',
      ...(state.review ? { experience_usage: { version: 1, eligible_count: 0, selected: [], excluded: [], needs_review: true, notices: [] } } : {}) };
    if (path.endsWith('/variants')) return route.fulfill({ json: { ...draft, variants: [{ ...draft, id: 'controlled', label: 'Controlled' }] } });
    if (path.endsWith('/stream')) return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ ...draft, stage: 'done' })}\n\n` });
    if (path.endsWith('/refine')) return route.fulfill({ json: { ...draft, method: 'llm' } });
    throw new Error('Unexpected writing request ' + path);
  });
  const open = async (navigate = true) => { if (navigate) await page.goto('/favorites'); await page.getByRole('button', { name: locale === 'zh' ? '起草邮件' : 'Draft Email', exact: true }).click(); };
  const ready = async () => { await expect(page.locator('#cold-email-body')).toHaveValue(BODY); await expect.poll(() => state.calls.filter(path => path.endsWith('/stream')).length).toBe(1); };
  const edit = async () => {
    await page.locator('#cold-email-subject').fill(EDIT.subject); await page.locator('#cold-email-body').fill(EDIT.body);
    await page.locator('#cold-email-to').fill(EDIT.to); await page.getByRole('textbox', { name: copy.requestLabel, exact: true }).fill(EDIT.request);
  };
  const retained = async () => {
    await expect(page.locator('#cold-email-subject')).toHaveValue(EDIT.subject); await expect(page.locator('#cold-email-body')).toHaveValue(EDIT.body);
    await expect(page.locator('#cold-email-to')).toHaveValue(EDIT.to); await expect(page.getByRole('textbox', { name: copy.requestLabel, exact: true })).toHaveValue(EDIT.request);
  };
  const saved = async () => expect(page.getByTestId('cold-email-draft-status')).toContainText(locale === 'zh' ? '已保存' : 'Saved on this browser');
  const close = async () => { await page.getByRole('button', { name: copy.closeAria, exact: true }).click(); await expect(page.getByRole('dialog', { name: copy.title })).toHaveCount(0); };
  const done = async () => {
    await info.attach('draft-recovery-audit', { body: JSON.stringify({ ...audit, writes: state.mutations, calls: state.calls }, null, 2), contentType: 'application/json' });
    await Promise.all(owners.map(item => item.http.dispose()));
    expect(audit.pageErrors).toEqual([]); expect(audit.external).toEqual([]); expect(audit.unexpected5xx).toEqual([]); expect(state.mutations).toEqual([]);
  };
  return { state, audit, owners, locale, copy, open, ready, edit, retained, saved, close, done };
}
async function proof(page: Page, info: TestInfo, name: string) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
  await page.screenshot({ path: info.outputPath(name), animations: 'disabled' });
}

test('manual editor survives close and reopen without automatic AI or sending', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await f.ready(); await f.edit(); await f.close(); const initialStreams = f.state.calls.filter(path => path.endsWith('/stream')).length;
    await f.open(false); await f.retained(); expect(f.state.calls.filter(path => path.endsWith('/stream'))).toHaveLength(initialStreams);
    await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
    const request = page.getByRole('textbox', { name: f.copy.requestLabel, exact: true }); await request.scrollIntoViewIfNeeded(); await request.click();
    await page.keyboard.press('ControlOrMeta+A'); await page.keyboard.type('New keyboard request after recovery'); await expect(request).toHaveValue('New keyboard request after recovery');
    await proof(page, info, 'restored-request-' + f.locale + '.png');
  } finally { await f.done(); }
});

test('profile visit and hard reload preserve unapplied background and the original text', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await f.ready(); await f.edit(); const panel = page.getByTestId('email-contact-context-panel'); await panel.locator('summary').click();
    const label = f.locale === 'zh' ? '可投入的时间（选填）' : 'When could you participate? (optional)';
    await panel.getByLabel(label, { exact: true }).fill('Possibly Tuesday; not confirmed 王'); await f.saved();
    const calls = f.state.calls.length; await page.goto('/'); await f.open(); await f.retained();
    await expect(panel.getByLabel(label, { exact: true })).toHaveValue('Possibly Tuesday; not confirmed 王');
    await expect(panel.getByRole('checkbox', { name: f.locale === 'zh' ? '我确认这些可投入时间属实。' : 'I confirm this availability is accurate.' })).not.toBeChecked();
    await expect(page.getByRole('button', { name: 'Gmail', exact: true })).toBeDisabled(); expect(f.state.calls).toHaveLength(calls);
    await page.reload(); await f.open(false); await f.retained(); await expect(panel.getByLabel(label, { exact: true })).toHaveValue('Possibly Tuesday; not confirmed 王');
    expect(f.state.calls).toHaveLength(calls); await panel.getByLabel(label, { exact: true }).scrollIntoViewIfNeeded(); await proof(page, info, 'restored-background-' + f.locale + '.png');
  } finally { await f.done(); }
});

test('a changed target preserves the recovered draft and blocks new compose', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await f.ready(); await f.edit(); await f.close(); f.state.version = V2; const streams = f.state.calls.filter(path => path.endsWith('/stream')).length;
    await f.open(false); await f.retained(); await expect(page.getByRole('button', { name: 'Gmail', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: f.copy.regenerateFromProfile, exact: true })).toBeVisible();
    expect(f.state.calls.filter(path => path.endsWith('/stream'))).toHaveLength(streams);
    expect(await page.evaluate(() => (window as unknown as { __recoveryCompose: { opens: number } }).__recoveryCompose.opens)).toBe(0);
    await proof(page, info, 'restored-stale-source-' + f.locale + '.png');
  } finally { await f.done(); }
});

test('switching accounts retires the old editor and never restores its text into the new account', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await f.ready(); await f.edit(); await f.saved();
    const next = await account(); f.owners.push(next); f.state.owner = next;
    await page.evaluate(session => {
      localStorage.setItem('ofe_auth', JSON.stringify(session)); const channel = new BroadcastChannel('ofe_auth');
      channel.postMessage({ event: 'SIGNED_IN', session }); channel.close();
    }, next.session);
    await expect(page.getByRole('dialog', { name: f.copy.title })).toHaveCount(0);
    await page.goto('/favorites');
    const schoolGate = page.locator('[role="dialog"][aria-labelledby="university-switcher-title"]');
    await expect(schoolGate).toBeVisible();
    await schoolGate.getByRole('button', { name: f.locale === 'zh' ? '关闭' : 'Close', exact: true }).click();
    await f.open(false); await expect(page.locator('#cold-email-body')).toHaveValue(BODY);
    await expect(page.locator('#cold-email-to')).toHaveValue('lab@example.edu'); await expect(page.getByRole('textbox', { name: f.copy.requestLabel, exact: true })).toHaveValue('');
    await expect(page.getByText(EDIT.body, { exact: true })).toHaveCount(0);
  } finally { await f.done(); }
});

test('a storage failure retains the active editor and blocks normal close with a clear warning', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await f.ready(); await f.saved(); f.audit.storageFailureInjected = true;
    await page.evaluate(prefix => {
      const original = Storage.prototype.setItem;
      Storage.prototype.setItem = function(key, value) { if (key.includes(prefix)) throw new DOMException('Fixture quota failure', 'QuotaExceededError'); original.call(this, key, value); };
    }, STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX);
    await f.edit(); await expect(page.getByTestId('cold-email-draft-status')).toContainText(f.locale === 'zh' ? '未能保存' : 'Could not save');
    await page.getByRole('button', { name: f.copy.closeAria, exact: true }).click(); await f.retained();
    await expect(page.getByRole('button', { name: f.locale === 'zh' ? '不保存并关闭' : 'Close without saving', exact: true })).toBeVisible();
    await page.getByTestId('cold-email-draft-status').scrollIntoViewIfNeeded(); await proof(page, info, 'save-failure-' + f.locale + '.png');
  } finally { await f.done(); }
});

test('cancelled clear keeps the draft and confirmed clear cannot revive it on reload', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await f.ready(); await f.edit(); await f.close(); await f.open(false); await f.retained();
    page.once('dialog', dialog => dialog.dismiss()); await page.getByTestId('cold-email-draft-clear').click(); await f.retained();
    page.once('dialog', dialog => dialog.accept()); await page.getByTestId('cold-email-draft-clear').click(); await expect(page.locator('#cold-email-body')).toHaveValue(BODY);
    await expect(page.getByRole('textbox', { name: f.copy.requestLabel, exact: true })).toHaveValue(''); await f.close();
    await page.reload(); await f.open(false); await expect(page.locator('#cold-email-body')).toHaveValue(BODY);
    await expect(page.getByRole('textbox', { name: f.copy.requestLabel, exact: true })).toHaveValue(''); await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
  } finally { await f.done(); }
});


test('the real profile review link flushes the draft and browser Back recovers it', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    f.state.review = true; await f.open(); await f.ready(); await f.edit();
    await page.getByRole('link', { name: f.copy.experienceReviewCta, exact: true }).click();
    await expect(page).toHaveURL(/\/#experience-library$/);
    await expect(page.getByRole('dialog', { name: f.copy.title })).toHaveCount(0);
    const streams = f.state.calls.filter(path => path.endsWith('/stream')).length;
    await page.goBack(); await expect(page).toHaveURL(/\/favorites$/); await f.open(false); await f.retained();
    expect(f.state.calls.filter(path => path.endsWith('/stream'))).toHaveLength(streams);
    await page.locator('#cold-email-body').scrollIntoViewIfNeeded(); await proof(page, info, 'review-link-return-' + f.locale + '.png');
  } finally { await f.done(); }
});
