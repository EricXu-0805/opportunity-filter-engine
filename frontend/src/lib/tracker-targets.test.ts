import { beforeEach, expect, it, vi } from 'vitest';
vi.mock('./api', () => ({ getShortlistOpportunities: vi.fn() }));
vi.mock('./private-import-target-api', async importOriginal => {
  const original = await importOriginal<typeof import('./private-import-target-api')>();
  return { ...original, resolvePrivateImportTrackerTargets: vi.fn() };
});
import { getShortlistOpportunities } from './api';
import { PrivateTargetError, resolvePrivateImportTrackerTargets } from './private-import-target-api';
import { loadTrackerTargets } from './tracker-targets';
import type { OwnerToken } from './identity-owner';
const owner = { uid: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', epoch: 1, generation: 1 } as OwnerToken;
const id = 'private-import:cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const publicRead = vi.mocked(getShortlistOpportunities); const privateRead = vi.mocked(resolvePrivateImportTrackerTargets);
type Resolution = Awaited<ReturnType<typeof resolvePrivateImportTrackerTargets>>;
beforeEach(() => { publicRead.mockReset(); privateRead.mockReset(); publicRead.mockResolvedValue({ opportunities: [], unavailableIds: [] }); });
it('keeps private IDs off the public endpoint and projects only display fields', async () => {
  privateRead.mockResolvedValue([{ id, status: 'resolved', tracker: { id, title: 'Own source', organization: 'Lab', source_url: null, url: null,
    target_truth: { actionable: true }, recipient: 'injected' } }] as unknown as Resolution);
  const result = await loadTrackerTargets(['public-1', id, id], owner);
  expect(publicRead).toHaveBeenCalledWith(['public-1']);
  expect(privateRead).toHaveBeenCalledOnce();
  expect(privateRead).toHaveBeenCalledWith([id], { owner });
  expect(result.opportunities).toEqual([{ id, title: 'Own source', organization: 'Lab', source_url: undefined, url: undefined }]);
});
it('keeps deleted/missing IDs as explicit history placeholders, not a fake empty list', async () => {
  const missing = 'private-import:dddddddd-dddd-4ddd-8ddd-dddddddddddd';
  privateRead.mockResolvedValueOnce([{ id, status: 'deleted' }, { id: missing, status: 'not_found' }]);
  expect(await loadTrackerTargets([id, missing], owner)).toEqual({ opportunities: [], unavailableIds: [id, missing] });
  expect(publicRead).not.toHaveBeenCalled();
});
it('does not relabel account or infrastructure failures as missing targets', async () => {
  privateRead.mockRejectedValueOnce(new PrivateTargetError('unavailable'));
  await expect(loadTrackerTargets([id], owner)).rejects.toMatchObject({ code: 'unavailable' });
});
it('freezes the caller owner through the public fetch wait', async () => {
  let resolve!: (value: Awaited<ReturnType<typeof getShortlistOpportunities>>) => void;
  publicRead.mockReturnValueOnce(new Promise(done => { resolve = done; }));
  privateRead.mockResolvedValueOnce([{ id, status: 'not_found' }]);
  const original = { ...owner }; const mutable = { ...owner };
  const pending = loadTrackerTargets(['public-1', id], mutable); mutable.uid = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  resolve({ opportunities: [], unavailableIds: [] }); await pending;
  expect(privateRead).toHaveBeenCalledWith([id], { owner: original });
});

it('stops dispatching remaining private batches after a failed batch', async () => {
  const ids = Array.from({ length: 150 }, (_, n) => `private-import:cccccccc-cccc-4ccc-8ccc-${String(n).padStart(12, '0')}`);
  privateRead.mockRejectedValueOnce(new PrivateTargetError('unavailable'));
  await expect(loadTrackerTargets(ids, owner)).rejects.toMatchObject({ code: 'unavailable' });
  expect(privateRead).toHaveBeenCalledOnce();
  expect(privateRead.mock.calls[0][0]).toEqual(ids.slice(0, 100));
});
