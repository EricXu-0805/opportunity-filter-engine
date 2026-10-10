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
    session.user = { ...session.user, is_anonymous: false, email: 'history@fixture.invalid', app_metadata: { provider: 'email', providers: ['email'] } };
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

async function setup(page: Page, info: TestInfo, sharedOwner?: Fixture) {
  const owner = sharedOwner ?? await account();
  const locale = info.project.name === 'mobile-chrome' ? 'zh' : 'en';
  const copy = (locale === 'zh' ? zh : en).coldEmail;
  if (locale === 'zh') await page.setViewportSize({ width: 390, height: 844 });
  const state = {
    offline: false, refineMode: 'proposal' as 'proposal' | 'unavailable', generatedBody: BODY, refinedBody: ACCEPTED,
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
    if (!localStorage.getItem('cold-email-history-seeded')) {
      localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, locale);
      localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('cold-email-history-seeded', '1');
    }
    const compose = { opens: 0 };
    (window as unknown as { __historyCompose: typeof compose }).__historyCompose = compose;
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
    const draft = { ...receipt, subject: 'Controlled subject', body: BODY, recipient_email: 'lab@example.edu', recipient_status: 'revealed', mailto_link: '', method: 'template', pipeline_version: 'b42-controlled', corpus_version: 'b42-controlled' };
    if (path.endsWith('/variants')) return route.fulfill({ json: { ...draft, variants: [{ ...draft, id: 'controlled', label: 'Controlled' }] } });
    if (path.endsWith('/stream')) return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ ...draft, body: state.generatedBody, method: state.generatedBody === BODY ? 'template' : 'ai', stage: 'done' })}\n\n` });
    if (path.endsWith('/refine')) {
      state.refinements.push({ current_body: payload.current_body, instruction: payload.instruction, selection: payload.selection, subject: payload.subject });
      expect(typeof payload.current_body).toBe('string'); expect(typeof payload.instruction).toBe('string');
      if (payload.selection) {
        expect(payload.selection).toEqual({ start_utf16: START, end_utf16: END, text: REPEATED });
        expect(payload.current_body.slice(START, END)).toBe(REPEATED);
      }
      if (state.refineMode === 'unavailable') {
        injectedFailures.set(route.request(), 'controlled_refine_503');
        return route.fulfill({ status: 503, json: { detail: 'Controlled editing service unavailable' } });
      }
      if (!payload.selection) return route.fulfill({ json: { ...receipt, body: state.refinedBody, method: 'llm' } });
      return route.fulfill({ json: { ...receipt, scope: 'selection', outcome: 'proposal', method: 'llm', proposal: {
        start_utf16: START, end_utf16: END, original_text: REPEATED, replacement: REPLACEMENT,
        base_body_sha256: createHash('sha256').update(payload.current_body, 'utf8').digest('hex'),
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
  const open = async (expectedBody = BODY, navigate = true) => {
    if (navigate) await page.goto('/favorites');
    const streams = state.calls.filter(path => path.endsWith('/stream')).length;
    await page.getByRole('button', { name: locale === 'zh' ? '起草邮件' : 'Draft Email', exact: true }).click();
    await expect(body).toHaveValue(expectedBody);
    await expect(page.getByRole('button', { name: copy.generateAiDraft, exact: true })).toBeEnabled();
    expect(state.calls.filter(path => path.endsWith('/stream'))).toHaveLength(streams);
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
    const opens = await page.evaluate(() => (window as unknown as { __historyCompose?: { opens: number } }).__historyCompose?.opens ?? 0);
    await info.attach('cold-email-history-audit', { body: JSON.stringify({ ...audit, writes: state.mutations, calls: state.calls, refinements: state.refinements, profileReads: state.profileReads, targetReads: state.targetReads, composerOpens: opens }, null, 2), contentType: 'application/json' });
    if (!sharedOwner) await owner.http.dispose();
    expect(audit.pageErrors).toEqual([]); expect(audit.external).toEqual([]); expect(state.mutations).toEqual([]); expect(opens).toBe(0);
    expect(audit.responses5xx.filter(item => item.injected !== 'controlled_refine_503')).toEqual([]);
  };
  return { owner, state, locale, copy, open, body, request, submit, suggestion, selectSecond, propose, done };
}
async function proof(page: Page, info: TestInfo, name: string) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
  await page.screenshot({ path: info.outputPath(name), animations: 'disabled' });
}

type Screen = Awaited<ReturnType<typeof setup>>;
type StoredVersion = { id: string; subject: string; body: string; [key: string]: unknown };
type StoredDraft = { subject: string; body: string; pendingEdit: string; history: StoredVersion[]; editScope: unknown; [key: string]: unknown };
type StoredRecord = { version: number; ownerId: string; opportunityId: string; revision: string; draft: StoredDraft };
const GENERATED = 'Dear Professor,\n\nThis is the controlled regenerated version C.\n\nThank you,\nRevision student 王';
async function stored(page: Page, f: Screen) {
  const records = await page.evaluate(({ prefix, uid, id }) => Object.keys(localStorage)
    .filter(key => key.includes(prefix)).flatMap(key => {
      const raw = localStorage.getItem(key)!;
      try {
        const value = JSON.parse(raw);
        return value.ownerId === uid && value.opportunityId === id && value.draft ? [{ key, raw, value }] : [];
      } catch { return []; }
    }), { prefix: STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX, uid: f.owner.session.user.id, id: ID });
  expect(records).toHaveLength(1);
  return records[0] as { key: string; raw: string; value: StoredRecord };
}
async function saved(page: Page, f: Screen) {
  await expect(page.getByTestId('cold-email-draft-status')).toContainText(f.locale === 'zh' ? '已保存' : 'Saved on this browser');
}
async function history(page: Page) {
  const panel = page.getByTestId('cold-email-history');
  await expect(panel).toBeVisible();
  const summary = panel.locator('summary');
  if (await summary.count() && await panel.getAttribute('open') === null) await summary.click();
  return panel;
}
async function card(page: Page, id: string) {
  const panel = await history(page);
  // The stable ID itself is the selector: never rely on list order or count.
  const stable = panel.locator(`[data-testid="cold-email-history-item"][data-version-id="${id}"]`);
  await expect(stable).toBeVisible(); return stable;
}
async function accept(page: Page, f: Screen, expectedBody = ACCEPTED) {
  await f.suggestion.getByRole('button', { name: f.locale === 'zh' ? '接受建议' : 'Accept suggestion', exact: true }).click();
  await expect(f.body).toHaveValue(expectedBody); await saved(page, f);
}
async function compare(page: Page, f: Screen, id: string) {
  await (await card(page, id)).getByRole('button', { name: f.locale === 'zh' ? '比较并恢复' : 'Compare and restore', exact: true }).click();
  const region = page.getByRole('region', { name: f.locale === 'zh' ? '比较邮件版本' : 'Compare email versions', exact: true });
  await expect(region).toBeVisible(); return region;
}
async function close(page: Page, f: Screen) {
  await page.getByRole('button', { name: f.copy.closeAria, exact: true }).click();
  await expect(page.getByRole('dialog', { name: f.copy.title, exact: true })).toHaveCount(0);
}
async function prepareTwoVersions(page: Page, f: Screen) {
  await f.open(); await f.propose(); await accept(page, f);
  const first = await stored(page, f);
  expect(first.value.version).toBe(2);
  expect(first.value.draft.history.map(value => value.body)).toEqual([BODY]);
  f.state.generatedBody = GENERATED;
  await page.getByRole('button', { name: f.copy.tone.warm, exact: true }).click();
  await page.getByRole('button', { name: f.copy.generateAiDraft, exact: true }).click();
  await expect(f.body).toHaveValue(GENERATED); await saved(page, f);
  const next = await stored(page, f);
  expect(next.value.draft.history.map(value => value.body).sort()).toEqual([BODY, ACCEPTED].sort());
  return next;
}

test('accept, regenerate and compare-restore preserve replaced drafts across close and reload', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    const initial = await prepareTwoVersions(page, f);
    const originalId = initial.value.draft.history.find(value => value.body === BODY)!.id;
    const region = await compare(page, f, originalId);
    await expect(region).toContainText(f.locale === 'zh' ? '当前草稿' : 'Current draft');
    await expect(region).toContainText(f.locale === 'zh' ? '已保存版本' : 'Saved version');
    await expect(region).toContainText(GENERATED); await expect(region).toContainText(BODY);
    await expect(f.body).toHaveValue(GENERATED);
    await region.getByRole('button', { name: f.locale === 'zh' ? '取消' : 'Cancel', exact: true }).click();
    await expect(f.body).toHaveValue(GENERATED);
    const active = await compare(page, f, originalId);
    await active.scrollIntoViewIfNeeded(); await proof(page, info, 'history-compare-' + f.locale + '.png');
    await active.getByRole('button', { name: f.locale === 'zh' ? '恢复此版本' : 'Restore this version', exact: true }).click();
    await expect(f.body).toHaveValue(BODY); await saved(page, f);
    const restored = await stored(page, f);
    expect(restored.value.draft.history.map(value => value.body).sort()).toEqual([BODY, ACCEPTED, GENERATED].sort());
    const ids = restored.value.draft.history.map(value => value.id).sort();
    expect(new Set(ids).size).toBe(ids.length);
    await close(page, f); await f.open(BODY, false);
    expect((await stored(page, f)).value.draft.history.map(value => value.id).sort()).toEqual(ids);
    await close(page, f); await page.reload(); await f.open(BODY, false);
    expect((await stored(page, f)).value.draft.history.map(value => value.id).sort()).toEqual(ids);
    await history(page); await proof(page, info, 'history-after-reload-' + f.locale + '.png');
  } finally { await f.done(); }
});

test('single-version deletion uses a stable ID and leaves current text and other history intact', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    const initial = await prepareTwoVersions(page, f);
    const remove = initial.value.draft.history.find(value => value.body === BODY)!.id;
    const keep = initial.value.draft.history.find(value => value.body === ACCEPTED)!.id;
    const confirmText = f.locale === 'zh' ? '删除这个历史版本？当前草稿会保留。' : 'Delete this saved version? Your current draft is kept.';
    page.once('dialog', async dialog => { expect(dialog.message()).toBe(confirmText); await dialog.dismiss(); });
    await (await card(page, remove)).getByRole('button', { name: f.locale === 'zh' ? '删除此版本' : 'Delete this version', exact: true }).click();
    expect((await stored(page, f)).value.draft.history.map(value => value.id).sort()).toEqual([remove, keep].sort());
    page.once('dialog', async dialog => { expect(dialog.message()).toBe(confirmText); await dialog.accept(); });
    await (await card(page, remove)).getByRole('button', { name: f.locale === 'zh' ? '删除此版本' : 'Delete this version', exact: true }).click();
    await saved(page, f);
    await expect.poll(async () => (await stored(page, f)).value.draft.history.map(value => value.id)).toEqual([keep]);
    await expect(f.body).toHaveValue(GENERATED);
    await close(page, f); await page.reload(); await f.open(GENERATED, false);
    expect((await stored(page, f)).value.draft.history.map(value => value.id)).toEqual([keep]);
    await history(page); await proof(page, info, 'history-delete-one-' + f.locale + '.png');
  } finally { await f.done(); }
});

test('quota failure cannot replace the editor or split current text from its history', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await f.propose(); await accept(page, f);
    f.state.refinedBody = GENERATED;
    await f.request.fill('Make the request clearer without adding claims.'); await f.submit.click();
    await expect(f.suggestion).toBeVisible(); await saved(page, f);
    const before = await stored(page, f);
    await page.evaluate(prefix => {
      const original = Storage.prototype.setItem;
      Storage.prototype.setItem = function(key, value) {
        if (key.includes(prefix)) throw new DOMException('Controlled history quota failure', 'QuotaExceededError');
        original.call(this, key, value);
      };
    }, STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX);
    await f.suggestion.getByRole('button', { name: f.locale === 'zh' ? '接受建议' : 'Accept suggestion', exact: true }).click();
    await expect(page.getByTestId('cold-email-draft-status')).toContainText(f.locale === 'zh' ? '未能保存' : 'Could not save');
    await expect(f.body).toHaveValue(ACCEPTED); await expect(f.request).toHaveValue('Make the request clearer without adding claims.');
    expect((await stored(page, f)).raw).toBe(before.raw);
    await page.getByRole('button', { name: f.copy.closeAria, exact: true }).click();
    await expect(page.getByRole('dialog', { name: f.copy.title, exact: true })).toBeVisible();
    await expect(f.body).toHaveValue(ACCEPTED);
    await page.getByTestId('cold-email-draft-status').scrollIntoViewIfNeeded(); await proof(page, info, 'history-quota-kept-' + f.locale + '.png');
  } finally { await f.done(); }
});

test('a selected request survives reopening while a legacy unknown scope requires explicit whole-body consent', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await f.selectSecond(); await f.request.fill(INSTRUCTION); await saved(page, f);
    await close(page, f); await page.reload(); await f.open(BODY, false);
    await expect(f.request).toHaveValue(INSTRUCTION);
    const recovered = (await stored(page, f)).value.draft;
    expect(recovered.editScope).toEqual({ start_utf16: START, end_utf16: END, text: REPEATED });
    await f.submit.click(); await expect(f.suggestion).toBeVisible();
    expect(f.state.refinements.at(-1)?.selection).toEqual({ start_utf16: START, end_utf16: END, text: REPEATED });
    await f.suggestion.getByRole('button', { name: f.locale === 'zh' ? '拒绝建议' : 'Reject suggestion', exact: true }).click();
    await saved(page, f); await close(page, f);
    const savedRecord = await stored(page, f);
    await page.evaluate(({ key, record }) => {
      const old = { ...record, version: 1, draft: Object.fromEntries(Object.entries(record.draft)
        .filter(([field]) => ['subject', 'body', 'manualRecipient', 'selectedStyle', 'pendingEdit', 'context', 'pendingPanel', 'sources'].includes(field))) };
      localStorage.setItem(key, JSON.stringify(old));
    }, { key: savedRecord.key, record: savedRecord.value });
    await page.reload(); await f.open(BODY, false);
    await expect(f.request).toHaveValue(INSTRUCTION); await expect(f.submit).toBeDisabled();
    const warning = page.getByTestId('cold-email-edit-scope-review'); await expect(warning).toBeVisible();
    await warning.scrollIntoViewIfNeeded(); await proof(page, info, 'history-legacy-scope-' + f.locale + '.png');
    await page.getByRole('button', { name: f.locale === 'zh' ? '改为整封' : 'Use full body', exact: true }).click();
    await expect(f.submit).toBeEnabled(); await f.submit.click(); await expect(f.suggestion).toBeVisible();
    expect(f.state.refinements.at(-1)?.selection).toBeUndefined();
    await expect(f.body).toHaveValue(BODY);
  } finally { await f.done(); }
});

test('a stale window cannot delete history or overwrite the newer window draft', async ({ page, context }, info) => {
  const f = await setup(page, info); let other: Page | undefined; let second: Screen | undefined;
  try {
    await f.open(); await f.propose(); await accept(page, f);
    const initial = await stored(page, f); const id = initial.value.draft.history[0].id;
    other = await context.newPage(); second = await setup(other, info, f.owner); await second.open(ACCEPTED);
    // Restoration may save refreshed metadata. The newly opened window is
    // therefore the latest writer; the original window is deliberately stale.
    const winner = ACCEPTED + '\nNewer window owns this new text.';
    await second.body.fill(winner); await saved(other, second);
    await expect.poll(async () => (await stored(other!, second!)).value.draft.body).toBe(winner);
    const durable = await stored(other, second);
    page.once('dialog', dialog => dialog.accept());
    await (await card(page, id)).getByRole('button', { name: f.locale === 'zh' ? '删除此版本' : 'Delete this version', exact: true }).click();
    await expect(page.getByTestId('cold-email-draft-status')).toContainText(f.locale === 'zh' ? '另一窗口' : 'Another window');
    await expect(f.body).toHaveValue(ACCEPTED);
    expect((await stored(other, second)).raw).toBe(durable.raw);
    await expect(second.body).toHaveValue(winner);
    await page.getByTestId('cold-email-draft-status').scrollIntoViewIfNeeded(); await proof(page, info, 'history-two-window-conflict-' + f.locale + '.png');
  } finally { if (second) await second.done(); if (other) await other.close(); await f.done(); }
});

test('restoring historical content keeps the current recipient and cannot restore sending authority', async ({ page }, info) => {
  const f = await setup(page, info);
  try {
    await f.open(); await page.locator('#cold-email-to').fill('old-manual@fixture.invalid');
    await f.propose(); await accept(page, f);
    const initial = await stored(page, f); const old = initial.value.draft.history[0];
    for (const key of ['recipient', 'manualRecipient', 'recipientStatus', 'context', 'pendingPanel', 'sent', 'sentAt', 'confirmed', 'reading']) expect(old).not.toHaveProperty(key);
    await page.locator('#cold-email-to').fill('current-manual@fixture.invalid'); await saved(page, f);
    const region = await compare(page, f, old.id);
    await region.getByRole('button', { name: f.locale === 'zh' ? '恢复此版本' : 'Restore this version', exact: true }).click();
    await expect(f.body).toHaveValue(BODY);
    await expect(page.locator('#cold-email-to')).toHaveValue('current-manual@fixture.invalid');
    await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
    expect(f.state.mutations).toEqual([]);
    await saved(page, f); await f.body.scrollIntoViewIfNeeded(); await proof(page, info, 'history-content-only-restore-' + f.locale + '.png');
  } finally { await f.done(); }
});
