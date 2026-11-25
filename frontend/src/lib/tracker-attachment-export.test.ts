// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import { exportTrackerAttachments } from './tracker-attachment-export';

vi.hoisted(() => {
  vi.stubGlobal('localStorage', { clear() {} });
  vi.stubGlobal('sessionStorage', { clear() {} });
});
const fixture = vi.hoisted(() => ({ uid: 'account', list: vi.fn(), download: vi.fn() }));
vi.mock('./supabase', () => ({
  ATTACHMENTS_BUCKET: 'tracker-attachments',
  getAuthState: () => Promise.resolve({ user: { id: fixture.uid } }),
  supabase: { storage: { from: () => fixture } },
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

describe('Tracker attachment export', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', webcrypto);
    fixture.uid = 'account';
    fixture.list.mockReset().mockResolvedValue(ok([row('old.pdf')]));
    fixture.download.mockReset().mockImplementation(async () => ok(await new Response('abc').blob()));
  });

  it('returns an empty result only for a confirmed empty inventory', async () => {
    fixture.list.mockImplementation(async (path: string) => ok(path === 'account' ? [folder('old')] : []));
    await expect(run()).resolves.toBeNull();
    expect(fixture.download).not.toHaveBeenCalled();
    fixture.list.mockResolvedValue({ data: null, error: {} });
    await expect(run()).rejects.toThrow();
  });

  it('retries the entire export after a read fails partway', async () => {
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
    fixture.list.mockImplementation(async (path: string) => ok(path === 'account' ? [folder('old')] : [row('old #%3F?.pdf')]));
    await expect(run()).resolves.toMatchObject({ count: 1 });
    expect(fixture.download).toHaveBeenCalledWith('account/old/old%20%23%253F%3F.pdf',
      { cacheNonce: expect.any(String) }, { cache: 'no-store', signal: expect.anything() });
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
});
