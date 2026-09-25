import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import type { ProfileData } from '@/lib/types';

const service = vi.hoisted(() => ({
  auth: null as null | ((state: { user: { id: string } | null }) => void),
  load: vi.fn<(signal?: AbortSignal) => Promise<LoadedProfile>>(),
  commit: vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
  params: new URLSearchParams(), router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
vi.mock('next/navigation', () => ({ useRouter: () => service.router, useSearchParams: () => service.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
// Only transport is replaced. Actual profile reconciliation, journal operations,
// owner capabilities, field provenance and Home save handling stay in use.
vi.mock('@/lib/supabase', () => ({
  loadProfile: (signal?: AbortSignal) => service.load(signal),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: typeof service.auth) => { service.auth = callback; return () => { service.auth = null; }; },
}));
import { useProfileForm } from './use-profile-form';
import { DEFAULT_PROFILE } from './types';
import { PROFILE_REFRESH_INTERVAL_MS } from '@/lib/use-profile-refresh';
import { advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, readUserScopedRaw, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { readProfileSyncEnvelope, resetProfileDirtyLedger } from '@/lib/profile-sync';
import { resetJournalLaneForTests } from '@/lib/profile-journal';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { encodeProfile } from '@/lib/profile-share';

const BASE: ProfileData = { ...DEFAULT_PROFILE, name: 'Alex', home_school: 'uiuc', institution: 'UIUC',
  college: 'Engineering', major: 'Computer Science', grade: 'Junior', research_interests: 'Original research' };
const t = (key: string) => key;
let remote: ProfileData | null;
let revision: number;
let uid: string;
let sequence = 0;
function deferred<T>() {
  let resolve!: (value: T) => void; let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function row(): LoadedProfile {
  return remote ? { source: 'cloud', profile: { ...structuredClone(remote) }, revision, token: captureOwnerToken() }
    : { source: 'cloud-absent', profile: null, revision: 0, token: captureOwnerToken() };
}
function publish(patch: Partial<ProfileData>) { remote = { ...remote!, ...patch }; revision += 1; }
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  if (!remote) return { status: 'missing', reason: 'absent' };
  if (intent.expectedRevision !== revision) return { status: 'conflict', profile: { ...structuredClone(remote) }, revision };
  remote = { ...remote, ...intent.patch }; revision += 1;
  return { status: 'saved', profile: { ...structuredClone(remote) }, revision };
}
const mirror = () => JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE) ?? 'null');
async function drain() {
  for (let pass = 0; pass < 4; pass += 1) {
    await act(async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); });
  }
}
async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); await drain();
}
async function start() {
  const hook = renderHook(() => useProfileForm(t));
  act(() => { service.auth?.({ user: { id: uid } }); }); await drain();
  expect(hook.result.current.hydrationState).toBe('ready');
  expect(hook.result.current.profile.major).toBe(BASE.major);
  return hook;
}
async function holdPeriodic() {
  const held = deferred<LoadedProfile>(); service.load.mockReturnValueOnce(held.promise);
  const before = service.load.mock.calls.length;
  await tick(PROFILE_REFRESH_INTERVAL_MS);
  expect(service.load).toHaveBeenCalledTimes(before + 1);
  return held;
}
beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.auth = null; service.params = new URLSearchParams();
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  uid = `home-foreground-${++sequence}`;
  advanceOwnerEpoch(null); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  expect(isOwnerTokenValid(captureOwnerToken(), uid)).toBe(true);
  remote = structuredClone(BASE); revision = 1;
  service.load.mockReset().mockImplementation(async () => row());
  service.commit.mockReset().mockImplementation(apply);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('Home foreground reads with real profile coordination', () => {
  it('accepts a remote update to a previously edited and successfully saved field without saving it back', async () => {
    const { result } = await start();
    act(() => { result.current.update('major', 'Mathematics'); }); await tick(1500);
    expect(service.commit).toHaveBeenCalledOnce(); expect(remote?.major).toBe('Mathematics');
    expect(result.current.saveStatus).toBe('saved');
    publish({ major: 'Remote Physics' }); await tick(PROFILE_REFRESH_INTERVAL_MS);
    expect(service.load).toHaveBeenCalledTimes(2);
    expect(result.current.profile.major).toBe('Remote Physics');
    expect(result.current.viewSnapshot?.baseProfile?.major).toBe('Remote Physics');
    expect(result.current.viewSnapshot?.revision).toBe(3);
    await tick(2000); expect(service.commit).toHaveBeenCalledOnce();
    expect(readProfileSyncEnvelope()?.pending).toBeNull();
  });

  it.each(['new-value', 'edited-back'] as const)('preserves a field %s during a held read and accepts untouched remote fields', async (mode) => {
    const { result } = await start(); const held = await holdPeriodic();
    expect(result.current.hydrationState).toBe('ready');
    act(() => { result.current.update('major', 'Local temporary'); });
    if (mode === 'edited-back') act(() => { result.current.update('major', BASE.major); });
    const desired = mode === 'edited-back' ? BASE.major : 'Local temporary';
    publish({ major: 'Remote Physics', grade: 'Senior' }); held.resolve(row()); await drain();
    expect(result.current.profile).toMatchObject({ major: desired, grade: 'Senior' });
    expect(result.current.viewSnapshot?.renderedProfile.major).toBe(desired);
    expect(result.current.viewSnapshot?.baseProfile?.major).toBe('Remote Physics');
    expect(result.current.viewSnapshot?.revision).toBe(2);
    expect(service.commit).not.toHaveBeenCalled();
  });

  it('keeps the latest typing burst that has not reached the journal when a read completes', async () => {
    const { result } = await start(); const held = await holdPeriodic();
    act(() => { result.current.update('research_interests', 'First recorded keystroke'); });
    act(() => { result.current.update('research_interests', 'Latest unflushed typing'); });
    publish({ grade: 'Senior' }); held.resolve(row()); await drain();
    expect(result.current.profile.research_interests).toBe('Latest unflushed typing');
    expect(result.current.viewSnapshot?.renderedProfile.research_interests).toBe('Latest unflushed typing');
    expect(result.current.profile.grade).toBe('Senior'); expect(service.commit).not.toHaveBeenCalled();
    await tick(1500);
    // The old authored baseline legitimately conflicts once; only the rebase
    // succeeds. Both attempts must carry the latest typing, never the first burst.
    expect(service.commit.mock.calls.map(([intent]) => intent.expectedRevision)).toEqual([1, 2]);
    expect(service.commit.mock.calls.every(([intent]) => intent.patch.research_interests === 'Latest unflushed typing')).toBe(true);
    expect(remote?.research_interests).toBe('Latest unflushed typing'); expect(revision).toBe(3);
  });

  it('keeps the local resume source bundle together when coursework changes during a read of replacement source text', async () => {
    remote = { ...BASE, resume_text: 'Original exact resume source', coursework: ['Original course'],
      experience_entries: [], resume_master: null };
    const { result } = await start(); const held = await holdPeriodic();
    act(() => { result.current.update('coursework', ['My course edit']); });
    publish({ resume_text: 'Replacement cloud resume source', coursework: ['Cloud replacement course'] });
    held.resolve(row()); await drain();
    expect(result.current.profile).toMatchObject({ resume_text: 'Original exact resume source',
      coursework: ['My course edit'], experience_entries: [], resume_master: null });
    expect(result.current.viewSnapshot?.renderedProfile).toMatchObject({ resume_text: 'Original exact resume source', coursework: ['My course edit'] });
    expect(result.current.viewSnapshot?.baseProfile).toMatchObject({ resume_text: 'Replacement cloud resume source', coursework: ['Cloud replacement course'] });
    expect(result.current.viewSnapshot?.revision).toBe(2); expect(service.commit).not.toHaveBeenCalled();
  });

  it('starts the next interval after completion; unchanged reads preserve save status and never autosave', async () => {
    const { result } = await start(); const status = result.current.saveStatus;
    const profile = structuredClone(result.current.profile);
    const held = await holdPeriodic();
    expect(result.current.profileRefreshStatus).toBe('checking');
    expect(result.current.saveStatus).toBe(status); expect(result.current.hydrationState).toBe('ready');
    await tick(10_000); expect(service.load).toHaveBeenCalledTimes(2);
    held.resolve(row()); await drain();
    expect(result.current.profileRefreshStatus).toBe('ready');
    expect(result.current.profile).toEqual(profile); expect(result.current.saveStatus).toBe(status);
    await tick(PROFILE_REFRESH_INTERVAL_MS - 1); expect(service.load).toHaveBeenCalledTimes(2);
    await tick(1); expect(service.load).toHaveBeenCalledTimes(3);
    expect(service.commit).not.toHaveBeenCalled();
  });

  it('does not replay an already dispatched local save while reading its old server revision', async () => {
    const { result } = await start(); const saving = deferred<ProfilePatchOutcome>();
    service.commit.mockReturnValueOnce(saving.promise);
    act(() => { result.current.update('major', 'Pending local major'); }); await tick(1500);
    expect(service.commit).toHaveBeenCalledOnce(); const intent = service.commit.mock.calls[0][0];
    await tick(PROFILE_REFRESH_INTERVAL_MS);
    expect(service.load).toHaveBeenCalledTimes(2); expect(service.commit).toHaveBeenCalledOnce();
    expect(result.current.profile.major).toBe('Pending local major'); expect(result.current.saveStatus).toBe('saving');
    saving.resolve(await apply(intent)); await drain();
    expect(result.current.saveStatus).toBe('saved'); expect(remote?.major).toBe('Pending local major');
    await tick(2000); expect(service.commit).toHaveBeenCalledOnce();
  });

  it('never rolls back an accepted save when an older periodic read settles later', async () => {
    const { result } = await start(); const saving = deferred<ProfilePatchOutcome>();
    service.commit.mockReturnValueOnce(saving.promise);
    act(() => { result.current.update('major', 'Saved during refresh'); }); await tick(1500);
    const intent = service.commit.mock.calls[0][0]; const old = row();
    const held = await holdPeriodic();
    saving.resolve(await apply(intent)); await drain();
    expect(result.current.viewSnapshot?.revision).toBe(2);
    held.resolve(old); await drain();
    expect(result.current.profile.major).toBe('Saved during refresh');
    expect(result.current.viewSnapshot?.revision).toBe(2);
    expect(result.current.viewSnapshot?.baseProfile?.major).toBe('Saved during refresh');
    expect(readProfileSyncEnvelope()?.confirmed?.revision).toBe(2);
    await tick(PROFILE_REFRESH_INTERVAL_MS);
    expect(service.load.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(service.commit).toHaveBeenCalledOnce();
  });

  it('rejects an old absent read after the first genuine create has been acknowledged', async () => {
    remote = null; revision = 0;
    const saving = deferred<ProfilePatchOutcome>(); service.commit.mockReturnValueOnce(saving.promise);
    const { result } = renderHook(() => useProfileForm(t));
    act(() => { service.auth?.({ user: { id: uid } }); }); await drain();
    expect(result.current.hydrationState).toBe('ready');
    act(() => { result.current.setProfile({ ...BASE, major: 'First saved major' }); }); await tick(1500);
    expect(service.commit).toHaveBeenCalledOnce();
    const intent = service.commit.mock.calls[0][0]; expect(intent.expectedRevision).toBe(0);
    const absent = row(); const held = await holdPeriodic();
    remote = { ...BASE, ...intent.patch }; revision = 1;
    saving.resolve({ status: 'saved', profile: { ...structuredClone(remote) }, revision }); await drain();
    expect(result.current.viewSnapshot?.revision).toBe(1);
    held.resolve(absent); await drain();
    expect(result.current.profile.major).toBe('First saved major');
    expect(result.current.viewSnapshot?.revision).toBe(1);
    expect(result.current.viewSnapshot?.baseProfile?.major).toBe('First saved major');
    // The real coordinator can already reconcile this stale absence to the
    // acknowledged row. Correctness does not require an unnecessary extra GET.
    expect(result.current.profileRefreshStatus).toBe('ready');
    expect(service.commit).toHaveBeenCalledOnce(); expect(readProfileSyncEnvelope()?.tombstone).toBeNull();
  });

  it('keeps a first confirmed-absent account ready instead of treating it as a deleted existing profile', async () => {
    remote = null; revision = 0;
    const { result } = renderHook(() => useProfileForm(t));
    act(() => { service.auth?.({ user: { id: uid } }); }); await drain();
    expect(result.current.hydrationState).toBe('ready');
    expect(result.current.profileRefreshStatus).toBe('ready');
    await tick(PROFILE_REFRESH_INTERVAL_MS);
    expect(result.current.profileRefreshStatus).toBe('ready');
    expect(service.commit).not.toHaveBeenCalled();
    expect(readProfileSyncEnvelope()?.tombstone).toBeNull();
  });

  it('rebuilds an existing conflict against the newly displayed remote revision without choosing either side', async () => {
    const { result } = await start();
    act(() => { result.current.update('major', 'My disputed major'); });
    publish({ major: 'Remote v2' }); await tick(1500);
    expect(result.current.saveStatus).toBe('conflict');
    expect(result.current.conflicts).toEqual(expect.arrayContaining([expect.objectContaining({ key: 'major', remote: 'Remote v2', remoteRevision: 2 })]));
    const sends = service.commit.mock.calls.length;
    publish({ major: 'Remote v3', grade: 'Senior' }); await tick(PROFILE_REFRESH_INTERVAL_MS);
    expect(result.current.profile.major).toBe('My disputed major'); expect(result.current.profile.grade).toBe('Senior');
    expect(result.current.viewSnapshot?.revision).toBe(3); expect(result.current.viewSnapshot?.baseProfile?.major).toBe('Remote v3');
    expect(result.current.saveStatus).toBe('conflict');
    expect(result.current.conflicts).toEqual(expect.arrayContaining([expect.objectContaining({ key: 'major', remote: 'Remote v3', remoteRevision: 3 })]));
    expect(service.commit).toHaveBeenCalledTimes(sends); expect(remote?.major).toBe('Remote v3');
  });

  it('retains the form on read failure and retries the read without sending edits during unknown freshness', async () => {
    const { result } = await start(); const held = await holdPeriodic();
    act(() => { result.current.update('research_interests', 'Kept during network failure'); });
    held.reject(new Error('Controlled failed profile read')); await drain();
    expect(result.current.profileRefreshStatus).toBe('failed');
    expect(result.current.hydrationState).toBe('ready');
    expect(result.current.profile.research_interests).toBe('Kept during network failure');
    expect(result.current.viewSnapshot?.baseProfile).toEqual(BASE);
    await tick(2000); expect(service.commit).not.toHaveBeenCalled();
    act(() => { result.current.handleSubmit(); result.current.retryCloudSave(); }); await drain();
    expect(service.commit).not.toHaveBeenCalled();
    act(() => { result.current.retryProfileRefresh(); }); await drain();
    expect(result.current.profileRefreshStatus).toBe('ready'); expect(service.load).toHaveBeenCalledTimes(3);
    expect(result.current.profile.research_interests).toBe('Kept during network failure');
    expect(readProfileSyncEnvelope()?.tombstone).toBeNull();
  });

  it('preserves the form when the whole profile was deleted and never recreates it on timers or Retry', async () => {
    const { result } = await start(); const held = await holdPeriodic();
    act(() => { result.current.update('research_interests', 'Unsent after cloud deletion'); });
    remote = null; revision = 0; held.resolve(row()); await drain();
    expect(result.current.profileRefreshStatus).toBe('deleted');
    expect(result.current.profile).toMatchObject({ name: 'Alex', research_interests: 'Unsent after cloud deletion' });
    // Keep the displayed baseline so nested editors are not unmounted; it is
    // no longer permission to send a profile write. Exercise those entry points.
    expect(result.current.viewSnapshot?.renderedProfile.research_interests).toBe('Unsent after cloud deletion');
    expect(readProfileSyncEnvelope()?.tombstone?.reason).toBe('deleted');
    act(() => { result.current.handleSubmit(); result.current.retryCloudSave(); }); await drain();
    expect(service.commit).not.toHaveBeenCalled();
    await tick(PROFILE_REFRESH_INTERVAL_MS + 2000);
    act(() => { result.current.retryProfileRefresh(); }); await drain(); await tick(2000);
    expect(service.commit).not.toHaveBeenCalled(); expect(remote).toBeNull();
    expect(result.current.profile.research_interests).toBe('Unsent after cloud deletion');
  });

  it.each([
    { mode: 'direct', edited: false }, { mode: 'after-read-failure', edited: false },
    { mode: 'direct', edited: true }, { mode: 'after-read-failure', edited: true },
  ])('accepts a genuinely recreated revision-one row $mode / local edit=$edited after confirmed deletion', async ({ mode, edited }) => {
    revision = 5;
    const { result } = await start(); const held = await holdPeriodic();
    const localText = edited ? 'Local input kept across deletion' : BASE.research_interests;
    if (edited) act(() => { result.current.update('research_interests', localText); });
    remote = null; revision = 0; held.resolve(row()); await drain();
    expect(result.current.profileRefreshStatus).toBe('deleted');
    expect(result.current.profile.research_interests).toBe(localText);
    expect(readProfileSyncEnvelope()?.tombstone?.reason).toBe('deleted');
    if (mode === 'after-read-failure') {
      service.load.mockRejectedValueOnce(new Error('Controlled read after deletion failed'));
      act(() => { result.current.retryProfileRefresh(); }); await drain();
      expect(result.current.profileRefreshStatus).toBe('failed');
      expect(result.current.profile.research_interests).toBe(localText);
    }
    // Another device explicitly creates a new row. Its counter restarts at one;
    // this read is newer evidence than the deleted row's old revision five.
    remote = { ...BASE, name: 'Recreated owner profile', grade: 'Senior' }; revision = 1;
    act(() => { result.current.retryProfileRefresh(); }); await drain(); await tick(0);
    expect(result.current.profileRefreshStatus).toBe('ready');
    expect(result.current.profile).toMatchObject({ name: 'Recreated owner profile', grade: 'Senior', research_interests: localText });
    expect(result.current.viewSnapshot?.revision).toBe(1);
    expect(result.current.viewSnapshot?.baseProfile).toEqual(remote);
    expect(result.current.viewSnapshot?.renderedProfile.research_interests).toBe(localText);
    expect(readProfileSyncEnvelope()?.confirmed?.revision).toBe(1);
    expect(readProfileSyncEnvelope()?.tombstone).toBeNull();
    expect(service.commit).not.toHaveBeenCalled();
    await tick(2000);
    if (edited) {
      // Only genuine unsaved input resumes. Its old authored revision conflicts
      // once, then the coordinator rebases that field onto the recreated row.
      expect(service.commit.mock.calls.map(([intent]) => intent.expectedRevision)).toEqual([5, 1]);
      expect(service.commit.mock.calls.every(([intent]) => Object.keys(intent.patch).length === 1
        && intent.patch.research_interests === localText)).toBe(true);
      expect(revision).toBe(2);
      expect(remote).toMatchObject({ name: 'Recreated owner profile', grade: 'Senior', research_interests: localText });
    } else {
      expect(service.commit).not.toHaveBeenCalled(); expect(revision).toBe(1);
    }
  });

  it('never reads or writes the owner profile while displaying and editing a shared draft', async () => {
    service.params = new URLSearchParams({ share: encodeProfile({ ...BASE, major: 'Shared major' }) });
    const { result } = renderHook(() => useProfileForm(t));
    act(() => { service.auth?.({ user: { id: uid } }); }); await drain();
    expect(result.current.profile.major).toBe('Shared major');
    act(() => { result.current.update('research_interests', 'Private shared-draft edit'); });
    await tick(PROFILE_REFRESH_INTERVAL_MS * 2);
    act(() => { result.current.retryProfileRefresh(); }); await drain();
    expect(service.load).not.toHaveBeenCalled(); expect(service.commit).not.toHaveBeenCalled();
    expect(result.current.profile.research_interests).toBe('Private shared-draft edit'); expect(mirror()).toBeNull();
  });

  it.each(['hidden', 'offline'] as const)('suspends background reads while %s and reads once when foreground online returns', async (mode) => {
    await start();
    if (mode === 'hidden') {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
      act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    } else {
      Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
      act(() => { window.dispatchEvent(new Event('offline')); });
    }
    await tick(PROFILE_REFRESH_INTERVAL_MS * 2); expect(service.load).toHaveBeenCalledOnce();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
    act(() => { if (mode === 'hidden') document.dispatchEvent(new Event('visibilitychange')); else window.dispatchEvent(new Event('online')); });
    await drain(); expect(service.load).toHaveBeenCalledTimes(2); expect(service.commit).not.toHaveBeenCalled();
  });

  it.each(['owner', 'generation', 'unmount'] as const)('rejects a held old-row receipt after %s retirement', async (mode) => {
    const { result, unmount } = await start(); const held = await holdPeriodic();
    const late: LoadedProfile = { ...row(), profile: { ...BASE, name: 'PRIVATE RETIRED ROW' }, revision: 99 };
    const before = captureOwnerToken();
    if (mode === 'unmount') unmount();
    else if (mode === 'owner') {
      await act(async () => { advanceOwnerEpoch('different-foreground-owner'); await syncLocalIdentityOwner('different-foreground-owner'); });
      remote = { ...BASE, name: 'Different owner row' }; revision = 1;
      act(() => { service.auth?.({ user: { id: 'different-foreground-owner' } }); }); await drain();
    } else {
      const marker = JSON.parse(localStorage.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER)!);
      localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, JSON.stringify({ ...marker, generation: marker.generation + 1 }));
      expect(isOwnerTokenValid(before, before.uid)).toBe(false);
    }
    held.resolve(late); await drain();
    expect(result.current.profile.name).not.toBe('PRIVATE RETIRED ROW');
    expect(mirror()?.name).not.toBe('PRIVATE RETIRED ROW');
    expect(readProfileSyncEnvelope()?.confirmed?.revision).not.toBe(99);
    if (mode === 'owner') {
      expect(result.current.profile.name).toBe('Different owner row');
      expect(result.current.profileRefreshStatus).toBe('ready');
      expect(result.current.viewSnapshot?.token).toEqual(captureOwnerToken());
    }
    expect(service.commit).not.toHaveBeenCalled();
  });
});
