import { Blob as NodeBlob } from 'node:buffer';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
vi.mock('./supabase', () => ({ getAuthState: vi.fn() }));
import { getAuthState } from './supabase';
import { deleteApplicationMaterial, downloadApplicationMaterial, getApplicationMaterial, getApplicationMaterials, uploadApplicationMaterial } from './application-material-api';
import { beginApplicationMaterialDeletion, prepareApplicationMaterialAttempt, readPendingApplicationMaterialAttempts,
  readPendingApplicationMaterialDeletions, settleApplicationMaterialAttempt } from './application-material-storage';
import { captureOwnerToken, OwnerMismatchError } from './identity-owner';
import { OWNER, OTHER, scope, input, file, PDF, wire, record, staged, tombstone, setupOwner, owner, deferred } from './application-material.test-utils';
import type { ApplicationMaterialAttempt } from './application-material';
const auth = vi.mocked(getAuthState); const fetchMock = vi.fn<typeof fetch>();
const options = () => ({ owner: captureOwnerToken() });
const authState = (uid = OWNER, isAnonymous = false) => ({ session: { user: { id: uid }, access_token: 'private-token' },
  user: { id: uid }, isAnonymous, email: 'private@example.test' }) as Awaited<ReturnType<typeof getAuthState>>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const one = (change: Record<string, unknown> = {}, value = input()) => json({ version: 1, record: wire(change, value) });
const post = (value = input(), change: Record<string, unknown> = {}) => json({ version: 1, record: wire(change, value), replayed: false });
const page = (items: unknown[] = [], next_cursor: unknown = null) => json({ version: 1, items, next_cursor });
const error = (code: string, status = 503) => json({ detail: { code } }, status);
const download = (change: Record<string, string> = {}, content = PDF) => new Response(content, { headers: { 'content-type': 'application/pdf',
  'x-ofe-material-id': input().materialId, 'x-ofe-material-record': input().recordId, 'x-ofe-material-sha256': input().bytesSha256, ...change } });
async function prepare(): Promise<ApplicationMaterialAttempt> {
  const prepared = await prepareApplicationMaterialAttempt(captureOwnerToken(), scope, file(), true);
  if (prepared.status !== 'ready') throw new Error('unexpected conflict'); return prepared.attempt;
}
beforeEach(async () => { await setupOwner(); auth.mockReset().mockResolvedValue(authState()); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('Blob', NodeBlob);
  // jsdom's multipart serializer only accepts its own Blob implementation;
  // this structural collector checks exact browser API inputs without network.
  vi.stubGlobal('FormData', class { fields = new Map<string, unknown>(); append(name: string, value: unknown, filename?: string) { this.fields.set(name, filename ? { value, filename } : value); } get(name: string) { return this.fields.get(name); } });
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:material-test') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
it('requires formal same-owner authentication before any HTTP request', async () => {
  for (const state of [authState(OWNER, true), { ...authState(), session: null }, { ...authState(), user: null }]) {
    auth.mockResolvedValueOnce(state); await expect(getApplicationMaterials(scope, options())).rejects.toMatchObject({ code: 'sign_in_required' });
  }
  auth.mockResolvedValueOnce(authState(OTHER)); await expect(getApplicationMaterials(scope, options())).rejects.toBeInstanceOf(OwnerMismatchError);
  expect(fetchMock).not.toHaveBeenCalled();
});
it('sends only scoped opaque query IDs, with bearer/no-store/no-redirect flags', async () => {
  fetchMock.mockResolvedValue(page([wire()])); expect((await getApplicationMaterials(scope, options())).items[0]).toEqual(record());
  const [url, init] = fetchMock.mock.calls[0]; const query = new URL(String(url), 'https://example.test').searchParams;
  expect(Object.fromEntries(query)).toEqual({ expected_owner_id: OWNER, opportunity_id: scope.opportunityId, application_event_id: scope.applicationEventId });
  expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer private-token');
  expect(init).toMatchObject({ cache: 'no-store', redirect: 'error' }); expect(String(url)).not.toContain('résumé');
});
it('only the controlled not_found 404 becomes null; other lookup/read errors remain visible', async () => {
  fetchMock.mockResolvedValueOnce(error('material_not_found', 404)); expect(await getApplicationMaterial(scope, input().recordId, options())).toBeNull();
  for (const response of [error('material_not_found', 500), error('unknown-secret-detail', 404), error('material_unavailable'), new Response('private body', { status: 500 })]) {
    fetchMock.mockResolvedValueOnce(response); await expect(getApplicationMaterial(scope, input().recordId, options())).rejects.toThrow();
  }
  fetchMock.mockResolvedValueOnce(error('material_owner_mismatch', 409)); await expect(getApplicationMaterials(scope, options())).rejects.toBeInstanceOf(OwnerMismatchError);
});
it('rejects unknown wrapper fields, mixed ownership, and an oversized JSON body', async () => {
  for (const response of [json({ version: 2, items: [], next_cursor: null }), json({ version: 1, items: [], next_cursor: null, secret: 'private' }),
    page([wire({ owner_id: OTHER })]), new Response('x'.repeat(128 * 1024 + 1))]) {
    fetchMock.mockResolvedValueOnce(response); await expect(getApplicationMaterials(scope, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  }
});
it('validates strict keyset order, duplicate IDs, tombstones and cursor boundaries', async () => {
  const rows = Array.from({ length: 20 }, (_, i) => wire({ record_id: `00000000-0000-4000-8000-${String(100 - i).padStart(12, '0')}`,
    material_id: `11111111-1111-4111-8111-${String(100 - i).padStart(12, '0')}` }));
  const cursor = { linked_at: rows[19].linked_at, record_id: rows[19].record_id };
  fetchMock.mockResolvedValueOnce(page(rows, cursor)); expect((await getApplicationMaterials(scope, options())).nextCursor).toEqual({ linkedAt: cursor.linked_at, recordId: cursor.record_id });
  for (const response of [page(rows.slice().reverse()), page([wire(), wire()]), page([wire(staged)]), page(rows.concat(rows[0])),
    page(rows, { ...cursor, record_id: input().recordId }), page([wire()], cursor), page([wire({ ...tombstone, archived_at: null, linked_at: null })])]) {
    fetchMock.mockResolvedValueOnce(response); await expect(getApplicationMaterials(scope, options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  }
  fetchMock.mockResolvedValueOnce(page([wire()])); await expect(getApplicationMaterials(scope, { ...options(), cursor: { linkedAt: wire().linked_at, recordId: input().recordId } })).rejects.toMatchObject({ code: 'invalid_receipt' });
});
it('uploads a durably frozen request with original filename even when a same-byte file was renamed', async () => {
  const attempt = await prepare(); fetchMock.mockResolvedValueOnce(post(attempt.input));
  const result = await uploadApplicationMaterial(attempt, file('renamed.pdf'), options());
  expect(result.record).toEqual(record({}, attempt.input)); expect(result.replayed).toBe(false);
  const init = fetchMock.mock.calls[0][1]!; const body = init.body as unknown as { get(name: string): unknown };
  expect(JSON.parse(body.get('metadata') as string)).toEqual({ version: 1, expected_owner_id: OWNER, opportunity_id: scope.opportunityId,
    application_event_id: scope.applicationEventId, material_id: attempt.input.materialId, record_id: attempt.input.recordId,
    filename: attempt.input.filename, mime_type: 'application/pdf', byte_length: attempt.input.byteLength, bytes_sha256: attempt.input.bytesSha256, attested: true });
  expect(body.get('file')).toMatchObject({ filename: attempt.input.filename });
  expect(new Headers(init.headers).has('Content-Type')).toBe(false);
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([attempt]);
});
it('refuses unprepared unseen uploads and mismatching reselected bytes before POST', async () => {
  fetchMock.mockResolvedValueOnce(error('material_not_found', 404));
  await expect(uploadApplicationMaterial({ scope, input: input() }, file(), options())).rejects.toMatchObject({ code: 'invalid_pending' });
  expect(fetchMock).toHaveBeenCalledTimes(1); expect(fetchMock.mock.calls[0][1]?.method).not.toBe('POST'); fetchMock.mockClear();
  const attempt = await prepare(); await expect(uploadApplicationMaterial(attempt, file('other.pdf', '%PDF-same-sized fake other content!'), options())).rejects.toMatchObject({ code: 'file_mismatch' });
  expect(fetchMock).not.toHaveBeenCalled();
});
it('permits a verified existing replay after another tab settles, without clearing a newer pending attempt', async () => {
  const a = await prepare(); await settleApplicationMaterialAttempt(captureOwnerToken(), scope, record({}, a.input)); const b = await prepare();
  fetchMock.mockResolvedValueOnce(one({}, a.input)).mockResolvedValueOnce(post(a.input));
  await uploadApplicationMaterial(a, file(), options());
  expect(fetchMock.mock.calls.map(call => call[1]?.method ?? 'GET')).toEqual(['GET', 'POST']);
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([b]);
});
it('keeps the same pending snapshot on unknown POST results and rejects staged or conflicting receipts', async () => {
  const attempt = await prepare();
  for (const response of [post(attempt.input, staged), post(attempt.input, { bytes_sha256: '0'.repeat(64) }), post(attempt.input, { record_id: input().recordId })]) {
    fetchMock.mockResolvedValueOnce(response); await expect(uploadApplicationMaterial(attempt, file(), options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  }
  fetchMock.mockRejectedValueOnce(new Error('private backend error')); await expect(uploadApplicationMaterial(attempt, file(), options())).rejects.toMatchObject({ code: 'unavailable' });
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([attempt]);
});
it('retains opaque deletion intent after unknown DELETE, blocks upload/download, and only tombstone settles', async () => {
  const attempt = await prepare(); const ids = { recordId: attempt.input.recordId, materialId: attempt.input.materialId };
  fetchMock.mockImplementationOnce(async () => { expect(readPendingApplicationMaterialDeletions(captureOwnerToken(), scope)).toHaveLength(1); throw new Error('uncertain'); });
  await expect(deleteApplicationMaterial(scope, ids, options())).rejects.toMatchObject({ code: 'unavailable' });
  await expect(uploadApplicationMaterial(attempt, file(), options())).rejects.toMatchObject({ code: 'deleted' });
  await expect(downloadApplicationMaterial(scope, record({}, attempt.input), options())).rejects.toMatchObject({ code: 'deleted' });
  fetchMock.mockResolvedValueOnce(one({}, attempt.input)); await getApplicationMaterial(scope, ids.recordId, options());
  expect(readPendingApplicationMaterialDeletions(captureOwnerToken(), scope)).toHaveLength(1);
  fetchMock.mockResolvedValueOnce(one(tombstone, attempt.input)); expect((await deleteApplicationMaterial(scope, ids, options())).status).toBe('deleted');
  expect(readPendingApplicationMaterialDeletions(captureOwnerToken(), scope)).toEqual([]); expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([]);
});
it('does not settle deletion with a mismatched material or non-tombstone response', async () => {
  for (const change of [{}, { ...tombstone, material_id: OTHER }]) {
    fetchMock.mockResolvedValueOnce(one(change)); await expect(deleteApplicationMaterial(scope, input(), options())).rejects.toMatchObject({ code: 'invalid_receipt' });
    expect(readPendingApplicationMaterialDeletions(captureOwnerToken(), scope)).toHaveLength(1);
  }
});
it('validates complete original bytes and headers before downloading with the archived filename', async () => {
  fetchMock.mockResolvedValueOnce(download({ 'content-disposition': 'attachment; filename="unsafe.html"' }));
  await downloadApplicationMaterial(scope, record(), options());
  expect(URL.createObjectURL).toHaveBeenCalledOnce(); expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce();
  const clicked = vi.mocked(HTMLAnchorElement.prototype.click).mock.contexts[0] as HTMLAnchorElement; expect(clicked.download).toBe(input().filename);
  const blob = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob; expect(await blob.text()).toBe(PDF);
});
it.each([
  ['wrong hash header', { 'x-ofe-material-sha256': 'f'.repeat(64) }, PDF],
  ['wrong material', { 'x-ofe-material-id': OTHER }, PDF], ['wrong record', { 'x-ofe-material-record': OTHER }, PDF],
  ['wrong MIME', { 'content-type': 'text/html' }, PDF], ['truncated bytes', {}, PDF.slice(1)],
  ['oversized bytes', {}, PDF + 'x'], ['wrong actual hash', {}, PDF.replace('exact', 'xxxxx')],
  ['wrong actual count', { 'content-length': '1' }, PDF],
])('does not download %s', async (_name, headers, bytes) => {
  fetchMock.mockResolvedValueOnce(download(headers, bytes)); await expect(downloadApplicationMaterial(scope, record(), options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
it('blocks a stream result after another tab requests deletion', async () => {
  const gate = deferred<void>(); let sent = false;
  const response = download();
  const stream = new ReadableStream<Uint8Array>({ async pull(controller) { await gate.promise; if (!sent) { sent = true; controller.enqueue(new TextEncoder().encode(PDF)); } else controller.close(); } });
  fetchMock.mockResolvedValueOnce(new Response(stream, { headers: response.headers }));
  const result = downloadApplicationMaterial(scope, record(), options()); const check = expect(result).rejects.toMatchObject({ code: 'deleted' });
  await beginApplicationMaterialDeletion(captureOwnerToken(), scope, input().recordId, input().materialId); gate.resolve(); await check;
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
it('retires late authentication, fetch and body results when ownership changes', async () => {
  for (const stage of ['auth', 'fetch', 'body']) {
    await owner(); auth.mockReset().mockResolvedValue(authState()); fetchMock.mockReset();
    const gate = deferred<Response>(); const authGate = deferred<Awaited<ReturnType<typeof getAuthState>>>();
    const bodyGate = deferred<ReadableStreamReadResult<Uint8Array>>(); const read = vi.fn(() => bodyGate.promise);
    if (stage === 'auth') auth.mockReturnValueOnce(authGate.promise);
    else if (stage === 'fetch') fetchMock.mockReturnValueOnce(gate.promise);
    else { const response = page(); Object.defineProperty(response, 'body', { value: { getReader: () => ({ read, cancel: async () => {} }) } }); fetchMock.mockResolvedValueOnce(response); }
    const result = getApplicationMaterials(scope, options()); const check = expect(result).rejects.toBeInstanceOf(OwnerMismatchError);
    if (stage === 'auth') await vi.waitFor(() => expect(auth).toHaveBeenCalledOnce());
    else if (stage === 'fetch') await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    else await vi.waitFor(() => expect(read).toHaveBeenCalledOnce());
    await owner(OTHER); await check;
    authGate.resolve(authState()); gate.resolve(page()); bodyGate.resolve({ done: true, value: undefined });
  }
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
it('does not create a download after ownership changes while its final digest is pending', async () => {
  const gate = deferred<ArrayBuffer>(); const digest = vi.spyOn(crypto.subtle, 'digest').mockReturnValueOnce(gate.promise);
  fetchMock.mockResolvedValueOnce(download()); const result = downloadApplicationMaterial(scope, record(), options());
  const check = expect(result).rejects.toBeInstanceOf(OwnerMismatchError);
  await vi.waitFor(() => expect(digest).toHaveBeenCalledOnce()); await owner(OTHER); await check;
  gate.resolve(new ArrayBuffer(32)); expect(URL.createObjectURL).not.toHaveBeenCalled();
});
it('copies caller scope and owner before authentication awaits', async () => {
  const held = deferred<Awaited<ReturnType<typeof getAuthState>>>(); auth.mockReturnValueOnce(held.promise); fetchMock.mockResolvedValueOnce(page());
  const target = { ...scope }; const token = captureOwnerToken(); const result = getApplicationMaterials(target, { owner: token });
  target.opportunityId = 'mutated'; token.uid = OTHER; held.resolve(authState()); await result;
  expect(String(fetchMock.mock.calls[0][0])).toContain('expected_owner_id=' + OWNER);
  expect(String(fetchMock.mock.calls[0][0])).not.toContain('mutated');
});

it('checks decoded bytes against the archived size when transport compression changes Content-Length', async () => {
  fetchMock.mockResolvedValueOnce(download({ 'content-encoding': 'gzip', 'content-length': '10' }));
  await downloadApplicationMaterial(scope, record(), options()); expect(URL.createObjectURL).toHaveBeenCalledOnce();
});

it('aborts the network body when headers fail before any download bytes are accepted', async () => {
  fetchMock.mockResolvedValueOnce(download({ 'x-ofe-material-id': OTHER }));
  await expect(downloadApplicationMaterial(scope, record(), options())).rejects.toMatchObject({ code: 'invalid_receipt' });
  expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true); expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it('cancels an unstarted upload using both frozen IDs and clears it only after the permanent tombstone', async () => {
  const attempt = await prepare(); const ids = { recordId: attempt.input.recordId, materialId: attempt.input.materialId };
  fetchMock.mockImplementationOnce(async (url, init) => {
    expect(String(url)).toBe('/api/application-materials/' + ids.recordId);
    expect(init?.method).toBe('DELETE');
    expect(JSON.parse(init?.body as string)).toEqual({ expected_owner_id: OWNER, opportunity_id: scope.opportunityId,
      application_event_id: scope.applicationEventId, material_id: ids.materialId });
    expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([attempt]);
    expect(readPendingApplicationMaterialDeletions(captureOwnerToken(), scope)).toHaveLength(1);
    return one({ ...tombstone, archived_at: null, linked_at: null }, attempt.input);
  });
  const removed = await deleteApplicationMaterial(scope, ids, options());
  expect(removed).toMatchObject({ status: 'deleted', archivedAt: null, linkedAt: null, filename: null });
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([]);
  expect(readPendingApplicationMaterialDeletions(captureOwnerToken(), scope)).toEqual([]);
  const next = await prepare(); expect(next.input.materialId).not.toBe(ids.materialId);
  // A late known-ID replay must discover the permanent tombstone rather than
  // using the new pending slot as authorization to resurrect the old upload.
  fetchMock.mockResolvedValueOnce(one({ ...tombstone, archived_at: null, linked_at: null }, attempt.input));
  await expect(uploadApplicationMaterial(attempt, file(), options())).rejects.toMatchObject({ code: 'deleted' });
  expect(fetchMock.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(0);
  expect(readPendingApplicationMaterialAttempts(captureOwnerToken(), scope)).toEqual([next]);
});
