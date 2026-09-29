import { beforeEach, expect, it, vi } from 'vitest';
vi.mock('./api', () => ({ getShortlistOpportunities: vi.fn() }));
vi.mock('./private-import-target-api', async importOriginal => {
  const original = await importOriginal<typeof import('./private-import-target-api')>();
  return { ...original, getResolvedPrivateImportTarget: vi.fn() };
});
import { getShortlistOpportunities } from './api';
import { getResolvedPrivateImportTarget, PrivateTargetError } from './private-import-target-api';
import { loadTrackerTargets } from './tracker-targets';
import type { OwnerToken } from './identity-owner';
const owner = { uid: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', epoch: 1, generation: 1 } as OwnerToken;
const id = 'private-import:cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const publicRead = vi.mocked(getShortlistOpportunities); const privateRead = vi.mocked(getResolvedPrivateImportTarget);
beforeEach(() => { publicRead.mockReset(); privateRead.mockReset(); publicRead.mockResolvedValue({ opportunities: [], unavailableIds: [] }); });
it('keeps private IDs off the public endpoint and projects only display fields', async () => {
  privateRead.mockResolvedValue({ tracker: { id, title: 'Own source', organization: 'Lab', source_url: null, url: null,
    target_truth: { actionable: true }, recipient: 'injected' } } as unknown as Awaited<ReturnType<typeof getResolvedPrivateImportTarget>>);
  const result = await loadTrackerTargets(['public-1', id], owner);
  expect(publicRead).toHaveBeenCalledWith(['public-1']);
  expect(privateRead).toHaveBeenCalledWith(id, expect.objectContaining({ owner, signal: expect.any(AbortSignal) }));
  expect(result.opportunities).toEqual([{ id, title: 'Own source', organization: 'Lab', source_url: undefined, url: undefined }]);
});
it('keeps deleted/missing IDs as explicit history placeholders, not a fake empty list', async () => {
  privateRead.mockRejectedValueOnce(new PrivateTargetError('deleted'));
  expect(await loadTrackerTargets([id], owner)).toEqual({ opportunities: [], unavailableIds: [id] });
  expect(publicRead).not.toHaveBeenCalled();
});
it('does not relabel account or infrastructure failures as missing targets', async () => {
  privateRead.mockRejectedValueOnce(new PrivateTargetError('unavailable'));
  await expect(loadTrackerTargets([id], owner)).rejects.toMatchObject({ code: 'unavailable' });
});
it('freezes the caller owner through the public fetch wait', async () => {
  let resolve!: (value: Awaited<ReturnType<typeof getShortlistOpportunities>>) => void;
  publicRead.mockReturnValueOnce(new Promise(done => { resolve = done; }));
  privateRead.mockRejectedValueOnce(new PrivateTargetError('not_found'));
  const original = { ...owner }; const mutable = { ...owner };
  const pending = loadTrackerTargets(['public-1', id], mutable); mutable.uid = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  resolve({ opportunities: [], unavailableIds: [] }); await pending;
  expect(privateRead).toHaveBeenCalledWith(id, expect.objectContaining({ owner: original, signal: expect.any(AbortSignal) }));
});

it('stops dispatching remaining private reads after a failed worker', async () => {
  const ids = Array.from({ length: 8 }, (_, n) => 'private-import:' + n);
  privateRead.mockImplementation(async (_id, options) => {
    if (_id === ids[0]) throw new PrivateTargetError('unavailable');
    await new Promise<void>(resolve => options.signal!.addEventListener('abort', () => resolve(), { once: true }));
    throw new PrivateTargetError('unavailable');
  });
  await expect(loadTrackerTargets(ids, owner)).rejects.toMatchObject({ code: 'unavailable' });
  expect(privateRead).toHaveBeenCalledTimes(4);
  expect(privateRead.mock.calls.every(([, options]) => options.signal!.aborted)).toBe(true);
});
