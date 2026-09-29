import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import type { ProfileData } from './types';
const mocks = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock('./private-email', async load => ({ ...await load<typeof import('./private-email')>(), getPrivateEmailContext: mocks.read }));
vi.mock('./use-profile-refresh', () => ({ PROFILE_REFRESH_DEADLINE_MS: 15_000 }));
import { privateEmailKey, type PrivateEmailContext } from './private-email';
import { usePrivateEmailTarget, PRIVATE_EMAIL_DEADLINE_MS, PRIVATE_EMAIL_INTERVAL_MS, type PrivateEmailActionReceipt } from './use-private-email-target';
import { useProfileAction } from './use-profile-action';

const OWNER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const OTHER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const ID = 'private-import:11111111-1111-4111-8111-111111111111';
function target(patch: Partial<PrivateEmailContext> = {}): PrivateEmailContext {
  return { version: 1, target_scope: 'private_import', verification: 'unverified', purpose: 'first_contact',
    id: ID, owner_id: OWNER, revision: 1, source_version: `pit1:${'a'.repeat(64)}`, writing_version: `pwt1:${'b'.repeat(64)}`,
    projection_version: 1, policy_version: 1, title: 'Private robotics programme 王🙂', organization: 'Example University',
    source_url: 'https://example.edu/programme', import_source: { version: 1, description_source: 'page_text', ai_input_scope: 'source_excerpt', llm_enriched: true },
    provider_allowed: false, contact_policy: { state: 'unknown', reason: 'unverified_import', quotes: [] }, ...patch };
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
async function drain() { await act(async () => { for (let n = 0; n < 20; n++) await Promise.resolve(); }); }
async function tick(ms: number) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); }
async function changeOwner(uid: string) { await act(async () => { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }); await drain(); }
function online(value: boolean) { Object.defineProperty(navigator, 'onLine', { configurable: true, value }); act(() => window.dispatchEvent(new Event(value ? 'online' : 'offline'))); }
beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  advanceOwnerEpoch(null); advanceOwnerEpoch(OWNER); await syncLocalIdentityOwner(OWNER);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
  mocks.read.mockReset().mockImplementation(async (id: string, options: { owner: { uid: string } }) => target({ id, owner_id: options.owner.uid }));
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('private email context lifecycle', () => {
  it('publishes the full unverified context and a fresh immutable owner-bound receipt without writes', async () => {
    const writes = vi.spyOn(localStorage, 'setItem');
    const { result } = renderHook(() => usePrivateEmailTarget(true, ID)); await drain();
    expect(result.current.status).toBe('ready'); expect(result.current.target).toEqual(target());
    expect(mocks.read).toHaveBeenCalledExactlyOnceWith(ID, { owner: captureOwnerToken(), signal: expect.any(AbortSignal) });
    const first = result.current.target;
    let receipt: PrivateEmailActionReceipt | null = null;
    await act(async () => { receipt = await result.current.checkForAction(); });
    expect(receipt).toMatchObject({ owner: captureOwnerToken(), target: target(), key: privateEmailKey(target()) });
    expect(receipt!.target).toBe(first); expect(Object.isFrozen(receipt)).toBe(true); expect(Object.isFrozen(receipt!.target.contact_policy)).toBe(true);
    expect(mocks.read).toHaveBeenCalledTimes(2); expect(writes).not.toHaveBeenCalled();
  });
  it('retains explicit blocked context for review but returns no action receipt', async () => {
    const blocked = target({ contact_policy: { state: 'blocked', reason: 'no_email', quotes: [{ start: 0, end: 8, quote: 'No email', restriction: 'no_email' }] } });
    mocks.read.mockResolvedValue(blocked);
    const { result } = renderHook(() => usePrivateEmailTarget(true, ID)); await drain();
    expect(result.current).toMatchObject({ status: 'blocked', reason: 'no_email', target: blocked });
    let receipt: PrivateEmailActionReceipt | null = null;
    await act(async () => { receipt = await result.current.checkForAction(); }); expect(receipt).toBeNull(); expect(result.current.status).toBe('blocked');
  });
  it.each(['not_found', 'deleted', 'invalid_receipt', 'timeout', 'unavailable'])('withdraws authority for %s, keeps same-session draft context, and permits explicit retry', async code => {
    const { result } = renderHook(() => usePrivateEmailTarget(true, ID)); await drain(); const previous = result.current.target;
    mocks.read.mockRejectedValueOnce({ code, message: 'PRIVATE response body' });
    let ready = true; await act(async () => { ready = await result.current.refresh(); });
    expect(ready).toBe(false); expect(result.current.status).toBe(['not_found', 'deleted'].includes(code) ? 'missing' : 'failed');
    expect(result.current.target).toBe(previous); expect(JSON.stringify(result.current)).not.toContain('PRIVATE response body');
    await act(async () => { ready = await result.current.refresh(); }); expect(ready).toBe(true); expect(result.current.status).toBe('ready');
  });
  it('bounds an ignored-abort read, permits retry, and cannot revive from its late result', async () => {
    const { result } = renderHook(() => usePrivateEmailTarget(true, ID)); await drain(); const old = result.current.target;
    const held = deferred<PrivateEmailContext>(); mocks.read.mockReturnValueOnce(held.promise);
    let receipt!: Promise<PrivateEmailActionReceipt | null>; act(() => { receipt = result.current.checkForAction(); }); await drain();
    const signal = mocks.read.mock.calls[1][1].signal as AbortSignal;
    await tick(PRIVATE_EMAIL_DEADLINE_MS); expect(await receipt).toBeNull(); expect(signal.aborted).toBe(true);
    expect(result.current).toMatchObject({ status: 'failed', reason: 'timeout' }); expect(result.current.target).toBe(old);
    await act(async () => { expect(await result.current.refresh()).toBe(true); });
    held.resolve(target({ title: 'Late obsolete source' })); await drain(); expect(result.current.target).toBe(old); expect(result.current.status).toBe('ready');
  });
  it.each(['close', 'id', 'owner', 'unmount'] as const)('immediately cancels the pending action on %s and ignores a late context', async change => {
    const held = deferred<PrivateEmailContext>(); mocks.read.mockReturnValueOnce(held.promise);
    const { result, rerender, unmount } = renderHook(({ open, id }) => usePrivateEmailTarget(open, id), { initialProps: { open: true, id: ID } }); await drain();
    const signal = mocks.read.mock.calls[0][1].signal as AbortSignal;
    let receipt!: Promise<PrivateEmailActionReceipt | null>; act(() => { receipt = result.current.checkForAction(); });
    if (change === 'close') rerender({ open: false, id: ID });
    else if (change === 'id') rerender({ open: true, id: `${ID}-other` });
    else if (change === 'owner') await changeOwner(OTHER); else unmount();
    await drain(); expect(signal.aborted).toBe(true); expect(await receipt).toBeNull();
    held.resolve(target({ title: 'Private old owner title' })); await drain();
    if (change !== 'unmount') expect(result.current.target?.title).not.toBe('Private old owner title');
    if (change === 'close') expect(result.current.target).toBeNull();
    if (change === 'owner') expect(result.current.target?.owner_id).toBe(OTHER);
  });
  it('does not expose old ready state after reopening, including the first render', async () => {
    const seen: string[] = [];
    const { result, rerender } = renderHook(({ open }) => { const value = usePrivateEmailTarget(open, ID); seen.push(value.status); return value; }, { initialProps: { open: true } }); await drain();
    rerender({ open: false }); const held = deferred<PrivateEmailContext>(); mocks.read.mockReturnValueOnce(held.promise);
    seen.length = 0; rerender({ open: true }); await drain(); expect(seen).not.toContain('ready'); expect(result.current.target).toBeNull();
    held.resolve(target()); await drain(); expect(result.current.status).toBe('ready');
  });
  it('retires the old same-account generation and never restores its source', async () => {
    const { result } = renderHook(() => usePrivateEmailTarget(true, ID)); await drain();
    const held = deferred<PrivateEmailContext>(); mocks.read.mockReturnValueOnce(held.promise);
    let receipt!: Promise<PrivateEmailActionReceipt | null>; act(() => { receipt = result.current.checkForAction(); }); await drain();
    mocks.read.mockResolvedValue(target({ title: 'New namespace source' }));
    await act(async () => {
      const marker = JSON.parse(localStorage.getItem('ofe_local_identity_owner')!);
      localStorage.setItem('ofe_local_identity_owner', JSON.stringify({ ...marker, generation: marker.generation + 1, phase: 'switching' }));
      window.dispatchEvent(new StorageEvent('storage', { key: 'ofe_local_identity_owner' })); await syncLocalIdentityOwner(OWNER);
    }); await drain(); expect(await receipt).toBeNull(); expect(result.current.target?.title).toBe('New namespace source');
    held.resolve(target()); await drain(); expect(result.current.target?.title).toBe('New namespace source');
  });
  it('shares one in-flight read but takes a fresh read for each completed action', async () => {
    const { result } = renderHook(() => usePrivateEmailTarget(true, ID)); await drain();
    const held = deferred<PrivateEmailContext>(); mocks.read.mockReturnValueOnce(held.promise); await tick(PRIVATE_EMAIL_INTERVAL_MS);
    let a!: Promise<PrivateEmailActionReceipt | null>, b!: Promise<PrivateEmailActionReceipt | null>;
    act(() => { a = result.current.checkForAction(); b = result.current.checkForAction(); }); expect(a).toBe(b); expect(result.current.status).toBe('checking');
    held.resolve(target({ revision: 2, writing_version: `pwt1:${'c'.repeat(64)}` })); await drain(); const receipt = await a;
    expect(receipt?.target.revision).toBe(2); expect(mocks.read).toHaveBeenCalledTimes(2);
    await act(async () => { const next = await result.current.checkForAction(); expect(next!.checkId).toBeGreaterThan(receipt!.checkId); });
    expect(mocks.read).toHaveBeenCalledTimes(3);
  });
  it('withdraws action authority offline and rechecks on return without local writes', async () => {
    const { result } = renderHook(() => usePrivateEmailTarget(true, ID)); await drain(); const previous = result.current.target;
    online(false); await drain(); expect(result.current.status).toBe('offline'); expect(await result.current.checkForAction()).toBeNull();
    await tick(PRIVATE_EMAIL_INTERVAL_MS * 2); expect(mocks.read).toHaveBeenCalledOnce(); expect(result.current.target).toBe(previous);
    online(true); await drain(); expect(mocks.read).toHaveBeenCalledTimes(2); expect(result.current.status).toBe('ready');
  });
});

const PROFILE: ProfileData = { institution: 'UIUC', college: 'Engineering', major: 'CS', grade: 'Junior', is_international: false, research_interests: 'robots', skills: [] };
describe('private target action consumption', () => {
  it.each(['edit', 'scope', 'none'] as const)('uses a fresh displayed private receipt and retires %s changes during the read', async change => {
    const execute = vi.fn();
    const { result, rerender } = renderHook(({ edit, scope }) => {
      const source = usePrivateEmailTarget(true, ID);
      const action = useProfileAction({ isOpen: true, profile: PROFILE, profileAvailable: true, scopeKey: scope, editRevision: edit,
        privateTarget: source.target, privateTargetRefresh: source, readiness: source.status === 'ready' ? 'ready' : 'waiting', execute });
      return { source, action };
    }, { initialProps: { edit: 0, scope: 'private' } }); await drain();
    const held = deferred<PrivateEmailContext>(); mocks.read.mockReturnValueOnce(held.promise);
    act(() => result.current.action.request({ kind: 'compose' })); await drain(); expect(execute).not.toHaveBeenCalled();
    if (change !== 'none') { rerender({ edit: change === 'edit' ? 1 : 0, scope: change === 'scope' ? 'public' : 'private' }); rerender({ edit: 0, scope: 'private' }); }
    held.resolve(target()); await drain(); expect(result.current.action.busy).toBe(false);
    if (change === 'none') expect(execute).toHaveBeenCalledExactlyOnceWith({ kind: 'compose' }); else expect(execute).not.toHaveBeenCalled();
  });
});
