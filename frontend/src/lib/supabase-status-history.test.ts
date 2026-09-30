import { beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
const api = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return { from: vi.fn(), session: vi.fn(), order: vi.fn(), eq: vi.fn() };
});
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({
  auth: { getSession: api.session, signInAnonymously: vi.fn(async () => ({ data: { session: null }, error: null })),
    onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })) }, from: api.from,
}) }));
import { getStatusChanges, OwnerMismatchError } from './supabase';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
const A = 'status-history-A', B = 'status-history-B';
const session = (uid: string) => ({ data: { session: { user: { id: uid, is_anonymous: true } } } });
const row = { from_status: 'applied', to_status: 'replied', changed_at: '2026-09-24T10:00:00Z' };
async function owner(uid: string) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(async () => {
  localStorage.clear(); await owner(A);
  api.session.mockReset().mockResolvedValue(session(A));
  api.order.mockReset().mockResolvedValue({ data: [row], error: null });
  api.eq.mockReset().mockImplementation(() => ({ eq: api.eq, order: api.order }));
  api.from.mockReset().mockReturnValue({ select: vi.fn(() => ({ eq: api.eq })) });
});
describe('getStatusChanges truthful owner-bound reads', () => {
  it('returns exact real changes from only the current owner and opportunity', async () => {
    expect(await getStatusChanges('opp-1')).toEqual([{ fromStatus: 'applied', toStatus: 'replied', changedAt: row.changed_at }]);
    expect(api.eq.mock.calls).toEqual([['device_id', A], ['opportunity_id', 'opp-1']]);
    expect(api.order).toHaveBeenCalledWith('changed_at', { ascending: true });
  });
  it('only a successful empty array is an empty history', async () => {
    api.order.mockResolvedValue({ data: [], error: null });
    expect(await getStatusChanges('opp-1')).toEqual([]);
  });
  it.each(['permission denied private data', 'relation does not exist'])('query failure is safe and distinguishable from no history: %s', async message => {
    api.order.mockResolvedValue({ data: null, error: { message } });
    await expect(getStatusChanges('opp-1')).rejects.toThrow('Status history could not be loaded');
  });
  it('a thrown transport failure is safe and never returned as empty', async () => {
    api.order.mockRejectedValue(new Error('private server body'));
    await expect(getStatusChanges('opp-1')).rejects.toThrow('Status history could not be loaded');
  });
  it.each([null, {}, [{ ...row, changed_at: 'invalid' }], [{ ...row, to_status: 'unknown' }]])('rejects malformed successful data %#', async data => {
    api.order.mockResolvedValue({ data, error: null });
    await expect(getStatusChanges('opp-1')).rejects.toThrow('Status history could not be loaded');
  });
  it('does not dispatch under an owner that resolves after this read began', async () => {
    const held = deferred<ReturnType<typeof session>>(); api.session.mockReturnValue(held.promise);
    const reading = getStatusChanges('opp-1');
    const assertion = expect(reading).rejects.toBeInstanceOf(OwnerMismatchError);
    await waitFor(() => expect(api.session).toHaveBeenCalled());
    await owner(B); held.resolve(session(B)); await assertion;
    expect(api.from).not.toHaveBeenCalled();
  });
  it('rejects a late response after a real owner change', async () => {
    const held = deferred<{ data: typeof row[]; error: null }>(); api.order.mockReturnValue(held.promise);
    const reading = getStatusChanges('opp-1'); const assertion = expect(reading).rejects.toBeInstanceOf(OwnerMismatchError);
    await waitFor(() => expect(api.order).toHaveBeenCalled());
    await owner(B); held.resolve({ data: [row], error: null }); await assertion;
  });
  it('rejects a late response after the same UID storage generation is rebuilt', async () => {
    const held = deferred<{ data: typeof row[]; error: null }>(); api.order.mockReturnValue(held.promise);
    const before = captureOwnerToken();
    const reading = getStatusChanges('opp-1'); const assertion = expect(reading).rejects.toBeInstanceOf(OwnerMismatchError);
    await waitFor(() => expect(api.order).toHaveBeenCalled());
    const marker = JSON.parse(localStorage.getItem('ofe_local_identity_owner')!);
    localStorage.setItem('ofe_local_identity_owner', JSON.stringify({ ...marker, generation: marker.generation + 1, phase: 'switching' }));
    await syncLocalIdentityOwner(A);
    expect(captureOwnerToken().generation).not.toBe(before.generation);
    held.resolve({ data: [row], error: null }); await assertion;
  });
});
