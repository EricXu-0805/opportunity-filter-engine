import { Blob as NodeBlob } from 'node:buffer';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
vi.mock('./supabase', () => ({ getAuthState: vi.fn() }));
import { getAuthState } from './supabase';
import { deleteContactMaterial, downloadContactMaterial, getContactMaterial, getContactMaterials, uploadContactMaterial } from './contact-material-api';
import { getApplicationMaterials } from './application-material-api';
import { beginContactMaterialDeletion, prepareContactMaterialAttempt, readPendingContactMaterialAttempts, readPendingContactMaterialDeletions } from './contact-material-storage';
import { prepareApplicationMaterialAttempt } from './application-material-storage';
import { parseContactMaterialRecord } from './contact-material';
import { captureOwnerToken, OwnerMismatchError } from './identity-owner';
import { OWNER, OTHER, scope as applicationScope, input, file, PDF, wire, tombstone, setupOwner, owner, deferred } from './application-material.test-utils';

const scope = { opportunityId: applicationScope.opportunityId, contactEventId: applicationScope.applicationEventId };
const auth = vi.mocked(getAuthState); const fetchMock = vi.fn<typeof fetch>();
const options = () => ({ owner: captureOwnerToken() });
const authState = () => ({ session: { user: { id: OWNER }, access_token: 'private-token' }, user: { id: OWNER }, isAnonymous: false, email: 'private@example.test' }) as Awaited<ReturnType<typeof getAuthState>>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const page = (items: unknown[] = [], next_cursor: unknown = null) => json({ version: 1, items, next_cursor });
function contactWire(changes: Record<string, unknown> = {}, selected = input()) { const { application_event_id, ...rest } = wire({}, selected); return { ...rest, contact_event_id: application_event_id, ...changes }; }
const one = (changes: Record<string, unknown> = {}, selected = input()) => json({ version: 1, record: contactWire(changes, selected) });
const record = (changes: Record<string, unknown> = {}, selected = input()) => parseContactMaterialRecord(contactWire(changes, selected), OWNER, scope);
const download = (content = PDF, changes: Record<string, string> = {}) => new Response(content, { headers: { 'content-type': 'application/pdf',
  'x-ofe-material-id': input().materialId, 'x-ofe-material-record': input().recordId, 'x-ofe-material-sha256': input().bytesSha256, ...changes } });
async function prepare() { const result = await prepareContactMaterialAttempt(captureOwnerToken(), scope, file(), true); if (result.status !== 'ready') throw new Error('unexpected conflict'); return result.attempt; }
beforeEach(async () => {
  await setupOwner(); auth.mockReset().mockResolvedValue(authState()); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); vi.stubGlobal('Blob', NodeBlob);
  vi.stubGlobal('FormData', class { fields = new Map<string, unknown>(); append(name: string, value: unknown, filename?: string) { this.fields.set(name, filename ? { value, filename } : value); } get(name: string) { return this.fields.get(name); } });
  URL.createObjectURL = vi.fn(() => 'blob:contact-test'); URL.revokeObjectURL = vi.fn(); vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('uses contact-only scope and authenticated no-store requests for list and lookup', async () => {
  fetchMock.mockResolvedValueOnce(page([contactWire()])).mockResolvedValueOnce(one());
  expect((await getContactMaterials(scope, options())).items).toEqual([record()]);
  expect(await getContactMaterial(scope, input().recordId, options())).toEqual(record());
  for (const [url, init] of fetchMock.mock.calls) {
    const parsed = new URL(String(url), 'https://example.test'); expect(parsed.pathname).toMatch(/^\/api\/contact-materials/);
    expect(Object.fromEntries(parsed.searchParams)).toEqual({ expected_owner_id: OWNER, opportunity_id: scope.opportunityId, contact_event_id: scope.contactEventId });
    expect(init).toMatchObject({ cache: 'no-store', redirect: 'error' }); expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer private-token');
  }
  expect(auth).toHaveBeenCalledWith({ throwOnError: true });
});
it('keeps application responses out of contact lists and contact responses out of application lists', async () => {
  fetchMock.mockResolvedValueOnce(page([wire()])); await expect(getContactMaterials(scope, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  fetchMock.mockResolvedValueOnce(page([contactWire()])); await expect(getApplicationMaterials(applicationScope, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
});
it.each(['contact', 'application'])('does not translate a failed strict auth read into a signed-out %s request', async kind => {
  auth.mockRejectedValue(new Error('sensitive auth diagnostics'));
  const result = kind === 'contact' ? getContactMaterials(scope, options()) : getApplicationMaterials(applicationScope, options());
  await expect(result).rejects.toMatchObject({ code: 'unavailable' }); expect(fetchMock).not.toHaveBeenCalled();
});
it('posts the selected original file using contact metadata only and retains the pending record until settlement', async () => {
  const attempt = await prepare(); fetchMock.mockResolvedValueOnce(json({ version: 1, record: contactWire({}, attempt.input), replayed: false }));
  const selected = file('renamed.pdf'); expect((await uploadContactMaterial(attempt, selected, options())).record).toEqual(record({}, attempt.input));
  const [url, init] = fetchMock.mock.calls[0]; expect(url).toBe('/api/contact-materials'); expect(init?.method).toBe('POST');
  const body = init?.body as unknown as { get(name: string): unknown };
  expect(JSON.parse(body.get('metadata') as string)).toEqual({ version: 1, expected_owner_id: OWNER, opportunity_id: scope.opportunityId,
    contact_event_id: scope.contactEventId, material_id: attempt.input.materialId, record_id: attempt.input.recordId,
    filename: attempt.input.filename, mime_type: 'application/pdf', byte_length: attempt.input.byteLength, bytes_sha256: attempt.input.bytesSha256, attested: true });
  expect(body.get('file')).toEqual({ value: selected, filename: attempt.input.filename });
  expect(readPendingContactMaterialAttempts(captureOwnerToken(), scope)).toEqual([attempt]);
});
it('cannot use an application pending attempt to authorize a contact upload', async () => {
  const app = await prepareApplicationMaterialAttempt(captureOwnerToken(), applicationScope, file(), true);
  if (app.status !== 'ready') throw new Error('unexpected conflict');
  fetchMock.mockResolvedValue(json({ detail: { code: 'material_not_found' } }, 404));
  await expect(uploadContactMaterial({ scope, input: app.attempt.input }, file(), options())).rejects.toMatchObject({ code: 'invalid_pending' });
  expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true);
  expect(readPendingContactMaterialAttempts(captureOwnerToken(), scope)).toEqual([]);
});
it('keeps unknown upload and deletion pending; only a verified contact tombstone settles both', async () => {
  const attempt = await prepare(); fetchMock.mockRejectedValueOnce(new Error('lost upload reply'));
  await expect(uploadContactMaterial(attempt, file(), options())).rejects.toMatchObject({ code: 'unavailable' });
  expect(fetchMock).toHaveBeenCalledOnce(); expect(readPendingContactMaterialAttempts(captureOwnerToken(), scope)).toEqual([attempt]);
  fetchMock.mockRejectedValueOnce(new Error('lost delete reply'));
  await expect(deleteContactMaterial(scope, attempt.input, options())).rejects.toMatchObject({ code: 'unavailable' });
  expect(readPendingContactMaterialDeletions(captureOwnerToken(), scope)).toHaveLength(1);
  await expect(uploadContactMaterial(attempt, file(), options())).rejects.toMatchObject({ code: 'deleted' });
  fetchMock.mockResolvedValueOnce(one(tombstone, attempt.input)); expect((await deleteContactMaterial(scope, attempt.input, options())).status).toBe('deleted');
  const [url, init] = fetchMock.mock.calls.at(-1)!; expect(url).toBe(`/api/contact-materials/${attempt.input.recordId}`);
  expect(JSON.parse(init!.body as string)).toEqual({ expected_owner_id: OWNER, opportunity_id: scope.opportunityId, contact_event_id: scope.contactEventId, material_id: attempt.input.materialId });
  expect(readPendingContactMaterialAttempts(captureOwnerToken(), scope)).toEqual([]); expect(readPendingContactMaterialDeletions(captureOwnerToken(), scope)).toEqual([]);
});
it('downloads verified original bytes with the archived name, not a response filename', async () => {
  fetchMock.mockResolvedValueOnce(download(PDF, { 'content-disposition': 'attachment; filename="unsafe.html"' }));
  await downloadContactMaterial(scope, record(), options());
  expect(fetchMock.mock.calls[0][0]).toContain(`/api/contact-materials/${input().recordId}/file?`);
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce();
  expect((vi.mocked(HTMLAnchorElement.prototype.click).mock.contexts[0] as HTMLAnchorElement).download).toBe(input().filename);
  expect(await (vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob).text()).toBe(PDF);
});
it('does not release mismatched download bytes or another record ID', async () => {
  for (const response of [download(PDF.replace('exact', 'xxxxx')), download(PDF, { 'x-ofe-material-record': OTHER })]) {
    fetchMock.mockResolvedValueOnce(response); await expect(downloadContactMaterial(scope, record(), options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  }
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
it('blocks a download when another tab records contact deletion while the response is pending', async () => {
  const gate = deferred<Response>(); fetchMock.mockReturnValueOnce(gate.promise);
  const pending = downloadContactMaterial(scope, record(), options()); const rejected = expect(pending).rejects.toMatchObject({ code: 'deleted' });
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
  await beginContactMaterialDeletion(captureOwnerToken(), scope, input().recordId, input().materialId); gate.resolve(download()); await rejected;
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
it('rejects a late contact response after the owner changes', async () => {
  const gate = deferred<Response>(); fetchMock.mockReturnValueOnce(gate.promise);
  const pending = getContactMaterials(scope, options()); const rejected = expect(pending).rejects.toBeInstanceOf(OwnerMismatchError);
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce()); await owner(OTHER); gate.resolve(page([contactWire()])); await rejected;
  expect((fetchMock.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
});
it('uses contact pagination and rejects an application row hidden in the next page', async () => {
  const cursor = { linkedAt: '2026-09-25T12:00:01Z', recordId: OTHER };
  fetchMock.mockResolvedValueOnce(page([contactWire()])); await getContactMaterials(scope, { ...options(), cursor });
  const query = new URL(String(fetchMock.mock.calls[0][0]), 'https://example.test').searchParams;
  expect(query.get('cursor_linked_at')).toBe(cursor.linkedAt); expect(query.get('cursor_record_id')).toBe(OTHER);
  fetchMock.mockResolvedValueOnce(page([wire()])); await expect(getContactMaterials(scope, { ...options(), cursor })).rejects.toMatchObject({ code: 'invalid_receipt' });
});
