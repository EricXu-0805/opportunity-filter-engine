import { StrictMode } from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedProfile } from '@/lib/supabase';
import type { ProfileHydration } from '@/lib/profile-sync';

const mocks = vi.hoisted(() => ({
  auth: null as null | ((state: { user: { id: string } | null }) => void),
  load: vi.fn<(signal?: AbortSignal) => Promise<LoadedProfile>>(), commit: vi.fn(),
  hydrations: [] as Promise<ProfileHydration>[], params: new URLSearchParams(),
  router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
vi.mock('next/navigation', () => ({ useRouter: () => mocks.router, useSearchParams: () => mocks.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
vi.mock('@/lib/supabase', () => ({
  loadProfile: (signal?: AbortSignal) => mocks.load(signal),
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
import { advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, readUserScopedRaw, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { hydrateProfile, readProfileSyncEnvelope, recordProfileIntent, resetProfileDirtyLedger, stageProfilePatch } from '@/lib/profile-sync';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { encodeProfile } from '@/lib/profile-share';

const UID = 'home-load-recovery-owner';
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
  mocks.auth = null; mocks.load.mockReset(); mocks.commit.mockReset(); mocks.hydrations = []; mocks.params = new URLSearchParams();
  resetProfileDirtyLedger(); advanceOwnerEpoch(null); advanceOwnerEpoch(UID);
  await syncLocalIdentityOwner(UID);
  expect(isOwnerTokenValid(captureOwnerToken(), UID)).toBe(true);
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });


const DEADLINE = 15_000;
const mirror = () => JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE) ?? 'null');
async function drain() { await act(async () => { for (let i = 0; i < 30; i += 1) await Promise.resolve(); }); }
function start() {
  const hook = renderHook(() => useProfileForm(t));
  act(() => { mocks.auth?.({ user: { id: UID } }); });
  return hook;
}
async function deadline() { await act(async () => { await vi.advanceTimersByTimeAsync(DEADLINE); }); }

describe('Home load deadline and explicit read recovery', () => {
  it('fails after 15 seconds without replacing the profile or writing defaults', async () => {
    const pending = deferred<LoadedProfile>(); mocks.load.mockReturnValue(pending.promise);
    const { result } = start(); await deadline();
    expect(result.current.hydrationState).toBe('failed');
    expect(mocks.load.mock.calls[0][0]?.aborted).toBe(true);
    expect(mirror()).toBeNull(); expect(readProfileSyncEnvelope()).toBeNull(); expect(mocks.commit).not.toHaveBeenCalled();
    pending.resolve(cloudRow('TOO LATE')); await settleHydrations();
    expect(result.current.hydrationState).toBe('failed'); expect(mirror()).toBeNull();
    expect(result.current.profile.name).not.toBe('TOO LATE');
  });

  it('retries with a fresh signal and does not reuse a hung read or let its late high-revision row fill the form', async () => {
    const old = deferred<LoadedProfile>(); const fresh = deferred<LoadedProfile>();
    const oldRow = { ...cloudRow('LATE OLD ROW'), revision: 99 };
    mocks.load.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const { result } = start(); await deadline();
    act(() => { result.current.retryProfileLoad(); });
    expect(result.current.hydrationState).toBe('loading'); expect(mocks.load).toHaveBeenCalledTimes(2);
    expect(mocks.load.mock.calls[1][0]).not.toBe(mocks.load.mock.calls[0][0]);
    fresh.resolve(cloudRow('Fresh retry')); await drain();
    expect(result.current.hydrationState).toBe('ready'); expect(result.current.profile.name).toBe('Fresh retry');
    old.resolve(oldRow); await settleHydrations();
    expect(result.current.profile.name).toBe('Fresh retry'); expect(mirror().name).toBe('Fresh retry');
    expect(readProfileSyncEnvelope()?.confirmed?.revision).toBe(1); expect(mocks.commit).not.toHaveBeenCalled();
  });

  it('keeps typed fields and the generation across failed-read retry, merging untouched cloud fields', async () => {
    const old = deferred<LoadedProfile>(); const next = deferred<LoadedProfile>();
    mocks.load.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
    const { result } = start(); const generation = result.current.identityGeneration;
    act(() => { result.current.update('research_interests', 'Personal typed text'); });
    await deadline(); expect(result.current.profile.research_interests).toBe('Personal typed text');
    expect(mocks.commit).not.toHaveBeenCalled();
    act(() => { result.current.retryProfileLoad(); });
    expect(result.current.profile.research_interests).toBe('Personal typed text');
    act(() => { result.current.update('research_interests', 'Personal edited during retry'); });
    next.resolve(cloudRow('Cloud name')); await drain();
    expect(result.current.identityGeneration).toBe(generation); expect(result.current.hydrationState).toBe('ready');
    expect(result.current.profile).toMatchObject({ name: 'Cloud name', major: 'Computer Science', research_interests: 'Personal edited during retry' });
    expect(mocks.commit).not.toHaveBeenCalled(); // No timers advanced into the normal autosave.
    old.resolve(cloudRow('Retired')); await settleHydrations();
  });

  it('retires an earlier same-generation attempt without allowing its finally to release the new read', async () => {
    const old = deferred<LoadedProfile>(); const next = deferred<LoadedProfile>();
    mocks.load.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
    const { result } = start();
    act(() => { result.current.retryProfileLoad(); });
    await drain(); expect(mocks.load).toHaveBeenCalledTimes(2);
    expect(mocks.load.mock.calls[0][0]?.aborted).toBe(true);
    old.reject(new Error('late retired failure')); await drain();
    expect(result.current.hydrationState).toBe('loading');
    act(() => { mocks.auth?.({ user: { id: UID } }); });
    expect(mocks.load).toHaveBeenCalledTimes(2);
    next.resolve(cloudRow('Active read')); await settleHydrations(); expect(result.current.profile.name).toBe('Active read');
  });

  it('cancels on a real owner switch and never merges the old input or receipt into the new row', async () => {
    const old = deferred<LoadedProfile>(); const oldRow = cloudRow('Private old name');
    mocks.load.mockReturnValueOnce(old.promise).mockImplementation(async () => cloudRow('Other owner'));
    const { result } = start();
    act(() => { result.current.update('research_interests', 'Old private input'); });
    await act(async () => {
      advanceOwnerEpoch('home-load-new-owner'); await syncLocalIdentityOwner('home-load-new-owner');
      mocks.auth?.({ user: { id: 'home-load-new-owner' } });
    });
    await drain(); expect(mocks.load.mock.calls[0][0]?.aborted).toBe(true);
    expect(result.current.profile.name).toBe('Other owner');
    expect(result.current.profile.research_interests).not.toBe('Old private input');
    old.resolve(oldRow); await settleHydrations(); expect(result.current.profile.name).toBe('Other owner');
    expect(mocks.commit).not.toHaveBeenCalled();
  });

  it('cancels on unmount before the cloud result can reach the coordinator mirror', async () => {
    const pending = deferred<LoadedProfile>(); mocks.load.mockReturnValue(pending.promise);
    const { unmount } = start(); unmount();
    expect(mocks.load.mock.calls[0][0]?.aborted).toBe(true);
    pending.resolve(cloudRow('Unmounted profile')); await settleHydrations(); await deadline();
    expect(mirror()).toBeNull(); expect(readProfileSyncEnvelope()).toBeNull(); expect(mocks.commit).not.toHaveBeenCalled();
  });

  it('fails a stale preflight with no active read; explicit retry uses a complete owner reset, not a buffer rebind', async () => {
    mocks.load.mockImplementation(async () => cloudRow('New owner row'));
    const { result } = renderHook(() => useProfileForm(t));
    act(() => { result.current.update('research_interests', 'OLD OWNER INPUT'); });
    await act(async () => { advanceOwnerEpoch('undelivered-owner'); await syncLocalIdentityOwner('undelivered-owner'); });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); }); // Fallback preflight rejects the old screen.
    expect(result.current.hydrationState).toBe('failed'); expect(mocks.load).not.toHaveBeenCalled();
    expect(result.current.viewSnapshot).toBeNull(); expect(mirror()).toBeNull();
    act(() => { result.current.retryProfileLoad(); }); await settleHydrations();
    expect(result.current.hydrationState).toBe('ready'); expect(result.current.profile.name).toBe('New owner row');
    expect(result.current.profile.research_interests).not.toBe('OLD OWNER INPUT');
    expect(result.current.viewSnapshot?.token).toEqual(captureOwnerToken()); expect(mocks.commit).not.toHaveBeenCalled();
  });

  it('reports null-origin timeout after first UID resolution, then explicitly carries only never-owned input', async () => {
    advanceOwnerEpoch(null); localStorage.clear();
    const old = deferred<LoadedProfile>(); mocks.load.mockReturnValueOnce(old.promise).mockImplementation(async () => cloudRow('First identity'));
    const { result } = renderHook(() => useProfileForm(t));
    act(() => { mocks.auth?.({ user: null }); result.current.update('research_interests', 'First-visit input'); });
    await act(async () => { advanceOwnerEpoch(UID); await syncLocalIdentityOwner(UID); }); // No Home auth callback yet.
    await deadline(); expect(result.current.hydrationState).toBe('failed');
    expect(result.current.viewSnapshot).toBeNull(); expect(mocks.commit).not.toHaveBeenCalled();
    act(() => { result.current.retryProfileLoad(); }); await drain();
    expect(result.current.hydrationState).toBe('ready');
    expect(result.current.profile).toMatchObject({ name: 'First identity', research_interests: 'First-visit input' });
    expect(result.current.viewSnapshot?.token).toEqual(captureOwnerToken());
    old.resolve(cloudRow('Retired null read')); await settleHydrations(); expect(result.current.profile.name).toBe('First identity');
  });

  it('retires a pending read when a valid share arrives; neither its timer nor late result replaces the draft', async () => {
    const pending = deferred<LoadedProfile>(); mocks.load.mockReturnValueOnce(pending.promise);
    const { result, rerender } = start();
    mocks.params = new URLSearchParams({ share: encodeProfile({ ...DEFAULT_PROFILE, college: 'Shared college', research_interests: 'Shared draft' }) });
    rerender();
    expect(result.current.hydrationState).toBe('ready'); expect(mocks.load.mock.calls[0][0]?.aborted).toBe(true);
    await deadline(); act(() => { result.current.retryProfileLoad(); });
    expect(result.current.hydrationState).toBe('ready'); expect(result.current.profile.research_interests).toBe('Shared draft');
    pending.resolve(cloudRow('Late owner profile')); await settleHydrations();
    expect(result.current.profile.research_interests).toBe('Shared draft'); expect(mirror()).toBeNull();
    expect(mocks.load).toHaveBeenCalledTimes(1); expect(mocks.commit).not.toHaveBeenCalled();
  });

  it('survives StrictMode setup/cleanup replay and same-owner notifications without duplicate healthy reads', async () => {
    const pending = deferred<LoadedProfile>(); mocks.load.mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useProfileForm(t), { wrapper: StrictMode });
    act(() => { mocks.auth?.({ user: { id: UID } }); mocks.auth?.({ user: { id: UID } }); });
    expect(mocks.load).toHaveBeenCalledTimes(1);
    pending.resolve(cloudRow('Strict mode current')); await settleHydrations();
    expect(result.current.hydrationState).toBe('ready'); expect(result.current.profile.name).toBe('Strict mode current');
    expect(mocks.commit).not.toHaveBeenCalled();
  });

  it('clears the read deadline before a valid recovered-outbox flush, keeping its actual pending and saved states', async () => {
    const base = cloudRow('Saved name'); mocks.load.mockResolvedValue(base);
    await hydrateProfile();
    const desired = { ...base.profile!, research_interests: 'Previously journalled' } as typeof DEFAULT_PROFILE;
    expect(recordProfileIntent(desired, ['research_interests'], captureOwnerToken())).toBe(true);
    mocks.commit.mockResolvedValueOnce({ status: 'transport-error', message: 'offline' });
    await stageProfilePatch(desired, ['research_interests'], captureOwnerToken());
    const save = deferred<unknown>(); mocks.commit.mockReset().mockReturnValue(save.promise);
    const { result } = start(); await drain();
    expect(result.current.hydrationState).toBe('ready'); expect(result.current.saveStatus).toBe('saving');
    expect(mocks.commit).toHaveBeenCalledTimes(1); await deadline();
    expect(result.current.hydrationState).toBe('ready'); expect(result.current.saveStatus).toBe('saving');
    expect(mocks.load.mock.calls.at(-1)?.[0]?.aborted).toBe(false);
    save.resolve({ status: 'saved', revision: 2, profile: desired }); await drain();
    expect(result.current.saveStatus).toBe('saved'); expect(mocks.commit).toHaveBeenCalledTimes(1);
  });
});
