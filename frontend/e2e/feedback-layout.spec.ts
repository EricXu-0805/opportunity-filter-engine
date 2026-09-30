import { test, expect, request as apiRequest, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { en, zh } from '../src/i18n/dictionaries';
import { contactReceiptForRequest } from './email-contact-receipt';

// Real browser interaction with the inline feedback form. Tickets, writing
// responses and private PDF HTTP are local fixtures; nothing is sent externally.
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const ORIGIN = `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3100)}`;
const TARGET = 'uiuc-siebel-ugresearch';
const EVENT = '33333333-3333-4333-8333-333333333333';
const RECORD = '33333333-3333-4333-8333-333333333334';
const MATERIAL = '33333333-3333-4333-8333-333333333335';
const TIME = '2026-09-25T11:00:00.000Z';
const TICKET = '33333333-3333-4333-8333-333333333336';
const DRAFT = 'Please keep this feedback draft. 王 <img src=x onerror=alert(1)>';
const PDF = Buffer.from('%PDF-1.4\nOriginal submitted file for the UI download fixture.\n%%EOF\n');
const HASH = createHash('sha256').update(PDF).digest('hex');
type Locale = 'en' | 'zh';
interface Owner { http: APIRequestContext; session: { access_token: string; refresh_token: string; user: { id: string; is_anonymous: boolean; email: string | null } } }
interface TicketInput { device_id: string; message: string; email: string | null; subject: string | null; category: string | null; client_token: string; props: { path: string } }
interface MaterialInput { expected_owner_id: string; opportunity_id: string; application_event_id: string; material_id: string; record_id: string; filename: string; mime_type: string; byte_length: number; bytes_sha256: string; attested: true }
const panel = (page: Page) => page.getByTestId('feedback-panel');
const copy = (locale: Locale) => (locale === 'zh' ? zh : en).feedback;
const materialCopy = en.applicationRecord.materials;
const materialPanel = (page: Page) => page.getByTestId('application-material-panel');
const materialAction = (page: Page, key: keyof typeof materialCopy) => materialPanel(page).getByRole('button', { name: materialCopy[key], exact: true });
const layouts = [
  { name: '320', width: 320, height: 760 },
  { name: '390', width: 390, height: 844 },
  { name: '768', width: 768, height: 1024 },
  { name: '1024-desktop-boundary', width: 1024, height: 768 },
  { name: 'desktop', width: 1280, height: 720 },
  { name: 'mobile-short', width: 390, height: 400 },
  { name: 'desktop-short', width: 1280, height: 360 },
  // 1280x720 at 200% exposes 640x360 CSS pixels. This checks the equivalent
  // reflow viewport; it does not claim to drive an OS browser zoom control.
  { name: '200-percent-equivalent-reflow', width: 640, height: 360 },
];

async function account(formal = false): Promise<Owner> {
  expect(new URL(STUB).hostname).toBe('127.0.0.1');
  const http = await apiRequest.newContext();
  try {
    const response = await http.post(STUB + '/auth/v1/signup', { data: {} }); expect(response.status()).toBe(200);
    const session = await response.json();
    const saved = await http.post(STUB + '/rest/v1/rpc/commit_profile_patch_cas', {
      headers: { Authorization: `Bearer ${session.access_token}` }, data: { p_expected_device_id: session.user.id, p_expected_revision: 0, p_patch: {
        name: 'Feedback layout student 王', institution: 'UIUC', home_school: 'uiuc', college: 'Grainger College of Engineering',
        major: 'Computer Science', grade: 'Sophomore', is_international: false, research_interests: 'research tools', skills: ['Python'], coursework: ['CS 225'], seeking_types: ['research'],
        resume_text: 'EXPERIENCE\n- I compared measurements with my project team.', experience_entries: [{ id: 'measurements', revision: 1, status: 'confirmed', text: 'I compared measurements with my project team.', source: { kind: 'manual' } }],
      } },
    }); expect(saved.status()).toBe(200); expect(await saved.json()).toMatchObject({ status: 'applied', revision: 1 });
    if (formal) {
      session.user = { ...session.user, is_anonymous: false, email: 'feedback-fixture@example.test', app_metadata: { provider: 'email', providers: ['email'] } };
      const parts = session.access_token.split('.'); const claims = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
      parts[1] = Buffer.from(JSON.stringify({ ...claims, is_anonymous: false })).toString('base64url'); session.access_token = parts.join('.');
    }
    return { http, session };
  } catch (error) { await http.dispose(); throw error; }
}
async function seed(page: Page, owner: Owner, locale: Locale = 'en') {
  await page.context().addCookies([{ name: STORAGE_KEYS.LOCALE, value: locale, url: ORIGIN }]);
  await page.addInitScript(({ session, keys, locale }) => {
    if (localStorage.getItem('feedback-layout-seeded')) return;
    localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, locale);
    localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('feedback-layout-seeded', '1');
  }, { session: owner.session, keys: STORAGE_KEYS, locale });
  // `next dev` pins its Dev Tools badge (<nextjs-portal>) over the bottom-left
  // corner and into the Tab order. It does not exist in the production build
  // users get, so hide it rather than let it cover the controls measured here.
  await page.addInitScript(() => document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style'); style.textContent = 'nextjs-portal { display: none !important; }'; document.head.append(style);
  }));
  await page.route('**/auth/v1/user', route => route.fulfill({ json: owner.session.user }));
  await page.route('**/auth/v1/token?grant_type=refresh_token', route => route.fulfill({ json: owner.session }));
}
function deferred() { let resolve!: () => void; return { promise: new Promise<void>(done => { resolve = done; }), resolve: () => resolve() }; }
async function ticketNetwork(page: Page, owner: Owner, options: { firstFails?: boolean; gate?: ReturnType<typeof deferred> } = {}) {
  const calls: TicketInput[] = [];
  await page.route('**/rest/v1/feedback**', async route => {
    expect(route.request().method()).toBe('POST'); const input = route.request().postDataJSON() as TicketInput;
    expect(input.device_id).toBe(owner.session.user.id); calls.push(input);
    if (options.gate) await options.gate.promise;
    if (options.firstFails && calls.length === 1) { await route.fulfill({ status: 500, json: { message: 'synthetic failure' } }); return; }
    await route.fulfill({ status: 201, json: { id: TICKET } });
  });
  return calls;
}
async function openFeedback(page: Page, locale: Locale = 'en') {
  const opener = page.getByTestId('feedback-open'); await expect(opener).toHaveAccessibleName(copy(locale).open);
  await opener.scrollIntoViewIfNeeded(); await opener.click(); await expect(panel(page)).toBeVisible();
  await expect(page.locator('#site-feedback-title')).toBeFocused();
  await expect(panel(page)).toHaveAccessibleName(copy(locale).title);
  await expect(page.getByRole('region', { name: copy(locale).title, exact: true })).toHaveCount(1);
}
async function fillFeedback(page: Page, locale: Locale = 'en') {
  await panel(page).getByRole('textbox', { name: copy(locale).messageLabel, exact: true }).fill(DRAFT);
  await page.getByTestId('feedback-subject').fill('Visible entry and clear draft handling');
  await page.getByTestId('feedback-category').selectOption('bug');
}
// The widget follows the account boundary: a form opened before the first
// identity resolves is closed when it does. Wait for this browser's owner.
async function ownerReady(page: Page, owner: Owner) {
  await expect.poll(() => page.evaluate(key => JSON.parse(localStorage.getItem(key) ?? 'null'), STORAGE_KEYS.LOCAL_IDENTITY_OWNER))
    .toMatchObject({ uid: owner.session.user.id, phase: 'ready' });
}
async function storedDraft(page: Page) {
  return page.evaluate(key => Object.entries(localStorage).filter(([name]) => name.endsWith(key)).map(([, value]) => JSON.parse(value)), STORAGE_KEYS.FEEDBACK_DRAFT);
}
async function noHorizontalOverflow(page: Page) {
  const configured = page.viewportSize(); expect(configured).not.toBeNull();
  const measured = await page.evaluate(() => ({ documentWidth: document.documentElement.scrollWidth, innerWidth, visualWidth: visualViewport?.width }));
  // Mobile innerWidth can expand to overflowing content. Compare with the
  // configured CSS viewport, not that already-expanded layout viewport.
  expect(measured.documentWidth, JSON.stringify({ configured, ...measured })).toBeLessThanOrEqual(configured!.width + 1);
}
async function inlineOnly(locator: Locator) {
  expect(await locator.evaluate(element => {
    for (let node: Element | null = element; node && node !== document.body; node = node.parentElement) {
      if (['fixed', 'sticky', 'absolute'].includes(getComputedStyle(node).position)) return false;
    }
    return true;
  })).toBe(true);
}
async function entireClickArea(locator: Locator, alignBottom = false) {
  await locator.scrollIntoViewIfNeeded();
  if (alignBottom) await locator.evaluate(element => { const r = element.getBoundingClientRect(); window.scrollTo({ top: scrollY + r.bottom - innerHeight + 12, behavior: 'instant' }); });
  await expect(locator).toBeVisible();
  const configured = locator.page().viewportSize(); expect(configured).not.toBeNull();
  const result = await locator.evaluate((element, viewport) => {
    const r = element.getBoundingClientRect(); const inset = Math.min(8, r.height / 4, r.width / 4);
    const points: Array<[number, number]> = [];
    for (const x of [r.left + inset, r.left + r.width / 4, r.left + r.width / 2, r.right - r.width / 4, r.right - inset]) {
      for (const y of [r.top + inset, r.top + r.height / 2, r.bottom - inset]) points.push([x, y]);
    }
    points.push([r.left + 1, r.top + r.height / 2], [r.right - 1, r.top + r.height / 2], [r.left + r.width / 2, r.top + 1], [r.left + r.width / 2, r.bottom - 1]);
    return { inViewport: r.left >= 0 && r.top >= 0 && r.right <= viewport!.width + 1 && r.bottom <= viewport!.height + 1,
      covered: points.filter(([x, y]) => !element.contains(document.elementFromPoint(x, y))).map(([x, y]) => ({ x, y, covering: document.elementFromPoint(x, y)?.outerHTML.slice(0, 200) })) };
  }, configured);
  expect(result.inViewport).toBe(true); expect(result.covered).toEqual([]);
}
async function reachableHeader(page: Page) {
  const header = page.getByRole('banner');
  await expect(header.locator('a').first()).toHaveAccessibleName(/\S/);
  const controls = header.getByRole('link').or(header.getByRole('button'));
  expect(await controls.count()).toBeGreaterThan(2);
  for (const control of await controls.all()) await entireClickArea(control);
}
async function clickLeftEdge(locator: Locator) { const box = await locator.boundingBox(); expect(box).not.toBeNull(); await locator.click({ position: { x: 8, y: box!.height / 2 } }); }

async function writingNetwork(page: Page) {
  await page.route('**/api/cold-email**', route => route.fulfill({ status: 503, json: {} }));
  await page.route('**/api/cold-email/variants', route => {
    const input = route.request().postDataJSON(); const receipt = contactReceiptForRequest(input);
    return route.fulfill({ json: { opportunity_id: input.opportunity_id, target_version: input.expected_target_version, contact_context_receipt: receipt,
      variants: [{ id: 'feedback-modal-fixture', label: 'Checked fixture', subject: 'Research question', body: 'Dear Professor,\nI compared measurements with my project team.\nBest,\nStudent', recipient_email: 'lab@example.test', mailto_link: '', contact_context_receipt: receipt }],
      recipient_status: 'revealed', lab_type: null, pipeline_version: 'w12.8', corpus_version: 'feedback-modal-fixture' } });
  });
  await page.route('**/api/tailor/status', route => route.fulfill({ json: { ai_available: false, pipeline_version: 'w13.3' } }));
}
async function materialsNetwork(page: Page, owner: Owner) {
  let deleted = false; let pending: MaterialInput | null = null;
  const state = { downloads: 0, deletions: [] as string[], uploads: [] as MaterialInput[] };
  const ready = { version: 1, owner_id: owner.session.user.id, opportunity_id: TARGET, application_event_id: EVENT, material_id: MATERIAL, record_id: RECORD, status: 'ready', filename: 'submitted-original.pdf', mime_type: 'application/pdf', byte_length: PDF.byteLength, bytes_sha256: HASH, staged_at: TIME, archived_at: '2026-09-25T12:00:00.000Z', linked_at: '2026-09-25T12:01:00.000Z', deleted_at: null, confirmation_source: 'user_reported' };
  await page.route('**/rest/v1/application_events?**', route => route.fulfill({ json: [{ event_id: EVENT, device_id: owner.session.user.id, opportunity_id: TARGET, channel: 'web_form', destination: 'https://example.edu/application', actual_submitted_at: '2026-08-01T15:00:00.000Z', notes: null, result_note: null, next_step: null, confirmed_at: TIME, confirmation_source: 'user_reported' }] }));
  await page.route('**/rest/v1/contact_events?**', route => route.fulfill({ json: [] }));
  await page.route('**/rest/v1/interactions**', route => route.fulfill({ json: [] }));
  await page.route('**/rest/v1/interaction_status_changes?**', route => route.fulfill({ json: [] }));
  await page.route('**/api/application-materials**', async route => {
    const request = route.request(), url = new URL(request.url()), id = url.pathname.split('/')[3];
    expect(request.headers().authorization).toBe(`Bearer ${owner.session.access_token}`);
    if (request.method() === 'POST') {
      const form = await new Response(new Uint8Array(request.postDataBuffer()!).buffer, { headers: { 'Content-Type': request.headers()['content-type'] } }).formData();
      pending = JSON.parse(String(form.get('metadata'))) as MaterialInput; const file = form.get('file') as File;
      expect(pending).toMatchObject({ expected_owner_id: owner.session.user.id, opportunity_id: TARGET, application_event_id: EVENT, attested: true, bytes_sha256: HASH });
      expect(Buffer.from(await file.arrayBuffer())).toEqual(PDF); state.uploads.push(pending);
      await route.fulfill({ status: 503, json: { detail: { code: 'material_unavailable' } } }); return;
    }
    if (request.method() === 'DELETE') {
      expect(request.postDataJSON()).toEqual({ expected_owner_id: owner.session.user.id, opportunity_id: TARGET, application_event_id: EVENT, material_id: id === RECORD ? MATERIAL : pending!.material_id });
      state.deletions.push(id); if (id === RECORD) deleted = true;
      await route.fulfill({ json: { version: 1, record: { ...ready, record_id: id, material_id: id === RECORD ? MATERIAL : pending!.material_id, status: 'deleted', filename: null, mime_type: null, byte_length: null, bytes_sha256: null, archived_at: id === RECORD ? ready.archived_at : null, linked_at: id === RECORD ? ready.linked_at : null, deleted_at: '2026-09-25T13:00:00.000Z' } } }); return;
    }
    expect(request.method()).toBe('GET'); expect(url.searchParams.get('expected_owner_id')).toBe(owner.session.user.id);
    expect(url.searchParams.get('opportunity_id')).toBe(TARGET); expect(url.searchParams.get('application_event_id')).toBe(EVENT);
    if (url.pathname.endsWith('/file')) { expect(id).toBe(RECORD); expect(deleted).toBe(false); state.downloads += 1; await route.fulfill({ body: PDF, headers: { 'content-type': 'application/pdf', 'x-ofe-material-id': MATERIAL, 'x-ofe-material-record': RECORD, 'x-ofe-material-sha256': HASH } }); return; }
    expect(id).toBeUndefined(); await route.fulfill({ json: { version: 1, items: deleted ? [{ ...ready, status: 'deleted', filename: null, mime_type: null, byte_length: null, bytes_sha256: null, deleted_at: '2026-09-25T13:00:00.000Z' }] : [ready], next_cursor: null } });
  }); return state;
}
async function openMaterials(page: Page) {
  await page.getByRole('button', { name: new RegExp('^' + en.detail.tracker.addButton) }).click();
  await page.getByTestId('application-history').locator('ol > li > details > summary').first().click();
  await page.getByRole('button', { name: materialCopy.open, exact: true }).click(); await expect(materialAction(page, 'download')).toBeVisible();
}

test.describe('Feedback entry and neighboring controls', () => {
  const errors = new WeakMap<Page, string[]>();
  test.beforeEach(async ({ page }) => { const current: string[] = []; errors.set(page, current); page.on('pageerror', error => current.push(error.message)); });
  test.afterEach(async ({ page }) => { expect(errors.get(page), 'Unexpected page errors, including hydration').toEqual([]); });

  for (const layout of layouts) test(`inline footer and reachable controls at ${layout.name}`, async ({ page }, info) => {
    const owner = await account();
    try {
      await page.setViewportSize({ width: layout.width, height: layout.height }); await seed(page, owner); await page.goto('/about'); await reachableHeader(page);
      const opener = page.getByTestId('feedback-open'); await expect(page.locator('footer').getByTestId('feedback-open')).toHaveCount(1);
      await expect(panel(page)).toHaveCount(0); await inlineOnly(opener);
      if (layout.width < 1024) {
        await page.getByTestId('mobile-nav-toggle').click(); await reachableHeader(page); await page.screenshot({ path: info.outputPath(`navigation-${layout.name}.png`) }); const link = page.getByTestId('mobile-feedback-link'); await expect(link).toHaveAttribute('href', '#site-feedback');
        await link.click(); await expect(page.getByTestId('mobile-nav-toggle')).toHaveAttribute('aria-expanded', 'false');
        await expect(page.locator('#site-feedback-title')).toBeFocused();
      } else await openFeedback(page);
      await expect(panel(page)).toHaveCount(1); await inlineOnly(panel(page)); await fillFeedback(page);
      for (const control of [page.getByTestId('feedback-category'), page.getByTestId('feedback-subject'), panel(page).getByRole('textbox', { name: en.feedback.messageLabel }), page.getByTestId('feedback-email'), page.getByTestId('feedback-send')]) await entireClickArea(control);
      await noHorizontalOverflow(page); expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).not.toBe('hidden');
      await page.screenshot({ path: info.outputPath(`feedback-${layout.name}.png`) });
      await panel(page).getByRole('textbox', { name: en.feedback.messageLabel }).focus(); await page.keyboard.press('Escape');
      await expect(panel(page)).toHaveCount(0); await expect(opener).toBeFocused(); await entireClickArea(opener);
    } finally { await owner.http.dispose(); }
  });

  test('keyboard entry, outside Escape, close and reload retain one exact draft', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); await page.goto('/about'); await ownerReady(page, owner);
      const opener = page.getByTestId('feedback-open'); await opener.focus(); await page.keyboard.press('Enter');
      await expect(page.locator('#site-feedback-title')).toBeFocused(); await page.keyboard.press('Tab');
      expect(await panel(page).evaluate(element => element.contains(document.activeElement))).toBe(true); await fillFeedback(page);
      await expect.poll(async () => (await storedDraft(page))[0]?.message).toBe(DRAFT); const before = await storedDraft(page); expect(before).toHaveLength(1); expect(before[0].clientToken).toBeTruthy();
      await page.locator('footer a[href="/privacy"]').focus(); await page.keyboard.press('Escape'); await expect(panel(page)).toBeVisible();
      await panel(page).getByRole('button', { name: en.feedback.close, exact: true }).click(); await expect(opener).toBeFocused();
      await openFeedback(page); await expect(panel(page).getByRole('textbox', { name: en.feedback.messageLabel })).toHaveValue(DRAFT);
      // After reload the marker is already ready while the page's own identity is
      // still resolving, so retry the open until the restored draft is shown.
      await page.reload(); await expect(async () => {
        await openFeedback(page); await expect(page.getByTestId('feedback-subject')).toHaveValue(before[0].subject, { timeout: 1_000 });
      }).toPass(); await expect(page.getByTestId('feedback-category')).toHaveValue('bug');
      expect(await storedDraft(page)).toEqual(before); await expect(panel(page).locator('img')).toHaveCount(0);
    } finally { await owner.http.dispose(); }
  });

  test('mobile link refocuses an open form without resetting draft or in-flight send', async ({ page }) => {
    const owner = await account(), gate = deferred();
    try {
      await page.setViewportSize({ width: 390, height: 844 }); await seed(page, owner); const calls = await ticketNetwork(page, owner, { gate }); await page.goto('/about');
      await openFeedback(page); await fillFeedback(page); await page.getByTestId('feedback-send').click(); await expect.poll(() => calls.length).toBe(1); await expect(page.getByTestId('feedback-send')).toBeDisabled();
      await page.getByTestId('mobile-nav-toggle').click(); await page.getByTestId('mobile-feedback-link').click();
      await expect(page.locator('#site-feedback-title')).toBeFocused(); await expect(panel(page).getByRole('textbox', { name: en.feedback.messageLabel })).toHaveValue(DRAFT);
      await expect(page.getByTestId('feedback-send')).toBeDisabled(); expect(calls).toHaveLength(1);
      gate.resolve(); await expect(page.getByTestId('feedback-thanks')).toBeVisible(); await expect.poll(() => storedDraft(page)).toEqual([]);
    } finally { gate.resolve(); await owner.http.dispose(); }
  });

  test('a failed submission keeps the same draft and retry token until confirmed', async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); const calls = await ticketNetwork(page, owner, { firstFails: true }); await page.goto('/about'); await openFeedback(page); await fillFeedback(page);
      await page.getByTestId('feedback-send').click(); await expect(page.getByTestId('feedback-error')).toHaveText(en.feedback.error); expect(calls).toHaveLength(1);
      await page.getByTestId('feedback-subject').press('Escape'); await openFeedback(page); await expect(panel(page).getByRole('textbox', { name: en.feedback.messageLabel })).toHaveValue(DRAFT);
      await page.getByTestId('feedback-send').click(); await expect(page.getByTestId('feedback-thanks')).toBeVisible(); expect(calls).toHaveLength(2);
      expect(calls[1]).toEqual(calls[0]); expect(calls[1]).toMatchObject({ message: DRAFT, category: 'bug', props: { path: '/about' } }); await expect.poll(() => storedDraft(page)).toEqual([]);
    } finally { await owner.http.dispose(); }
  });

  test('Chinese mobile entry and form remain labeled without hydration errors', async ({ page }, info) => {
    const owner = await account();
    try {
      await page.setViewportSize({ width: 320, height: 760 }); await seed(page, owner, 'zh'); await page.goto('/about'); await reachableHeader(page);
      await page.getByTestId('mobile-nav-toggle').click(); await expect(page.getByTestId('mobile-feedback-link')).toHaveText(zh.feedback.button); await page.getByTestId('mobile-feedback-link').click();
      await expect(panel(page)).toHaveAccessibleName(zh.feedback.title); await expect(page.locator('#site-feedback-title')).toBeFocused(); await fillFeedback(page, 'zh');
      await entireClickArea(page.getByTestId('feedback-send')); await noHorizontalOverflow(page); await page.screenshot({ path: info.outputPath('feedback-zh-320.png') });
      await page.getByTestId('feedback-subject').press('Escape'); await expect(page.getByTestId('feedback-open')).toBeFocused(); await openFeedback(page, 'zh');
      await expect(panel(page).getByRole('textbox', { name: zh.feedback.messageLabel })).toHaveValue(DRAFT);
    } finally { await owner.http.dispose(); }
  });

  for (const modal of ['cold-email', 'tailor', 'auth'] as const) test(`${modal} Escape leaves inline feedback and its draft intact`, async ({ page }) => {
    const owner = await account();
    try {
      await seed(page, owner); await writingNetwork(page); await page.goto(`/opportunities/${TARGET}`); await openFeedback(page); await fillFeedback(page);
      if (modal === 'cold-email') {
        await page.getByRole('button', { name: 'Draft email', exact: true }).click(); await expect(page.locator('#cold-email-body')).toBeEditable(); await page.locator('#cold-email-body').focus();
      } else if (modal === 'tailor') {
        await page.getByRole('button', { name: en.card.tailorResume, exact: true }).click(); await expect(page.locator('#tailor-bullets-input')).toBeEditable(); await page.locator('#tailor-bullets-input').focus();
      } else {
        await page.getByTestId('account-menu').filter({ visible: true }).click(); await expect(page.getByRole('dialog')).toBeVisible();
        await page.getByRole('dialog').getByRole('textbox', { name: en.auth.modal.signin.emailLabel, exact: true }).focus();
      }
      await expect(page.getByRole('dialog')).toHaveCount(1); await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(panel(page)).toBeVisible(); await expect(panel(page).getByRole('textbox', { name: en.feedback.messageLabel })).toHaveValue(DRAFT);
      await page.getByTestId('feedback-subject').press('Escape'); await expect(panel(page)).toHaveCount(0); await expect(page.getByTestId('feedback-open')).toBeFocused();
    } finally { await owner.http.dispose(); }
  });

  for (const layout of layouts) test(`PDF download, keep and confirmation full click areas at ${layout.name}`, async ({ page }, info) => {
    const owner = await account(true);
    try {
      await page.setViewportSize({ width: layout.width, height: layout.height }); await seed(page, owner); const net = await materialsNetwork(page, owner); await page.goto(`/opportunities/${TARGET}`);
      await openFeedback(page); await fillFeedback(page); await openMaterials(page);
      await entireClickArea(materialAction(page, 'download'), true); await page.screenshot({ path: info.outputPath(`download-${layout.name}.png`) });
      const downloadPromise = page.waitForEvent('download'); await clickLeftEdge(materialAction(page, 'download')); const download = await downloadPromise;
      const path = info.outputPath('downloaded-original.pdf'); await download.saveAs(path); expect(download.suggestedFilename()).toBe('submitted-original.pdf'); expect(await readFile(path)).toEqual(PDF); expect(net.downloads).toBe(1);
      await materialPanel(page).getByLabel(materialCopy.fileLabel, { exact: true }).setInputFiles({ name: 'pending-upload.pdf', mimeType: 'application/pdf', buffer: PDF });
      await materialPanel(page).getByRole('checkbox', { name: materialCopy.attestation, exact: true }).check(); await materialAction(page, 'save').click(); await expect(materialPanel(page).getByRole('alert')).toHaveText(materialCopy.unavailable); expect(net.uploads).toHaveLength(1);
      await materialAction(page, 'cancelUpload').click(); await entireClickArea(materialAction(page, 'keepUpload'), true); await entireClickArea(materialAction(page, 'confirmCancelUpload'), true);
      await page.screenshot({ path: info.outputPath(`cancel-${layout.name}.png`) }); await clickLeftEdge(materialAction(page, 'keepUpload')); expect(net.deletions).toHaveLength(0);
      await expect(materialPanel(page).getByTestId('application-material-pending')).toBeVisible(); await materialAction(page, 'cancelUpload').click(); await entireClickArea(materialAction(page, 'confirmCancelUpload'), true); await clickLeftEdge(materialAction(page, 'confirmCancelUpload'));
      await expect(materialPanel(page)).toContainText(materialCopy.cancelled); expect(net.deletions).toEqual([net.uploads[0].record_id]);
      await materialAction(page, 'delete').click(); await entireClickArea(materialAction(page, 'cancel'), true); await entireClickArea(materialAction(page, 'confirmDelete'), true); await clickLeftEdge(materialAction(page, 'cancel')); expect(net.deletions).toHaveLength(1);
      await materialAction(page, 'delete').click(); await entireClickArea(materialAction(page, 'confirmDelete'), true); await clickLeftEdge(materialAction(page, 'confirmDelete'));
      await expect(materialPanel(page).getByTestId('application-material-record')).toContainText(materialCopy.deleted); await expect(materialAction(page, 'download')).toHaveCount(0); expect(net.deletions).toEqual([net.uploads[0].record_id, RECORD]);
      await expect(panel(page).getByRole('textbox', { name: en.feedback.messageLabel })).toHaveValue(DRAFT); await noHorizontalOverflow(page);
    } finally { await owner.http.dispose(); }
  });
});
