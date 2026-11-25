import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-key';
  return { session: vi.fn(), anon: vi.fn(), list: vi.fn(), upload: vi.fn(), replace: vi.fn(), rpc: vi.fn(), remove: vi.fn(), signed: vi.fn(), from: vi.fn() };
});
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({
  auth: { getSession: mocks.session, signInAnonymously: mocks.anon },
  storage: { from: mocks.from }, rpc: mocks.rpc,
}) }));
import { ATTACHMENTS_BUCKET, listAttachments, uploadAttachment, replaceAttachment, deleteAttachment, getAttachmentSignedUrl } from './supabase';
import { ATTACHMENT_REQUEST_TIMEOUT_MS, AttachmentRequestError } from './attachment-request';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, OwnerMismatchError } from './identity-owner';
const U1 = '11111111-1111-4111-8111-111111111111';
const U2 = '22222222-2222-4222-8222-222222222222';
const OPP = 'faculty-old-opportunity';
const path = `${U1}/${OPP}/resume.pdf`;
const file = () => new File(['original bytes'], 'resume.pdf', { type: 'application/pdf' });
const session = (uid: string | null = U1, guest = false) => ({ data: { session: uid ? { user: { id: uid, is_anonymous: guest }, access_token: 'token' } : null }, error: null });
const row = { name: 'resume.pdf', id: 'object-id', metadata: { size: 14, mimetype: 'application/pdf' }, created_at: '2026-01-01T00:00:00Z' };
const target = { name: 'resume.pdf', sizeBytes: 14, mimeType: 'application/pdf', createdAt: row.created_at,
  revision: { id: row.id, etag: '"original"', updatedAt: null } };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (cause: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
async function until(check: () => boolean) { for (let i = 0; i < 100 && !check(); i++) await Promise.resolve(); expect(check()).toBe(true); }
async function owner(uid: string) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }
beforeEach(async () => {
  vi.clearAllMocks(); localStorage.clear(); await owner(U1);
  mocks.session.mockReset().mockResolvedValue(session());
  mocks.list.mockReset().mockResolvedValue({ data: [row], error: null });
  mocks.upload.mockReset().mockImplementation(async (uploadedPath: string) => ({ data: { path: uploadedPath, id: 'object-id' }, error: null }));
  mocks.rpc.mockReset().mockResolvedValue({ data: 'old-version', error: null });
  mocks.replace.mockReset().mockResolvedValue({ data: { path, id: row.id }, error: null });
  mocks.remove.mockReset().mockResolvedValue({ data: [{ name: path }], error: null });
  mocks.signed.mockReset().mockResolvedValue({ data: { signedUrl: 'https://test.supabase.co/original.pdf' }, error: null });
  mocks.from.mockImplementation(() => ({ list: mocks.list, upload: mocks.upload, update: mocks.replace, remove: mocks.remove, createSignedUrl: mocks.signed }));
});
afterEach(() => { vi.useRealTimers(); });
const operations = {
  list: (signal?: AbortSignal) => listAttachments(OPP, captureOwnerToken(), { signal }),
  upload: (signal?: AbortSignal) => uploadAttachment(OPP, file(), captureOwnerToken(), { signal }),
  replace: (signal?: AbortSignal) => replaceAttachment(OPP, target, file(), captureOwnerToken(), { signal }),
  remove: (signal?: AbortSignal) => deleteAttachment(OPP, 'resume.pdf', captureOwnerToken(), { signal }),
  signed: (signal?: AbortSignal) => getAttachmentSignedUrl(OPP, 'resume.pdf', 300, captureOwnerToken(), { signal }),
};

describe('legacy attachment protocol and failures', () => {
  it('uses the old bucket/prefix and preserves actual metadata', async () => {
    expect(await operations.list()).toEqual([{ name: 'resume.pdf', sizeBytes: 14, mimeType: 'application/pdf', createdAt: row.created_at }]);
    expect(mocks.from).toHaveBeenCalledWith(ATTACHMENTS_BUCKET);
    expect(ATTACHMENTS_BUCKET).toBe('tracker-attachments');
    expect(mocks.list).toHaveBeenCalledWith(`${U1}/${OPP}`, { limit: 100, offset: 0, sortBy: { column: 'name', order: 'asc' } }, { signal: expect.any(AbortSignal) });
  });
  const namedRows = (count: number) => Array.from({ length: count }, (_, i) => {
    const name = `file-${String(i).padStart(3, '0')}.pdf`;
    return { ...row, name, id: name };
  });
  it.each([100, 101, 199, 205])('reads every file when Storage lists %i raw entries', async count => {
    const objects = namedRows(count);
    objects[1].created_at = '2025-01-01T00:00:00Z';
    objects[count - 1].created_at = '2026-02-01T00:00:00Z';
    const entries = [{ name: '.emptyFolderPlaceholder' }, ...objects.slice(1, 49),
      { name: 'file-049', id: null, metadata: null }, ...objects.slice(50)];
    mocks.list.mockImplementation(async (_prefix, { offset, limit }) => ({
      data: entries.slice(offset, offset + limit), error: null,
    }));
    const result = await operations.list();
    expect(result.map(file => file.name)).toEqual([objects[count - 1], ...objects.slice(2, 49),
      ...objects.slice(50, -1), objects[1]].map(file => file.name));
    expect(mocks.list.mock.calls.map(call => call[1].offset)).toEqual(entries.length <= 198 ? [0, 99] : [0, 99, 198]);
  });
  it.each(['failed', 'shifted', 'empty'])('rejects an incomplete read when the next page is %s and retries from the beginning', async failure => {
    const objects = namedRows(101);
    mocks.list.mockResolvedValueOnce({ data: objects.slice(0, 100), error: null });
    if (failure === 'failed') mocks.list.mockResolvedValueOnce({ data: null, error: { statusCode: '503' } });
    if (failure === 'shifted') mocks.list.mockResolvedValueOnce({ data: objects.slice(100), error: null });
    if (failure === 'empty') mocks.list.mockResolvedValueOnce({ data: [], error: null });
    await expect(operations.list()).rejects.toMatchObject({ code: 'unavailable' });
    mocks.list.mockImplementation(async (_prefix, { offset, limit }) => ({ data: objects.slice(offset, offset + limit), error: null }));
    expect((await operations.list()).map(file => file.name)).toEqual(objects.map(file => file.name));
    expect(mocks.list.mock.calls.map(call => call[1].offset)).toEqual([0, 99, 0, 99]);
  });
  it('only a successful empty array means empty; absent data and SDK error are failures', async () => {
    mocks.list.mockResolvedValueOnce({ data: [], error: null }).mockResolvedValueOnce({ data: null, error: null }).mockResolvedValueOnce({ data: [], error: { message: 'private details' } });
    expect(await operations.list()).toEqual([]);
    await expect(operations.list()).rejects.toMatchObject({ code: 'unavailable' });
    await expect(operations.list()).rejects.toMatchObject({ code: 'unavailable', message: 'Attachment request could not be completed' });
  });
  it('ignores storage virtual directories/placeholders but keeps old metadata-light files without inventing dates', async () => {
    mocks.list.mockResolvedValue({ data: [{ name: 'folder', id: null, metadata: null }, { name: '.emptyFolderPlaceholder' }, { name: 'trailing/' }, { name: 'old.txt', id: 'old-id', metadata: null }], error: null });
    expect(await operations.list()).toEqual([{ name: 'old.txt', sizeBytes: 0, mimeType: 'application/octet-stream', createdAt: '' }]);
  });
  it.each([null, { name: 12 }, { name: 'wrong/target.pdf' }, { name: 'size.pdf', metadata: { size: -1 } }])('malformed row cannot become successful empty or a usable file (%j)', async bad => {
    mocks.list.mockResolvedValue({ data: [bad], error: null });
    await expect(operations.list()).rejects.toBeInstanceOf(AttachmentRequestError);
  });
  it('uploads original bytes to the compatible sanitized path without upsert', async () => {
    const original = new File(['original bytes'], '../res:ume.pdf', { type: 'application/pdf' });
    expect(await uploadAttachment(OPP, original, captureOwnerToken())).toEqual({ ok: true, name: '_res_ume.pdf' });
    expect(mocks.upload).toHaveBeenCalledWith(`${U1}/${OPP}/_res_ume.pdf`, original, { contentType: 'application/pdf', upsert: false });
  });
  it('rejects unsupported or oversized files before touching auth/storage', async () => {
    expect(await uploadAttachment(OPP, new File(['x'], 'a.exe', { type: 'application/octet-stream' }), captureOwnerToken())).toEqual({ ok: false, reason: 'wrong_type' });
    const huge = file(); Object.defineProperty(huge, 'size', { value: 5 * 1024 * 1024 + 1 });
    expect(await uploadAttachment(OPP, huge, captureOwnerToken())).toEqual({ ok: false, reason: 'too_large' });
    expect(mocks.session).not.toHaveBeenCalled(); expect(mocks.from).not.toHaveBeenCalled();
  });
  it.each([null, { path: 'wrong-account/resume.pdf', id: 'object-id' }, { path }])('incomplete or mismatched upload receipt cannot claim completion (%j)', async receipt => {
    mocks.upload.mockResolvedValue({ data: receipt, error: null });
    await expect(operations.upload()).rejects.toMatchObject({ code: 'unavailable' });
  });
  it('a guest session cannot upload: refused before any storage request, while its files stay readable', async () => {
    mocks.session.mockResolvedValue(session(U1, true));
    expect(await operations.upload()).toEqual({ ok: false, reason: 'guest' });
    expect(mocks.from).not.toHaveBeenCalled(); expect(mocks.upload).not.toHaveBeenCalled();
    expect(await operations.list()).toHaveLength(1);
    expect(await operations.remove()).toBe(true);
  });
  it('duplicate is a safe explicit refusal with no server message', async () => {
    mocks.upload.mockResolvedValue({ data: null, error: { message: 'Duplicate private path secret' } });
    expect(await operations.upload()).toEqual({ ok: false, reason: 'duplicate' });
  });
  it('empty or unrelated delete receipt is not confirmation', async () => {
    mocks.remove.mockResolvedValueOnce({ data: [], error: null }).mockResolvedValueOnce({ data: [{ name: 'someone-else/file.pdf' }], error: null });
    await expect(operations.remove()).rejects.toMatchObject({ code: 'unavailable' });
    await expect(operations.remove()).rejects.toMatchObject({ code: 'unavailable' });
  });
  it('confirmed delete and signed URL use only the old owner path', async () => {
    expect(await operations.remove()).toBe(true); expect(mocks.remove).toHaveBeenCalledWith([path]);
    expect(await operations.signed()).toBe('https://test.supabase.co/original.pdf');
    expect(mocks.signed).toHaveBeenCalledWith(path, 300);
  });
  it.each(['javascript:alert(1)', 'data:text/html,secret', 'http://external.example/file'])('refuses unsafe signed URL %s', async url => {
    mocks.signed.mockResolvedValue({ data: { signedUrl: url }, error: null });
    await expect(operations.signed()).rejects.toMatchObject({ code: 'unavailable' });
  });
});

for (const [kind, request] of Object.entries(operations)) describe(`${kind}: bounded auth/storage and identity`, () => {
  it('no session is distinct from read failure, and never creates an anonymous account', async () => {
    mocks.session.mockResolvedValue(session(null));
    await expect(request()).rejects.toMatchObject({ code: 'unauthenticated' });
    expect(mocks.from).not.toHaveBeenCalled(); expect(mocks.anon).not.toHaveBeenCalled();
  });
  it.each(['returned', 'rejected'])('auth %s failure is unavailable, without a storage request', async mode => {
    if (mode === 'returned') mocks.session.mockResolvedValue({ ...session(), error: new Error('SDK secret') });
    else mocks.session.mockRejectedValue(new Error('SDK secret'));
    await expect(request()).rejects.toMatchObject({ code: 'unavailable' }); expect(mocks.from).not.toHaveBeenCalled();
  });
  it('SDK resolving another uid without its callback cannot borrow this owner token', async () => {
    mocks.session.mockResolvedValue(session(U2));
    await expect(request()).rejects.toBeInstanceOf(OwnerMismatchError); expect(mocks.from).not.toHaveBeenCalled();
  });
  it('owner changes during auth: no old request reaches storage under the new account', async () => {
    const pending = deferred<ReturnType<typeof session>>(); mocks.session.mockReturnValue(pending.promise);
    const read = request(); const rejected = expect(read).rejects.toBeInstanceOf(OwnerMismatchError);
    await owner(U2); pending.resolve(session(U2)); await rejected; expect(mocks.from).not.toHaveBeenCalled();
  });
  it('owner changes while storage is pending: no old result is accepted', async () => {
    const pending = deferred<never>(); mocks[kind as keyof typeof operations].mockReturnValue(pending.promise);
    const read = request(); const rejected = expect(read).rejects.toBeInstanceOf(OwnerMismatchError);
    await until(() => mocks[kind as keyof typeof operations].mock.calls.length === 1);
    await owner(U2); pending.reject(new Error('late private error')); await rejected;
  });
  it('stalled auth times out; resolving it later never starts the storage operation', async () => {
    vi.useFakeTimers(); const pending = deferred<ReturnType<typeof session>>(); mocks.session.mockReturnValue(pending.promise);
    const read = request(); const rejected = expect(read).rejects.toMatchObject({ code: 'timeout' });
    await vi.advanceTimersByTimeAsync(ATTACHMENT_REQUEST_TIMEOUT_MS); await rejected;
    pending.resolve(session()); await Promise.resolve(); await Promise.resolve(); expect(mocks.from).not.toHaveBeenCalled();
  });
  it('one deadline spans auth and storage; no timeout retries the operation', async () => {
    vi.useFakeTimers(); const auth = deferred<ReturnType<typeof session>>(); mocks.session.mockReturnValue(auth.promise);
    const pending = deferred<never>(); mocks[kind as keyof typeof operations].mockReturnValue(pending.promise);
    const read = request(); const rejected = expect(read).rejects.toMatchObject({ code: 'timeout' });
    await vi.advanceTimersByTimeAsync(20_000); auth.resolve(session()); await until(() => mocks[kind as keyof typeof operations].mock.calls.length === 1);
    await vi.advanceTimersByTimeAsync(10_000); await rejected;
    pending.reject(new Error('late SDK rejection')); await Promise.resolve(); expect(mocks[kind as keyof typeof operations]).toHaveBeenCalledTimes(1);
  });
  it('caller cancellation settles promptly and ignores late failures', async () => {
    const pending = deferred<never>(); mocks[kind as keyof typeof operations].mockReturnValue(pending.promise);
    const controller = new AbortController(); const read = request(controller.signal); const rejected = expect(read).rejects.toMatchObject({ name: 'AbortError' });
    await until(() => mocks[kind as keyof typeof operations].mock.calls.length === 1); controller.abort(); await rejected;
    pending.reject(new Error('late')); await Promise.resolve(); expect(mocks[kind as keyof typeof operations]).toHaveBeenCalledTimes(1);
  });
  it('SDK 401 is session-required; SDK 403 is unavailable, not empty/success', async () => {
    mocks[kind as keyof typeof operations].mockResolvedValueOnce({ data: null, error: { statusCode: '401' } }).mockResolvedValueOnce({ data: null, error: { statusCode: '403' } });
    await expect(request()).rejects.toMatchObject({ code: 'unauthenticated' });
    await expect(request()).rejects.toMatchObject({ code: 'unavailable' });
  });
});

describe('conditional attachment replacement', () => {
  it('retains list evidence for the selected file and sends new bytes to its original path', async () => {
    mocks.list.mockResolvedValue({ data: [{ ...row, metadata: { ...row.metadata, eTag: '"original"' } }], error: null });
    const [selection] = await operations.list();
    expect(selection.revision).toEqual(target.revision);
    const next = new File(['new bytes'], 'revised.PDF', { type: 'application/pdf' });
    expect(await replaceAttachment(OPP, selection, next, captureOwnerToken())).toEqual({ ok: true, name: row.name });
    expect(mocks.rpc).toHaveBeenCalledWith('tracker_attachment_replace_version', {
      p_path: path, p_id: row.id, p_etag: '"original"', p_updated_at: null, p_mime: 'application/pdf',
    });
    expect(mocks.replace).toHaveBeenCalledWith(path, next, {
      contentType: 'application/pdf', metadata: { ofe_replace: { id: row.id, version: 'old-version', mime: 'application/pdf' } },
    });
    expect(mocks.upload).not.toHaveBeenCalled(); expect(mocks.remove).not.toHaveBeenCalled();
  });
  it.each([['wrong.png', 'application/pdf'], ['wrong.pdf', 'image/png'], ['no-extension', 'application/pdf']])(
    'refuses an inconsistent new file %s/%s before any storage access', async (name, type) => {
      const f = new File(['bytes'], name, { type });
      expect(await replaceAttachment(OPP, target, f, captureOwnerToken())).toEqual({ ok: false, reason: 'format' });
      expect(mocks.rpc).not.toHaveBeenCalled(); expect(mocks.replace).not.toHaveBeenCalled();
    });
  it('refuses a signed-out guest, a missing migration, and a changed selection before PUT', async () => {
    mocks.session.mockResolvedValueOnce(session(U1, true));
    expect(await operations.replace()).toEqual({ ok: false, reason: 'guest' });
    mocks.rpc.mockResolvedValueOnce({ data: null, error: { code: 'PGRST202' } });
    expect(await operations.replace()).toEqual({ ok: false, reason: 'replace_unavailable' });
    mocks.rpc.mockResolvedValueOnce({ data: null, error: null });
    expect(await operations.replace()).toEqual({ ok: false, reason: 'changed' });
    expect(mocks.replace).not.toHaveBeenCalled();
  });
  it('cannot continue a verified revision into another account', async () => {
    const pending = deferred<{ data: string; error: null }>();
    mocks.rpc.mockReturnValue(pending.promise);
    const done = expect(operations.replace()).rejects.toBeInstanceOf(OwnerMismatchError);
    await until(() => mocks.rpc.mock.calls.length === 1);
    await owner(U2); pending.resolve({ data: 'old-version', error: null }); await done;
    expect(mocks.replace).not.toHaveBeenCalled();
  });
  it('rejects a receipt for a different object at the same path', async () => {
    mocks.replace.mockResolvedValue({ data: { path, id: 'another-id' }, error: null });
    await expect(operations.replace()).rejects.toMatchObject({ code: 'unavailable' });
  });
});
