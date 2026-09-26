import { expect, request as apiRequest, type APIRequestContext, type Page, type Request, type Route } from '@playwright/test';
import { createHash } from 'node:crypto';
import { STORAGE_KEYS } from '../src/lib/storage-keys';

// Browser fixture only. Contact events and material HTTP replies are scoped
// to the current page; actual storage and ownership are verified separately.
const injected = new WeakMap<Request, string>();
export const audits = new WeakMap<Page, { pageErrors: string[]; responses: { path: string; status: number; injected: string | null }[]; external: string[] }>();
function fault(route: Route, status: number, label: string, body: unknown) { injected.set(route.request(), label); return route.fulfill({ status, json: body }); }

const STUB = `http://127.0.0.1:${Number(process.env.E2E_SUPABASE_PORT ?? 54321)}`;
export const TARGET = 'uiuc-siebel-ugresearch';
export const EVENT = '22222222-2222-4222-8222-222222222222';
export const SUBMITTED = '2026-08-01T15:30:00.000Z';
export const CONFIRMED = '2026-09-25T11:00:00.000Z';
export const ARCHIVED = '2026-09-25T12:01:00.000Z';
export const LINKED = '2026-09-25T12:02:00.000Z';
const DELETED = '2026-09-25T13:00:00.000Z';
export function pdf(text = 'The submitted original') {
  const stream = `BT /F1 12 Tf 20 40 Td (${text}) Tj ET`;
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`];
  let data = '%PDF-1.4\n'; const offsets = [0];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(data)); data += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = Buffer.byteLength(data); data += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(data);
}
export const PDF = pdf();
const hash = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex');
export interface Owner { http: APIRequestContext; session: { access_token: string; refresh_token: string; user: { id: string; is_anonymous: boolean; email: string | null } } }
export interface Metadata { version: 1; expected_owner_id: string; opportunity_id: string; contact_event_id: string; material_id: string; record_id: string; filename: string; mime_type: 'application/pdf'; byte_length: number; bytes_sha256: string; attested: true }
export interface RecordWire { version: 1; owner_id: string; opportunity_id: string; contact_event_id: string; material_id: string; record_id: string; status: 'staged' | 'ready' | 'deleted'; filename: string | null; mime_type: string | null; byte_length: number | null; bytes_sha256: string | null; staged_at: string; archived_at: string | null; linked_at: string | null; deleted_at: string | null; confirmation_source: 'user_reported' }
export async function account(anonymous = false): Promise<Owner> {
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
export async function seed(page: Page, owner: Owner, locale: 'en' | 'zh' = 'en') {
  await page.context().addCookies([{ name: STORAGE_KEYS.LOCALE, value: locale, url: `http://127.0.0.1:${Number(process.env.E2E_PORT ?? 3100)}` }]);
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
export function fromInput(input: Metadata, status: RecordWire['status'] = 'ready'): RecordWire {
  return { version: 1, owner_id: input.expected_owner_id, opportunity_id: input.opportunity_id, contact_event_id: input.contact_event_id,
    material_id: input.material_id, record_id: input.record_id, status, filename: status === 'deleted' ? null : input.filename,
    mime_type: status === 'deleted' ? null : input.mime_type, byte_length: status === 'deleted' ? null : input.byte_length,
    bytes_sha256: status === 'ready' ? input.bytes_sha256 : null, staged_at: CONFIRMED,
    archived_at: status === 'staged' ? null : ARCHIVED, linked_at: status === 'staged' ? null : LINKED, deleted_at: status === 'deleted' ? DELETED : null, confirmation_source: 'user_reported' };
}
export function seeded(owner: Owner, name = 'submitted-original.pdf', index = 0, eventId = EVENT): Metadata {
  return { version: 1, expected_owner_id: owner.session.user.id, opportunity_id: TARGET, contact_event_id: eventId,
    material_id: `00000000-0000-4000-8001-${String(index).padStart(12, '0')}`, record_id: `00000000-0000-4000-8002-${String(index).padStart(12, '0')}`,
    filename: name, mime_type: 'application/pdf', byte_length: PDF.byteLength, bytes_sha256: hash(PDF), attested: true };
}
export async function network(page: Page, owner: Owner, options: { uploadUnknown?: 'ready' | 'staged' | 'absent'; deleteUnknown?: 'deleted' | 'ready'; firstReadFails?: boolean; rejectPdf?: boolean } = {}) {
  const audit = { pageErrors: [] as string[], responses: [] as { path: string; status: number; injected: string | null }[], external: [] as string[] }; audits.set(page, audit);
  page.on('pageerror', error => audit.pageErrors.push(error.message));
  page.on('response', response => { if (response.status() >= 400) audit.responses.push({ path: new URL(response.url()).pathname, status: response.status(), injected: injected.get(response.request()) ?? null }); });
  await page.context().route('**/*', route => { const url = new URL(route.request().url()); if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) { audit.external.push(url.origin); return route.abort('blockedbyclient'); } return route.continue(); });
  const state = { records: new Map<string, RecordWire>(), files: new Map<string, Buffer>(), uploads: [] as Metadata[], bodies: [] as Buffer[], deletions: [] as string[], reads: 0, lookups: 0, downloads: 0, statusWrites: 0, appWrites: 0, contactWrites: 0, applicationMaterialRequests: 0, rejectReads: false, pageFails: false, cursorReads: [] as string[] };
  const event = { event_id: EVENT, device_id: owner.session.user.id, opportunity_id: TARGET, recipient: 'actual-recipient@example.test', subject: 'Original saved message 王', body: 'The original body stays unchanged.', materials: [{ kind: 'profile', version: 'saved-profile-v1' }], actual_sent_at: SUBMITTED, confirmed_at: CONFIRMED, confirmation_source: 'user_reported' };
  const events = [event];
  await page.route('**/rest/v1/contact_events?**', route => route.fulfill({ json: [...events].sort((a, b) => b.confirmed_at.localeCompare(a.confirmed_at) || b.event_id.localeCompare(a.event_id)) }));
  await page.route('**/rest/v1/application_events?**', route => route.fulfill({ json: [{ event_id: EVENT, device_id: owner.session.user.id, opportunity_id: TARGET, channel: 'web_form', destination: 'https://example.test/form', actual_submitted_at: SUBMITTED, notes: null, result_note: null, next_step: null, confirmed_at: CONFIRMED, confirmation_source: 'user_reported' }] }));
  await page.route('**/rest/v1/interaction_status_changes?**', route => route.fulfill({ json: [] }));
  await page.route('**/rest/v1/interactions**', route => { if (route.request().method() !== 'GET') state.statusWrites += 1; return route.fulfill({ json: [] }); });
  await page.route('**/rest/v1/rpc/confirm_application_event', route => { state.appWrites += 1; return route.fulfill({ status: 500, json: {} }); });
  await page.route('**/rest/v1/rpc/confirm_contact_event', route => { state.contactWrites += 1; return route.fulfill({ status: 500, json: {} }); });
  await page.route('**/api/application-materials**', route => { state.applicationMaterialRequests += 1; return route.fulfill({ json: { version: 1, items: [], next_cursor: null } }); });
  await page.route('**/api/contact-materials**', async route => {
    const request = route.request(); const url = new URL(request.url()); const method = request.method();
    expect(request.headers().authorization).toBe(`Bearer ${owner.session.access_token}`);
    if (method === 'POST') {
      const form = await new Response(new Uint8Array(request.postDataBuffer()!).buffer, { headers: { 'Content-Type': request.headers()['content-type'] } }).formData();
      expect([...form.keys()].sort()).toEqual(['file', 'metadata']); const input = JSON.parse(String(form.get('metadata'))) as Metadata;
      const file = form.get('file') as File; const bytes = Buffer.from(await file.arrayBuffer());
      expect(input).toMatchObject({ version: 1, expected_owner_id: owner.session.user.id, opportunity_id: TARGET, contact_event_id: expect.any(String), attested: true, mime_type: 'application/pdf' });
      expect(events.some(event => event.event_id === input.contact_event_id)).toBe(true);
      expect(input).not.toHaveProperty('application_event_id'); expect(input).not.toHaveProperty('artifact_kind');
      expect(bytes.byteLength).toBe(input.byte_length); expect(hash(bytes)).toBe(input.bytes_sha256); expect(file.name).toBe(input.filename);
      state.uploads.push(input); state.bodies.push(bytes); const previous = state.records.get(input.record_id);
      const firstUnknown = options.uploadUnknown && state.uploads.length === 1;
      if (options.rejectPdf && state.uploads.length === 1) { await route.fulfill({ status: 422, json: { detail: { code: 'material_invalid_pdf' } } }); return; }
      if (!(firstUnknown && options.uploadUnknown === 'absent')) {
        const record = fromInput(input, firstUnknown && options.uploadUnknown === 'staged' ? 'staged' : 'ready');
        state.records.set(input.record_id, record); state.files.set(input.record_id, bytes);
      }
      if (firstUnknown) { await fault(route, 503, 'controlled material operation unavailable', { detail: { code: 'material_unavailable' } }); return; }
      await route.fulfill({ json: { version: 1, record: state.records.get(input.record_id), replayed: !!previous && previous.status === 'ready' } }); return;
    }
    const id = url.pathname.split('/')[3];
    if (method === 'DELETE') {
      expect(request.postDataJSON()).toEqual({ expected_owner_id: owner.session.user.id, opportunity_id: TARGET, contact_event_id: expect.any(String), material_id: request.postDataJSON().material_id }); state.deletions.push(id);
      const existing = state.records.get(id) ?? { ...fromInput(state.uploads.find(row => row.record_id === id)!, 'deleted'), archived_at: null, linked_at: null };
      expect(request.postDataJSON().material_id).toBe(existing.material_id);
      if (!(options.deleteUnknown === 'ready' && state.deletions.length === 1)) state.records.set(id, { ...existing, status: 'deleted', filename: null, mime_type: null, byte_length: null, bytes_sha256: null, deleted_at: DELETED });
      if (options.deleteUnknown && state.deletions.length === 1) { await fault(route, 503, 'controlled material operation unavailable', { detail: { code: 'material_unavailable' } }); return; }
      await route.fulfill({ json: { version: 1, record: state.records.get(id) } }); return;
    }
    expect(method).toBe('GET'); expect(url.searchParams.get('expected_owner_id')).toBe(owner.session.user.id); expect(url.searchParams.get('opportunity_id')).toBe(TARGET); expect(events.some(event => event.event_id === url.searchParams.get('contact_event_id'))).toBe(true); expect(url.searchParams.has('application_event_id')).toBe(false);
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
    if (options.firstReadFails && state.reads === 1) { await fault(route, 500, 'controlled first material list failure', { private: 'not shown' }); return; }
    let rows = [...state.records.values()].filter(row => row.linked_at && row.contact_event_id === url.searchParams.get('contact_event_id')).sort((a, b) => b.linked_at!.localeCompare(a.linked_at!) || b.record_id.localeCompare(a.record_id));
    const cursor = url.searchParams.get('cursor_record_id');
    if (cursor) {
      state.cursorReads.push(cursor); if (state.pageFails) { state.pageFails = false; await fault(route, 503, 'controlled material operation unavailable', { detail: { code: 'material_unavailable' } }); return; }
      const linked = url.searchParams.get('cursor_linked_at')!; rows = rows.filter(row => row.linked_at! < linked || (row.linked_at === linked && row.record_id < cursor));
    }
    const items = rows.slice(0, 20); const last = items.at(-1);
    await route.fulfill({ json: { version: 1, items, next_cursor: rows.length > 20 ? { linked_at: last!.linked_at, record_id: last!.record_id } : null } });
  });
  return { state, events };
}

export function addRecord(net: Awaited<ReturnType<typeof network>>, input: Metadata) { net.state.records.set(input.record_id, fromInput(input)); net.state.files.set(input.record_id, PDF); }
