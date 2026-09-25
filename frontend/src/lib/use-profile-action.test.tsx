import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('./use-profile-refresh', () => ({ PROFILE_REFRESH_DEADLINE_MS: 15_000 }));
import { useProfileAction, type ProfileActionOptions } from './use-profile-action';
import type { ProfileActionReceipt } from './use-profile-refresh';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import type { ProfileData } from './types';

const profile: ProfileData = { institution: 'UIUC', college: 'Engineering', major: 'CS', grade: 'Junior',
  is_international: false, research_interests: 'robots', skills: [] };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
async function drain() { await act(async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); }); }
function receipt(next: ProfileData | null = profile): ProfileActionReceipt {
  return { checkId: 1, owner: captureOwnerToken(), revision: 2, source: next ? 'cloud' : 'cloud-absent', profile: next };
}
function setup(extra: Partial<ProfileActionOptions<{ kind: string }>> = {}) {
  const read = deferred<ProfileActionReceipt | null>();
  const check = vi.fn(() => read.promise); const execute = vi.fn();
  const options: ProfileActionOptions<{ kind: string }> = { isOpen: true, profile, profileAvailable: true,
    scopeKey: 'target-one', editRevision: 1, readiness: 'ready', refresh: { status: 'ready', refresh: vi.fn(), checkForAction: check }, execute, ...extra };
  const hook = renderHook((props) => useProfileAction(props), { initialProps: options });
  return { ...hook, options, read, check, execute };
}
beforeEach(async () => { vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  advanceOwnerEpoch(null); advanceOwnerEpoch('action-owner'); await syncLocalIdentityOwner('action-owner'); });
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('read before profile-dependent action', () => {
  it('waits for the checked profile to commit and runs the latest executor once', async () => {
    const { result, rerender, options, read, check, execute } = setup();
    const intent = { kind: 'create' }; act(() => result.current.request(intent)); intent.kind = 'mutated';
    expect(result.current.busy).toBe(true); expect(execute).not.toHaveBeenCalled(); await drain();
    const next = { ...profile, major: 'Physics' }; read.resolve(receipt(next)); await drain();
    expect(execute).not.toHaveBeenCalled(); expect(result.current.busy).toBe(true);
    const currentExecutor = vi.fn(); rerender({ ...options, profile: next, readiness: 'waiting', execute: currentExecutor });
    expect(currentExecutor).not.toHaveBeenCalled();
    rerender({ ...options, profile: next, readiness: 'ready', execute: currentExecutor }); await drain();
    expect(currentExecutor).toHaveBeenCalledExactlyOnceWith({ kind: 'create' }); expect(execute).not.toHaveBeenCalled();
    expect(check).toHaveBeenCalledOnce(); expect(result.current.busy).toBe(false);
    rerender({ ...options, profile: next, execute: currentExecutor }); await drain(); expect(currentExecutor).toHaveBeenCalledOnce();
  });
  it('deduplicates synchronous double-clicks and ignores object-key order only', async () => {
    const { result, read, check, execute } = setup();
    act(() => { result.current.request({ kind: 'first' }); result.current.request({ kind: 'second' }); }); await drain();
    read.resolve(receipt(Object.fromEntries(Object.entries(profile).reverse()) as unknown as ProfileData)); await drain();
    expect(check).toHaveBeenCalledOnce(); expect(execute).toHaveBeenCalledExactlyOnceWith({ kind: 'first' });
  });
  it('does not run a stale request after a third source replaces the checked candidate', async () => {
    const { result, options, rerender, read, execute } = setup();
    act(() => result.current.request({ kind: 'create' })); await drain();
    read.resolve(receipt({ ...profile, major: 'Physics' })); await drain();
    rerender({ ...options, profile: { ...profile, major: 'Chemistry' } }); await drain();
    expect(result.current.error).toBe('changed'); expect(result.current.busy).toBe(false); expect(execute).not.toHaveBeenCalled();
  });
  it('retires a matched candidate that later reverts while target readiness is pending', async () => {
    const { result, options, rerender, read, execute } = setup({ readiness: 'waiting' });
    act(() => result.current.request({ kind: 'create' })); await drain();
    const next = { ...profile, major: 'Physics' }; read.resolve(receipt(next));
    rerender({ ...options, profile: next }); await drain();
    rerender({ ...options, readiness: 'ready' }); await drain();
    expect(result.current.error).toBe('changed'); expect(execute).not.toHaveBeenCalled();
  });
  it.each(['edit', 'scope', 'close', 'delete'] as const)('retires %s during the read and does not revive on restoration', async (change) => {
    const { result, options, rerender, read, execute } = setup();
    act(() => result.current.request({ kind: 'create' })); await drain();
    rerender({ ...options, ...(change === 'edit' ? { editRevision: 2 } : change === 'scope' ? { scopeKey: 'target-two' }
      : change === 'close' ? { isOpen: false } : { profile: null, profileAvailable: false }) });
    rerender(options); read.resolve(receipt()); await drain();
    expect(result.current.busy).toBe(false); expect(execute).not.toHaveBeenCalled();
  });
  it.each(['uid', 'epoch', 'generation'] as const)('rejects a changed owner %s even if the same profile returns', async (change) => {
    const { result, read, execute } = setup(); const old = receipt();
    act(() => result.current.request({ kind: 'create' })); await drain();
    await act(async () => {
      if (change === 'generation') {
        const marker = JSON.parse(localStorage.getItem('ofe_local_identity_owner') ?? 'null');
        expect(marker).not.toBeNull();
        localStorage.setItem('ofe_local_identity_owner', JSON.stringify({ ...marker, generation: marker.generation + 1, phase: 'switching' }));
        window.dispatchEvent(new StorageEvent('storage', { key: 'ofe_local_identity_owner' }));
        await syncLocalIdentityOwner('action-owner');
      } else { advanceOwnerEpoch(null); advanceOwnerEpoch(change === 'uid' ? 'other-owner' : 'action-owner'); await syncLocalIdentityOwner(captureOwnerToken().uid!); }
    });
    read.resolve(old); await drain(); expect(execute).not.toHaveBeenCalled(); expect(result.current.busy).toBe(false);
  });
  it.each(['null', 'deleted', 'reject'] as const)('clears the intent after a %s result without exposing errors', async (kind) => {
    const { result, read, execute } = setup(); act(() => result.current.request({ kind: 'create' })); await drain();
    if (kind === 'reject') read.reject(new Error('PRIVATE cloud body'));
    else read.resolve(kind === 'deleted' ? receipt(null) : null);
    await drain(); expect(result.current.error).toBe('unavailable'); expect(result.current.busy).toBe(false); expect(execute).not.toHaveBeenCalled();
  });
  it('permits a new check after an earlier failed status, but not a settled blocked target', async () => {
    const { result, read, check, execute } = setup({ readiness: 'blocked' });
    act(() => result.current.request({ kind: 'create' })); await drain(); expect(check).toHaveBeenCalledOnce();
    read.resolve(receipt()); await drain(); expect(result.current.error).toBe('unavailable'); expect(execute).not.toHaveBeenCalled();
  });
  it.each(['checking', 'render', 'target'] as const)('bounds an unresolved %s phase without executing', async (phase) => {
    const { result, read, execute } = setup({ readiness: phase === 'target' ? 'waiting' : 'ready' });
    act(() => result.current.request({ kind: 'create' })); await drain();
    if (phase !== 'checking') { read.resolve(receipt(phase === 'render' ? { ...profile, major: 'Fresh' } : profile)); await drain(); }
    await act(async () => vi.advanceTimersByTimeAsync(15_000));
    expect(result.current.busy).toBe(false); expect(result.current.error).toBe('unavailable');
    read.resolve(receipt()); await drain(); expect(execute).not.toHaveBeenCalled();
  });
  it('cancel and unmount retire late receipts without cancelling another consumer shared read', async () => {
    const { result, read, unmount, check, execute } = setup();
    act(() => result.current.request({ kind: 'create' })); await drain(); act(() => result.current.cancel());
    expect(result.current.busy).toBe(false); unmount(); read.resolve(receipt()); await drain();
    expect(check).toHaveBeenCalledOnce(); expect(execute).not.toHaveBeenCalled();
  });
  it('does not start a queued read after synchronous unmount', async () => {
    const { result, unmount, check } = setup(); act(() => result.current.request({ kind: 'create' })); unmount(); await drain();
    expect(check).not.toHaveBeenCalled();
  });
  it('supports unchanged legacy callers without claiming a cloud check', async () => {
    const { result, check, execute } = setup({ refresh: undefined });
    act(() => result.current.request({ kind: 'legacy' })); await drain();
    expect(check).not.toHaveBeenCalled(); expect(execute).toHaveBeenCalledExactlyOnceWith({ kind: 'legacy' });
  });
});
