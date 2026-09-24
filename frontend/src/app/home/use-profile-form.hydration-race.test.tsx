import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedProfile } from '@/lib/supabase';
import type { ProfileHydration } from '@/lib/profile-sync';

const mocks = vi.hoisted(() => ({
  auth: null as null | ((state: { user: { id: string } | null }) => void),
  load: vi.fn<() => Promise<LoadedProfile>>(), commit: vi.fn(),
  hydrations: [] as Promise<ProfileHydration>[], params: new URLSearchParams(),
  router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
vi.mock('next/navigation', () => ({ useRouter: () => mocks.router, useSearchParams: () => mocks.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
vi.mock('@/lib/supabase', () => ({
  loadProfile: () => mocks.load(),
  commitProfilePatch: (...args: unknown[]) => mocks.commit(...args),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: typeof mocks.auth) => { mocks.auth = callback; return () => { mocks.auth = null; }; },
}));
// Keep real reconciliation and capability guards. Await its exact promises;
// no sleeps or larger timeout can make this controlled schedule pass.
vi.mock('@/lib/profile-sync', async (importActual) => {
  const actual = await importActual<typeof import('@/lib/profile-sync')>();
  return { ...actual, hydrateProfile: (...args: Parameters<typeof actual.hydrateProfile>) => {
    const pending = actual.hydrateProfile(...args); mocks.hydrations.push(pending); return pending;
  } };
});
import { useProfileForm } from './use-profile-form';
import { DEFAULT_PROFILE } from './types';
import { advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, OwnerNotReadyError, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { resetProfileDirtyLedger } from '@/lib/profile-sync';

const UID = 'hydration-race-owner';
const t = (key: string) => key;
function deferred<T>() {
  let resolve!: (value: T) => void; let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const cloudRow = (name: string): LoadedProfile => ({ source: 'cloud', revision: 1,
  profile: { ...DEFAULT_PROFILE, name, college: 'Engineering', major: 'Computer Science', grade: 'Junior' },
  token: captureOwnerToken() });
async function settleHydrations() {
  await act(async () => {
    let seen = -1;
    while (seen !== mocks.hydrations.length) {
      seen = mocks.hydrations.length;
      await Promise.allSettled([...mocks.hydrations]);
    }
  });
}
beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  mocks.auth = null; mocks.load.mockReset(); mocks.commit.mockReset(); mocks.hydrations = [];
  resetProfileDirtyLedger(); advanceOwnerEpoch(null); advanceOwnerEpoch(UID);
  await syncLocalIdentityOwner(UID);
  expect(isOwnerTokenValid(captureOwnerToken(), UID)).toBe(true);
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('Home hydration after owner epoch replacement', () => {
  it('control: the same UID and epoch re-observation does not duplicate a healthy pending load', async () => {
    const pending = deferred<LoadedProfile>(); const row = cloudRow('Current owner row');
    mocks.load.mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useProfileForm(t));
    act(() => { mocks.auth?.({ user: { id: UID } }); });
    expect(mocks.load).toHaveBeenCalledTimes(1);
    act(() => { mocks.auth?.({ user: { id: UID } }); });
    expect(mocks.load).toHaveBeenCalledTimes(1);
    pending.resolve(row); await settleHydrations();
    expect(result.current.hydrationState).toBe('ready');
    expect(result.current.profile.name).toBe('Current owner row');
    expect(mocks.commit).not.toHaveBeenCalled();
  });
  it('control: a real UID transition loads the new row while the old read is pending and never paints the old row', async () => {
    const pending = deferred<LoadedProfile>(); const oldRow = cloudRow('RETIRED PRIVATE ROW');
    mocks.load.mockReturnValueOnce(pending.promise).mockImplementation(async () => cloudRow('Different owner row'));
    const { result } = renderHook(() => useProfileForm(t));
    act(() => { mocks.auth?.({ user: { id: UID } }); });
    await act(async () => {
      advanceOwnerEpoch('hydration-race-second-owner');
      await syncLocalIdentityOwner('hydration-race-second-owner');
      mocks.auth?.({ user: { id: 'hydration-race-second-owner' } });
    });
    expect(mocks.load).toHaveBeenCalledTimes(2);
    pending.resolve(oldRow); await settleHydrations();
    expect(result.current.hydrationState).toBe('ready');
    expect(result.current.profile.name).toBe('Different owner row');
    expect(result.current.viewSnapshot?.token).toEqual(captureOwnerToken());
    expect(mocks.commit).not.toHaveBeenCalled();
  });
  it('starts a new screen after same-UID epoch replacement without reauthorizing a buffered edit', async () => {
    mocks.load.mockImplementation(async () => cloudRow('Saved cloud name'));
    const { result, unmount } = renderHook(() => useProfileForm(t));
    act(() => { mocks.auth?.({ user: { id: UID } }); });
    await settleHydrations();
    const before = result.current.identityGeneration;
    // First keystroke is already journalled for this account. Only the next
    // keystroke remains in the screen's debounce buffer.
    act(() => { result.current.update('research_interests', 'Durable first edit'); });
    act(() => { result.current.update('research_interests', 'RETIRED UNSAVED EDIT'); });
    expect(result.current.profile.research_interests).toBe('RETIRED UNSAVED EDIT');
    await act(async () => {
      advanceOwnerEpoch(null); advanceOwnerEpoch(UID); await syncLocalIdentityOwner(UID);
      mocks.auth?.({ user: { id: UID } });
    });
    await settleHydrations();
    expect(result.current.identityGeneration).toBe(before + 1);
    expect(result.current.profile.research_interests).toBe('Durable first edit');
    expect(result.current.viewSnapshot?.token).toEqual(captureOwnerToken());
    unmount();
    await act(async () => { await vi.runAllTimersAsync(); });
    expect(mocks.commit.mock.calls.every(([intent]) => intent.patch.research_interests !== 'RETIRED UNSAVED EDIT')).toBe(true);
  });
  it('retries a failed read on the same epoch without resetting the screen generation', async () => {
    mocks.load.mockRejectedValueOnce(new Error('offline')).mockImplementation(async () => cloudRow('Retry name'));
    const { result } = renderHook(() => useProfileForm(t));
    act(() => { mocks.auth?.({ user: { id: UID } }); });
    await settleHydrations();
    expect(result.current.hydrationState).toBe('failed');
    const before = result.current.identityGeneration;
    act(() => { mocks.auth?.({ user: { id: UID } }); });
    await settleHydrations();
    expect(result.current.identityGeneration).toBe(before);
    expect(result.current.hydrationState).toBe('ready');
    expect(result.current.profile.name).toBe('Retry name');
    expect(mocks.load).toHaveBeenCalledTimes(2);
    expect(mocks.commit).not.toHaveBeenCalled();
  });
  it.each(['before-select-abandonment', 'late-row'] as const)(
    'recovers the current epoch after a same-UID observation raced with %s', async (outcome) => {
      const pending = deferred<LoadedProfile>(); const oldRow = cloudRow('RETIRED PRIVATE ROW');
      const originalToken = oldRow.token;
      mocks.load.mockReturnValueOnce(pending.promise).mockImplementation(async () => cloudRow('Fresh owner row'));
      const { result } = renderHook(() => useProfileForm(t));
      act(() => { mocks.auth?.({ user: { id: UID } }); });
      expect(mocks.load).toHaveBeenCalledTimes(1);
      expect(result.current.hydrationState).toBe('loading');
      // An authority update can precede this subscriber's notification. The
      // same UID across a null/sign-out cycle is a different capability.
      await act(async () => {
        advanceOwnerEpoch(null); advanceOwnerEpoch(UID); await syncLocalIdentityOwner(UID);
        mocks.auth?.({ user: { id: UID } });
      });
      expect(captureOwnerToken().epoch).not.toBe(originalToken.epoch);
      expect(isOwnerTokenValid(captureOwnerToken(), UID)).toBe(true);
      if (outcome === 'before-select-abandonment') pending.reject(new OwnerNotReadyError());
      else pending.resolve(oldRow); // Actual coordinator refuses the stale row.
      await settleHydrations();
      expect(result.current.profile.name).not.toBe('RETIRED PRIVATE ROW');
      expect(mocks.commit).not.toHaveBeenCalled();
      // Even an observation AFTER finally must not reuse the retired origin.
      act(() => { mocks.auth?.({ user: { id: UID } }); });
      await settleHydrations();
      expect(result.current.hydrationState,
        'all old promises settled and a valid current owner was observed twice; Loading must not remain stranded').toBe('ready');
      expect(mocks.load).toHaveBeenCalledTimes(2);
      expect(result.current.profile.name).toBe('Fresh owner row');
      expect(result.current.viewSnapshot?.token).toEqual(captureOwnerToken());
      expect(mocks.commit).not.toHaveBeenCalled();
    },
  );
});
