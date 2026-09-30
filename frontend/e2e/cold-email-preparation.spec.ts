import { test, expect, request as apiRequest, type APIRequestContext, type Page, type Request, type TestInfo } from '@playwright/test';
import { researchFixture, RESEARCH_TITLE, RESEARCH_ABSTRACT } from './research-fixture';
import type { ResearchContext } from '../src/lib/research-context';
import type { LabContext } from '../src/lib/lab-context';
import labGolden from '../../tests/fixtures/lab-context-v1-golden.json';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { contactReceiptForRequest } from './email-contact-receipt';
import type { ContactInstructions } from '../src/lib/contact-instructions';
import type { EmailContactContext } from '../src/lib/types';

// Loopback production UI + real local auth/profile CAS. Source snapshots and
// writing results are controlled. All composer windows are inert JS objects.
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const ID = 'uiuc-siebel-ugresearch';
const V1 = `wt1:${'d'.repeat(64)}`, V2 = `wt1:${'e'.repeat(64)}`;
const BODY = 'Controlled draft: I measured samples; the team designed the study. 王';
const PAPER = 'Verified sensor study';
const rule = { quote: 'Official contact instructions for applicants.', source_url: 'https://example.edu/lab', checked_at: '2026-09-25T00:00:00Z' };
const policy = (rules: ContactInstructions['rules'], email_policy: ContactInstructions['email_policy'] = 'allowed'): ContactInstructions => ({ version: 1, status: email_policy === 'conflicting' ? 'conflicting' : 'known', email_policy, rules });
const pathOf = (url: string) => new URL(url).pathname;
interface Call { path: string; opportunity_id: string; expected_target_version: string; contact_context: EmailContactContext; experience_evidence: { entries: { text: string }[] } }
type Validation = Omit<Call, 'path'> & { subject: string; body: string };
interface Fixture { http: APIRequestContext; session: { access_token: string; refresh_token: string; user: { id: string; is_anonymous: boolean; email: string; app_metadata: Record<string, unknown> } } }
const fact = (id: string, value: string) => ({ id, revision: 1, status: 'confirmed', value, source: { kind: 'manual' } });
async function account(): Promise<Fixture> {
  expect(new URL(STUB).hostname).toBe('127.0.0.1'); const http = await apiRequest.newContext();
  try {
    const result = await http.post(`${STUB}/auth/v1/signup`, { data: {} }); expect(result.status()).toBe(200); const session = await result.json();
    // Formal SDK state is required for the independent address-reveal read.
    session.user = { ...session.user, is_anonymous: false, email: 'preparation@fixture.invalid', app_metadata: { provider: 'email', providers: ['email'] } };
    const token = session.access_token.split('.'); const claims = JSON.parse(Buffer.from(token[1], 'base64url').toString());
    token[1] = Buffer.from(JSON.stringify({ ...claims, is_anonymous: false })).toString('base64url'); session.access_token = token.join('.');
    const headers = { Authorization: `Bearer ${session.access_token}` };
    const saved = await http.post(`${STUB}/rest/v1/rpc/commit_profile_patch_cas`, { headers, data: { p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: {
      name: 'Preparation student 王', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Sophomore',
      is_international: false, research_interests: 'sensors', seeking_types: ['research'], skills: [], coursework: [], resume_text: 'Original complete source 王', experience_entries: [],
      resume_master: { version: 1, id: 'email-master', revision: 1, source_signature: null,
        basics: { name: fact('name', 'Preparation student 王'), links: [] }, education: [],
        activities: [{ id: 'project-1', kind: 'project', title: fact('project-title', 'Instrument project'), details: [] }],
        publications: [], skills: [], other_sections: [], section_order: ['basics', 'education', 'activities', 'publications', 'skills'], unmapped_ranges: [] },
    } } }); expect(saved.status()).toBe(200); expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1 });
    const favorite = await http.post(`${STUB}/rest/v1/favorites`, { headers, data: { device_id: session.user.id, opportunity_id: ID } }); expect(favorite.status()).toBe(201);
    return { http, session };
  } catch (error) { await http.dispose(); throw error; }
}
function audit(page: Page) {
  const injected = new Set<Request>(); const state = { pageErrors: [] as string[], console: [] as string[], external: [] as string[], unexpected5xx: [] as string[], injected5xx: [] as string[] };
  page.on('pageerror', error => state.pageErrors.push(error.message)); page.on('console', entry => { if (entry.type() === 'error') state.console.push(entry.text()); });
  page.on('request', request => { const url = new URL(request.url()); if (url.protocol.startsWith('http') && !['127.0.0.1', 'localhost'].includes(url.hostname)) state.external.push(request.url()); });
  page.on('response', response => { if (response.status() >= 500) (injected.has(response.request()) ? state.injected5xx : state.unexpected5xx).push(`${response.status()} ${response.url()}`); });
  return { state, injected };
}
async function setup(page: Page, info: TestInfo, locale: 'en' | 'zh' = 'en') {
  const owner = await account(); const checks = audit(page);
  const state = { instructions: { version: 1, status: 'unknown', email_policy: 'unknown', rules: [] } as ContactInstructions,
    version: V1, email: 'lab@example.edu', emailStatus: 'revealed', calls: [] as Call[], detailReads: 0,
    hold: false, held: false, lateServed: 0, readingError: false, papers: true, blocked: false, research: undefined as ResearchContext | undefined, lab: undefined as LabContext | undefined,
    validations: [] as { subject: string; body: string }[] };
  let release!: () => void; const gate = new Promise<void>(r => { release = r; });
  await page.addInitScript(({ session, keys, locale }) => {
    if (!localStorage.getItem('email-preparation-seeded')) { localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, locale); localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('email-preparation-seeded', '1'); }
    (window as unknown as { __nativeEmailOpen: typeof window.open }).__nativeEmailOpen = window.open.bind(window);
    const state = { blocked: false, windows: [] as { closed: boolean; location: { href: string }; opener: unknown; close: () => void }[] };
    (window as unknown as { __emailCompose: typeof state }).__emailCompose = state;
    window.open = (() => { if (state.blocked) return null; const item = { closed: false, location: { href: 'about:blank' }, opener: null, close() { this.closed = true; } }; state.windows.push(item); return item as unknown as Window; });
  }, { session: owner.session, keys: STORAGE_KEYS, locale });
  await page.route('**/auth/v1/user', route => route.fulfill({ json: owner.session.user }));
  await page.route('**/auth/v1/token?grant_type=refresh_token', route => {
    expect(route.request().postDataJSON().refresh_token).toBe(owner.session.refresh_token);
    return route.fulfill({ json: owner.session });
  });
  await page.route(`**/api/opportunities/${ID}**`, async route => {
    state.detailReads++; const late = state.hold && !route.request().headers().authorization; if (late) { state.held = true; await gate; }
    const response = await route.fetch({ maxRetries: 0 }); expect(response.status()).toBe(200); const value = await response.json();
    value.writing_target_version = state.version; value.contact_instructions = state.instructions;
    if (state.research) value.research_context = state.research;
    if (state.lab) value.lab_context = state.lab;
    value.metadata.publication_attribution_status = 'verified_author_id'; value.metadata.recent_works = state.papers ? [{ title: PAPER, year: 2025 }] : [];
    if (route.request().headers().authorization) { value.contact_email_status = state.emailStatus; if (state.emailStatus === 'revealed') value.contact_email = state.email; else delete value.contact_email; }
    await route.fulfill({ response, json: value }); if (late) state.lateServed++;
  });
  await page.route('**/api/cold-email**', async route => {
    const request = route.request(), path = pathOf(request.url()), payload = request.postDataJSON() as Call; state.calls.push({ ...payload, path });
    expect(payload.opportunity_id).toBe(ID); expect(payload.expected_target_version).toBe(state.version);
    if (state.readingError && path === '/api/cold-email/refine') { await route.fulfill({ status: 422, json: { detail: { code: 'EMAIL_READING_CHANGED', message: 'private source diagnostic', retryable: false } } }); return; }
    const bound = { opportunity_id: ID, target_version: payload.expected_target_version, contact_context_receipt: contactReceiptForRequest(payload) };
    const draft = { ...bound, subject: 'Initial subject', body: BODY, recipient_email: 'lab@example.edu', recipient_status: 'revealed', mailto_link: '', method: 'template', pipeline_version: 'b38-controlled', corpus_version: 'b38-controlled' };
    if (path.endsWith('/variants')) { await route.fulfill({ json: { ...draft, variants: [{ ...draft, id: 'controlled', label: 'Controlled' }] } }); return; }
    if (path.endsWith('/stream')) { await route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ ...draft, stage: 'done' })}\n\n` }); return; }
    if (path.endsWith('/refine')) { await route.fulfill({ json: { ...bound, body: BODY, method: 'llm' } }); return; }
    throw new Error('Unexpected writing request ' + path);
  });
  // Registered after the writing stub so it answers /validate first. The provider-free pre-send check
  // must run against this spec's controlled target version, which the real backend would reject, so it
  // is answered here in the backend's receipt shape; each test asserts which exact text it checked.
  await page.route('**/api/cold-email/validate', async route => {
    const payload = route.request().postDataJSON() as Validation; state.validations.push({ subject: payload.subject, body: payload.body });
    expect(payload.opportunity_id).toBe(ID); expect(payload.expected_target_version).toBe(state.version);
    await route.fulfill({ json: { opportunity_id: ID, target_version: payload.expected_target_version, pipeline_version: 'b38-controlled',
      contact_context_receipt: contactReceiptForRequest(payload), target_conditions: { version: 1, record_kind: 'faculty_contact', conditions: [], template_request: null },
      outcome: 'ready', issues: [] } });
  });
  // The E2E backend has no Supabase service key, so the saved private-import list that /favorites loads
  // would answer 503. This spec does not test private imports: serve the real empty list for this owner only.
  await page.route(url => url.pathname === '/api/private-import-targets', route => {
    const request = route.request(); if (request.method() !== 'GET') return route.fallback();
    expect(new URL(request.url()).searchParams.get('expected_owner_id')).toBe(owner.session.user.id);
    expect(request.headers().authorization).toBe(`Bearer ${owner.session.access_token}`);
    return route.fulfill({ json: { version: 1, items: [], next_cursor: null } });
  });
  const mutations: string[] = []; page.on('request', request => { if (request.method() !== 'GET' && /confirm_contact_event|commit_profile_patch_cas/.test(request.url())) mutations.push(pathOf(request.url())); });
  const open = async () => { await page.goto('/favorites'); await page.getByRole('button', { name: locale === 'zh' ? '起草邮件' : 'Draft Email', exact: true }).click(); };
  const ready = async () => { await expect(page.locator('#cold-email-body')).toHaveValue(BODY); await expect.poll(() => state.calls.filter(call => call.path.endsWith('/stream')).length).toBe(1); await expect(page.getByRole('button', { name: 'Gmail', exact: true })).toBeEnabled(); };
  const done = async () => { release(); await info.attach('network-audit', { body: JSON.stringify(checks.state, null, 2), contentType: 'application/json' }); await owner.http.dispose(); expect(checks.state.pageErrors).toEqual([]); expect(checks.state.external).toEqual([]); expect(checks.state.unexpected5xx).toEqual([]); };
  return { state, checks, open, ready, release, done, mutations, owner };
}
const composer = (page: Page) => page.getByRole('button', { name: 'Gmail', exact: true });
const windows = (page: Page) => page.evaluate(() => (window as unknown as { __emailCompose: { windows: { closed: boolean; location: { href: string } }[] } }).__emailCompose.windows.map(item => ({ closed: item.closed, url: item.location.href })));
const expandRules = async (page: Page) => { const details = page.getByTestId('contact-instructions').locator('..'); if (await details.getAttribute('open') === null) await details.locator('summary').click(); };
async function screenProof(page: Page, info: TestInfo, name: string) { expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true); await page.screenshot({ path: info.outputPath(name), fullPage: false, animations: 'disabled' }); }

async function readingLayout(page: Page, info: TestInfo, locale: 'en' | 'zh') {
  const name = locale === 'zh' ? '我确认自己对这篇论文的阅读程度。' : 'I confirm this reading level for the selected paper.';
  const checkbox = page.getByRole('checkbox', { name, exact: true });
  const shape = await checkbox.evaluate(input => {
    const label = input.closest('label')!, text = label.querySelector('span')!;
    const a = input.getBoundingClientRect(), b = text.getBoundingClientRect(), c = label.getBoundingClientRect();
    return { checkboxWidth: a.width, checkboxHeight: a.height, textWidth: b.width, textHeight: b.height, contained: b.right <= c.right + 1, viewport: innerWidth };
  });
  await info.attach('reading-confirmation-layout-' + locale, { body: JSON.stringify(shape, null, 2), contentType: 'application/json' });
  expect(shape.checkboxWidth).toBeGreaterThanOrEqual(12); expect(shape.checkboxWidth).toBeLessThanOrEqual(22);
  expect(shape.checkboxHeight).toBeLessThanOrEqual(22); expect(shape.textWidth).toBeGreaterThanOrEqual(100);
  expect(shape.textHeight).toBeLessThan(120); expect(shape.contained).toBe(true);
  await checkbox.scrollIntoViewIfNeeded(); await checkbox.click(); await expect(checkbox).toBeChecked();
}

for (const blocked of ['not_accepted', 'form_only', 'conflicting'] as const) test('official ' + blocked + ' instructions prevent generation', async ({ page }, info) => {
  const f = await setup(page, info); try { f.state.instructions = policy([{ ...rule, kind: blocked === 'not_accepted' ? 'no_email' : 'form_only' }], blocked); await f.open(); await expect(page.getByTestId('contact-instructions')).toBeVisible(); await expect(page.getByRole('status').filter({ hasText: /source|sources/ }).first()).toBeVisible(); expect(f.state.calls).toEqual([]); expect(f.mutations).toEqual([]); await screenProof(page, info, blocked + '.png'); } finally { await f.done(); }
});

test('exact subject and material instructions preserve the manual body; composer is still not a send', async ({ page }, info) => {
  const f = await setup(page, info); try { f.state.instructions = policy([{ ...rule, kind: 'subject', subject: 'Research application' }, { ...rule, kind: 'materials', materials: ['resume_cv', 'unofficial_transcript'] }]); await f.open(); await expect(page.locator('#cold-email-body')).toHaveValue(BODY); await expect(composer(page)).toBeDisabled();
    await page.locator('#cold-email-body').fill('Kept complete manual draft 王'); await expandRules(page); await page.getByRole('button', { name: 'Use this subject', exact: true }).click(); await expect(page.locator('#cold-email-subject')).toHaveValue('Research application'); await expect(page.locator('#cold-email-body')).toHaveValue('Kept complete manual draft 王');
    await expect(page.getByText('Preparing a draft does not attach files or submit an application.')).toBeVisible(); await composer(page).click(); await expect.poll(async () => (await windows(page))[0]?.url).toContain('mail.google.com'); expect(f.state.validations).toEqual([{ subject: 'Research application', body: 'Kept complete manual draft 王' }]); expect(f.mutations).toEqual([]); await screenProof(page, info, 'subject-materials-composer.png');
  } finally { await f.done(); }
});

test('Chinese subject format needs manual completion and confirmation; editing revokes it', async ({ page }, info) => {
  if (info.project.name === 'mobile-chrome') await page.setViewportSize({ width: 320, height: 568 });
  const f = await setup(page, info, 'zh'); try { f.state.instructions = policy([{ ...rule, kind: 'subject', subject_template: 'APOCROP-[LastName]' }]); await f.open(); await expect(page.locator('#cold-email-body')).toHaveValue(BODY); await expandRules(page);
    const confirm = page.getByRole('checkbox', { name: '我已按来源格式填写主题，并核对无误。' }); await page.locator('#cold-email-subject').fill('APOCROP-[LastName]'); await confirm.check(); await expect(composer(page)).toBeDisabled();
    await page.locator('#cold-email-subject').fill('APOCROP-Xu'); await expect(confirm).not.toBeChecked(); await confirm.check(); await expect(composer(page)).toBeEnabled();
    await page.locator('#cold-email-subject').focus(); await page.keyboard.press('End'); await page.keyboard.type(' revised'); await expect(confirm).not.toBeChecked(); await expect(composer(page)).toBeDisabled(); expect(f.mutations).toEqual([]); await screenProof(page, info, 'zh-subject-format-keyboard.png');
    await page.getByTestId('contact-instructions').locator('..').locator('summary').click();
    const background = page.getByTestId('email-contact-context-panel'); await background.locator('summary').click();
    await background.getByLabel('你看过的论文（选填）', { exact: true }).selectOption(JSON.stringify([PAPER, 2025]));
    await background.getByLabel('你读到了哪一步？', { exact: true }).selectOption('title_only');
    await readingLayout(page, info, 'zh');
    await background.getByLabel('你读到了哪一步？', { exact: true }).scrollIntoViewIfNeeded(); await screenProof(page, info, 'zh-reading-level.png');
    await background.locator('summary').click();
    const contribution = page.getByTestId('cold-email-supplement'); await contribution.locator('summary').click();
    await page.getByTestId('resume-supplement-panel').getByLabel('你本人具体做了什么？', { exact: true }).fill('本人负责测量样本，团队设计实验。');
    await screenProof(page, info, 'zh-personal-contribution.png'); await contribution.locator('summary').click();
    const request = page.getByRole('textbox', { name: '输入修改请求', exact: true }); await request.fill('保留我原来的表述');
    await request.scrollIntoViewIfNeeded(); await expect(request).toBeVisible();
    const inputGeometry = await request.evaluate(element => { const r = element.getBoundingClientRect(); const hit = document.elementFromPoint(r.left + 4, r.top + r.height / 2); return { top: r.top, bottom: r.bottom, height: r.height, innerHeight, scrollY, hit: hit?.tagName, receivesPointer: element.contains(hit), ancestors: [element.parentElement, element.closest('[data-testid="cold-email-workspace"]')].map(parent => parent ? { scrollTop: parent.scrollTop, clientHeight: parent.clientHeight, scrollHeight: parent.scrollHeight } : null) }; });
    await info.attach('request-geometry', { body: JSON.stringify(inputGeometry, null, 2), contentType: 'application/json' });
    expect(inputGeometry.top >= 0 && inputGeometry.bottom <= inputGeometry.innerHeight + 1 && inputGeometry.receivesPointer).toBe(true);
    // Chromium scrollIntoView can leave a fractional border pixel outside the viewport.
    await request.click(); await page.keyboard.press('End'); await page.keyboard.type('。');
    await expect(request).toHaveValue('保留我原来的表述。');
    await screenProof(page, info, 'zh-320-request.png');
  } finally { await f.done(); }
});

test('fresh composer reads reject a changed official policy without losing the draft', async ({ page }, info) => {
  const f = await setup(page, info); try { await f.open(); await f.ready(); await page.locator('#cold-email-body').fill('Manual retained body 王'); await page.locator('#cold-email-to').fill('chosen@example.edu'); f.state.version = V2; f.state.instructions = policy([{ ...rule, kind: 'no_email' }], 'not_accepted');
    await composer(page).click(); await expect.poll(async () => (await windows(page))[0]?.closed).toBe(true); expect((await windows(page))[0].url).toBe('about:blank'); await expect(page.locator('#cold-email-body')).toHaveValue('Manual retained body 王'); await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0); expect(f.state.validations).toEqual([]); expect(f.mutations).toEqual([]); await screenProof(page, info, 'new-policy-cancels-compose.png');
  } finally { await f.done(); }
});

test('revoked source recipient cannot open email; a user-selected address remains their choice', async ({ page }, info) => {
  const f = await setup(page, info); try { await f.open(); await f.ready(); f.state.emailStatus = 'unavailable'; await composer(page).click(); await expect(page.getByTestId('cold-email-compose-status')).toContainText('review the recipient'); expect((await windows(page))[0]).toEqual({ closed: true, url: 'about:blank' });
    await page.locator('#cold-email-to').fill('chosen@example.edu'); await composer(page).click(); await expect.poll(async () => (await windows(page))[1]?.url).toContain('chosen%40example.edu'); expect(f.state.validations.map(item => item.body)).toEqual([BODY, BODY]); expect(f.mutations).toEqual([]);
  } finally { await f.done(); }
});

test('editing during a held source check closes the blank popup and ignores its late success', async ({ page }, info) => {
  const f = await setup(page, info); try { await f.open(); await f.ready(); f.state.hold = true; await composer(page).click(); await expect.poll(() => f.state.held).toBe(true); await page.locator('#cold-email-body').fill('Newer keyboard draft 王'); f.release(); await expect.poll(() => f.state.lateServed).toBeGreaterThan(0); await expect.poll(async () => (await windows(page))[0]?.closed).toBe(true); expect((await windows(page))[0].url).toBe('about:blank'); await expect(page.getByTestId('cold-email-compose-status')).toHaveCount(0); await expect(page.locator('#cold-email-body')).toHaveValue('Newer keyboard draft 王'); expect(f.state.validations).toEqual([]); expect(f.mutations).toEqual([]);
  } finally { await f.done(); }
});

test('a blocked popup performs no fresh read and creates no contact attestation', async ({ page }, info) => {
  const f = await setup(page, info); try { await f.open(); await f.ready(); const reads = f.state.detailReads; await page.evaluate(() => { (window as unknown as { __emailCompose: { blocked: boolean } }).__emailCompose.blocked = true; }); await composer(page).click(); await expect(page.getByTestId('cold-email-compose-status')).toContainText('browser blocked'); expect(f.state.detailReads).toBe(reads); expect(await windows(page)).toEqual([]); expect(f.state.validations).toEqual([]); await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
  } finally { await f.done(); }
});

test('paper level is explicitly confirmed and transport-bound; server changes reopen background without replay', async ({ page }, info) => {
  if (info.project.name === 'mobile-chrome') await page.setViewportSize({ width: 320, height: 568 });
  const f = await setup(page, info); try { await f.open(); await f.ready(); const panel = page.getByTestId('email-contact-context-panel'); await panel.locator('summary').click(); await panel.getByLabel('Paper you looked at (optional)', { exact: true }).selectOption(JSON.stringify([PAPER, 2025])); await panel.getByLabel('How much did you read?', { exact: true }).selectOption('abstract'); await readingLayout(page, info, 'en');
    await panel.getByRole('button', { name: 'Apply background to this draft' }).click(); const before = f.state.calls.length; await expect(page.locator('#cold-email-body')).toHaveValue(BODY); expect(f.state.calls.length).toBe(before); await page.getByRole('button', { name: 'Regenerate from updated materials', exact: true }).click(); await expect.poll(() => f.state.calls.length).toBe(before + 2); expect(f.state.calls.at(-1)?.contact_context.paper_reading).toEqual({ title: PAPER, year: 2025, level: 'abstract', confirmed: true });
    await page.locator('#cold-email-body').fill('Manual preserved reading draft'); await panel.locator('summary').click(); f.state.readingError = true; await page.getByRole('button', { name: 'Shorter', exact: true }).click(); await expect(page.getByTestId('cold-email-reading-changed')).toBeVisible(); await expect(panel).toHaveAttribute('open'); await expect(panel.getByRole('checkbox', { name: 'I confirm this reading level for the selected paper.' })).not.toBeChecked(); await expect(page.locator('#cold-email-body')).toHaveValue('Manual preserved reading draft'); await expect(page.getByText('private source diagnostic')).toHaveCount(0); expect(f.mutations).toEqual([]); await panel.getByLabel('How much did you read?', { exact: true }).scrollIntoViewIfNeeded(); await screenProof(page, info, 'reading-changed-preserved-draft.png');
  } finally { await f.done(); }
});

test('confirmed personal contribution is saved once and reused only after explicit regeneration', async ({ page }, info) => {
  const f = await setup(page, info); try { await f.open(); await f.ready(); const wrapper = page.getByTestId('cold-email-supplement'); await wrapper.locator('summary').click(); const panel = page.getByTestId('resume-supplement-panel'); await panel.getByLabel('Project or experience in your master résumé', { exact: true }).selectOption('project-1');
    const own = 'I measured 12 samples; the team designed the experiment. 王'; await panel.getByLabel('What did you personally do?', { exact: true }).fill(own); await panel.getByRole('checkbox', { name: 'Include my role', exact: true }).check(); await panel.getByRole('checkbox', { name: 'I confirm the selected information is accurate.', exact: true }).check(); expect(f.mutations).toEqual([]);
    await panel.getByRole('button', { name: 'Confirm and add to my master résumé', exact: true }).click(); await expect(panel.getByText('Saved to your profile and master résumé. Your current email is kept. Generate a new draft when ready.')).toBeVisible(); await expect(page.locator('#cold-email-body')).toHaveValue(BODY); expect(f.mutations.filter(path => path.endsWith('commit_profile_patch_cas'))).toHaveLength(1); const before = f.state.calls.length;
    await page.getByRole('button', { name: 'Regenerate from updated materials', exact: true }).click(); await expect.poll(() => f.state.calls.length).toBe(before + 2); expect(f.state.calls.at(-1)?.experience_evidence.entries.some(entry => entry.text === `My role: ${own}`)).toBe(true); expect(f.mutations.some(path => path.includes('confirm_contact_event'))).toBe(false); await panel.scrollIntoViewIfNeeded(); await screenProof(page, info, 'contribution-saved-reused.png');
  } finally { await f.done(); }
});


test('native blank popup navigates only to an intercepted local compose response with no opener', async ({ page, context }, info) => {
  test.skip(info.project.name !== 'chromium', 'Native desktop popup mechanics are checked once; logical cancellation covers both viewports.');
  const f = await setup(page, info); let composeIntercepts = 0;
  try {
    await context.route('**/*', route => {
      const host = new URL(route.request().url()).hostname;
      return ['127.0.0.1', 'localhost'].includes(host) ? route.continue() : route.abort('blockedbyclient');
    });
    await context.route('https://mail.google.com/mail/**', route => {
      composeIntercepts++; return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Local compose fixture</title><p>Local intercepted composer. No email sent.</p>' });
    });
    await f.open(); await f.ready();
    await page.evaluate(() => { window.open = (window as unknown as { __nativeEmailOpen: typeof window.open }).__nativeEmailOpen; });
    const opened = page.waitForEvent('popup'); await composer(page).click(); const popup = await opened;
    await expect(popup).toHaveURL(/^https:\/\/mail\.google\.com\/mail\/\?view=cm/);
    await expect(popup.getByText('Local intercepted composer. No email sent.')).toBeVisible();
    expect(await popup.evaluate(() => window.opener === null)).toBe(true); expect(composeIntercepts).toBe(1); expect(f.state.validations.map(item => item.body)).toEqual([BODY]); expect(f.mutations).toEqual([]);
    await info.attach('native-popup-local-interception', { body: JSON.stringify({ intercepted: composeIntercepts, url: popup.url(), openerNull: true, networkFetch: false }), contentType: 'application/json' });
    await popup.close();
  } finally { await f.done(); }
});

for (const status of ['available', 'stale'] as const) test(`research ${status} keeps source text separate from the reading confirmation`, async ({ page }, info) => {
  const locale = info.project.name === 'mobile-chrome' ? 'zh' : 'en';
  const copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  if (locale === 'zh') await page.setViewportSize({ width: 390, height: 844 });
  const f = await setup(page, info, locale);
  try {
    f.state.research = researchFixture(status);
    // A stale response deliberately carries old legacy metadata as well: UI
    // must not use it to bypass the stronger research status.
    await f.open(); await f.ready();
    const panel = page.getByTestId('email-contact-context-panel'); await panel.locator(':scope > summary').click();
    const papers = panel.getByLabel(copy('Paper you looked at (optional)', '你看过的论文（选填）'), { exact: true });
    if (status === 'stale') {
      await expect(papers).toBeDisabled();
      await expect(papers.locator('option')).toHaveCount(1);
      expect(f.state.calls.every(call => !call.contact_context.paper_reading)).toBe(true);
    } else {
      await papers.selectOption({ label: RESEARCH_TITLE + ' (2025)' });
      const sourceLink = panel.getByRole('link', { name: RESEARCH_TITLE, exact: true });
      await expect(sourceLink).toHaveAttribute('href', 'https://doi.org/10.1234/synthetic-instrument-study');
      await expect(sourceLink).toHaveText(RESEARCH_TITLE);
      await expect(sourceLink).toBeVisible();
      expect(await sourceLink.getAttribute('aria-label')).toBeNull();
      const titleLayout = await sourceLink.evaluate(link => {
        const box = link.getBoundingClientRect(); const style = getComputedStyle(link);
        const range = document.createRange(); range.selectNodeContents(link);
        return { wraps: style.overflowWrap === 'anywhere', fits: link.scrollWidth <= link.clientWidth + 1,
          textFits: [...range.getClientRects()].every(rect => rect.left >= box.left - 1 && rect.right <= box.right + 1),
          inViewport: box.left >= 0 && box.right <= innerWidth + 1 };
      });
      expect(titleLayout).toEqual({ wraps: true, fits: true, textFits: true, inViewport: true });
      await panel.getByText(copy('Source abstract', '来源摘要'), { exact: true }).click();
      await expect(panel).toContainText(RESEARCH_ABSTRACT);
      const confirm = panel.getByRole('checkbox', { name: copy('I confirm this reading level for the selected paper.', '我确认自己对这篇论文的阅读程度。'), exact: true });
      await expect(confirm).not.toBeChecked();
      await panel.getByLabel(copy('How much did you read?', '你读到了哪一步？'), { exact: true }).selectOption('abstract');
      await expect(confirm).not.toBeChecked();
      const reading = page.getByTestId('email-paper-reading'); await reading.scrollIntoViewIfNeeded();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2)).toBe(true);
      await reading.screenshot({ path: info.outputPath(`research-reading-${locale}.png`), animations: 'disabled' });
      const before = f.state.calls.length;
      await confirm.check(); await panel.getByRole('button', { name: copy('Apply background to this draft', '将背景应用于草稿'), exact: true }).click();
      expect(f.state.calls.length).toBe(before);
      await page.getByRole('button', { name: copy('Regenerate from updated materials', '按最新资料和机会重新生成'), exact: true }).click();
      await expect.poll(() => f.state.calls.length).toBe(before + 2);
      expect(f.state.calls.at(-1)?.contact_context.paper_reading).toEqual({ title: RESEARCH_TITLE, year: 2025, level: 'abstract', confirmed: true,
        work_id: f.state.research.snapshot!.works[0].work_id, snapshot_version: f.state.research.snapshot!.snapshot_version });
    }
    expect(f.mutations).toEqual([]);
    await info.attach('research-reading-requests', { body: JSON.stringify({ status, calls: f.state.calls }, null, 2), contentType: 'application/json' });
  } finally { await f.done(); }
});


for (const status of ['available', 'stale'] as const) test(`website lab ${status} stays separate from reading and restored draft authority`, async ({ page }, info) => {
  const locale = info.project.name === 'mobile-chrome' ? 'zh' : 'en';
  const copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  if (locale === 'zh') await page.setViewportSize({ width: 390, height: 844 });
  const f = await setup(page, info, locale);
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    return /^https?:$/.test(url.protocol) && !['127.0.0.1', 'localhost'].includes(url.hostname)
      ? route.abort('blockedbyclient') : route.fallback();
  });
  try {
    f.state.lab = structuredClone(labGolden) as LabContext; f.state.lab.status = status;
    f.state.research = researchFixture('available');
    await f.open(); await f.ready();
    const panel = page.getByTestId('email-contact-context-panel'); await panel.locator(':scope > summary').click();
    const sources = panel.getByRole('region', { name: copy('Faculty and lab website sources', '教授与实验室官网资料'), exact: true });
    await expect(sources).toBeVisible();
    if (status === 'stale') await expect(sources).toContainText(copy('These sources are out of date', '资料已过期'));
    const papers = panel.getByLabel(copy('Paper you looked at (optional)', '你看过的论文（选填）'), { exact: true });
    await papers.selectOption({ label: RESEARCH_TITLE + ' (2025)' });
    await panel.getByLabel(copy('How much did you read?', '你读到了哪一步？'), { exact: true }).selectOption('abstract');
    const confirm = panel.getByRole('checkbox', { name: copy('I confirm this reading level for the selected paper.', '我确认自己对这篇论文的阅读程度。'), exact: true });
    const before = f.state.calls.length;
    await sources.locator('summary').click();
    const snapshot = f.state.lab.snapshot!;
    for (const section of snapshot.pages[0].sections) await expect(sources).toContainText(section.text);
    await expect(sources.getByRole('link', { name: copy('Open source page', '打开原始页面'), exact: true })).toHaveAttribute('href', snapshot.pages[0].source_url);
    await expect(confirm).not.toBeChecked(); expect(f.state.calls.length).toBe(before);
    expect(f.state.calls.every(call => !call.contact_context.paper_reading)).toBe(true);
    await sources.scrollIntoViewIfNeeded(); await screenProof(page, info, `website-lab-${status}-${locale}.png`);
    const geometry = await sources.evaluate(element => {
      const box = element.getBoundingClientRect();
      return { fits: element.scrollWidth <= element.clientWidth + 2, inViewport: box.left >= 0 && box.right <= innerWidth + 2 };
    });
    expect(geometry).toEqual({ fits: true, inViewport: true });
    await confirm.check(); await panel.getByRole('button', { name: copy('Apply background to this draft', '将背景应用于草稿'), exact: true }).click();
    expect(f.state.calls.length).toBe(before);
    await page.getByRole('button', { name: copy('Regenerate from updated materials', '按最新资料和机会重新生成'), exact: true }).click();
    await expect.poll(() => f.state.calls.length).toBe(before + 2);
    const manual = 'Handwritten draft stays complete. 官网更新不改我的原稿。🧪';
    await page.locator('#cold-email-body').fill(manual);
    await expect(page.getByTestId('cold-email-draft-status')).toContainText(copy('Saved on this browser', '已保存'));
    await page.getByRole('button', { name: copy('Close email editor', '关闭邮件编辑器'), exact: true }).click();
    await expect(page.locator('#cold-email-body')).toHaveCount(0);
    const callsBeforeReopen = f.state.calls.length;
    if (status === 'available') {
      f.state.lab.snapshot!.pages[0].sections[0].text += ' Updated source.';
      f.state.lab.snapshot!.snapshot_version = 'ls1:' + 'c'.repeat(64);
    } else f.state.lab = { version: 1, status: 'unavailable', snapshot: null };
    f.state.version = V2;
    await f.open(); await expect(page.locator('#cold-email-body')).toHaveValue(manual);
    const restoredPanel = page.getByTestId('email-contact-context-panel');
    if (await restoredPanel.getAttribute('open') === null) await restoredPanel.locator(':scope > summary').click();
    await expect(restoredPanel.getByRole('checkbox', { name: copy('I confirm this reading level for the selected paper.', '我确认自己对这篇论文的阅读程度。'), exact: true })).not.toBeChecked();
    await expect(composer(page)).toBeDisabled(); expect(await windows(page)).toEqual([]);
    expect(f.state.calls.length).toBe(callsBeforeReopen); expect(f.mutations).toEqual([]);
    await info.attach('website-lab-source-and-request-audit', { body: JSON.stringify({ status, source: snapshot, calls: f.state.calls, geometry, manualRetained: true }, null, 2), contentType: 'application/json' });
  } finally { await f.done(); }
});


test('B51 supplement draft survives close, reload and storage failure without restoring confirmation', async ({ page }, info) => {
  test.setTimeout(60_000);
  const locale = info.project.name === 'mobile-chrome' ? 'zh' : 'en';
  const copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const f = await setup(page, info, locale);
  try {
    await f.open(); await f.ready();
    const wrapper = page.getByTestId('cold-email-supplement'); await wrapper.locator(':scope > summary').click();
    const panel = page.getByTestId('resume-supplement-panel');
    const task = panel.getByLabel(copy('What was the task?', '当时要完成什么任务？'), { exact: true });
    const method = panel.getByLabel(copy('What methods or tools did you use?', '用了哪些方法或工具？'), { exact: true });
    const activity = panel.getByLabel(copy('Project or experience in your master résumé', '母版中的项目或经历'), { exact: true });
    const original = '  Exact unfinished task 王. I did not lead the team.  ';
    await activity.selectOption('project-1'); await task.fill(original); await method.fill('Unselected private method 王');
    await panel.getByRole('checkbox', { name: copy('Include task', '纳入任务'), exact: true }).check();
    await panel.getByRole('checkbox', { name: copy('I confirm the selected information is accurate.', '我确认所选内容属实。'), exact: true }).check();
    await page.locator('#cold-email-body').fill('Manual email kept 王');
    const close = page.getByRole('button', { name: copy('Close email editor', '关闭邮件编辑器'), exact: true });
    await close.click(); await expect(page.locator('#cold-email-body')).toHaveCount(0);
    await page.getByRole('button', { name: copy('Draft Email', '起草邮件'), exact: true }).click();
    await expect(task).toHaveValue(original); await expect(method).toHaveValue('Unselected private method 王'); await expect(activity).toHaveValue('project-1');
    const review = panel.getByRole('checkbox', { name: copy('I reviewed the current activity and profile, and confirm the selected information is accurate.', '我已核对当前经历和资料，确认所选内容属实。'), exact: true });
    await expect(review).not.toBeChecked(); await expect(panel.getByRole('button', {name:copy('Confirm and add to my master résumé','确认并加入简历母版'),exact:true})).toBeDisabled();
    const checkCurrent = async (confirm: boolean) => {
      const refresh = panel.getByRole('button', {name:copy('Review current materials','重新核对当前材料'),exact:true});
      // Returning profile availability deliberately asks for an explicit review, and it can republish the
      // panel as stale after it first looks settled, so settle (and confirm) inside one retry.
      await expect(async () => {
        if (await refresh.isVisible()) await refresh.click();
        await expect(activity.locator('option:checked')).toHaveText('Instrument project', { timeout: 1_000 });
        await expect(review).toBeEnabled({ timeout: 1_000 });
        if (confirm && !(await review.isChecked())) await review.check({ timeout: 1_000 });
        await expect(refresh).toBeHidden({ timeout: 500 });
        await expect(review).toBeChecked({ checked: confirm, timeout: 500 });
      }).toPass({ timeout: 15_000 });
    };
    await checkCurrent(true);
    await expect(panel.getByRole('button',{name:copy('Confirm and add to my master résumé','确认并加入简历母版'),exact:true})).toBeEnabled();
    await review.uncheck();
    expect(f.mutations).toEqual([]); await expect(page.locator('#cold-email-body')).toHaveValue('Manual email kept 王');
    await review.scrollIntoViewIfNeeded(); await screenProof(page, info, 'b51-single-confirmation-' + locale + '.png');
    await task.scrollIntoViewIfNeeded(); await screenProof(page, info, 'b51-restored-' + locale + '.png');
    const generationCount = f.state.calls.filter(call=>call.path.endsWith('/stream')).length;
    await page.reload(); await page.getByRole('button', { name: copy('Draft Email', '起草邮件'), exact: true }).click();
    await expect(task).toHaveValue(original); await expect(method).toHaveValue('Unselected private method 王'); await expect(review).not.toBeChecked();
    await checkCurrent(false);
    expect(f.state.calls.filter(call=>call.path.endsWith('/stream'))).toHaveLength(generationCount);
    await page.evaluate(prefix => {
      const original = Storage.prototype.setItem;
      (window as unknown as { __restoreB51Storage: () => void }).__restoreB51Storage = () => { Storage.prototype.setItem = original; };
      Storage.prototype.setItem = function (key: string, value: string) { if (key.includes(prefix)) throw new DOMException('Local B51 quota fixture', 'QuotaExceededError'); return original.call(this,key,value); };
    }, STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX);
    await task.fill('Latest unsaved task 王');
    await expect(page.getByTestId('cold-email-draft-status')).toContainText(copy('Could not save', '未能保存'));
    await close.click(); await expect(task).toHaveValue('Latest unsaved task 王'); await expect(method).toHaveValue('Unselected private method 王');
    await expect(page.locator('#cold-email-body')).toHaveValue('Manual email kept 王'); await expect(panel).toBeVisible();
    await task.scrollIntoViewIfNeeded(); await screenProof(page, info, 'b51-failed-close-kept-' + locale + '.png');
    await page.evaluate(() => (window as unknown as { __restoreB51Storage: () => void }).__restoreB51Storage());
    await page.getByTestId('cold-email-draft-retry').click(); await expect(page.getByTestId('cold-email-draft-status')).toContainText(copy('Saved on this browser', '已保存在此浏览器'));
    await close.click(); await expect(page.locator('#cold-email-body')).toHaveCount(0); await page.getByRole('button', { name: copy('Draft Email', '起草邮件'), exact: true }).click();
    await expect(task).toHaveValue('Latest unsaved task 王'); await expect(review).not.toBeChecked();
    page.once('dialog',dialog=>dialog.dismiss()); await panel.getByRole('button',{name:copy('Discard recovered answers and start again','放弃恢复的答案并重新补充'),exact:true}).click(); await expect(task).toHaveValue('Latest unsaved task 王');
    page.once('dialog',dialog=>dialog.accept()); await panel.getByRole('button',{name:copy('Discard recovered answers and start again','放弃恢复的答案并重新补充'),exact:true}).click(); await expect(task).toHaveValue(''); await expect(method).toHaveValue('');
    await expect(page.locator('#cold-email-body')).toHaveValue('Manual email kept 王'); expect(f.mutations).toEqual([]); expect(await windows(page)).toEqual([]);
    await info.attach('b51-supplement-proof',{body:JSON.stringify({locale,closeReopen:true,refreshRecovery:true,quotaFailureRetained:true,retryPersisted:true,confirmationRestored:false,unselectedAnswerRecovered:true,discardPreservesEmail:true,profileMutations:0,sendCalls:0,generationCount}),contentType:'application/json'});
  } finally { await f.done(); }
});
