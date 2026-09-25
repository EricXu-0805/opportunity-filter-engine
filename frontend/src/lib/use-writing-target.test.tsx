import { StrictMode } from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Opportunity } from './types';
import { advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, syncLocalIdentityOwner } from './identity-owner';

const mocks = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock('./writing-target', async (load) => ({ ...await load<typeof import('./writing-target')>(), readWritingTarget: mocks.read }));
import { writingTargetKey } from './writing-target';
import { useWritingTarget, WRITING_TARGET_DEADLINE_MS, WRITING_TARGET_INTERVAL_MS, type TargetActionReceipt } from './use-writing-target';

const OWNER = 'writing-target-owner';
const TARGET: Opportunity = {
  id: 'target-a', title: 'Vision lab', organization: 'Example University', opportunity_type: 'research',
  paid: 'unknown', location: 'Campus', on_campus: true, description_clean: 'Full description with its final paragraph.',
  keywords: ['vision'], source_type: 'campus_program', record_kind: 'listing',
  eligibility: { international_friendly: 'yes', skills_required: ['Python'], preferred_year: ['Junior'], majors: ['CS'], citizenship_required: null },
  application: { requires_resume: 'yes', contact_method: 'email', application_effort: 'low' },
  metadata: { is_active: true, confidence_score: 0.75 },
  target_truth: { listing_state: 'open', reference_only: false, actionable: true, accepting_state: 'accepting', reason_code: null, verified_at: null, expires_at: null },
};
const fresh = (overrides: Partial<Opportunity> = {}) => structuredClone({ ...TARGET, ...overrides });
function deferred<T>() {
  let resolve!: (value: T) => void; let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
async function drain() { await act(async () => { for (let n = 0; n < 20; n += 1) await Promise.resolve(); }); }
async function tick(ms: number) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); }
function event(name: string) { act(() => { window.dispatchEvent(new Event(name)); }); }
function visibility(value: 'hidden' | 'visible') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value });
  act(() => { document.dispatchEvent(new Event('visibilitychange')); });
}
function online(value: boolean) {
  Object.defineProperty(navigator, 'onLine', { configurable: true, value }); event(value ? 'online' : 'offline');
}
async function changeOwner(uid: string) {
  await act(async () => { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }); await drain();
}
async function refresh(result: { current: ReturnType<typeof useWritingTarget> }) {
  let value = false; await act(async () => { value = await result.current.refresh(); }); return value;
}
beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  advanceOwnerEpoch(null); advanceOwnerEpoch(OWNER); await syncLocalIdentityOwner(OWNER);
  expect(isOwnerTokenValid(captureOwnerToken(), OWNER)).toBe(true);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
  mocks.read.mockReset().mockImplementation(async (id: string) => fresh({ id }));
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('owner-scoped full target reads', () => {
  it('publishes the complete actionable result and fresh immutable receipt without local writes', async () => {
    const writes = vi.spyOn(localStorage, 'setItem');
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain();
    expect(result.current.status).toBe('ready'); expect(result.current.target).toEqual(TARGET);
    expect(mocks.read).toHaveBeenCalledExactlyOnceWith(TARGET.id, { signal: expect.any(AbortSignal) });
    const first = result.current.target;
    let receipt: TargetActionReceipt | null = null;
    await act(async () => { receipt = await result.current.checkForAction(); });
    expect(receipt).toMatchObject({ owner: captureOwnerToken(), target: TARGET, key: writingTargetKey(TARGET) });
    expect(receipt!.target).toBe(first); expect(Object.isFrozen(receipt)).toBe(true);
    expect(Object.isFrozen(receipt!.target.eligibility)).toBe(true); expect(writes).not.toHaveBeenCalled();
    expect(mocks.read).toHaveBeenCalledTimes(2);
  });
  it('does not read until enabled and a real owner capability is ready', async () => {
    advanceOwnerEpoch(null); localStorage.clear();
    const { result, rerender } = renderHook(({ enabled }) => useWritingTarget(enabled, TARGET.id), { initialProps: { enabled: false } });
    await drain(); expect(mocks.read).not.toHaveBeenCalled(); expect(await result.current.checkForAction()).toBeNull();
    rerender({ enabled: true }); await drain(); expect(mocks.read).not.toHaveBeenCalled();
    await changeOwner(OWNER); expect(result.current.status).toBe('ready'); expect(mocks.read).toHaveBeenCalledOnce();
  });
  it('does not expose previous ready state on any render after re-opening', async () => {
    const seen: string[] = [];
    const { result, rerender } = renderHook(({ enabled }) => { const value = useWritingTarget(enabled, TARGET.id); seen.push(value.status); return value; }, { initialProps: { enabled: true } });
    await drain(); expect(result.current.status).toBe('ready');
    rerender({ enabled: false }); expect(result.current.target).toBeNull();
    const held = deferred<Opportunity>(); mocks.read.mockReturnValueOnce(held.promise);
    seen.length = 0; rerender({ enabled: true }); await drain();
    expect(seen).not.toContain('ready'); expect(result.current.target).toBeNull();
    held.resolve(fresh()); await drain(); expect(result.current.status).toBe('ready');
  });
  it.each(['close', 'target switch', 'owner switch', 'unmount'] as const)('settles pending action waiters immediately on %s and rejects the late result', async (change) => {
    const held = deferred<Opportunity>(); mocks.read.mockReturnValueOnce(held.promise);
    const { result, rerender, unmount } = renderHook(({ enabled, id }) => useWritingTarget(enabled, id), { initialProps: { enabled: true, id: TARGET.id } });
    await drain(); const firstSignal = mocks.read.mock.calls[0][1].signal as AbortSignal;
    let action!: Promise<TargetActionReceipt | null>;
    act(() => { action = result.current.checkForAction(); });
    if (change === 'close') rerender({ enabled: false, id: TARGET.id });
    else if (change === 'target switch') rerender({ enabled: true, id: 'target-b' });
    else if (change === 'owner switch') await changeOwner('second-owner');
    else unmount();
    await drain(); expect(firstSignal.aborted).toBe(true); expect(await action).toBeNull();
    held.resolve(fresh({ description_clean: 'Late old target text' })); await drain();
    if (change !== 'unmount') expect(result.current.target?.description_clean).not.toBe('Late old target text');
    if (change === 'target switch') expect(result.current.target?.id).toBe('target-b');
    if (change === 'close') expect(result.current.status).toBe('checking');
  });
  it('shares one explicit attempt but never reuses a completed action receipt', async () => {
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain();
    const held = deferred<Opportunity>(); mocks.read.mockReturnValueOnce(held.promise);
    let first!: Promise<TargetActionReceipt | null>, second!: Promise<TargetActionReceipt | null>, refreshed!: Promise<boolean>;
    act(() => { first = result.current.checkForAction(); second = result.current.checkForAction(); refreshed = result.current.refresh(); });
    expect(first).toBe(second); await drain(); expect(mocks.read).toHaveBeenCalledTimes(2);
    held.resolve(fresh()); await drain(); const receipt = await first; expect(await refreshed).toBe(true);
    let next: TargetActionReceipt | null = null; await act(async () => { next = await result.current.checkForAction(); });
    expect(next!.checkId).toBeGreaterThan(receipt!.checkId); expect(mocks.read).toHaveBeenCalledTimes(3);
  });
  it('does not accept transport aliases or mutations as the validated target', async () => {
    const incoming = fresh(); mocks.read.mockResolvedValueOnce(incoming);
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain();
    incoming.eligibility.skills_required.push('Unvalidated new skill');
    expect(result.current.target?.eligibility.skills_required).toEqual(['Python']);
    expect(Object.isFrozen(result.current.target)).toBe(true);
  });
});

describe('completion-relative foreground target refresh', () => {
  it('counts sixty seconds from completion and preserves ready/object identity while unchanged reads wait', async () => {
    const first = deferred<Opportunity>(); mocks.read.mockReturnValueOnce(first.promise);
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain();
    await tick(4_000); first.resolve(fresh()); await drain(); const target = result.current.target;
    await tick(WRITING_TARGET_INTERVAL_MS - 1); expect(mocks.read).toHaveBeenCalledOnce();
    const held = deferred<Opportunity>(); mocks.read.mockReturnValueOnce(held.promise);
    await tick(1); expect(mocks.read).toHaveBeenCalledTimes(2); expect(result.current.status).toBe('ready'); expect(result.current.target).toBe(target);
    event('focus'); event('online'); visibility('visible'); await drain(); expect(mocks.read).toHaveBeenCalledTimes(2);
    await tick(5_000); expect(mocks.read).toHaveBeenCalledTimes(2);
    const reordered = Object.fromEntries(Object.entries(fresh()).reverse()) as unknown as Opportunity;
    held.resolve(reordered); await drain(); expect(result.current.target).toBe(target); expect(result.current.status).toBe('ready');
    await tick(WRITING_TARGET_INTERVAL_MS - 1); expect(mocks.read).toHaveBeenCalledTimes(2);
    await tick(1); expect(mocks.read).toHaveBeenCalledTimes(3);
  });
  it('upgrades an automatic in-flight read to a blocking action check and returns that actual result', async () => {
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain();
    const held = deferred<Opportunity>(); mocks.read.mockReturnValueOnce(held.promise);
    await tick(WRITING_TARGET_INTERVAL_MS); expect(result.current.status).toBe('ready');
    let action!: Promise<TargetActionReceipt | null>;
    act(() => { action = result.current.checkForAction(); }); expect(result.current.status).toBe('checking');
    const changed = fresh({ description_clean: 'Updated complete source, same identity' });
    held.resolve(changed); await drain(); const receipt = await action;
    expect(receipt?.target).toEqual(changed); expect(receipt?.key).toBe(writingTargetKey(changed));
    expect(result.current.target).toBe(receipt?.target); expect(mocks.read).toHaveBeenCalledTimes(2);
  });
  it('suspends hidden/offline timers and resumes with one read without a catch-up burst', async () => {
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain();
    visibility('hidden'); await tick(3 * WRITING_TARGET_INTERVAL_MS); expect(mocks.read).toHaveBeenCalledOnce();
    online(false); visibility('visible'); event('focus'); await drain(); expect(mocks.read).toHaveBeenCalledOnce();
    online(true); await drain(); expect(mocks.read).toHaveBeenCalledTimes(2); expect(result.current.status).toBe('ready');
    await tick(WRITING_TARGET_INTERVAL_MS - 1); expect(mocks.read).toHaveBeenCalledTimes(2);
    await tick(1); expect(mocks.read).toHaveBeenCalledTimes(3);
  });
  it('waits for a foreground online window before the initial read', async () => {
    visibility('hidden'); online(false);
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain();
    expect(mocks.read).not.toHaveBeenCalled(); expect(result.current.status).toBe('checking');
    visibility('visible'); await drain(); expect(mocks.read).not.toHaveBeenCalled();
    online(true); await drain(); expect(mocks.read).toHaveBeenCalledOnce(); expect(result.current.status).toBe('ready');
  });
  it('replaces the target when a nested source field changes under the same id/title', async () => {
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain(); const previous = result.current.target;
    const changed = fresh({ eligibility: { ...TARGET.eligibility, preferred_year: ['Senior'] } }); mocks.read.mockResolvedValueOnce(changed);
    await tick(WRITING_TARGET_INTERVAL_MS);
    expect(result.current.target).toEqual(changed); expect(result.current.target).not.toBe(previous); expect(result.current.status).toBe('ready');
  });
});

describe('refusals and bounded target read failures', () => {
  it.each([
    [{ status: 404, code: 'HTTP_404', message: 'private body' }, 'missing', 'not_found'],
    [{ status: 503, code: 'HTTP_503', message: 'private body' }, 'failed', 'read_failed'],
    [{ status: 200, code: 'INVALID_TARGET_RESPONSE' }, 'failed', 'invalid_target'],
    [{ status: 408, code: 'TARGET_READ_TIMEOUT' }, 'failed', 'timeout'],
  ] as const)('withdraws authority after %s while retaining the last same-session target', async (error, status, reason) => {
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain(); const previous = result.current.target;
    mocks.read.mockRejectedValueOnce(error); expect(await refresh(result)).toBe(false);
    expect(result.current.status).toBe(status); expect(result.current.reason).toBe(reason); expect(result.current.target).toBe(previous);
    expect(JSON.stringify(result.current)).not.toContain('private body');
    expect(await refresh(result)).toBe(true); expect(result.current.status).toBe('ready'); expect(result.current.reason).toBeNull();
  });
  it.each(['closed', 'unknown'] as const)('withdraws authority for %s truth without publishing the rejected target', async (kind) => {
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain(); const previous = result.current.target;
    const rejected = fresh({ description_clean: 'New rejected source', target_truth: kind === 'closed'
      ? { ...TARGET.target_truth!, actionable: false, listing_state: 'closed', accepting_state: 'not_accepting', reason_code: 'listing_closed' }
      : null });
    mocks.read.mockResolvedValueOnce(rejected); expect(await refresh(result)).toBe(false);
    expect(result.current.status).toBe(kind === 'closed' ? 'blocked' : 'failed');
    expect(result.current.reason).toBe(kind === 'closed' ? 'listing_closed' : 'status_unverified'); expect(result.current.target).toBe(previous);
  });
  it('rejects an unexpected returned target id despite an actionable truth', async () => {
    mocks.read.mockResolvedValueOnce(fresh({ id: 'different-target' }));
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain();
    expect(result.current.status).toBe('failed'); expect(result.current.reason).toBe('invalid_target'); expect(result.current.target).toBeNull();
  });
  it('settles ignored-abort transport at the deadline and cannot revive from its late success or block retry', async () => {
    const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain(); const previous = result.current.target;
    const held = deferred<Opportunity>(); mocks.read.mockReturnValueOnce(held.promise);
    let action!: Promise<TargetActionReceipt | null>; act(() => { action = result.current.checkForAction(); }); await drain();
    const signal = mocks.read.mock.calls[1][1].signal as AbortSignal;
    await tick(WRITING_TARGET_DEADLINE_MS); expect(await action).toBeNull(); expect(signal.aborted).toBe(true);
    expect(result.current.status).toBe('failed'); expect(result.current.reason).toBe('timeout'); expect(result.current.target).toBe(previous);
    expect(await refresh(result)).toBe(true);
    held.resolve(fresh({ description_clean: 'Late obsolete source' })); await drain();
    expect(result.current.status).toBe('ready'); expect(result.current.target).toBe(previous); expect(mocks.read).toHaveBeenCalledTimes(3);
  });
  it('handles StrictMode effect retirement without leaking timers or accepting the abandoned read', async () => {
    const held = deferred<Opportunity>(); mocks.read.mockReturnValueOnce(held.promise);
    const { result, unmount } = renderHook(() => useWritingTarget(true, TARGET.id), { wrapper: StrictMode }); await drain();
    // The abandoned setup is cancelled before its queued transport call.
    expect(mocks.read).toHaveBeenCalledOnce(); held.resolve(fresh()); await drain(); expect(result.current.status).toBe('ready');
    unmount(); await drain(); expect(vi.getTimerCount()).toBe(0);
  });
});

it('retires a same-UID old generation and only accepts the newly verified namespace', async () => {
  const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain();
  const origin = captureOwnerToken();
  const held = deferred<Opportunity>(); mocks.read.mockReturnValueOnce(held.promise);
  await tick(WRITING_TARGET_INTERVAL_MS);
  let action!: Promise<TargetActionReceipt | null>; act(() => { action = result.current.checkForAction(); });
  mocks.read.mockResolvedValue(fresh({ description_clean: 'New generation target' }));
  await act(async () => {
    const marker = JSON.parse(localStorage.getItem('ofe_local_identity_owner')!);
    localStorage.setItem('ofe_local_identity_owner', JSON.stringify({ ...marker, generation: marker.generation + 1, phase: 'switching' }));
    window.dispatchEvent(new StorageEvent('storage', { key: 'ofe_local_identity_owner' }));
    await syncLocalIdentityOwner(OWNER);
  });
  await drain();
  expect(captureOwnerToken()).toMatchObject({ uid: origin.uid, epoch: origin.epoch, generation: origin.generation + 1 });
  expect(await action).toBeNull();
  expect(result.current.target?.description_clean).toBe('New generation target');
  held.resolve(fresh({ description_clean: 'Old generation target' })); await drain();
  expect(result.current.target?.description_clean).toBe('New generation target'); expect(result.current.status).toBe('ready');
});

it('does not expose a prior session target when an owner changes and the new owner read fails', async () => {
  const { result } = renderHook(() => useWritingTarget(true, TARGET.id)); await drain();
  expect(result.current.target).not.toBeNull();
  mocks.read.mockRejectedValueOnce({ status: 503, message: 'not a public message' });
  await changeOwner('another-owner');
  expect(result.current.status).toBe('failed'); expect(result.current.target).toBeNull(); expect(result.current.reason).toBe('read_failed');
});
