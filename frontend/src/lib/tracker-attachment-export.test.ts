// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import { exportTrackerAttachments, type ExportVolume } from './tracker-attachment-export';

vi.hoisted(() => {
  vi.stubGlobal('localStorage', { clear() {} });
  vi.stubGlobal('sessionStorage', { clear() {} });
});
const fixture = vi.hoisted(() => ({ uid: 'account', list: vi.fn(), download: vi.fn(), rpc: vi.fn(), versionDownload: vi.fn(), resolve: vi.fn() }));
vi.mock('./supabase', () => ({
  ATTACHMENTS_BUCKET: 'tracker-attachments', ATTACHMENTS_MAX_BYTES: 5 * 1024 * 1024,
  getAuthState: () => Promise.resolve({ user: { id: fixture.uid } }),
  resolveTrackerAttachmentVersions: fixture.resolve,
  supabase: { rpc: fixture.rpc, storage: { from: (name: string) => name === 'tracker-attachments' ? fixture : { download: fixture.versionDownload } } },
}));
vi.mock('./identity-owner', () => ({
  OwnerMismatchError: class extends Error {},
  isTokenOwnerStillCurrent: (token: { uid: string }) => token.uid === fixture.uid,
  isOwnerTokenValid: (token: { uid: string }, uid: string) => uid === fixture.uid && uid === token.uid,
}));
const token = { uid: 'account', epoch: 1, generation: 1 };
const run = (signal = new AbortController().signal) => exportTrackerAttachments('account', token, signal, vi.fn());
const row = (name: string, etag = 'one') => ({ name, id: name, updated_at: '2026-11-25', metadata: { size: 3, eTag: etag } });
const folder = (name: string) => ({ name, id: null, metadata: null });
const ok = (data: unknown) => ({ data, error: null });
const versionId = 'aae001be-0c8b-4de1-9a2f-e2159b02558c';
const legacy = (path: string) => ({
  path, anchorId: path.split('/').at(-1)!, revision: 'old revision', storageBucket: 'tracker-attachments',
  storagePath: path, sizeBytes: 3, mimeType: 'text/plain', etag: 'one', updatedAt: '2026-11-25',
});
const replacement = (path: string) => ({
  ...legacy(path), revision: 'new revision', storageBucket: 'tracker-attachment-versions',
  storagePath: 'account/' + versionId, mimeType: 'application/pdf', sizeBytes: 7,
});


const observedAt = '2026-11-26T06:17:01Z';
const hash = (input: string) => createHash('sha256').update(input, 'utf8').digest('hex');
function marker(files: ReturnType<typeof legacy>[]) {
  const items = files.map(f => hash([f.path, f.anchorId, f.revision, f.sizeBytes, f.mimeType].join('\0')));
  return ok({ count: items.length, digest: hash(items.sort().join('')), observedAt });
}
function mark(files: ReturnType<typeof legacy>[]) {
  fixture.rpc.mockReturnValue(marker(files));
}

describe('Tracker attachment export', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', webcrypto);
    fixture.uid = 'account';
    fixture.rpc.mockReset();
    mark([legacy('account/old.pdf')]);
    fixture.list.mockReset().mockResolvedValue(ok([row('old.pdf')]));
    fixture.resolve.mockReset().mockImplementation(async (paths: string[]) => new Map(paths.map(path => [path, legacy(path)])));
    fixture.versionDownload.mockReset().mockImplementation(async () => ok(await new Response('current').blob()));
    fixture.download.mockReset().mockImplementation(async () => ok(await new Response('abc').blob()));
  });

  it('returns an empty result only for a confirmed empty inventory', async () => {
    mark([]);
    fixture.list.mockImplementation(async (path: string) => ok(path === 'account' ? [folder('old')] : []));
    await expect(run()).resolves.toBeNull();
    expect(fixture.download).not.toHaveBeenCalled();
    fixture.list.mockResolvedValue({ data: null, error: {} });
    await expect(run()).rejects.toThrow();
  });

  it('retries the entire export after a read fails partway', async () => {
    mark(['account/a.pdf', 'account/b.pdf'].map(legacy));
    fixture.list.mockResolvedValue(ok([row('a.pdf'), row('b.pdf')]));
    fixture.download.mockResolvedValueOnce(ok(await new Response('abc').blob())).mockResolvedValueOnce({ data: null, error: {} });
    await expect(run()).rejects.toThrow();
    const file = await run();
    expect(file?.count).toBe(2);
    expect(fixture.download.mock.calls.map(call => call[0])).toEqual(['account/a.pdf', 'account/b.pdf', 'account/a.pdf', 'account/b.pdf']);
  });

  it('rejects a truncated download, malformed storage rows and a revision change after download', async () => {
    fixture.download.mockResolvedValueOnce(ok(await new Response('ab').blob()));
    await expect(run()).rejects.toThrow();
    mark([legacy('account/a.pdf')]);
    fixture.list.mockResolvedValueOnce(ok([{ ...row('a.pdf'), metadata: {} }]));
    await expect(run()).rejects.toThrow();
    fixture.list.mockResolvedValueOnce(ok([row('a.pdf')])).mockResolvedValueOnce(ok([row('a.pdf', 'two')]));
    await expect(run()).rejects.toThrow();
    fixture.list.mockResolvedValueOnce(ok([row('a.pdf')])).mockResolvedValueOnce(ok([row('a.pdf'), row('new.pdf')]));
    await expect(run()).rejects.toThrow();
  });

  it('rejects a shifting pagination boundary before reading file bytes', async () => {
    fixture.list.mockResolvedValueOnce(ok(Array.from({ length: 100 }, (_, i) => row(String(i)))))
      .mockResolvedValueOnce(ok([row('different')]));
    await expect(run()).rejects.toThrow();
    expect(fixture.download).not.toHaveBeenCalled();
  });

  it('encodes each path segment once for legacy names and always reads the current version', async () => {
    mark([legacy('account/old/old #%3F?.pdf')]);
    fixture.list.mockImplementation(async (path: string) => ok(path === 'account' ? [folder('old')] : [row('old #%3F?.pdf')]));
    await expect(run()).resolves.toMatchObject({ count: 1 });
    expect(fixture.download).toHaveBeenCalledWith('account/old/old%20%23%253F%3F.pdf',
      { cacheNonce: expect.any(String) }, { cache: 'no-store', signal: expect.anything() });
  });

  it('exports only current versions under the logical names, even for retained anchors', async () => {
    mark([legacy('account/old.pdf'), replacement('account/replaced.pdf')]);
    fixture.list.mockResolvedValue(ok([row('gone.pdf'), row('old.pdf'), row('replaced.pdf')]));
    fixture.resolve.mockImplementation(async (paths: string[]) => new Map(paths.map(path => [
      path, path.endsWith('/gone.pdf') ? null : path.endsWith('/replaced.pdf') ? replacement(path) : legacy(path),
    ])));
    const result = await run();
    expect(result?.count).toBe(2);
    expect(fixture.download.mock.calls.map(([key]) => key)).toEqual(['account/old.pdf']);
    expect(fixture.versionDownload.mock.calls.map(([key]) => key)).toEqual(['account/' + versionId]);
    const archive = await result!.blob.text();
    expect(archive).toContain('"originalPath": "replaced.pdf"');
    expect(archive).toContain('current');
    expect(archive).not.toContain(versionId);
    expect(archive).not.toContain('gone.pdf');
    expect(fixture.resolve).toHaveBeenCalledTimes(2);
  });

  it('rejects versions that switch or disappear while building the ZIP', async () => {
    const path = 'account/old.pdf';
    mark([replacement(path)]);
    fixture.resolve.mockResolvedValueOnce(new Map([[path, replacement(path)]]))
      .mockResolvedValueOnce(new Map([[path, null]]));
    await expect(run()).rejects.toThrow();
    fixture.resolve.mockResolvedValueOnce(new Map([[path, replacement(path)]]))
      .mockResolvedValueOnce(new Map([[path, { ...replacement(path), revision: 'another revision' }]]));
    await expect(run()).rejects.toThrow();
  });

  it('distinguishes an account with only deleted files from an incomplete or foreign resolution', async () => {
    const path = 'account/old.pdf';
    mark([]);
    fixture.resolve.mockResolvedValue(new Map([[path, null]]));
    await expect(run()).resolves.toBeNull();
    for (const invalid of [new Map(), new Map([[path, { ...legacy(path), anchorId: 'recreated' }]]),
      new Map([[path, { ...replacement(path), storagePath: 'other/' + versionId }]])]) {
      fixture.resolve.mockResolvedValueOnce(invalid);
      await expect(run()).rejects.toThrow();
    }
    expect(fixture.versionDownload).not.toHaveBeenCalled();
    expect(fixture.download).not.toHaveBeenCalled();
  });

  it('resolves at most 100 logical paths per call on both inventory passes', async () => {
    const rows = Array.from({ length: 101 }, (_, i) => row(String(i).padStart(3, '0')));
    mark(rows.map(r => legacy('account/' + r.name)));
    fixture.list.mockImplementation(async (_path: string, options: { offset: number; limit: number }) =>
      ok(rows.slice(options.offset, options.offset + options.limit)));
    expect((await run())?.count).toBe(101);
    expect(fixture.resolve.mock.calls.map(([paths]) => paths.length)).toEqual([100, 1, 100, 1]);
  });

  it('drops a late read on account switch and verifies the live session even for an empty list', async () => {
    fixture.download.mockImplementationOnce(async () => { fixture.uid = 'other'; return ok(await new Response('abc').blob()); });
    await expect(run()).rejects.toThrow();
    fixture.uid = 'account';
    fixture.list.mockImplementationOnce(async () => { fixture.uid = 'other'; return ok([]); });
    await expect(run()).rejects.toThrow();
  });

  it('cancels a held read promptly and never proceeds to the next file', async () => {
    const controller = new AbortController();
    fixture.download.mockImplementation(() => new Promise(() => {}));
    const pending = run(controller.signal);
    await vi.waitFor(() => expect(fixture.download).toHaveBeenCalled());
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(fixture.list).toHaveBeenCalledTimes(1);
  });

  function archiveWithFourLargeFiles() {
    const size = 4 * 1024 * 1024;
    const rows = ['a.pdf', 'b.pdf', 'c.pdf', 'd.pdf'].map(name => row(name));
    mark(rows.map(r => ({ ...legacy('account/' + r.name), sizeBytes: size })));
    fixture.list.mockResolvedValue(ok(rows));
    fixture.resolve.mockImplementation(async (paths: string[]) => new Map(paths.map(path => [path, { ...legacy(path), sizeBytes: size }])));
    const file = new Blob([new Uint8Array(size)]);
    fixture.download.mockResolvedValue(ok(file));
  }

  it('includes metadata and ZIP overhead in the limit and issues checksums for precisely the requested volumes', async () => {
    archiveWithFourLargeFiles();
    const expected: string[] = [];
    const result = await exportTrackerAttachments('account', token, new AbortController().signal, vi.fn(), async part => {
      expect(part.total).toBe(2);
      expect(part.blob.size).toBeLessThanOrEqual(16 * 1024 * 1024);
      expect(fixture.download).toHaveBeenCalledTimes(part.number === 1 ? 3 : 4);
      expect(await part.blob.text()).toContain('"scope": "partial-volume"');
      expected.push(createHash('sha256').update(new Uint8Array(await part.blob.arrayBuffer())).digest('hex') + '  ' + part.filename);
    });
    expect(result?.parts).toBe(2);
    expect(await result?.blob.text()).toEqual('# Verified at ' + observedAt + '\n' + expected.join('\n') + '\n');
    expect(result?.filename).toMatch(/-complete[.]sha256$/);
    fixture.list.mockResolvedValue(ok([]));
    await expect(result?.downloadFreshReceipt?.()).rejects.toThrow();
  });

  it('never releases a completion receipt after cancellation or drift, and starts a new export on retry', async () => {
    archiveWithFourLargeFiles();
    const controller = new AbortController();
    const partial = vi.fn(async (part: ExportVolume) => {
      expect(part.filename).toMatch(/-partial-1-of-2[.]zip$/);
      controller.abort();
    });
    await expect(exportTrackerAttachments('account', token, controller.signal, vi.fn(), partial)).rejects.toMatchObject({ name: 'AbortError' });
    expect(partial).toHaveBeenCalledTimes(1);
    expect(fixture.download).toHaveBeenCalledTimes(3);
    let retryName = '';
    await expect(exportTrackerAttachments('account', token, new AbortController().signal, vi.fn(), async part => {
      if (part.number === 1) retryName = part.filename;
      if (part.number === 2) fixture.list.mockResolvedValue(ok([]));
    })).rejects.toThrow();
    expect(retryName).not.toBe(partial.mock.calls[0][0].filename);
  });

  it('names an oversized legacy file before reading bytes or offering a part', async () => {
    mark([legacy('account/first.pdf'), { ...legacy('account/legacy.pdf'), sizeBytes: 5 * 1024 * 1024 + 1 }]);
    fixture.list.mockResolvedValue(ok([row('first.pdf'), row('legacy.pdf')]));
    fixture.resolve.mockImplementation(async (paths: string[]) => new Map(paths.map(path => [
      path, { ...legacy(path), sizeBytes: path.endsWith('/legacy.pdf') ? 5 * 1024 * 1024 + 1 : 3 },
    ])));
    const offer = vi.fn();
    await expect(exportTrackerAttachments('account', token, new AbortController().signal, vi.fn(), offer))
      .rejects.toMatchObject({ path: 'legacy.pdf' });
    expect(fixture.download).not.toHaveBeenCalled();
    expect(offer).not.toHaveBeenCalled();
  });

  it('rejects a change to an earlier resolver page during the final 100+29 read', async () => {
    const rows = Array.from({ length: 129 }, (_, i) => row(String(i).padStart(3, '0')));
    const versions = rows.map(r => legacy('account/' + r.name));
    fixture.rpc.mockImplementation(() => marker(versions));
    fixture.list.mockImplementation(async (_path, { offset, limit }) => ok(rows.slice(offset, offset + limit)));
    const exported = await exportTrackerAttachments('account', token, new AbortController().signal, vi.fn(), vi.fn());
    expect(exported?.parts).toBe(2);
    fixture.resolve.mockImplementation(async (paths: string[]) => {
      const result = new Map(paths.map(path => [path, legacy(path)]));
      if (paths.length === 29) versions[0] = { ...versions[0], revision: 'replaced after page one' };
      return result;
    });
    await expect(exported?.downloadFreshReceipt?.()).rejects.toThrow();
    expect(fixture.rpc).toHaveBeenLastCalledWith('tracker_attachment_export_marker', {});
  });

  it('rejects a mixed first inventory even when the database changes back before the final marker', async () => {
    fixture.resolve.mockResolvedValue(new Map([['account/old.pdf', replacement('account/old.pdf')]]));
    await expect(run()).rejects.toThrow();
    expect(fixture.download).not.toHaveBeenCalled();
    expect(fixture.versionDownload).not.toHaveBeenCalled();
  });

  it('fails closed when the snapshot response is unavailable or malformed', async () => {
    for (const result of [{ error: {}, data: null }, ok({ count: 1, digest: hash('x') }), ok({ count: -1, digest: hash('x'), observedAt })]) {
      fixture.rpc.mockReturnValueOnce(result);
      await expect(run()).rejects.toThrow();
    }
    expect(fixture.download).not.toHaveBeenCalled();
  });

  it('matches the database fingerprint for a Unicode legacy path and preserves the observed verification time', async () => {
    const uid = '3b000000-0000-4000-8000-000000000001';
    const anchorId = '3b000000-0000-4000-8000-000000000003';
    const path = uid + '/retired/é.pdf';
    fixture.uid = uid;
    fixture.list.mockImplementation(async (prefix: string) => ok(prefix === uid ? [folder('retired')] : [{ ...row('é.pdf'), id: anchorId }]));
    fixture.resolve.mockResolvedValue(new Map([[path, { ...legacy(path), anchorId, sizeBytes: 8, mimeType: 'application/pdf',
      revision: 'o:' + anchorId + ':legacy-1:1767225600.000000:one' }]]));
    fixture.rpc.mockResolvedValue(ok({ count: 1, observedAt,
      digest: '905256d7e66e23e42435de6bcc517df70bcec4ca8649a4d6081faee7d33cc003' }));
    fixture.download.mockResolvedValue(ok(new Blob(['original'])));
    await expect(exportTrackerAttachments(uid, { ...token, uid }, new AbortController().signal, vi.fn()))
      .resolves.toMatchObject({ count: 1, verifiedAt: observedAt, filename: 'tracker-attachments.zip' });
  });
});
