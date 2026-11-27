// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import type { OwnerToken } from './identity-owner';

vi.hoisted(() => {
  vi.stubGlobal('localStorage', { clear() {} });
  vi.stubGlobal('sessionStorage', { clear() {} });
});
const f = vi.hoisted(() => ({
  rpc: vi.fn(), list: vi.fn(), signed: vi.fn(), legacyOpen: vi.fn(), remove: vi.fn(), bucket: vi.fn(),
}));
const token: OwnerToken = { uid: 'owner', epoch: 1, generation: 1 };
const path = 'owner/op/old.pdf';
const anchorId = '27c7be2c-0fa5-4100-8c90-cf0b33becaf7';
const operation = '6f1aeb36-c93e-431c-b2cb-9e6199de0bb0';
const revision = 'v:' + operation;
const resolver = 'resolve_tracker_attachment_versions';
const marker = 'tracker_attachment_export_marker';
const original = { name: 'old.pdf', createdAt: '', sizeBytes: 3, mimeType: 'application/pdf', revision: { id: anchorId, etag: 'test', updatedAt: null } };
const version = { path, anchorId, revision, storageBucket: 'tracker-attachment-versions',
  storagePath: 'owner/' + operation, sizeBytes: 0, mimeType: 'application/pdf' };
const missing = (name: string) => ({ status: 404, error: { code: 'PGRST202', message: 'Could not find the function public.' + name + '() in the schema cache' } });
const success = (data: unknown) => ({ status: 200, data, error: null });
vi.mock('./supabase', () => ({
  ATTACHMENTS_BUCKET: 'tracker-attachments', supabase: { rpc: f.rpc, storage: { from: f.bucket } },
  getAuthState: async () => ({ user: { id: 'owner' } }), listAttachments: f.list,
  getAttachmentSignedUrl: f.legacyOpen, deleteAttachment: f.remove,
}));
vi.mock('./identity-owner', () => ({
  OwnerMismatchError: class extends Error {}, captureOwnerToken: () => token,
  isTokenOwnerStillCurrent: () => true, isOwnerTokenValid: (_: unknown, uid: string) => uid === 'owner',
}));
const load = () => import('./tracker-attachment-reader');
beforeEach(() => {
  vi.resetModules(); vi.resetAllMocks();
  f.list.mockResolvedValue([original]);
  f.rpc.mockImplementation(async name => missing(name));
  f.legacyOpen.mockResolvedValue('https://storage.example/original');
  f.bucket.mockReturnValue({ createSignedUrl: f.signed });
  f.signed.mockResolvedValue(success({ signedUrl: 'https://storage.example/current' }));
  f.remove.mockResolvedValue(true);
});

describe('Tracker staged read compatibility', () => {
  it('keeps legacy reads and ordinary deletion only when each named catalog RPC is missing', async () => {
    const api = await load();
    expect(await api.listReadableAttachments('op', token)).toEqual([{ ...original, canReplace: false }]);
    expect(await api.getReadableAttachmentUrl('op', 'old.pdf', 300, token)).toMatch(/original$/);
    expect(await api.deleteReadableAttachment('op', original, token)).toBe(true);
    expect(f.rpc.mock.calls.map(c => c[0])).toEqual([resolver, marker, resolver, marker, resolver, marker]);
    expect(f.remove).toHaveBeenCalledTimes(1);
  });
  it.each([[403,'42501',resolver],[503,'PGRST002',resolver],[404,'PGRST201',resolver],[404,'PGRST202',marker],
    [401,'PGRST202',resolver]])('never downgrades on %s %s for %s', async (status, code, name) => {
    f.rpc.mockResolvedValue({status,error:{...missing(String(name)).error,code}});
    const api = await load();
    await expect(api.getReadableAttachmentUrl('op','old.pdf',300,token)).rejects.toThrow();
    expect(f.legacyOpen).not.toHaveBeenCalled();
  });
  it('fails closed on a partial migration, a rejected request and a later catalog outage', async () => {
    const api = await load();
    f.rpc.mockImplementation(async name => name === marker ? missing(marker) : success({ [path]: version }));
    await expect(api.attachmentCatalogMarker('owner',token,new AbortController().signal)).rejects.toThrow();
    f.rpc.mockRejectedValueOnce(new Error('disconnected'));
    await expect(api.getReadableAttachmentUrl('op','old.pdf',300,token)).rejects.toThrow();
    await expect(api.listReadableAttachments('op',token)).resolves.toMatchObject([{ catalogRevision: revision, sizeBytes: 0, canReplace: false }]);
    f.rpc.mockImplementation(async name => missing(name));
    await expect(api.getReadableAttachmentUrl('op','old.pdf',300,token)).rejects.toThrow();
    expect(f.legacyOpen).not.toHaveBeenCalled();
  });
  it('remembers that the resolver exists even if only the corroborating request saw it', async () => {
    const api = await load();
    f.rpc.mockImplementation(async name => name === marker ? missing(name) : success({}));
    await expect(api.attachmentCatalogMarker('owner',token,new AbortController().signal)).rejects.toThrow();
    f.rpc.mockImplementation(async name => missing(name));
    await expect(api.getReadableAttachmentUrl('op','old.pdf',300,token)).rejects.toThrow();
    expect(f.legacyOpen).not.toHaveBeenCalled();
  });
  it('requires the missing-function message to identify the requested function itself', async () => {
    const api = await load();
    f.rpc.mockResolvedValue({status:404,error:{code:'PGRST202',
      message:'Could not find the function public.unrelated() near public.' + resolver + '()'}});
    await expect(api.getReadableAttachmentUrl('op','old.pdf',300,token)).rejects.toThrow();
    expect(f.legacyOpen).not.toHaveBeenCalled();
  });
  it('opens the current immutable bytes with bounded TTL and hides tombstones', async () => {
    const api = await load();
    f.rpc.mockResolvedValue(success({ [path]: version }));
    await expect(api.getReadableAttachmentUrl('op','old.pdf',999,token)).resolves.toMatch(/current$/);
    expect(f.bucket).toHaveBeenCalledWith('tracker-attachment-versions');
    expect(f.signed).toHaveBeenCalledWith(version.storagePath, 300);
    f.rpc.mockResolvedValue(success({ [path]: null }));
    expect(await api.listReadableAttachments('op',token)).toEqual([]);
    expect(await api.getReadableAttachmentUrl('op','old.pdf',300,token)).toBe(null);
  });
  it.each([{}, { [path]: { ...version, storagePath: 'another-owner/'+operation } },
    { [path]: { ...version, storageBucket: 'tracker-attachments' } }, { [path]: { ...version, sizeBytes: '0' } }])(
    'requires the original key, owner, bucket and typed metadata', async data => {
      const api = await load(); f.rpc.mockResolvedValue(success(data));
      await expect(api.getReadableAttachmentUrl('op','old.pdf',300,token)).rejects.toThrow();
      expect(f.legacyOpen).not.toHaveBeenCalled();
    });
  it('does not remove the physical anchor when the displayed version has changed or the CAS rejects', async () => {
    const api = await load(); f.rpc.mockResolvedValue(success({ [path]: version }));
    expect(await api.deleteReadableAttachment('op',original,token)).toBe(false);
    const file = {...original, catalogRevision: revision};
    f.rpc.mockResolvedValueOnce(success({ [path]: version })).mockResolvedValueOnce(success(false));
    expect(await api.deleteReadableAttachment('op', file, token)).toBe(false);
    expect(f.remove).not.toHaveBeenCalled();
    f.rpc.mockResolvedValueOnce(success({ [path]: version })).mockResolvedValueOnce(success(true));
    expect(await api.deleteReadableAttachment('op', file, token)).toBe(true);
    expect(f.rpc).toHaveBeenCalledWith('delete_tracker_attachment',{p_path:path,p_revision:revision});
    expect(f.remove).toHaveBeenCalledTimes(1);
  });
});

const sha = (value: string) => createHash('sha256').update(value).digest('hex');

it('exports the published bytes under the logical name and rechecks the snapshot before offering the ZIP', async () => {
  vi.stubGlobal('crypto', webcrypto);
  const current = { ...version, sizeBytes: 3 };
  const snapshot = { count: 1, digest: sha(sha([path, anchorId, revision, '3', current.mimeType].join('\0'))),
    observedAt: '2026-11-27T00:00:00Z' };
  const list = vi.fn(async (prefix: string) => success(prefix === 'owner' ? [{ name: 'op', id: null, metadata: null }] :
    [{ name: 'old.pdf', id: anchorId, updated_at: '2026-11-01', metadata: { size: 3, eTag: 'legacy' } }]));
  const download = vi.fn(async () => success(new Blob(['new'])));
  const touches: string[] = [];
  f.bucket.mockImplementation(bucket => { touches.push(bucket); return bucket === 'tracker-attachments' ? { list } : { download }; });
  f.rpc.mockImplementation(async name => success(name === marker ? snapshot : { [path]: current }));
  const { exportTrackerAttachments } = await import('./tracker-attachment-export');
  const run = () => exportTrackerAttachments('owner', token, new AbortController().signal, vi.fn());
  const archive = await run();
  expect(archive?.count).toBe(1);
  const wire = await archive?.blob.text();
  expect(wire).toContain(sha('new'));
  expect(wire).toContain('op/old.pdf');
  expect(touches).toContain('tracker-attachment-versions');
  expect(download.mock.calls[0]).toEqual([current.storagePath, { cacheNonce: revision }, { cache:'no-store', signal:expect.anything() }]);
  let reads = 0;
  f.rpc.mockImplementation(async name => success(name === resolver ? { [path]: current } :
    ++reads === 1 ? snapshot : { ...snapshot, digest: '0'.repeat(64) }));
  await expect(run()).rejects.toThrow();
});
it('withholds even an empty ZIP result when the legacy database becomes versioned during the same export', async () => {
  vi.stubGlobal('crypto', webcrypto);
  f.bucket.mockReturnValue({ list: vi.fn(async () => success([])) });
  let initial = true;
  f.rpc.mockImplementation(async name => {
    if (name === resolver) { initial = false; return missing(name); }
    return initial ? missing(name) : success({ count: 0, digest: sha(''), observedAt: '2026-11-27T00:00:00Z' });
  });
  const { exportTrackerAttachments } = await import('./tracker-attachment-export');
  await expect(exportTrackerAttachments('owner', token, new AbortController().signal, vi.fn())).rejects.toThrow();
});
