import { createHash } from 'node:crypto';
import { test, expect, request as apiRequest, type APIRequestContext, type Page, type Request, type Route, type TestInfo } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { en, zh } from '../src/i18n/dictionaries';
import { contactReceiptForRequest } from './email-contact-receipt';

// Real production UI, local controlled auth/profile fixtures and intercepted
// generation. No provider, mail, tracking mutation or external navigation runs.
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const FRONTEND = `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3100)}`;
const ID = 'uiuc-siebel-ugresearch';
const VERSION = `wt1:${'d'.repeat(64)}`;
const REPEATED = '我负责测试 🧪，团队负责系统。';
const BODY = `Dear Professor,\n\n${REPEATED}\n\n两段之间的文字保持不变。\n\n${REPEATED}\n\nThank you,\nRevision student 王`;
const REPLACEMENT = '我的工作是编写测试 🧪；系统由团队完成。';
const INSTRUCTION = '只改选中的第二段，保留我与团队的分工。';
const START = BODY.lastIndexOf(REPEATED);
const END = START + REPEATED.length;
const ACCEPTED = BODY.slice(0, START) + REPLACEMENT + BODY.slice(END);
const fact = (id: string, value: string) => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
interface Fixture {
  http: APIRequestContext;
  session: { access_token: string; refresh_token: string; user: { id: string; is_anonymous: boolean; email: string; app_metadata: Record<string, unknown> } };
}
function gate() {
  let release!: () => void;
  const promise = new Promise<void>(resolve => { release = resolve; });
  return { promise, release };
}
async function account(): Promise<Fixture> {
  expect(new URL(STUB).hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const result = await http.post(`${STUB}/auth/v1/signup`, { data: {} });
    expect(result.status()).toBe(200);
    const session = await result.json();
    // The loopback stand-in alone accepts these synthetic formal-user claims.
    // This is not a real Supabase JWT or an authentication acceptance test.
    session.user = { ...session.user, is_anonymous: false, email: 'revisions@fixture.invalid', app_metadata: { provider: 'email', providers: ['email'] } };
    const token = session.access_token.split('.');
    const claims = JSON.parse(Buffer.from(token[1], 'base64url').toString());
    token[1] = Buffer.from(JSON.stringify({ ...claims, is_anonymous: false })).toString('base64url');
    session.access_token = token.join('.');
    const headers = { Authorization: `Bearer ${session.access_token}` };
    const saved = await http.post(`${STUB}/rest/v1/rpc/commit_profile_patch_cas`, { headers, data: {
      p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: {
        name: 'Revision student 王', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Sophomore',
        is_international: false, research_interests: 'sensors', seeking_types: ['research'], skills: [], coursework: [], resume_text: 'Complete controlled source 王', experience_entries: [],
        resume_master: { version: 1, id: 'revision-master', revision: 1, source_signature: null,
          basics: { name: fact('name', 'Revision student 王'), links: [] }, education: [],
          activities: [{ id: 'project-1', kind: 'project', title: fact('project-title', 'Instrument project'), details: [] }],
          publications: [], skills: [], other_sections: [], section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [] },
      },
    } });
    expect(saved.status()).toBe(200); expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1 });
    const favorite = await http.post(`${STUB}/rest/v1/favorites`, { headers, data: { device_id: session.user.id, opportunity_id: ID } });
    expect(favorite.status()).toBe(201);
    return { http, session };
  } catch (error) { await http.dispose(); throw error; }
}

async function setup(page: Page, info: TestInfo) {
  const owner = await account();
  const locale = info.project.name === 'mobile-chrome' ? 'zh' : 'en';
  const copy = (locale === 'zh' ? zh : en).coldEmail;
  if (locale === 'zh') await page.setViewportSize({ width: 390, height: 844 });
  const state = {
    offline: false, refineMode: 'proposal' as 'proposal' | 'unavailable',
    calls: [] as string[], refinements: [] as Record<string, unknown>[], mutations: [] as string[],
    profileReads: 0, completedProfileReads: 0, targetReads: 0, completedTargetReads: 0,
    holdProfile: null as ReturnType<typeof gate> | null, holdTarget: null as ReturnType<typeof gate> | null,
  };
  const injectedFailures = new WeakMap<Request, string>();
  const audit = {
    pageErrors: [] as string[], consoleErrors: [] as string[], external: [] as string[],
    responses5xx: [] as { path: string; status: number; injected: string | null }[],
    networkFailures: [] as { path: string; error: string | null; injected: string | null }[],
    requests: [] as { method: string; path: string }[],
  };
  const abortOffline = (route: Route) => { injectedFailures.set(route.request(), 'controlled_offline'); return route.abort('internetdisconnected'); };
  page.on('pageerror', error => audit.pageErrors.push(error.message));
  page.on('console', entry => { if (entry.type() === 'error') audit.consoleErrors.push(entry.text()); });
  page.on('requestfailed', request => audit.networkFailures.push({ path: new URL(request.url()).pathname, error: request.failure()?.errorText ?? null, injected: injectedFailures.get(request) ?? null }));
  page.on('response', response => {
    if (response.status() >= 500) audit.responses5xx.push({ path: new URL(response.url()).pathname, status: response.status(), injected: injectedFailures.get(response.request()) ?? null });
  });
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    audit.requests.push({ method: request.method(), path });
    if (request.method() !== 'GET' && /confirm_contact_event|commit_profile_patch_cas/.test(path)) state.mutations.push(path);
  });
  // Any unexpected outbound host is recorded and blocked before transmission.
  await page.context().route('**/*', route => {
    const url = new URL(route.request().url());
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) { audit.external.push(url.origin); return route.abort('blockedbyclient'); }
    if (state.offline) return abortOffline(route);
    return route.continue();
  });
  await page.context().addCookies([{ name: STORAGE_KEYS.LOCALE, value: locale, url: FRONTEND }]);
  await page.addInitScript(({ session, keys, locale }) => {
    if (!localStorage.getItem('cold-email-revisions-seeded')) {
      localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, locale);
      localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('cold-email-revisions-seeded', '1');
    }
    const compose = { opens: 0 };
    (window as unknown as { __revisionCompose: typeof compose }).__revisionCompose = compose;
    window.open = (() => {
      compose.opens++;
      const popup = { closed: false, opener: null, location: { href: 'about:blank' }, close() { popup.closed = true; } };
      return popup as unknown as Window;
    });
  }, { session: owner.session, keys: STORAGE_KEYS, locale });
  await page.route('**/auth/v1/user', route => state.offline ? abortOffline(route) : route.fulfill({ json: owner.session.user }));
  await page.route('**/auth/v1/token?grant_type=refresh_token', route => {
    if (state.offline) return abortOffline(route);
    expect(route.request().postDataJSON().refresh_token).toBe(owner.session.refresh_token);
    return route.fulfill({ json: owner.session });
  });
  await page.route('**/rest/v1/profiles?**', async route => {
    expect(route.request().method()).toBe('GET');
    if (state.offline) return abortOffline(route);
    state.profileReads++;
    await state.holdProfile?.promise;
    const response = await route.fetch({ maxRetries: 0 }); expect(response.status()).toBe(200);
    await route.fulfill({ response }); state.completedProfileReads++;
  });
  await page.route(`**/api/opportunities/${ID}**`, async route => {
    if (state.offline) return abortOffline(route);
    state.targetReads++;
    await state.holdTarget?.promise;
    const response = await route.fetch({ maxRetries: 0 }); expect(response.status()).toBe(200);
    const value = await response.json(); value.writing_target_version = VERSION;
    value.contact_instructions = { version: 1, status: 'unknown', email_policy: 'unknown', rules: [] };
    if (route.request().headers().authorization) { value.contact_email_status = 'revealed'; value.contact_email = 'lab@example.edu'; }
    return route.fulfill({ response, json: value }).then(() => { state.completedTargetReads++; });
  });
  await page.route('**/api/cold-email**', async route => {
    if (state.offline) return abortOffline(route);
    const path = new URL(route.request().url()).pathname;
    const payload = route.request().postDataJSON(); state.calls.push(path);
    expect(payload.opportunity_id).toBe(ID); expect(payload.expected_target_version).toBe(VERSION);
    const receipt = { opportunity_id: ID, target_version: VERSION, contact_context_receipt: contactReceiptForRequest(payload) };
    const draft = { ...receipt, subject: 'Controlled subject', body: BODY, recipient_email: 'lab@example.edu', recipient_status: 'revealed', mailto_link: '', method: 'template', pipeline_version: 'b41-controlled', corpus_version: 'b41-controlled' };
    if (path.endsWith('/variants')) return route.fulfill({ json: { ...draft, variants: [{ ...draft, id: 'controlled', label: 'Controlled' }] } });
    if (path.endsWith('/stream')) return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ ...draft, stage: 'done' })}\n\n` });
    if (path.endsWith('/refine')) {
      state.refinements.push({ current_body: payload.current_body, instruction: payload.instruction, selection: payload.selection, subject: payload.subject });
      expect(payload.current_body).toBe(BODY); expect(payload.instruction).toBe(INSTRUCTION);
      expect(payload.selection).toEqual({ start_utf16: START, end_utf16: END, text: REPEATED });
      expect(payload.subject).toBe('Controlled subject');
      if (state.refineMode === 'unavailable') {
        injectedFailures.set(route.request(), 'controlled_refine_503');
        return route.fulfill({ status: 503, json: { detail: 'Controlled editing service unavailable' } });
      }
      return route.fulfill({ json: { ...receipt, scope: 'selection', outcome: 'proposal', method: 'llm', proposal: {
        start_utf16: START, end_utf16: END, original_text: REPEATED, replacement: REPLACEMENT,
        base_body_sha256: createHash('sha256').update(BODY, 'utf8').digest('hex'),
      } } });
    }
    throw new Error('Unexpected writing request ' + path);
  });
  // The E2E backend has no Supabase service key, so the saved private-import list that /favorites loads
  // would answer 503. This spec does not test private imports: serve the real empty list for this owner only.
  await page.route(url => url.pathname === '/api/private-import-targets', route => {
    const request = route.request(); if (request.method() !== 'GET') return route.fallback();
    if (state.offline) return abortOffline(route);
    expect(new URL(request.url()).searchParams.get('expected_owner_id')).toBe(owner.session.user.id);
    expect(request.headers().authorization).toBe(`Bearer ${owner.session.access_token}`);
    return route.fulfill({ json: { version: 1, items: [], next_cursor: null } });
  });
  const body = page.locator('#cold-email-body');
  const request = page.getByRole('textbox', { name: copy.requestLabel, exact: true });
  const submit = page.getByRole('button', { name: copy.submitRequest, exact: true });
  const suggestion = page.getByRole('region', { name: locale === 'zh' ? '待确认的修改建议' : 'Pending edit suggestion', exact: true });
  const open = async () => {
    await page.goto('/favorites');
    await page.getByRole('button', { name: locale === 'zh' ? '起草邮件' : 'Draft Email', exact: true }).click();
    await expect(body).toHaveValue(BODY);
    await expect(page.getByRole('button', { name: copy.generateAiDraft, exact: true })).toBeEnabled();
    expect(state.calls.filter(path => path.endsWith('/stream'))).toEqual([]);
  };
  const selectSecond = async () => {
    await body.scrollIntoViewIfNeeded();
    await body.click();
    await page.keyboard.press('ControlOrMeta+A');
    await page.keyboard.press('ArrowLeft');
    // Real keyboard events exercise React's selection handling. ArrowRight
    // moves over one Unicode code point here; API offsets remain UTF-16.
    for (const character of Array.from(BODY.slice(0, START))) {
      void character; await page.keyboard.press('ArrowRight');
    }
    await page.keyboard.down('Shift');
    try {
      for (const character of Array.from(REPEATED)) {
        void character; await page.keyboard.press('ArrowRight');
      }
    } finally { await page.keyboard.up('Shift'); }
    await expect(page.getByText(locale === 'zh' ? '本次只修改选中的内容；加入课程需切回整封。' : 'This request edits only the selected text. Use full body to add coursework.', { exact: true })).toBeVisible();
    await expect(body).toHaveJSProperty('selectionStart', START); await expect(body).toHaveJSProperty('selectionEnd', END);
  };
  const propose = async () => {
    await selectSecond(); await request.fill(INSTRUCTION); await submit.click();
    await expect(suggestion).toBeVisible(); await expect(suggestion.getByText(REPEATED, { exact: true })).toBeVisible();
    await expect(suggestion.getByText(REPLACEMENT, { exact: true })).toBeVisible();
    await expect(body).toHaveValue(BODY); await expect(request).toHaveValue(INSTRUCTION);
  };
  const done = async () => {
    state.holdProfile?.release(); state.holdTarget?.release();
    const opens = await page.evaluate(() => (window as unknown as { __revisionCompose?: { opens: number } }).__revisionCompose?.opens ?? 0);
    await info.attach('cold-email-revisions-audit', { body: JSON.stringify({ ...audit, writes: state.mutations, calls: state.calls, refinements: state.refinements, profileReads: state.profileReads, targetReads: state.targetReads, composerOpens: opens }, null, 2), contentType: 'application/json' });
    await owner.http.dispose();
    expect(audit.pageErrors).toEqual([]); expect(audit.external).toEqual([]); expect(state.mutations).toEqual([]); expect(opens).toBe(0);
    expect(audit.responses5xx.filter(item => item.injected !== 'controlled_refine_503')).toEqual([]);
  };
  return { state, locale, copy, open, body, request, submit, suggestion, selectSecond, propose, done };
}
async function proof(page: Page, info: TestInfo, name: string) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
  await page.screenshot({ path: info.outputPath(name), animations: 'disabled' });
}

test('preview is inert, accepting changes only the second repeated Unicode paragraph, and undo restores it', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await f.propose();
    await proof(page, info, 'selection-preview-' + f.locale + '.png');
    const accept = f.suggestion.getByRole('button', { name: f.locale === 'zh' ? '接受建议' : 'Accept suggestion', exact: true });
    await accept.scrollIntoViewIfNeeded(); await proof(page, info, 'selection-preview-controls-' + f.locale + '.png');
    await accept.click();
    await expect(f.body).toHaveValue(ACCEPTED); await expect(f.suggestion).toHaveCount(0);
    expect((await f.body.inputValue()).indexOf(REPEATED)).toBe(BODY.indexOf(REPEATED));
    expect((await f.body.inputValue()).lastIndexOf(REPEATED)).toBe(BODY.indexOf(REPEATED));
    await expect(f.request).toHaveValue('');
    const undo = page.getByRole('button', { name: f.locale === 'zh' ? '撤销上次接受的修改' : 'Undo last accepted edit', exact: true });
    await undo.scrollIntoViewIfNeeded(); await proof(page, info, 'selection-accepted-' + f.locale + '.png');
    await undo.click(); await expect(f.body).toHaveValue(BODY); await expect(undo).toHaveCount(0);
    expect(f.state.refinements).toHaveLength(1);
  } finally { await f.done(); }
});

test('rejecting a suggestion and a failed retry keep the original body and typed request', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await f.propose();
    await f.suggestion.getByRole('button', { name: f.locale === 'zh' ? '拒绝建议' : 'Reject suggestion', exact: true }).click();
    await expect(f.suggestion).toHaveCount(0); await expect(f.body).toHaveValue(BODY); await expect(f.request).toHaveValue(INSTRUCTION);
    f.state.refineMode = 'unavailable'; await f.selectSecond(); await f.submit.click();
    await expect.poll(() => f.state.refinements.length).toBe(2);
    await expect(page.getByText(f.copy.editFailed, { exact: true })).toBeVisible();
    await expect(f.submit).toBeEnabled(); await expect(f.suggestion).toHaveCount(0);
    await expect(f.body).toHaveValue(BODY); await expect(f.request).toHaveValue(INSTRUCTION);
    await f.request.scrollIntoViewIfNeeded(); await proof(page, info, 'selection-failure-kept-' + f.locale + '.png');
  } finally { await f.done(); }
});

test('editing the body retires a pending selected-text suggestion', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await f.propose();
    const manual = BODY + '\n我自己追加的说明。';
    await f.body.fill(manual);
    await expect(f.body).toHaveValue(manual); await expect(f.suggestion).toHaveCount(0); await expect(f.request).toHaveValue(INSTRUCTION);
    await expect(page.getByRole('button', { name: f.locale === 'zh' ? '接受建议' : 'Accept suggestion', exact: true })).toHaveCount(0);
    expect(f.state.refinements).toHaveLength(1);
    await f.body.scrollIntoViewIfNeeded(); await proof(page, info, 'selection-manual-edit-' + f.locale + '.png');
  } finally { await f.done(); }
});

test('real offline state pauses actions and reconnect waits for both fresh source checks without replacing the draft', async ({ page, context }, info) => {
  const f = await setup(page, info);
  try {
    await f.open();
    const manual = BODY + '\n保留这条离线前的手写补充。';
    await f.body.fill(manual); await f.request.fill(INSTRUCTION);
    const ai = page.getByRole('button', { name: f.copy.generateAiDraft, exact: true });
    const gmail = page.getByRole('button', { name: 'Gmail', exact: true });
    await expect(ai).toBeEnabled(); await expect(gmail).toBeEnabled(); await expect(f.submit).toBeEnabled();
    const writingCalls = f.state.calls.length;
    f.state.offline = true; await context.setOffline(true);
    expect(await page.evaluate(() => navigator.onLine)).toBe(false);
    const dialog = page.getByRole('dialog', { name: f.copy.title, exact: true });
    const banner = dialog.getByTestId('profile-refresh-status');
    await expect(banner).toContainText(f.locale === 'zh' ? '当前离线。草稿仍保留' : "You're offline. Your draft is kept");
    await expect(ai).toBeDisabled(); await expect(gmail).toBeDisabled(); await expect(f.submit).toBeDisabled();
    await expect(page.getByRole('button', { name: f.copy.quickActions.formal, exact: true })).toBeDisabled();
    await expect(f.body).toHaveValue(manual); await expect(f.request).toHaveValue(INSTRUCTION);
    await banner.scrollIntoViewIfNeeded(); await proof(page, info, 'offline-banner-' + f.locale + '.png');
    const profileReads = f.state.profileReads, targetReads = f.state.targetReads;
    const completedProfileReads = f.state.completedProfileReads;
    f.state.holdProfile = gate(); f.state.holdTarget = gate();
    f.state.offline = false; await context.setOffline(false);
    expect(await page.evaluate(() => navigator.onLine)).toBe(true);
    await expect.poll(() => f.state.profileReads).toBeGreaterThan(profileReads);
    await expect.poll(() => f.state.targetReads).toBeGreaterThan(targetReads);
    await expect(ai).toBeDisabled(); await expect(gmail).toBeDisabled(); await expect(f.submit).toBeDisabled();
    f.state.holdProfile.release(); f.state.holdProfile = null;
    await expect.poll(() => f.state.completedProfileReads).toBeGreaterThan(completedProfileReads);
    await expect(gmail).toBeDisabled(); await expect(ai).toBeDisabled();
    await expect(dialog.getByTestId('writing-target-status')).toContainText(f.locale === 'zh' ? '正在核对' : 'Checking current opportunity');
    f.state.holdTarget.release(); f.state.holdTarget = null;
    await expect(banner).toHaveCount(0); await expect(ai).toBeEnabled(); await expect(gmail).toBeEnabled(); await expect(f.submit).toBeEnabled();
    await expect(f.body).toHaveValue(manual); await expect(f.request).toHaveValue(INSTRUCTION);
    expect(f.state.calls).toHaveLength(writingCalls);
    await f.body.scrollIntoViewIfNeeded(); await proof(page, info, 'online-sources-rechecked-' + f.locale + '.png');
  } finally { f.state.offline = false; await context.setOffline(false); await f.done(); }
});
