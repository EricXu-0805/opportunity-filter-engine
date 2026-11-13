import golden from '../../../tests/fixtures/private-resume-context-v5-golden.json';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import type { Opportunity, ProfileData } from './types';
const mocks = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock('./private-resume', () => ({ getPrivateResumeContext: mocks.read }));
vi.mock('./use-profile-refresh', () => ({ PROFILE_REFRESH_DEADLINE_MS: 15_000 }));
import { privateResumeKey, type PrivateResumeContext } from './private-resume-context';
import { usePrivateResumeTarget, type PrivateResumeActionReceipt, type PrivateResumeTargetState } from './use-private-resume-target';
import { useProfileAction } from './use-profile-action';

const OWNER = golden.receipt.context.private_source.owner_id;
const OTHER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const ID = golden.receipt.context.opportunity_id;
const target = (patch: Partial<PrivateResumeContext> = {}): PrivateResumeContext => ({ ...structuredClone(golden.receipt.context), ...patch } as PrivateResumeContext);
const withOwner = (owner_id: string) => target({ private_source: { ...target().private_source, owner_id } });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
async function drain() { await act(async () => { for (let n = 0; n < 20; n++) await Promise.resolve(); }); }
async function changeOwner(uid: string) { await act(async () => { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }); await drain(); }
beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  advanceOwnerEpoch(null); advanceOwnerEpoch(OWNER); await syncLocalIdentityOwner(OWNER);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
  mocks.read.mockReset().mockImplementation(async () => target());
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('private résumé source read', () => {
  it('publishes the full unverified source and a fresh frozen owner-bound receipt', async () => {
    const { result } = renderHook(() => usePrivateResumeTarget(true, ID)); await drain();
    expect(result.current.status).toBe('ready'); expect(result.current.target).toEqual(target());
    expect(mocks.read).toHaveBeenCalledExactlyOnceWith(ID, { owner: captureOwnerToken(), signal: expect.any(AbortSignal) });
    let receipt: PrivateResumeActionReceipt | null = null;
    await act(async () => { receipt = await result.current.checkForAction(); });
    expect(receipt).toMatchObject({ owner: captureOwnerToken(), target: target(), key: privateResumeKey(target()) });
    expect(Object.isFrozen(receipt)).toBe(true); expect(Object.isFrozen(receipt!.target.private_source)).toBe(true);
    expect(mocks.read).toHaveBeenCalledTimes(2);
  });
  it('refuses a source read for another import', async () => {
    mocks.read.mockResolvedValue(target({ opportunity_id: 'private-import:b2000000-0000-4000-8000-000000000001' }));
    const { result } = renderHook(() => usePrivateResumeTarget(true, ID)); await drain();
    expect(result.current).toMatchObject({ status: 'failed', reason: 'invalid_target', target: null });
  });
  it.each([['too_large', 'too_large'], ['unavailable', 'read_failed'], ['invalid_receipt', 'invalid_target']])('reports %s as reason %s', async (code, reason) => {
    mocks.read.mockRejectedValue({ code });
    const { result } = renderHook(() => usePrivateResumeTarget(true, ID)); await drain();
    expect(result.current).toMatchObject({ status: 'failed', reason });
  });
  it('cancels a pending action on an account change and ignores its late source', async () => {
    const held = deferred<PrivateResumeContext>(); mocks.read.mockReturnValueOnce(held.promise);
    const { result } = renderHook(() => usePrivateResumeTarget(true, ID)); await drain();
    let receipt!: Promise<PrivateResumeActionReceipt | null>; act(() => { receipt = result.current.checkForAction(); });
    await changeOwner(OTHER); expect(await receipt).toBeNull();
    held.resolve(target({ title: 'Previous account title' })); await drain();
    expect(result.current.target?.title).not.toBe('Previous account title');
  });
});

const PROFILE: ProfileData = { institution: 'Example University', college: 'Engineering', major: 'CS', grade: 'Junior', is_international: false, research_interests: 'robots', skills: [] };
describe('private résumé action', () => {
  it.each(['edit', 'scope', 'none'] as const)('runs only on a fresh displayed receipt and retires %s changes during the read', async change => {
    const execute = vi.fn();
    const { result, rerender } = renderHook(({ edit, scope }) => {
      const source = usePrivateResumeTarget(true, ID);
      const action = useProfileAction({ isOpen: true, profile: PROFILE, profileAvailable: true, scopeKey: scope, editRevision: edit,
        privateResume: source.target, privateResumeRefresh: source, readiness: source.status === 'ready' ? 'ready' : 'waiting', execute });
      return { source, action };
    }, { initialProps: { edit: 0, scope: 'private' } }); await drain();
    const held = deferred<PrivateResumeContext>(); mocks.read.mockReturnValueOnce(held.promise);
    act(() => result.current.action.request({ kind: 'compose' })); await drain(); expect(execute).not.toHaveBeenCalled();
    if (change !== 'none') { rerender({ edit: change === 'edit' ? 1 : 0, scope: change === 'scope' ? 'public' : 'private' }); rerender({ edit: 0, scope: 'private' }); }
    held.resolve(target()); await drain(); expect(result.current.action.busy).toBe(false);
    if (change === 'none') expect(execute).toHaveBeenCalledExactlyOnceWith({ kind: 'compose' }); else expect(execute).not.toHaveBeenCalled();
  });
  it('does not run on a receipt whose source names another account', async () => {
    mocks.read.mockImplementation(async () => withOwner(OTHER));
    const execute = vi.fn();
    const { result } = renderHook(() => {
      const source = usePrivateResumeTarget(true, ID);
      return useProfileAction({ isOpen: true, profile: PROFILE, profileAvailable: true, scopeKey: 'private', editRevision: 0,
        privateResume: source.target, privateResumeRefresh: source, readiness: source.status === 'ready' ? 'ready' : 'waiting', execute });
    }); await drain();
    act(() => result.current.request({ kind: 'compose' })); await drain();
    expect(execute).not.toHaveBeenCalled(); expect(result.current.error).toBe('unavailable');
  });
  it.each(['changed', 'relabelled', 'mixed'] as const)('does not run when the checked source is not the displayed one (%s)', async fault => {
    const execute = vi.fn(), shown = target(), checked = fault === 'changed' ? target({ title: 'Changed source' }) : shown;
    const state: PrivateResumeTargetState = { status: 'ready', target: shown, reason: null, refresh: async () => true,
      checkForAction: async () => ({ checkId: 1, owner: captureOwnerToken(), target: checked, key: fault === 'relabelled' ? 'another key' : privateResumeKey(checked)! }) };
    const { result } = renderHook(() => useProfileAction({ isOpen: true, profile: PROFILE, profileAvailable: true, scopeKey: 'private',
      editRevision: 0, privateResume: shown, privateResumeRefresh: state, readiness: 'ready', execute,
      ...(fault === 'mixed' ? { target: { id: ID } as Opportunity } : {}) }));
    act(() => result.current.request({ kind: 'compose' })); await drain(); await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(execute).not.toHaveBeenCalled();
  });
  it('refuses a private résumé source with no source check', async () => {
    const execute = vi.fn();
    const { result } = renderHook(() => useProfileAction({ isOpen: true, profile: PROFILE, profileAvailable: true, scopeKey: 'private',
      editRevision: 0, privateResume: target(), readiness: 'ready', execute }));
    act(() => result.current.request({ kind: 'compose' })); await drain();
    expect(execute).not.toHaveBeenCalled(); expect(result.current.error).toBe('unavailable');
  });
});
