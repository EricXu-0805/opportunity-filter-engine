import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';

const { mockFrom, mockGetSession, mockUpsert, mockVersionInsert, mockMaybeSingle, mockHistory } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return { mockFrom: vi.fn(), mockGetSession: vi.fn(), mockUpsert: vi.fn(),
    mockVersionInsert: vi.fn(), mockMaybeSingle: vi.fn(), mockHistory: vi.fn() };
});
vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: { getSession: mockGetSession, signInAnonymously: vi.fn(),
      onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })) },
    from: mockFrom,
  }),
}));

import { loadRenovation, listRenovationVersions, saveRenovation } from './supabase';
import { advanceOwnerEpoch, captureOwnerToken, isLocalOwnerReady, syncLocalIdentityOwner } from './identity-owner';

const A = 'renovation-anonymous-a';
const B = 'renovation-anonymous-b';
const session = (uid: string) => ({ data: { session: { user: { id: uid, is_anonymous: true } } } });
const stored = { doc: { sections: ['a'] }, base_snapshot: {}, method: 'ai', warnings: [], updated_at: '' };
let filters: Array<[string, unknown]>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
async function establish(uid: string) {
  advanceOwnerEpoch(uid);
  await syncLocalIdentityOwner(uid);
  await waitFor(() => expect(isLocalOwnerReady(uid)).toBe(true));
}
function save(doc: Record<string, unknown> = { sections: ['a'] }, token = captureOwnerToken()) {
  return saveRenovation('opp-1', doc, {}, 'ai', [], token);
}

beforeEach(async () => {
  localStorage.clear();
  await establish(A);
  filters = [];
  mockGetSession.mockReset().mockResolvedValue(session(A));
  mockUpsert.mockReset().mockResolvedValue({ error: null });
  mockVersionInsert.mockReset().mockResolvedValue({ error: null });
  mockMaybeSingle.mockReset().mockResolvedValue({ data: stored, error: null });
  mockHistory.mockReset().mockResolvedValue({ data: [{ id: 'v1', doc: stored.doc, created_at: '' }], error: null });
  mockFrom.mockReset().mockImplementation(() => {
    const chain = {
      upsert: mockUpsert,
      insert: mockVersionInsert,
      select: () => chain,
      eq: (column: string, value: unknown) => { filters.push([column, value]); return chain; },
      maybeSingle: mockMaybeSingle,
      order: () => chain,
      limit: mockHistory,
    };
    return chain;
  });
});

describe('renovation persistence capability', () => {
  it('saves working doc and history for the already-established anonymous owner', async () => {
    expect(await save()).toBe(true);
    expect(mockUpsert.mock.calls[0][0].device_id).toBe(A);
    expect(mockVersionInsert.mock.calls[0][0].device_id).toBe(A);
    expect(await loadRenovation('opp-1')).toEqual(stored);
    expect(await listRenovationVersions('opp-1')).toEqual([{ id: 'v1', doc: stored.doc, created_at: '' }]);
    expect(filters).toEqual([['device_id', A], ['opportunity_id', 'opp-1'], ['device_id', A], ['opportunity_id', 'opp-1']]);
  });

  it('does not adopt an account that resolves after the action starts', async () => {
    const pending = deferred<ReturnType<typeof session>>();
    mockGetSession.mockReturnValueOnce(pending.promise);
    const result = save();
    const rejection = expect(result).rejects.toThrow('identity');
    await waitFor(() => expect(mockGetSession).toHaveBeenCalled());
    await establish(B);
    pending.resolve(session(B));
    await rejection;
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('never starts history after a working-save response crosses an identity change', async () => {
    const pending = deferred<{ error: null }>();
    mockUpsert.mockReturnValueOnce(pending.promise);
    const result = save();
    const rejection = expect(result).rejects.toThrow('identity');
    await waitFor(() => expect(mockUpsert).toHaveBeenCalled());
    await establish(B);
    pending.resolve({ error: null });
    await rejection;
    expect(mockVersionInsert).not.toHaveBeenCalled();
  });

  it('serializes successive working-document saves and skips stale queued work', async () => {
    const pending = deferred<{ error: null }>();
    mockUpsert.mockReturnValueOnce(pending.promise);
    const owner = captureOwnerToken();
    const first = save({ version: 1 }, owner);
    const firstRejection = expect(first).rejects.toThrow('identity');
    const second = save({ version: 2 }, owner);
    const secondRejection = expect(second).rejects.toThrow('identity');
    await waitFor(() => expect(mockUpsert).toHaveBeenCalledTimes(1));
    await establish(B);
    pending.resolve({ error: null });
    await Promise.all([firstRejection, secondRejection]);
    expect(mockUpsert).toHaveBeenCalledTimes(1);
  });

  it('does not let a newer working doc overtake an earlier pending save', async () => {
    const pending = deferred<{ error: null }>();
    mockUpsert.mockReturnValueOnce(pending.promise);
    const first = save({ version: 1 });
    const second = save({ version: 2 });
    await waitFor(() => expect(mockUpsert).toHaveBeenCalledTimes(1));
    pending.resolve({ error: null });
    expect(await Promise.all([first, second])).toEqual([true, true]);
    expect(mockUpsert.mock.calls.map(([payload]) => payload.doc.version)).toEqual([1, 2]);
  });

  it.each(['working', 'history'] as const)('rejects a late %s read after identity changes', async (kind) => {
    const pending = deferred<{ data: unknown; error: null }>();
    (kind === 'working' ? mockMaybeSingle : mockHistory).mockReturnValueOnce(pending.promise);
    const result = kind === 'working' ? loadRenovation('opp-1') : listRenovationVersions('opp-1');
    const rejection = expect(result).rejects.toThrow('identity');
    await waitFor(() => expect(kind === 'working' ? mockMaybeSingle : mockHistory).toHaveBeenCalled());
    await establish(B);
    pending.resolve({ data: kind === 'working' ? stored : [stored], error: null });
    await rejection;
  });

  it('reports a working-save failure without creating a history snapshot', async () => {
    mockUpsert.mockResolvedValueOnce({ error: { message: 'offline' } });
    expect(await save()).toBe(false);
    expect(mockVersionInsert).not.toHaveBeenCalled();
  });

  it.each(['pending', 'rejected'] as const)('still confirms the working doc when best-effort history is %s', async (kind) => {
    mockVersionInsert.mockReturnValueOnce(kind === 'pending'
      ? new Promise(() => {}) : Promise.reject(new Error('history offline')));
    expect(await save()).toBe(true);
    expect(mockUpsert).toHaveBeenCalledTimes(1);
  });
});
