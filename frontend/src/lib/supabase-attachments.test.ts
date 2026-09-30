import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-key';
  return { session: vi.fn(), anon: vi.fn(), list: vi.fn(), upload: vi.fn(), remove: vi.fn(), signed: vi.fn(), from: vi.fn() };
});
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({
  auth: { getSession: mocks.session, signInAnonymously: mocks.anon },
  storage: { from: mocks.from },
}) }));
import { ATTACHMENTS_BUCKET, listAttachments, uploadAttachment, deleteAttachment, getAttachmentSignedUrl } from './supabase';
import { ATTACHMENT_REQUEST_TIMEOUT_MS, AttachmentRequestError } from './attachment-request';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner, OwnerMismatchError } from './identity-owner';
const U1 = '11111111-1111-4111-8111-111111111111';
const U2 = '22222222-2222-4222-8222-222222222222';
const OPP = 'faculty-old-opportunity';
const path = `${U1}/${OPP}/resume.pdf`;
const file = () => new File(['original bytes'], 'resume.pdf', { type: 'application/pdf' });
const session = (uid: string | null = U1) => ({ data: { session: uid ? { user: { id: uid, is_anonymous: true }, access_token: 'token' } : null }, error: null });
const row = { name: 'resume.pdf', id: 'object-id', metadata: { size: 14, mimetype: 'application/pdf' }, created_at: '2026-01-01T00:00:00Z' };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (cause: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
async function until(check: () => boolean) { for (let i = 0; i < 100 && !check(); i++) await Promise.resolve(); expect(check()).toBe(true); }
async function owner(uid: string) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }
beforeEach(async () => {
  vi.clearAllMocks(); localStorage.clear(); await owner(U1);
  mocks.session.mockReset().mockResolvedValue(session());
  mocks.list.mockReset().mockResolvedValue({ data: [row], error: null });
  mocks.upload.mockReset().mockImplementation(async (uploadedPath: string) => ({ data: { path: uploadedPath, id: 'object-id' }, error: null }));
  mocks.remove.mockReset().mockResolvedValue({ data: [{ name: path }], error: null });
  mocks.signed.mockReset().mockResolvedValue({ data: { signedUrl: 'https://test.supabase.co/original.pdf' }, error: null });
  mocks.from.mockImplementation(() => ({ list: mocks.list, upload: mocks.upload, remove: mocks.remove, createSignedUrl: mocks.signed }));
});
afterEach(() => { vi.useRealTimers(); });
const operations = {
  list: (signal?: AbortSignal) => listAttachments(OPP, captureOwnerToken(), { signal }),
  upload: (signal?: AbortSignal) => uploadAttachment(OPP, file(), captureOwnerToken(), { signal }),
  remove: (signal?: AbortSignal) => deleteAttachment(OPP, 'resume.pdf', captureOwnerToken(), { signal }),
  signed: (signal?: AbortSignal) => getAttachmentSignedUrl(OPP, 'resume.pdf', 300, captureOwnerToken(), { signal }),
};

describe('legacy attachment protocol and failures', () => {
  it('uses the old bucket/prefix and preserves actual metadata', async () => {
    expect(await operations.list()).toEqual([{ name: 'resume.pdf', sizeBytes: 14, mimeType: 'application/pdf', createdAt: row.created_at }]);
    expect(mocks.from).toHaveBeenCalledWith(ATTACHMENTS_BUCKET);
    expect(ATTACHMENTS_BUCKET).toBe('tracker-attachments');
    expect(mocks.list).toHaveBeenCalledWith(`${U1}/${OPP}`, { limit: 100, sortBy: { column: 'created_at', order: 'desc' } }, { signal: expect.any(AbortSignal) });
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
