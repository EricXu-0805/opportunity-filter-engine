import { test, expect, type Page, type Request, type Route } from '@playwright/test';
import { account, seed, PDF, TARGET, type Owner } from './contact-materials-fixture';
import { en, zh } from '../src/i18n/dictionaries';

// Real production UI/SDK, scoped loopback Storage responses. Real Storage is
// exercised separately by verify_material_archive_local.py --legacy-tracker.
const OTHER = 'purdue-74a073b99827';
const listing = '**/storage/v1/object/list/tracker-attachments';
const panel = (page: Page) => page.getByTestId('tracker-attachments');
const dict = (locale: 'en' | 'zh' = 'en') => (locale === 'zh' ? zh : en).detail.attachments;
const row = (name: string) => ({ name, id: name, created_at: '2026-09-25T12:00:00Z', updated_at: '2026-09-25T12:00:00Z', metadata: { size: PDF.length, mimetype: 'application/pdf' } });
function gate() { let release!: () => void; const promise = new Promise<void>(resolve => { release = resolve; }); return { release, promise }; }
type Audit = { pageErrors: string[]; external: string[]; responses: { path: string; status: number; injected: string | null }[]; console: { type: string; text: string }[] };
const audits = new WeakMap<Page, Audit>();

async function setup(page: Page, owner: Owner, options: { failure?: number; holdFirst?: ReturnType<typeof gate>; locale?: 'en' | 'zh' } = {}) {
  await seed(page, owner, options.locale); const injected = new WeakMap<Request, string>();
  const audit: Audit = { pageErrors: [], external: [], responses: [], console: [] }; audits.set(page, audit);
  page.on('pageerror', error => audit.pageErrors.push(error.message));
  page.on('console', message => { if (['warning', 'error'].includes(message.type())) audit.console.push({ type: message.type(), text: message.text() }); });
  page.on('response', response => { if (response.status() >= 400) audit.responses.push({ path: new URL(response.url()).pathname, status: response.status(), injected: injected.get(response.request()) ?? null }); });
  await page.context().route('**/*', route => { const url = new URL(route.request().url()); if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) { audit.external.push(url.origin); return route.abort('blockedbyclient'); } return route.continue(); });
  const state = { owner, reads: [] as string[], uploads: 0, deletes: 0, signings: 0, failure: options.failure ?? 0, failAfterWrite: false, unknownWrite: false, emptyDeleteReceipt: false, files: new Map<string, string[]>([[owner.session.user.id + '/' + TARGET, ['original.pdf']]]) };
  const fault = (route: Route, code: number, label: string) => { injected.set(route.request(), label); return route.fulfill({ status: code, json: { statusCode: String(code), error: 'controlled fixture', message: label } }); };
  await page.route('**/auth/v1/user', route => route.fulfill({ json: state.owner.session.user }));
  await page.route('**/rest/v1/interactions**', route => {
    const query = new URL(route.request().url()).searchParams; const target = (query.get('opportunity_id') ?? '').replace(/^eq\./, '') || TARGET;
    expect(route.request().method()).toBe('GET');
    return route.fulfill({ json: [{ device_id: state.owner.session.user.id, opportunity_id: target, interaction_type: 'contacted', notes: null, remind_at: null, last_contacted_at: '2026-09-25T12:00:00Z', updated_at: '2026-09-25T12:00:00Z' }] });
  });
  for (const table of ['contact_events', 'application_events', 'interaction_status_changes']) await page.route(`**/rest/v1/${table}?**`, route => route.fulfill({ json: [] }));
  await page.route(listing, async route => {
    expect(route.request().method()).toBe('POST'); const prefix = route.request().postDataJSON().prefix as string; state.reads.push(prefix);
    const snapshot = [...(state.files.get(prefix) ?? [])];
    if (options.holdFirst && state.reads.length === 1) await options.holdFirst.promise;
    if (state.failure) { await fault(route, state.failure, 'injected attachment list failure'); return; }
    try { await route.fulfill({ json: [...snapshot.map(row), { name: 'folder', id: null, metadata: null }] }); }
    catch (error) { if (!/abort|cancel/i.test(route.request().failure()?.errorText ?? '')) throw error; }
  });
  await page.route('**/storage/v1/object/tracker-attachments/**', async route => {
    expect(route.request().method()).toBe('POST'); state.uploads += 1;
    const path = decodeURIComponent(new URL(route.request().url()).pathname.split('/tracker-attachments/')[1]); const split = path.lastIndexOf('/');
    expect(path.startsWith(state.owner.session.user.id + '/')).toBe(true);
    state.files.set(path.slice(0, split), [...(state.files.get(path.slice(0, split)) ?? []), path.slice(split + 1)]);
    if (state.failAfterWrite) state.failure = 500;
    if (state.unknownWrite) { await fault(route, 503, 'injected upload result unknown after commit'); return; }
    await route.fulfill({ json: { Key: 'tracker-attachments/' + path, Id: 'fixture-object' } });
  });
  await page.route('**/storage/v1/object/tracker-attachments', async route => {
    expect(route.request().method()).toBe('DELETE'); state.deletes += 1; const paths = route.request().postDataJSON().prefixes as string[];
    if (state.emptyDeleteReceipt) { await route.fulfill({ json: [] }); return; }
    for (const path of paths) { const split = path.lastIndexOf('/'); state.files.set(path.slice(0, split), (state.files.get(path.slice(0, split)) ?? []).filter(name => name !== path.slice(split + 1))); }
    if (state.failAfterWrite) state.failure = 500;
    await route.fulfill({ json: paths.map(name => ({ name })) });
  });
  await page.route('**/storage/v1/object/sign/tracker-attachments/**', route => { state.signings += 1; return route.fulfill({ json: { signedURL: '/object/sign/tracker-attachments/fixture.pdf?token=synthetic' } }); });
  await page.goto(`/opportunities/${TARGET}`); await openPanel(page, options.locale);
  return state;
}
async function openPanel(page: Page, locale: 'en' | 'zh' = 'en') {
  const copy = (locale === 'zh' ? zh : en).detail.tracker;
  const toggle = page.getByRole('button', { name: new RegExp(`${copy.addButton}|${copy.openButton}`) });
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await expect(panel(page)).toBeVisible();
}
const retry = (page: Page, locale: 'en' | 'zh' = 'en') => panel(page).getByRole('button', { name: dict(locale).retryList, exact: true });
const openFile = (page: Page, name = 'original.pdf', locale: 'en' | 'zh' = 'en') => panel(page).getByRole('button', { name: dict(locale).openAria.replace('{name}', name), exact: true });
const deleteFile = (page: Page, name = 'original.pdf') => panel(page).getByRole('button', { name: dict().deleteAria.replace('{name}', name), exact: true });

test.describe('Legacy Tracker attachment recovery', () => {
  test.afterEach(async ({ page }, info) => { const audit = audits.get(page); if (!audit) return; await info.attach('legacy-attachment-network-audit', { body: JSON.stringify(audit, null, 2), contentType: 'application/json' }); expect(audit.pageErrors).toEqual([]); expect(audit.external).toEqual([]); expect(audit.responses.filter(row => row.status >= 500 && !row.injected)).toEqual([]); });

  for (const locale of ['en', 'zh'] as const) test(`${locale} list failure stays distinct from empty and keyboard retry restores files`, async ({ page }, info) => {
    const owner = await account(); try {
      if (locale === 'zh') await page.setViewportSize({ width: 320, height: 760 });
      const state = await setup(page, owner, { failure: 500, locale });
      await expect(page.getByTestId('tracker-attachments-error')).toHaveText(dict(locale).listError); await expect(page.getByTestId('tracker-attachments-empty')).toHaveCount(0);
      await expect(panel(page).getByRole('button', { name: dict(locale).addButton, exact: true })).toBeDisabled();
      await panel(page).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(`legacy-error-${locale}.png`) });
      state.failure = 0; await retry(page, locale).focus(); await page.keyboard.press('Enter'); await expect(openFile(page, 'original.pdf', locale)).toBeEnabled();
      await expect(panel(page)).not.toContainText('folder'); expect(state.reads).toHaveLength(2); expect(state.uploads + state.deletes).toBe(0);
      expect(await panel(page).evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
      await page.screenshot({ path: info.outputPath(`legacy-recovered-${locale}.png`) });
    } finally { await owner.http.dispose(); }
  });

  test('a held list times out, offers retry and ignores the late first response', async ({ page }) => {
    const owner = await account(); const held = gate(); try {
      await page.clock.install(); const state = await setup(page, owner, { holdFirst: held }); await expect.poll(() => state.reads.length).toBe(1);
      await page.clock.fastForward(30_001); await expect(page.getByTestId('tracker-attachments-error')).toBeVisible();
      state.files.set(owner.session.user.id + '/' + TARGET, ['newer.pdf']); await retry(page).click(); await expect(openFile(page, 'newer.pdf')).toBeEnabled(); held.release();
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))); await expect(openFile(page)).toHaveCount(0);
    } finally { held.release(); await owner.http.dispose(); }
  });

  test('unauthenticated Storage read shows sign-in state and a manual check restores the same account', async ({ page }) => {
    const owner = await account(); try {
      const state = await setup(page, owner, { failure: 401 }); await expect(page.getByTestId('tracker-attachments-signed-out')).toHaveText(dict().signIn); await expect(page.getByTestId('tracker-attachments-empty')).toHaveCount(0);
      state.failure = 0; await panel(page).getByRole('button', { name: dict().checkAgain, exact: true }).click(); await expect(openFile(page)).toBeEnabled(); expect(state.reads).toHaveLength(2);
    } finally { await owner.http.dispose(); }
  });

  test('upload success remains explicit when the following list fails; retry never uploads twice', async ({ page }) => {
    const owner = await account(); try {
      const state = await setup(page, owner); await expect(openFile(page)).toBeEnabled(); state.failAfterWrite = true;
      await panel(page).locator('input[type=file]').setInputFiles({ name: 'new-file.pdf', mimeType: 'application/pdf', buffer: PDF });
      await expect(page.getByTestId('tracker-attachments-notice')).toHaveText(dict().uploaded.replace('{name}', 'new-file.pdf')); await expect(page.getByTestId('tracker-attachments-error')).toBeVisible(); await expect(openFile(page)).toBeDisabled(); await expect(page.getByTestId('tracker-attachments-empty')).toHaveCount(0);
      state.failure = 0; await retry(page).click(); await expect(openFile(page, 'new-file.pdf')).toBeEnabled(); expect(state.uploads).toBe(1);
    } finally { await owner.http.dispose(); }
  });

  test('delete success is retained when the following list fails; retry only reads', async ({ page }) => {
    const owner = await account(); try {
      const state = await setup(page, owner); await expect(openFile(page)).toBeEnabled(); state.failAfterWrite = true; await deleteFile(page).click();
      await expect(page.getByTestId('tracker-attachments-notice')).toHaveText(dict().deleted.replace('{name}', 'original.pdf')); await expect(page.getByTestId('tracker-attachments-error')).toBeVisible(); await expect(page.getByTestId('tracker-attachments-empty')).toHaveCount(0);
      state.failure = 0; await retry(page).click(); await expect(page.getByTestId('tracker-attachments-empty')).toBeVisible(); expect(state.deletes).toBe(1);
    } finally { await owner.http.dispose(); }
  });

  test('an unknown committed upload can only be checked before another write', async ({ page }) => {
    const owner = await account(); try {
      const state = await setup(page, owner); await expect(openFile(page)).toBeEnabled(); state.unknownWrite = true;
      await panel(page).locator('input[type=file]').setInputFiles({ name: 'unknown.pdf', mimeType: 'application/pdf', buffer: PDF }); await expect(panel(page)).toContainText(dict().uploadUnknown);
      await expect(panel(page).locator('input[type=file]')).toBeDisabled(); await retry(page).click(); await expect(openFile(page, 'unknown.pdf')).toBeEnabled(); expect(state.uploads).toBe(1);
    } finally { await owner.http.dispose(); }
  });

  test('an empty deletion receipt does not claim deletion or remove the original file', async ({ page }) => {
    const owner = await account(); try {
      const state = await setup(page, owner); await expect(openFile(page)).toBeEnabled(); state.emptyDeleteReceipt = true; await deleteFile(page).click();
      await expect(panel(page)).toContainText(dict().deleteUnknown); await expect(page.getByTestId('tracker-attachments-notice')).toHaveCount(0); await expect(openFile(page)).toBeDisabled(); await retry(page).click(); await expect(openFile(page)).toBeEnabled(); expect(state.deletes).toBe(1);
    } finally { await owner.http.dispose(); }
  });

  test('a delayed previous-owner list cannot expose its files after account switch', async ({ page }) => {
    const owner = await account(), next = await account(); const held = gate(); try {
      const state = await setup(page, owner, { holdFirst: held }); await expect.poll(() => state.reads.length).toBe(1);
      await page.route('**/auth/v1/token?grant_type=refresh_token', route => {
        expect(route.request().postDataJSON().refresh_token).toBe(next.session.refresh_token);
        return route.fulfill({ json: next.session });
      });
      state.owner = next; state.files.set(next.session.user.id + '/' + TARGET, ['next-owner.pdf']);
      await page.evaluate(session => { localStorage.setItem('ofe_auth', JSON.stringify(session)); const channel = new BroadcastChannel('ofe_auth'); channel.postMessage({ event: 'SIGNED_IN', session }); channel.close(); }, next.session);
      await expect(panel(page)).toHaveCount(0); await openPanel(page);
      await expect(openFile(page, 'next-owner.pdf')).toBeEnabled(); held.release(); await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))); await expect(openFile(page)).toHaveCount(0);
    } finally { held.release(); await owner.http.dispose(); await next.http.dispose(); }
  });

  test('a late signed URL cannot open the previous target file after navigation', async ({ page }) => {
    const owner = await account(); const held = gate(); let signingStarted = false;
    try {
      await page.addInitScript(() => { const tracked = window as typeof window & { __attachmentOpenCalls: number }; tracked.__attachmentOpenCalls = 0; window.open = () => { tracked.__attachmentOpenCalls += 1; return null; }; });
      const state = await setup(page, owner); await expect(openFile(page)).toBeEnabled(); state.files.set(owner.session.user.id + '/' + OTHER, ['next-target.pdf']);
      await page.route('**/storage/v1/object/sign/tracker-attachments/**', async route => { signingStarted = true; await held.promise; await route.fulfill({ json: { signedURL: '/object/sign/tracker-attachments/fixture.pdf?token=synthetic' } }); });
      const completed = page.waitForResponse(response => new URL(response.url()).pathname.includes('/object/sign/tracker-attachments/'));
      await openFile(page).click(); await expect.poll(() => signingStarted).toBe(true);
      await page.locator(`a[href="/opportunities/${OTHER}"]`).first().click(); await expect(page).toHaveURL(new RegExp(`/opportunities/${OTHER}$`)); await openPanel(page); await expect(openFile(page, 'next-target.pdf')).toBeEnabled();
      held.release(); await (await completed).finished(); await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      expect(await page.evaluate(() => (window as typeof window & { __attachmentOpenCalls: number }).__attachmentOpenCalls)).toBe(0);
    } finally { held.release(); await owner.http.dispose(); }
  });

  test('a delayed previous-target list cannot replace files after in-app navigation', async ({ page }) => {
    const owner = await account(); const held = gate(); try {
      const state = await setup(page, owner, { holdFirst: held }); await expect.poll(() => state.reads.length).toBe(1); state.files.set(owner.session.user.id + '/' + OTHER, ['next-target.pdf']);
      await page.locator(`a[href="/opportunities/${OTHER}"]`).first().click(); await expect(page).toHaveURL(new RegExp(`/opportunities/${OTHER}$`)); await openPanel(page);
      await expect(openFile(page, 'next-target.pdf')).toBeEnabled(); held.release(); await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))); await expect(openFile(page)).toHaveCount(0);
    } finally { held.release(); await owner.http.dispose(); }
  });
});
