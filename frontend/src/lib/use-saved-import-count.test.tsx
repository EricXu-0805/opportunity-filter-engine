/* @vitest-environment jsdom */
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { CustomImport } from './custom-imports';
import type { PrivateImportCursor, PrivateImportSummary } from './private-import-target-api';
import type { PrivateImportListView } from './use-private-import-list';
import { useSavedImportCount } from './use-saved-import-count';

const mocks = vi.hoisted(() => ({ list: vi.fn(), derive: vi.fn() }));
vi.mock('./private-import-adoption', () => ({ derivePrivateImportTargetId: mocks.derive }));
vi.mock('./private-import-target-api', () => ({ listPrivateImportTargets: mocks.list }));
vi.mock('./identity-owner', () => ({ captureOwnerToken: () => ({ uid: 'owner' }), isOwnerTokenValid: () => true }));

function view(ids: string[], cursor: PrivateImportCursor | null = null): PrivateImportListView {
  return { status: 'ready', items: ids.map(id => ({ id, title: 'Same name' } as PrivateImportSummary)), cursor,
    code: null, more: 'idle', detail: { status: 'closed' }, deleted: false };
}
const locals = [{ id: 'old-device-id', account_copy_key: 'replacement' }, { id: 'device-only' }] as CustomImport[];
beforeEach(() => {
  vi.resetAllMocks();
  mocks.derive.mockImplementation(async (_owner: string, id: string) => 'private:' + id);
});

it('deduplicates the actual account copy and counts independent same-name imports on subsequent pages', async () => {
  const cursor = { id: 'first', updated_at: '2026-11-01T00:00:00Z' };
  const first = view(['private:replacement'], cursor);
  mocks.list.mockResolvedValue({ items: view(['private:separate']).items, next_cursor: null });
  const { result } = renderHook(() => useSavedImportCount(first, locals));
  await waitFor(() => expect(result.current).toEqual({ status: 'ready', cloudOnly: 1 }));
  expect(mocks.list).toHaveBeenCalledWith(expect.objectContaining({ cursor, limit: 50 }));
  expect(mocks.derive.mock.calls).toEqual([['owner', 'replacement'], ['owner', 'device-only']]);
});

it('withholds a partial total when the next page fails and retries on a newly read list', async () => {
  const cursor = { id: 'first', updated_at: '2026-11-01T00:00:00Z' };
  const local: CustomImport[] = [];
  mocks.list.mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce({ items: [], next_cursor: null });
  const { result, rerender } = renderHook(({ list }) => useSavedImportCount(list, local), { initialProps: { list: view(['first'], cursor) } });
  await waitFor(() => expect(result.current.status).toBe('error'));
  rerender({ list: view(['first'], cursor) });
  await waitFor(() => expect(result.current).toEqual({ status: 'ready', cloudOnly: 1 }));
});

it('discards an old account pagination response after the session changes to guest', async () => {
  let resolve = (_page: unknown) => {};
  mocks.list.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  const guest: PrivateImportListView = { ...view([]), status: 'sign_in_required' };
  const { result, rerender } = renderHook(({ list }) => useSavedImportCount(list, locals), {
    initialProps: { list: view(['private:old'], { id: 'old', updated_at: '2026-11-01T00:00:00Z' }) },
  });
  rerender({ list: guest });
  resolve({ items: [{ id: 'stale' }], next_cursor: null });
  await waitFor(() => expect(result.current).toEqual({ status: 'ready', cloudOnly: 0 }));
});
