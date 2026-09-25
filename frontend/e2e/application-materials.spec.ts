import { test, expect, request as apiRequest, type APIRequestContext, type Page, type Locator } from '@playwright/test';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { STORAGE_KEYS } from '../src/lib/storage-keys';
import { en, zh } from '../src/i18n/dictionaries';

// Real browser storage, crypto, auth SDK, file selection and download. The
// material HTTP boundary is page-scoped; backend/PDF/RLS guarantees are tested separately.
const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
const TARGET = 'uiuc-siebel-ugresearch';
const EVENT = '22222222-2222-4222-8222-222222222222';
const SUBMITTED = '2026-08-01T15:30:00.000Z';
const CONFIRMED = '2026-09-25T11:00:00.000Z';
const ARCHIVED = '2026-09-25T12:01:00.000Z';
const LINKED = '2026-09-25T12:02:00.000Z';
const DELETED = '2026-09-25T13:00:00.000Z';
function pdf(text = 'The submitted original') {
  const stream = `BT /F1 12 Tf 20 40 Td (${text}) Tj ET`;
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`];
  let data = '%PDF-1.4\n'; const offsets = [0];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(data)); data += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = Buffer.byteLength(data); data += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(data);
}
const PDF = pdf();
const hash = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex');
interface Owner { http: APIRequestContext; session: { access_token: string; refresh_token: string; user: { id: string; is_anonymous: boolean; email: string | null } } }
interface Metadata { version: 1; expected_owner_id: string; opportunity_id: string; application_event_id: string; material_id: string; record_id: string; filename: string; mime_type: 'application/pdf'; byte_length: number; bytes_sha256: string; attested: true }
interface RecordWire { version: 1; owner_id: string; opportunity_id: string; application_event_id: string; material_id: string; record_id: string; status: 'staged' | 'ready' | 'deleted'; filename: string | null; mime_type: string | null; byte_length: number | null; bytes_sha256: string | null; staged_at: string; archived_at: string | null; linked_at: string | null; deleted_at: string | null; confirmation_source: 'user_reported' }
const copy = (locale: 'en' | 'zh' = 'en') => (locale === 'zh' ? zh : en).applicationRecord.materials;
const panel = (page: Page) => page.getByTestId('application-material-panel');
const action = (parent: Locator, key: keyof ReturnType<typeof copy>, locale: 'en' | 'zh' = 'en') => parent.getByRole('button', { name: copy(locale)[key], exact: true });
async function account(anonymous = false): Promise<Owner> {
  expect(new URL(STUB).hostname).toBe('127.0.0.1'); const http = await apiRequest.newContext();
  try {
    const response = await http.post(STUB + '/auth/v1/signup', { data: {} }); expect(response.status()).toBe(200);
    const session = await response.json();
    // Only this browser fixture is converted. No hosted login, account mutation or email.
    if (!anonymous) {
      session.user = { ...session.user, is_anonymous: false, email: 'materials@example.test', app_metadata: { provider: 'email', providers: ['email'] } };
      const parts = session.access_token.split('.'); const claims = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
      parts[1] = Buffer.from(JSON.stringify({ ...claims, is_anonymous: false })).toString('base64url'); session.access_token = parts.join('.');
    }
    return { http, session };
  } catch (error) { await http.dispose(); throw error; }
}
async function seed(page: Page, owner: Owner, locale: 'en' | 'zh' = 'en') {
  await page.addInitScript(({ session, keys, locale }) => {
    if (localStorage.getItem('material-fixture-seeded')) return;
    localStorage.setItem('ofe_auth', JSON.stringify(session)); localStorage.setItem(keys.LOCALE, locale); localStorage.setItem(keys.ONBOARDING_SEEN, '1'); localStorage.setItem('material-fixture-seeded', '1');
  }, { session: owner.session, keys: STORAGE_KEYS, locale });
  await page.route('**/auth/v1/user', route => route.fulfill({ json: owner.session.user }));
  await page.route('**/auth/v1/token?grant_type=refresh_token', route => {
    expect(route.request().postDataJSON().refresh_token).toBe(owner.session.refresh_token);
    return route.fulfill({ json: owner.session });
  });
}
function fromInput(input: Metadata, status: RecordWire['status'] = 'ready'): RecordWire {
  return { version: 1, owner_id: input.expected_owner_id, opportunity_id: input.opportunity_id, application_event_id: input.application_event_id,
    material_id: input.material_id, record_id: input.record_id, status, filename: status === 'deleted' ? null : input.filename,
    mime_type: status === 'deleted' ? null : input.mime_type, byte_length: status === 'deleted' ? null : input.byte_length,
    bytes_sha256: status === 'ready' ? input.bytes_sha256 : null, staged_at: CONFIRMED,
    archived_at: status === 'staged' ? null : ARCHIVED, linked_at: status === 'staged' ? null : LINKED, deleted_at: status === 'deleted' ? DELETED : null, confirmation_source: 'user_reported' };
}
function seeded(owner: Owner, name = 'submitted-original.pdf', index = 0): Metadata {
  return { version: 1, expected_owner_id: owner.session.user.id, opportunity_id: TARGET, application_event_id: EVENT,
    material_id: `00000000-0000-4000-8001-${String(index).padStart(12, '0')}`, record_id: `00000000-0000-4000-8002-${String(index).padStart(12, '0')}`,
    filename: name, mime_type: 'application/pdf', byte_length: PDF.byteLength, bytes_sha256: hash(PDF), attested: true };
}
async function network(page: Page, owner: Owner, options: { uploadUnknown?: 'ready' | 'staged' | 'absent'; deleteUnknown?: 'deleted' | 'ready'; firstReadFails?: boolean; rejectPdf?: boolean } = {}) {
  const state = { records: new Map<string, RecordWire>(), files: new Map<string, Buffer>(), uploads: [] as Metadata[], bodies: [] as Buffer[], deletions: [] as string[], reads: 0, lookups: 0, downloads: 0, statusWrites: 0, appWrites: 0, rejectReads: false, pageFails: false, cursorReads: [] as string[] };
  await page.route('**/rest/v1/application_events?**', route => route.fulfill({ json: [{ event_id: EVENT, device_id: owner.session.user.id, opportunity_id: TARGET,
    channel: 'web_form', destination: 'https://example.edu/application', actual_submitted_at: SUBMITTED, notes: 'I submitted my original PDF.', result_note: null, next_step: null, confirmed_at: CONFIRMED, confirmation_source: 'user_reported' }] }));
  await page.route('**/rest/v1/contact_events?**', route => route.fulfill({ json: [] }));
  await page.route('**/rest/v1/interaction_status_changes?**', route => route.fulfill({ json: [] }));
  await page.route('**/rest/v1/interactions**', route => { if (route.request().method() !== 'GET') state.statusWrites += 1; return route.fulfill({ json: [] }); });
  await page.route('**/rest/v1/rpc/confirm_application_event', route => { state.appWrites += 1; return route.fulfill({ status: 500, json: {} }); });
  await page.route('**/api/application-materials**', async route => {
    const request = route.request(); const url = new URL(request.url()); const method = request.method();
    expect(request.headers().authorization).toBe(`Bearer ${owner.session.access_token}`);
    if (method === 'POST') {
      const form = await new Response(new Uint8Array(request.postDataBuffer()!).buffer, { headers: { 'Content-Type': request.headers()['content-type'] } }).formData();
      expect([...form.keys()].sort()).toEqual(['file', 'metadata']); const input = JSON.parse(String(form.get('metadata'))) as Metadata;
      const file = form.get('file') as File; const bytes = Buffer.from(await file.arrayBuffer());
      expect(input).toMatchObject({ version: 1, expected_owner_id: owner.session.user.id, opportunity_id: TARGET, application_event_id: EVENT, attested: true, mime_type: 'application/pdf' });
      expect(bytes.byteLength).toBe(input.byte_length); expect(hash(bytes)).toBe(input.bytes_sha256); expect(file.name).toBe(input.filename);
      state.uploads.push(input); state.bodies.push(bytes); const previous = state.records.get(input.record_id);
      const firstUnknown = options.uploadUnknown && state.uploads.length === 1;
      if (options.rejectPdf && state.uploads.length === 1) { await route.fulfill({ status: 422, json: { detail: { code: 'material_invalid_pdf' } } }); return; }
      if (!(firstUnknown && options.uploadUnknown === 'absent')) {
        const record = fromInput(input, firstUnknown && options.uploadUnknown === 'staged' ? 'staged' : 'ready');
        state.records.set(input.record_id, record); state.files.set(input.record_id, bytes);
      }
      if (firstUnknown) { await route.fulfill({ status: 503, json: { detail: { code: 'material_unavailable' } } }); return; }
      await route.fulfill({ json: { version: 1, record: state.records.get(input.record_id), replayed: !!previous && previous.status === 'ready' } }); return;
    }
    const id = url.pathname.split('/')[3];
    if (method === 'DELETE') {
      expect(request.postDataJSON()).toEqual({ expected_owner_id: owner.session.user.id, opportunity_id: TARGET, application_event_id: EVENT, material_id: request.postDataJSON().material_id }); state.deletions.push(id);
      const existing = state.records.get(id) ?? { ...fromInput(state.uploads.find(row => row.record_id === id)!, 'deleted'), archived_at: null, linked_at: null };
      expect(request.postDataJSON().material_id).toBe(existing.material_id);
      if (!(options.deleteUnknown === 'ready' && state.deletions.length === 1)) state.records.set(id, { ...existing, status: 'deleted', filename: null, mime_type: null, byte_length: null, bytes_sha256: null, deleted_at: DELETED });
      if (options.deleteUnknown && state.deletions.length === 1) { await route.fulfill({ status: 503, json: { detail: { code: 'material_unavailable' } } }); return; }
      await route.fulfill({ json: { version: 1, record: state.records.get(id) } }); return;
    }
    expect(method).toBe('GET'); expect(url.searchParams.get('expected_owner_id')).toBe(owner.session.user.id); expect(url.searchParams.get('opportunity_id')).toBe(TARGET); expect(url.searchParams.get('application_event_id')).toBe(EVENT);
    if (url.pathname.endsWith('/file')) {
      state.downloads += 1; const record = state.records.get(id)!;
      expect(record.status).toBe('ready'); await route.fulfill({ body: state.files.get(id)!, headers: { 'content-type': 'application/pdf', 'x-ofe-material-id': record.material_id,
        'x-ofe-material-record': record.record_id, 'x-ofe-material-sha256': record.bytes_sha256! } }); return;
    }
    if (id) {
      state.lookups += 1; const row = state.records.get(id);
      await route.fulfill(row ? { json: { version: 1, record: row } } : { status: 404, json: { detail: { code: 'material_not_found' } } }); return;
    }
    state.reads += 1;
    if (state.rejectReads) { await route.fulfill({ status: 401, json: { detail: { code: 'material_auth_required' } } }); return; }
    if (options.firstReadFails && state.reads === 1) { await route.fulfill({ status: 500, json: { private: 'not shown' } }); return; }
    let rows = [...state.records.values()].filter(row => row.linked_at).sort((a, b) => b.linked_at!.localeCompare(a.linked_at!) || b.record_id.localeCompare(a.record_id));
    const cursor = url.searchParams.get('cursor_record_id');
    if (cursor) {
      state.cursorReads.push(cursor); if (state.pageFails) { state.pageFails = false; await route.fulfill({ status: 503, json: { detail: { code: 'material_unavailable' } } }); return; }
      const linked = url.searchParams.get('cursor_linked_at')!; rows = rows.filter(row => row.linked_at! < linked || (row.linked_at === linked && row.record_id < cursor));
    }
    const items = rows.slice(0, 20); const last = items.at(-1);
    await route.fulfill({ json: { version: 1, items, next_cursor: rows.length > 20 ? { linked_at: last!.linked_at, record_id: last!.record_id } : null } });
  });
  return state;
}
async function history(page: Page, locale: 'en' | 'zh' = 'en') {
  const dict = locale === 'zh' ? zh : en; const toggle = page.getByRole('button', { name: new RegExp('^' + dict.detail.tracker.addButton) });
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  const history = page.getByTestId('application-history'); const event = history.locator('ol > li > details').first();
  if (await event.getAttribute('open') === null) await event.locator(':scope > summary').click();
  return history;
}
async function open(page: Page, locale: 'en' | 'zh' = 'en') { const list = await history(page, locale); await list.getByRole('button', { name: copy(locale).open, exact: true }).click(); await expect(panel(page)).toBeVisible(); return panel(page); }
async function upload(page: Page, name = 'submitted-original.pdf', bytes = PDF, locale: 'en' | 'zh' = 'en') {
  await panel(page).getByLabel(copy(locale).fileLabel, { exact: true }).setInputFiles({ name, mimeType: 'application/pdf', buffer: bytes });
  await panel(page).getByRole('checkbox', { name: copy(locale).attestation, exact: true }).check(); await action(panel(page), 'save', locale).click();
}
async function start(page: Page, owner: Owner, options: Parameters<typeof network>[2] = {}, locale: 'en' | 'zh' = 'en') {
  await seed(page, owner, locale); const net = await network(page, owner, options); await page.goto(`/opportunities/${TARGET}`); return net;
}
function addRecord(net: Awaited<ReturnType<typeof network>>, input: Metadata) { net.records.set(input.record_id, fromInput(input)); net.files.set(input.record_id, PDF); }
async function pendingValues(page: Page, prefix: string) { return page.evaluate(prefix => Object.keys(localStorage).filter(key => key.includes(prefix)).map(key => localStorage.getItem(key)!), prefix); }

test.describe('Submitted application PDF records', () => {
  test('keeps material reads lazy and offers sign-in to anonymous users', async ({ page }) => {
    const owner = await account(true); try {
      const net = await start(page, owner); const list = await history(page); expect(net.reads).toBe(0);
      await list.getByRole('button', { name: copy().open, exact: true }).click(); await expect(list).toContainText(copy().signInHint); expect(net.reads).toBe(0);
      await list.getByRole('button', { name: copy().signIn, exact: true }).click(); await expect(page.getByRole('dialog')).toBeVisible(); expect(net.uploads).toHaveLength(0);
    } finally { await owner.http.dispose(); }
  });
  test('archives selected exact bytes, separates dates and downloads the original', async ({ page }, info) => {
    const owner = await account(); try {
      const net = await start(page, owner); await open(page); await expect(action(panel(page), 'save')).toBeDisabled();
      await panel(page).getByLabel(copy().fileLabel, { exact: true }).setInputFiles({ name: 'submitted-original.pdf', mimeType: 'application/pdf', buffer: PDF });
      await expect(action(panel(page), 'save')).toBeDisabled(); await panel(page).getByRole('checkbox').check(); await action(panel(page), 'save').click();
      await expect(panel(page)).toContainText(copy().saved); expect(net.uploads).toHaveLength(1); expect(net.bodies[0]).toEqual(PDF); expect(net.statusWrites).toBe(0); expect(net.appWrites).toBe(0);
      const row = panel(page).getByTestId('application-material-record'); await expect(row.locator('time').nth(0)).toHaveAttribute('datetime', ARCHIVED); await expect(row.locator('time').nth(1)).toHaveAttribute('datetime', LINKED);
      const event = page.getByTestId('application-history').locator('ol > li > details'); await expect(event.locator('dl > div > dd > time').first()).toHaveAttribute('datetime', SUBMITTED);
      const downloadPromise = page.waitForEvent('download'); await action(panel(page), 'download').click(); const download = await downloadPromise;
      expect(download.suggestedFilename()).toBe('submitted-original.pdf'); const path = info.outputPath('downloaded-original.pdf'); await download.saveAs(path); expect(await readFile(path)).toEqual(PDF);
      await row.scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('material-archived-list.png') });
      await expect.poll(() => pendingValues(page, STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX)).toEqual([]);
    } finally { await owner.http.dispose(); }
  });
  test('unknown committed upload survives reload and check finds the same saved record without a new upload', async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner, { uploadUnknown: 'ready' }); await open(page); await upload(page);
      await expect(panel(page).getByRole('alert')).toHaveText(copy().unavailable); expect(net.records.size).toBe(1);
      const pending = await pendingValues(page, STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX); expect(pending).toHaveLength(1); expect(pending[0]).not.toContain('%PDF');
      await page.reload(); await open(page); await expect(panel(page)).toContainText(copy().cleanupPending); await action(panel(page), 'check').click();
      await expect(panel(page)).toContainText(copy().saved); expect(net.uploads).toHaveLength(1); expect(net.lookups).toBe(1); await expect.poll(() => pendingValues(page, STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX)).toEqual([]);
    } finally { await owner.http.dispose(); }
  });
  test('staged recovery is unconfirmed, then retries identical bytes under the original file name and IDs', async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner, { uploadUnknown: 'staged' }); await open(page); await upload(page); await expect(panel(page).getByRole('alert')).toBeVisible();
      await page.reload(); await open(page); await action(panel(page), 'check').click(); await expect(panel(page)).toContainText(copy().staged);
      await expect(panel(page)).not.toContainText(copy().saved); await expect(action(panel(page), 'retrySave')).toBeDisabled();
      await panel(page).getByLabel(copy().fileLabel, { exact: true }).setInputFiles({ name: 'renamed-copy.pdf', mimeType: 'application/pdf', buffer: PDF }); await action(panel(page), 'retrySave').click();
      await expect(panel(page)).toContainText(copy().saved); expect(net.uploads).toHaveLength(2); expect(net.uploads[1]).toEqual(net.uploads[0]); expect(net.records.size).toBe(1); expect(net.bodies[1]).toEqual(PDF);
    } finally { await owner.http.dispose(); }
  });
  test('different bytes cannot replace a pending upload', async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner, { uploadUnknown: 'absent' }); await open(page); await upload(page); await expect(panel(page).getByRole('alert')).toBeVisible();
      await panel(page).getByLabel(copy().fileLabel, { exact: true }).setInputFiles({ name: 'different.pdf', mimeType: 'application/pdf', buffer: pdf('A later revision') }); await action(panel(page), 'retrySave').click();
      await expect(panel(page).getByRole('alert')).toHaveText(copy().fileMismatch); expect(net.uploads).toHaveLength(1); expect(net.records.size).toBe(0);
      await action(panel(page), 'check').click(); await expect(panel(page).getByRole('alert')).toHaveText(copy().notFound);
    } finally { await owner.http.dispose(); }
  });
  test('each explicitly added PDF uses new immutable IDs while the earlier PDF stays unchanged', async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner); await open(page); await upload(page); await expect(panel(page)).toContainText(copy().saved);
      const original = structuredClone([...net.records.values()][0]); await action(panel(page), 'another').click(); await expect(panel(page).getByRole('checkbox')).not.toBeChecked();
      await upload(page, 'other-submitted-document.pdf', pdf('A second document submitted at the time')); await expect(panel(page)).toContainText(copy().saved);
      expect(net.uploads).toHaveLength(2); expect(net.uploads[0].record_id).not.toBe(net.uploads[1].record_id); expect(net.uploads[0].material_id).not.toBe(net.uploads[1].material_id);
      expect(net.records.get(original.record_id)).toEqual(original); await expect(panel(page).getByTestId('application-material-record')).toHaveCount(2);
    } finally { await owner.http.dispose(); }
  });
  test('delete requires explicit confirmation and preserves only a dated tombstone after reload', async ({ page }, info) => {
    const owner = await account(); try {
      const net = await start(page, owner); addRecord(net, seeded(owner)); await open(page); await action(panel(page), 'delete').click();
      await expect(panel(page).getByRole('alertdialog')).toHaveAccessibleName(copy().deleteTitle); await expect(action(panel(page), 'cancel')).toBeFocused(); await panel(page).getByRole('alertdialog').scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('material-delete-confirmation.png') }); await page.keyboard.press('Escape');
      await expect(action(panel(page), 'delete')).toBeFocused(); expect(net.deletions).toHaveLength(0); await action(panel(page), 'delete').click(); await action(panel(page), 'confirmDelete').click();
      await expect(panel(page).getByTestId('application-material-record')).toContainText(copy().deleted); await expect(panel(page)).not.toContainText('submitted-original.pdf'); await expect(action(panel(page), 'download')).toHaveCount(0);
      await page.reload(); await open(page); await expect(panel(page)).not.toContainText('submitted-original.pdf'); await expect(panel(page).getByTestId('application-material-record').locator('time')).toHaveCount(3);
      expect([...net.records.values()][0]).toMatchObject({ status: 'deleted', filename: null, bytes_sha256: null, byte_length: null }); expect(net.downloads).toBe(0);
    } finally { await owner.http.dispose(); }
  });
  for (const outcome of ['deleted', 'ready'] as const) test(`unknown deletion with ${outcome} receipt stays download-blocked through reload and resolves explicitly`, async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner, { deleteUnknown: outcome }); const input = seeded(owner); addRecord(net, input); await open(page); await action(panel(page), 'delete').click(); await action(panel(page), 'confirmDelete').click();
      await expect(panel(page).getByTestId('application-material-delete-pending')).toBeVisible(); await expect(action(panel(page), 'download')).toHaveCount(0);
      const pending = await pendingValues(page, STORAGE_KEYS.APPLICATION_MATERIAL_DELETE_PREFIX); expect(pending).toHaveLength(1); expect(pending[0]).not.toContain(input.filename); expect(pending[0]).not.toContain(input.bytes_sha256);
      await page.reload(); await open(page); await expect(panel(page)).not.toContainText(input.filename); await action(panel(page), 'check').click();
      if (outcome === 'ready') { await expect(panel(page).getByRole('alert')).toHaveText(copy().deleteUnknown); await expect(action(panel(page), 'download')).toHaveCount(0); await action(panel(page), 'retryDelete').click(); }
      await expect(panel(page).getByTestId('application-material-record')).toContainText(copy().deleted); if (outcome === 'ready') expect(net.deletions).toEqual([input.record_id, input.record_id]); await expect.poll(() => pendingValues(page, STORAGE_KEYS.APPLICATION_MATERIAL_DELETE_PREFIX)).toEqual([]); expect(net.downloads).toBe(0);
    } finally { await owner.http.dispose(); }
  });
  test('invalid PDF bytes and unavailable local persistence cause no upload', async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner); await open(page); await upload(page, 'false.pdf', Buffer.from('This is not a PDF'));
      await expect(panel(page).getByRole('alert')).toHaveText(copy().invalidFile); expect(net.uploads).toHaveLength(0);
      await page.evaluate(prefix => { const write = Storage.prototype.setItem; Storage.prototype.setItem = function (key, value) { if (key.includes(prefix)) throw new DOMException('Test storage failure', 'QuotaExceededError'); return write.call(this, key, value); }; }, STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX);
      await upload(page); await expect(panel(page).getByRole('alert')).toHaveText(copy().storageError); expect(net.uploads).toHaveLength(0);
    } finally { await owner.http.dispose(); }
  });
  test('a server-rejected PDF can be explicitly cancelled before choosing a new export with new IDs', async ({ page }, info) => {
    const owner = await account(); try {
      const net = await start(page, owner, { rejectPdf: true }); await open(page); await upload(page, 'damaged.pdf', Buffer.from('%PDF-1.4 damaged structure'));
      await expect(panel(page).getByRole('alert')).toHaveText(copy().invalidFile); expect(net.records.size).toBe(0);
      await action(panel(page), 'cancelUpload').click(); await expect(action(panel(page), 'keepUpload')).toBeFocused(); expect(net.deletions).toHaveLength(0); await panel(page).getByRole('alertdialog').scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath('material-cancel-confirmation.png') });
      await action(panel(page), 'confirmCancelUpload').click(); await expect(panel(page)).toContainText(copy().cancelled); await expect.poll(() => pendingValues(page, STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX)).toEqual([]);
      await action(panel(page), 'another').click(); await upload(page, 'fresh-export.pdf'); await expect(panel(page)).toContainText(copy().saved);
      expect(net.uploads).toHaveLength(2); expect(net.uploads[1].record_id).not.toBe(net.uploads[0].record_id); expect(net.uploads[1].material_id).not.toBe(net.uploads[0].material_id);
      expect(net.records.get(net.uploads[0].record_id)).toMatchObject({ status: 'deleted', filename: null, archived_at: null, linked_at: null });
      await expect(panel(page).getByTestId('application-material-record')).toHaveCount(1); await expect(panel(page)).not.toContainText('damaged.pdf');
    } finally { await owner.http.dispose(); }
  });
  test('unknown cancellation remains blocked after reload until its tombstone is checked', async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner, { rejectPdf: true, deleteUnknown: 'deleted' }); await open(page); await upload(page, 'damaged.pdf', Buffer.from('%PDF-1.4 damaged structure'));
      await expect(panel(page).getByRole('alert')).toBeVisible(); await action(panel(page), 'cancelUpload').click(); await action(panel(page), 'confirmCancelUpload').click();
      await expect(panel(page).getByRole('alert')).toHaveText(copy().cancelUnknown); await expect(panel(page).getByLabel(copy().fileLabel, { exact: true })).toHaveCount(0);
      await page.reload(); await open(page); await expect(panel(page)).toContainText(copy().cancelUnknown); await expect(panel(page).getByLabel(copy().fileLabel, { exact: true })).toHaveCount(0);
      await action(panel(page), 'check').click(); await expect(panel(page)).toContainText(copy().cancelled); expect(net.deletions).toHaveLength(1);
      await expect.poll(() => pendingValues(page, STORAGE_KEYS.APPLICATION_MATERIAL_DELETE_PREFIX)).toEqual([]); await expect.poll(() => pendingValues(page, STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX)).toEqual([]); expect(net.uploads).toHaveLength(1);
    } finally { await owner.http.dispose(); }
  });
  test('read errors stay distinct from empty history; pagination preserves 21 unique records and retries its cursor', async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner, { firstReadFails: true }); for (let index = 0; index < 21; index += 1) addRecord(net, seeded(owner, `submitted-${index}.pdf`, index));
      await open(page); await expect(panel(page).getByRole('alert')).toContainText(copy().loadError); await expect(panel(page)).not.toContainText(copy().empty); await action(panel(page), 'retry').click();
      await expect(panel(page).getByTestId('application-material-record')).toHaveCount(20); net.pageFails = true; await action(panel(page), 'loadMore').click();
      await expect(panel(page).getByRole('alert')).toHaveText(copy().moreError); await expect(panel(page).getByTestId('application-material-record')).toHaveCount(20); await action(panel(page), 'loadMore').click();
      await expect(panel(page).getByTestId('application-material-record')).toHaveCount(21); expect(net.cursorReads).toHaveLength(2); expect(net.cursorReads[0]).toBe(net.cursorReads[1]);
      await expect(action(panel(page), 'loadMore')).toHaveCount(0);
    } finally { await owner.http.dispose(); }
  });
  test('an expired formal session replaces private files with sign-in instead of stale download controls', async ({ page }) => {
    const owner = await account(); try {
      const net = await start(page, owner); addRecord(net, seeded(owner)); await open(page); await expect(action(panel(page), 'download')).toBeVisible();
      await page.getByTestId('application-history').getByRole('button', { name: copy().close, exact: true }).click(); net.rejectReads = true;
      await page.getByTestId('application-history').getByRole('button', { name: copy().open, exact: true }).click(); await expect(page.getByTestId('application-history')).toContainText(copy().signInHint);
      await expect(panel(page)).toHaveCount(0); await expect(page.getByText('submitted-original.pdf', { exact: true })).toHaveCount(0); expect(net.downloads).toBe(0);
    } finally { await owner.http.dispose(); }
  });
  for (const locale of ['en', 'zh'] as const) test(`${locale} 320px file form and safe long-name history remain keyboard usable`, async ({ page }, info) => {
    const owner = await account(); try {
      await page.setViewportSize({ width: 320, height: 760 }); const net = await start(page, owner, {}, locale); await open(page, locale);
      await panel(page).scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(`material-form-${locale}-320.png`) });
      const filename = '<img onerror=alert(1)>王'.repeat(5) + '.pdf'; await upload(page, filename, PDF, locale); await expect(panel(page)).toContainText(copy(locale).saved);
      const name = panel(page).getByText(filename, { exact: true }); await expect(name).toBeVisible(); await expect(panel(page).locator('img,script,svg')).toHaveCount(0);
      expect(await panel(page).evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      await action(panel(page), 'delete', locale).focus(); await page.keyboard.press('Enter'); await expect(action(panel(page), 'cancel', locale)).toBeFocused(); await page.keyboard.press('Escape'); await expect(action(panel(page), 'delete', locale)).toBeFocused(); expect(net.deletions).toHaveLength(0);
      await panel(page).getByTestId('application-material-record').scrollIntoViewIfNeeded(); await page.screenshot({ path: info.outputPath(`material-history-${locale}-320.png`) });
    } finally { await owner.http.dispose(); }
  });
});
