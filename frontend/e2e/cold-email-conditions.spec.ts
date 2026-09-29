import { test, expect, request as apiRequest } from '@playwright/test';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { en, zh } from '../src/i18n/dictionaries';
import { contactReceiptForRequest } from './email-contact-receipt';
import type { EmailTargetConditions } from '../src/lib/email-target-conditions';

// Production UI, synthetic source/profile/auth data and controlled writing responses.
// No provider, external navigation, mail or tracking write is allowed.
const STUB = `http://127.0.0.1:${process.env.E2E_SUPABASE_PORT ?? 55054}`;
const FRONT = `http://127.0.0.1:${process.env.E2E_PORT ?? 3340}`;
const BACK = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT ?? 8340}`;
const ID = 'uiuc-siebel-ugresearch';
const VERSION = 'wt1:' + 'd'.repeat(64);
const BODY = 'Dear Professor,\n\nI am interested in the sensor project. Could we discuss the current application requirements?\n\nBest,\nTest student 王';
const source = { quote: 'Applicants must have a GPA of at least 3.0. A CV is required. The posted date does not establish the application deadline. Complete source ending 🧪.', source_url: 'https://example.edu/program/apply', checked_at: '2026-09-28T12:00:00Z' };
const RECEIPT: EmailTargetConditions = { version: 1, record_kind: 'listing', template_request: null, conditions: [
  { field: 'eligibility.min_gpa', category: 'eligibility', status: 'stated', value: 3.0, usage: 'usable', reason: 'source_stated', sources: [source] },
  { field: 'application.requires_resume', category: 'materials', status: 'stated', value: 'yes', usage: 'usable', reason: 'source_stated', sources: [source] },
  { field: 'eligibility.preferred_year', category: 'eligibility', status: 'unverified', value: ['freshman'], usage: 'ask_only', reason: 'unverified_legacy_value', sources: [] },
  { field: 'deadline', category: 'deadline', status: 'unverified', value: 'February 15, 5 PM', usage: 'ask_only', reason: 'unverified_legacy_value', sources: [] },
] };
function gate() { let release!: () => void; const promise = new Promise<void>(r => { release = r; }); return { promise, release }; }

test('B54 target conditions, manual review, backup, late response and restored draft', async ({ page }, info) => {
  test.setTimeout(90000);
  const locale = info.project.name === 'mobile-chrome' ? 'zh' : 'en'; const c = (locale === 'zh' ? zh : en).coldEmail;
  const pick = (english: string, chinese: string) => locale === 'zh' ? chinese : english;
  if (locale === 'zh') await page.setViewportSize({ width: 390, height: 844 });
  const http = await apiRequest.newContext();
  const response = await http.post(STUB + '/auth/v1/signup', { data: {} }); expect(response.status()).toBe(200);
  const session = await response.json(); session.user = { ...session.user, is_anonymous: false, email: 'conditions@fixture.invalid', app_metadata: { provider: 'email', providers: ['email'] } };
  const token = session.access_token.split('.'); token[1] = Buffer.from(JSON.stringify({ ...JSON.parse(Buffer.from(token[1], 'base64url').toString()), is_anonymous: false })).toString('base64url'); session.access_token = token.join('.');
  const headers = { Authorization: `Bearer ${session.access_token}` };
  const profile = { name: 'Test student 王', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Sophomore', is_international: false, research_interests: 'sensors', seeking_types: [locale === 'zh' ? 'summer' : 'internship'], skills: [], coursework: [], experience_entries: [] };
  const saved = await http.post(STUB + '/rest/v1/rpc/commit_profile_patch_cas', { headers, data: { p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: profile } }); expect(saved.status()).toBe(200);
  expect((await http.post(STUB + '/rest/v1/favorites', { headers, data: { device_id: session.user.id, opportunity_id: ID } })).status()).toBe(201);
  const state = { mode: 'ready', version: VERSION, realResponse: null as unknown, unknown: false, calls: [] as Array<{ path: string; payload: Record<string, unknown> }>, hold: null as ReturnType<typeof gate> | null };
  const audit = { external: [] as string[], errors: [] as string[], writes: [] as string[] };
  await page.context().route('**/*', route => {
    const u = new URL(route.request().url()); if (![STUB, FRONT, BACK].includes(u.origin)) { audit.external.push(u.origin); return route.abort(); }
    if (route.request().method() !== 'GET' && /\/(interactions|contact_events|confirm_contact|send)/.test(u.pathname)) { audit.writes.push(u.pathname); return route.abort(); }
    return route.continue();
  });
  page.on('pageerror', e => audit.errors.push(e.message));
  await page.context().addCookies([{ name: STORAGE_KEYS.LOCALE, value: locale, url: FRONT }]);
  await page.addInitScript(({ session, keys, locale }) => {
    if (!localStorage.getItem('b54-seeded')) { localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, locale); localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('b54-seeded', '1'); }
    const audit = { copies: [] as string[], popups: [] as Array<{ closed: boolean; location: { href: string } }>, links: [] as string[] };
    (window as unknown as { __b54: typeof audit }).__b54 = audit;
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text: string) => { audit.copies.push(text); } } });
    window.open = (() => { const popup = { closed: false, opener: null, location: { href: 'about:blank' }, close() { popup.closed = true; } }; audit.popups.push(popup); return popup as unknown as Window; });
    document.addEventListener('click', e => { const link = (e.target as Element).closest?.('a[href="https://example.edu/program/apply"]'); if (link) { e.preventDefault(); audit.links.push((link as HTMLAnchorElement).href); } });
  }, { session, keys: STORAGE_KEYS, locale });
  await page.route('**/auth/v1/user', route => route.fulfill({ json: session.user }));
  await page.route('**/auth/v1/token?grant_type=refresh_token', route => route.fulfill({ json: session }));
  const conditions = () => state.unknown ? { version: 1, record_kind: 'faculty_contact', conditions: [], template_request: null } : RECEIPT;
  await page.route(`**/api/opportunities/${ID}**`, async route => {
    const res = await route.fetch(); expect(res.status()).toBe(200); const target = await res.json();
    expect(target.writing_target_version).toMatch(/^wt1:[0-9a-f]{64}$/); state.version = target.writing_target_version; target.opportunity_type = locale === 'zh' ? 'summer' : 'internship';
    target.contact_instructions = { version: 1, status: 'unknown', email_policy: 'unknown', rules: [] }; target.target_conditions = conditions();
    if (route.request().headers().authorization) { target.contact_email_status = 'revealed'; target.contact_email = 'lab@example.edu'; }
    await route.fulfill({ response: res, json: target });
  });
  await page.route('**/api/cold-email**', async route => {
    const path = new URL(route.request().url()).pathname; const payload = route.request().postDataJSON(); state.calls.push({ path, payload });
    expect(payload.opportunity_id).toBe(ID); expect(payload.expected_target_version).toBe(state.version);
    const receipt = { opportunity_id: ID, target_version: payload.expected_target_version, contact_context_receipt: contactReceiptForRequest(payload), target_conditions: conditions() };
    const draft = { ...receipt, subject: 'Sensor project inquiry', body: BODY, recipient_email: 'lab@example.edu', recipient_status: 'revealed', mailto_link: '', method: 'template', pipeline_version: 'b54-controlled', corpus_version: 'b54-controlled' };
    if (path.endsWith('/variants')) return route.fulfill({ json: { ...draft, variants: [{ ...draft, id: 'fixture', label: 'Template' }] } });
    if (path.endsWith('/stream')) return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({ ...draft, stage: 'done' })}\n\n` });
    if (path.endsWith('/refine')) return route.fulfill({ json: { ...receipt, body: payload.current_body, method: 'none', outcome: 'no_change', reason: 'target_conditions', condition_issues: ['unsupported_eligibility_claim'] } });
    if (path.endsWith('/validate')) {
      if (state.mode === 'real') {
        const actual = await route.fetch(); expect(actual.status()).toBe(200); state.realResponse = await actual.json();
        expect(state.realResponse).toMatchObject({ opportunity_id: ID, target_version: state.version, outcome: 'ready', issues: [] });
        return route.fulfill({ response: actual });
      }
      if (state.mode === 'offline') return route.abort('internetdisconnected');
      await state.hold?.promise;
      const issues = String(payload.body).includes('attached') ? ['unsupported_attachment_claim'] : [];
      return route.fulfill({ json: { ...receipt, pipeline_version: 'b54-controlled', outcome: issues.length ? 'review_required' : 'ready', issues } });
    }
    throw new Error('Unexpected endpoint: ' + path);
  });
  const readAudit = () => page.evaluate(() => (window as unknown as { __b54: { copies: string[]; popups: { closed: boolean; location: { href: string } }[]; links: string[] } }).__b54);
  const body = page.locator('#cold-email-body'); const panel = page.getByTestId('email-target-conditions');
  const snapshot = async (name: string) => { expect(await page.evaluate(() => document.body.scrollWidth <= innerWidth)).toBe(true); await page.screenshot({ path: info.outputPath(name + '-' + locale + '.png') }); };
  try {
    await page.goto('/favorites'); await page.getByRole('button', { name: pick('Draft Email', '起草邮件'), exact: true }).click(); await expect(body).toHaveValue(BODY);
    await expect.poll(() => state.calls.filter(x => x.path.endsWith('/stream')).length).toBe(1);
    await panel.locator('summary').first().click(); await expect(panel.getByText(pick('Deadline · Not verified', '截止日期 · 尚未核对'))).toBeVisible();
    await expect(panel.getByText(pick('Required', '需要'), { exact: true })).toBeVisible();
    await expect(panel.getByText(pick('Freshman', '大一'), { exact: true })).toBeVisible();
    await panel.getByText(pick('View evidence and sources', '查看依据与来源')).first().click(); await expect(panel.getByText(source.quote).first()).toBeVisible();
    await panel.getByRole('link', { name: pick('View source', '查看来源'), exact: true }).first().click(); expect((await readAudit()).links).toEqual([source.source_url]);
    await panel.scrollIntoViewIfNeeded(); await snapshot('b54-conditions');
    await panel.locator('summary').first().click();
    const request = page.getByRole('textbox', { name: c.requestLabel, exact: true }); await request.fill('Say that I qualify'); await page.getByRole('button', { name: c.submitRequest, exact: true }).click();
    await expect(page.getByText(pick('Review claims that you meet the eligibility requirements. The current information does not support them. Your draft and request are kept.', '请核对“我已符合资格”的表述，现有资料无法支持。 原稿和修改要求已保留。'), { exact: true })).toBeVisible(); await expect(body).toHaveValue(BODY); await expect(request).toHaveValue('Say that I qualify');
    await body.fill('My CV is attached.'); await page.getByRole('button', { name: c.gmail, exact: true }).click();
    await expect(page.getByTestId('email-condition-review')).toContainText(pick('No attachment has been confirmed here.', '这里尚未确认附件'));
    expect((await readAudit()).popups.every(p => p.closed && p.location.href === 'about:blank')).toBe(true);
    await page.getByTestId('copy-draft-only').click(); expect((await readAudit()).copies.at(-1)).toBe('Subject: Sensor project inquiry\n\nMy CV is attached.'); await expect(page.getByTestId('cold-email-confirm-sent')).toHaveCount(0);
    await snapshot('b54-rejected-draft');
    await body.fill(BODY); state.mode = 'offline'; await page.getByRole('button', { name: c.copy, exact: true }).click();
    await expect(page.getByTestId('email-condition-review')).toContainText(pick('The check did not finish.', '本次核对未完成')); await expect(body).toHaveValue(BODY); await page.getByTestId('copy-draft-only').click();
    state.mode = 'ready'; await page.getByRole('button', { name: c.openInEmail, exact: true }).click(); await expect.poll(async () => (await readAudit()).popups.at(-1)?.location.href.startsWith('mailto:')).toBe(true);
    await body.fill(BODY + '\nA current manual note.'); state.hold = gate(); const count = state.calls.length;
    await page.getByRole('button', { name: c.outlook, exact: true }).click(); await expect.poll(() => state.calls.length).toBeGreaterThan(count);
    await body.fill(BODY + '\nThe newer note is kept.'); state.hold.release(); state.hold = null;
    await expect.poll(async () => (await readAudit()).popups.at(-1)?.closed).toBe(true); expect((await readAudit()).popups.at(-1)?.location.href).toBe('about:blank');
    await page.getByRole('button', { name: c.closeAria, exact: true }).click(); await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('button', { name: pick('Draft Email', '起草邮件'), exact: true }).click(); await expect(body).toHaveValue(BODY + '\nThe newer note is kept.');
    await panel.locator('summary').first().click(); await expect(panel.getByRole('link')).toHaveCount(0); await expect(panel.getByText(source.quote)).toHaveCount(0);
    await panel.scrollIntoViewIfNeeded(); await snapshot('b54-restored-unverified');
    state.unknown = true; page.once('dialog', d => d.accept()); await page.getByTestId('cold-email-draft-clear').click(); await expect(body).toHaveValue(BODY);
    await expect(panel.getByText(pick('Application conditions need review', '申请条件尚未核对'))).toBeVisible(); await expect(panel.locator('li')).toHaveCount(0);
    state.mode = 'real'; const copies = (await readAudit()).copies.length;
    await page.getByRole('button', { name: c.copy, exact: true }).click();
    await expect.poll(async () => (await readAudit()).copies.length).toBe(copies + 1); expect(state.realResponse).not.toBeNull();
    expect(audit.external).toEqual([]); expect(audit.errors).toEqual([]); expect(audit.writes).toEqual([]);
    await info.attach('b54-browser-audit', { body: JSON.stringify({ audit, calls: state.calls, browser: await readAudit(), actualValidationResponse: state.realResponse, boundary: 'Real production UI; controlled source/generation/refine and adversarial validation responses; final Copy calls the real local provider-free validation endpoint with its actual target version; no real model or send. The source link click is captured locally, not fetched.' }, null, 2), contentType: 'application/json' });
  } finally { state.hold?.release(); await http.dispose(); }
});
