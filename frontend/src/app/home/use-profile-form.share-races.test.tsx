import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import type { ProfileData } from '@/lib/types';

const service = vi.hoisted(() => ({
  auth: null as null | ((state: { user: { id: string } | null }) => void),
  load: vi.fn<(signal?: AbortSignal) => Promise<LoadedProfile>>(),
  commit: vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
  params: new URLSearchParams(), router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
  clipboard: vi.fn<(value: string) => Promise<void>>(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => service.router, useSearchParams: () => service.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
// Control transport and delivery of the already-established auth observation.
// Home, reconciliation, durable journal, owner capabilities and share codec are real.
vi.mock('@/lib/supabase', () => ({
  loadProfile: (signal?: AbortSignal) => service.load(signal),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: typeof service.auth) => { service.auth = callback; return () => { service.auth = null; }; },
}));
import { useProfileForm } from './use-profile-form';
import { DEFAULT_PROFILE } from './types';
import { advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, readUserScopedRaw, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { resetProfileDirtyLedger } from '@/lib/profile-sync';
import { resetJournalLaneForTests } from '@/lib/profile-journal';
import { decodeProfile } from '@/lib/profile-share';
import { STORAGE_KEYS } from '@/lib/storage-keys';

const t = (key: string) => key;
const FIELDS = { college: 'Grainger College of Engineering', major: 'Computer Science', grade: 'Junior',
  research_interests: 'MARKER_SHARED_E2E_ZZZ' } as const;
const BASE: ProfileData = { ...DEFAULT_PROFILE, name: 'Existing owner', college: 'Original college',
  major: 'Original major', grade: 'Freshman', research_interests: 'Original interests' };
let uid: string;
let sequence = 0;
let remote: ProfileData | null;
let revision: number;
let originalClipboard: PropertyDescriptor | undefined;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}
function row(): LoadedProfile {
  return remote ? { source: 'cloud', profile: { ...structuredClone(remote) }, revision, token: captureOwnerToken() }
    : { source: 'cloud-absent', profile: null, revision: 0, token: captureOwnerToken() };
}
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  if (intent.expectedRevision !== revision) return { status: 'conflict', profile: { ...remote! }, revision };
  remote = { ...(remote ?? {}), ...intent.patch } as ProfileData; revision += 1;
  return { status: 'saved', profile: { ...structuredClone(remote) }, revision };
}
async function drain() {
  for (let pass = 0; pass < 4; pass += 1) {
    await act(async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); });
  }
}
async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); await drain();
}
function fill(form: ReturnType<typeof useProfileForm>, interests: string = FIELDS.research_interests) {
  act(() => {
    form.update('college', FIELDS.college); form.update('major', FIELDS.major);
    form.update('grade', FIELDS.grade); form.update('research_interests', interests);
  });
}
async function copy(form: ReturnType<typeof useProfileForm>) {
  const before = service.clipboard.mock.calls.length;
  await act(async () => { await form.handleShare(); });
  expect(service.clipboard).toHaveBeenCalledTimes(before + 1);
  const encoded = new URL(service.clipboard.mock.calls.at(-1)![0]).searchParams.get('share');
  expect(encoded).not.toBeNull();
  return decodeProfile(encoded!);
}
async function knownOwner() {
  advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  expect(isOwnerTokenValid(captureOwnerToken(), uid)).toBe(true);
}
async function startReady() {
  await knownOwner(); remote = structuredClone(BASE); revision = 1;
  const hook = renderHook(() => useProfileForm(t));
  act(() => { service.auth?.({ user: { id: uid } }); }); await drain();
  expect(hook.result.current.hydrationState).toBe('ready');
  expect(hook.result.current.profile).toMatchObject(BASE);
  return hook;
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  resetProfileDirtyLedger(); resetJournalLaneForTests(); advanceOwnerEpoch(null);
  uid = `home-share-race-${++sequence}`; remote = null; revision = 0;
  service.auth = null; service.params = new URLSearchParams();
  service.load.mockReset().mockImplementation(async () => row());
  service.commit.mockReset().mockImplementation(apply);
  service.clipboard.mockReset().mockResolvedValue(undefined);
  originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: service.clipboard } });
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => {
  cleanup(); vi.clearAllTimers(); vi.useRealTimers();
  if (originalClipboard) Object.defineProperty(navigator, 'clipboard', originalClipboard);
  else delete (navigator as { clipboard?: unknown }).clipboard;
});

describe('Home first-visit and focus/read share schedules', () => {
  it('keeps four fields typed in the first-UID gap when the loading screen already held a null origin', async () => {
    const old = deferred<LoadedProfile>(); const fresh = deferred<LoadedProfile>();
    service.load.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const { result } = renderHook(() => useProfileForm(t));
    act(() => { service.auth?.({ user: null }); });
    expect(service.load).toHaveBeenCalledOnce();
    // Same order as the adapter: epoch first, owner establishment, then Home notification.
    // Input is deliberately inside the first gap, not after a seeded ready profile.
    act(() => { advanceOwnerEpoch(uid); });
    expect(isOwnerTokenValid(captureOwnerToken(), uid)).toBe(false);
    fill(result.current); expect(result.current.profile).toMatchObject(FIELDS);
    expect(service.commit).not.toHaveBeenCalled();
    await act(async () => { await syncLocalIdentityOwner(uid); service.auth?.({ user: { id: uid } }); });
    await drain(); expect(service.load).toHaveBeenCalledTimes(2);
    expect(service.load.mock.calls[0][0]?.aborted).toBe(true);
    fresh.resolve(row()); await drain();
    expect(result.current.profile).toMatchObject(FIELDS);
    expect(await copy(result.current)).toMatchObject(FIELDS);
    old.resolve(row()); await drain();
    expect(result.current.profile).toMatchObject(FIELDS);
    expect(service.commit).not.toHaveBeenCalled();
  });

  it('keeps first-visit four-field input when the first fallback captures the UID before its auth notification', async () => {
    const old = deferred<LoadedProfile>(); const fresh = deferred<LoadedProfile>();
    service.load.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const { result } = renderHook(() => useProfileForm(t));
    // No Home auth callback has arrived. Another legitimate SDK subscriber
    // has advanced the first owner, but the local realm is not ready yet.
    act(() => { advanceOwnerEpoch(uid); });
    await tick(0); expect(service.load).toHaveBeenCalledOnce();
    expect(result.current.viewSnapshot).toBeNull();
    expect(isOwnerTokenValid(captureOwnerToken(), uid)).toBe(false);
    fill(result.current); expect(result.current.profile).toMatchObject(FIELDS);
    expect(service.commit).not.toHaveBeenCalled();
    await act(async () => { await syncLocalIdentityOwner(uid); service.auth?.({ user: { id: uid } }); });
    await drain(); expect(service.load).toHaveBeenCalledTimes(2);
    expect.soft(result.current.profile, 'the first auth notification must not reset this first-owner input').toMatchObject(FIELDS);
    fresh.resolve(row()); await drain();
    expect.soft(result.current.profile, 'the resolved empty cloud row must retain the input').toMatchObject(FIELDS);
    expect.soft(await copy(result.current), 'the actual copied URL must carry all four fields').toMatchObject(FIELDS);
    old.resolve(row()); await drain();
    expect.soft(result.current.profile, 'the retired read must not change the result').toMatchObject(FIELDS);
    expect(service.commit).not.toHaveBeenCalled();
  });

  it.each(['different-uid', 'same-uid-new-epoch'] as const)('does not carry an unaccepted first-owner buffer through %s', async (transition) => {
    const old = deferred<LoadedProfile>(); const fresh = deferred<LoadedProfile>();
    service.load.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const { result } = renderHook(() => useProfileForm(t));
    act(() => { advanceOwnerEpoch(uid); }); await tick(0);
    const oldToken = captureOwnerToken();
    fill(result.current); expect(result.current.profile).toMatchObject(FIELDS);
    const nextUid = transition === 'different-uid' ? `${uid}-next` : uid;
    await act(async () => {
      if (transition === 'same-uid-new-epoch') advanceOwnerEpoch(null);
      advanceOwnerEpoch(nextUid); await syncLocalIdentityOwner(nextUid);
      service.auth?.({ user: { id: nextUid } });
    });
    await drain(); expect(captureOwnerToken().epoch).not.toBe(oldToken.epoch);
    fresh.resolve(row()); await drain();
    expect(result.current.profile.research_interests).toBe('');
    expect(await copy(result.current)).toMatchObject({ college: '', major: '', grade: '', research_interests: '' });
    old.resolve({ source: 'cloud-absent', profile: null, revision: 0, token: oldToken }); await drain();
    expect(result.current.profile.research_interests).toBe('');
    expect(service.commit).not.toHaveBeenCalled();
  });

  it('does not transfer a buffer from an already-established generation to a new same-UID namespace', async () => {
    await knownOwner();
    const old = deferred<LoadedProfile>(); const fresh = deferred<LoadedProfile>();
    service.load.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const { result } = renderHook(() => useProfileForm(t)); await tick(0);
    const oldToken = captureOwnerToken(); expect(oldToken.generation).toBeGreaterThanOrEqual(0);
    fill(result.current); expect(result.current.profile).toMatchObject(FIELDS);
    await act(async () => {
      // A different tab's replacement realm, deliberately without an epoch change here.
      localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, JSON.stringify({
        v: 2, uid, generation: oldToken.generation + 1, phase: 'switching',
      }));
      await syncLocalIdentityOwner(uid); service.auth?.({ user: { id: uid } });
    });
    await drain(); const current = captureOwnerToken();
    expect(current.epoch).toBe(oldToken.epoch); expect(current.generation).not.toBe(oldToken.generation);
    fresh.resolve(row()); await drain();
    expect(await copy(result.current)).toMatchObject({ college: '', major: '', grade: '', research_interests: '' });
    old.resolve({ source: 'cloud-absent', profile: null, revision: 0, token: oldToken }); await drain();
    expect(result.current.profile.research_interests).toBe(''); expect(service.commit).not.toHaveBeenCalled();
  });

  it('does not carry a fallback-accepted account row when the first Home auth notification names another owner', async () => {
    await knownOwner(); remote = structuredClone(BASE); revision = 1;
    const { result } = renderHook(() => useProfileForm(t)); await tick(0);
    expect(result.current.hydrationState).toBe('ready');
    expect(result.current.viewSnapshot?.baseProfile?.name).toBe(BASE.name);
    fill(result.current); const oldShare = result.current.handleShare;
    const nextUid = `${uid}-next`;
    await act(async () => { advanceOwnerEpoch(nextUid); await syncLocalIdentityOwner(nextUid); });
    await act(async () => { await oldShare(); }); expect(service.clipboard).not.toHaveBeenCalled();
    remote = null; revision = 0;
    act(() => { service.auth?.({ user: { id: nextUid } }); }); await drain();
    expect(await copy(result.current)).toMatchObject({ college: '', major: '', grade: '', research_interests: '' });
    expect(service.commit).not.toHaveBeenCalled();
  });

  it('copies the latest four fields after a held focus read, before the typing burst or CAS acknowledgement', async () => {
    const { result } = await startReady();
    fill(result.current, 'First research text');
    const heldRead = deferred<LoadedProfile>(); service.load.mockReturnValueOnce(heldRead.promise);
    const heldSave = deferred<ProfilePatchOutcome>();
    service.commit.mockImplementationOnce(() => heldSave.promise);
    act(() => { window.dispatchEvent(new Event('focus')); }); await drain();
    expect(service.load).toHaveBeenCalledTimes(2);
    expect(result.current.profileRefreshStatus).toBe('checking');
    // No fake time has reached the 400 ms text-burst flush or the 1.5 s autosave.
    act(() => { result.current.update('research_interests', FIELDS.research_interests); });
    heldRead.resolve(row()); await drain();
    expect(result.current.profileRefreshStatus).toBe('ready');
    expect(result.current.profile).toMatchObject(FIELDS);
    expect(service.commit).not.toHaveBeenCalled();
    expect(await copy(result.current)).toMatchObject(FIELDS);
    await tick(1500); expect(service.commit).toHaveBeenCalledOnce();
    const intent = service.commit.mock.calls[0][0];
    expect(intent.patch).toMatchObject(FIELDS);
    expect(await copy(result.current)).toMatchObject(FIELDS);
    heldSave.resolve(await apply(intent)); await drain();
    expect(result.current.profile).toMatchObject(FIELDS);
    expect(await copy(result.current)).toMatchObject(FIELDS);
    expect(service.commit).toHaveBeenCalledOnce();
  });

  it('never copies old input across a genuine account transition, including a retained old share callback', async () => {
    const { result } = await startReady(); fill(result.current);
    expect(await copy(result.current)).toMatchObject(FIELDS);
    const oldShare = result.current.handleShare;
    const copies = service.clipboard.mock.calls.length;
    const nextUid = `${uid}-next`; const held = deferred<LoadedProfile>();
    service.load.mockReturnValueOnce(held.promise);
    await act(async () => { advanceOwnerEpoch(nextUid); await syncLocalIdentityOwner(nextUid); });
    // The browser owner has already changed while Home still renders its old view.
    await act(async () => { await oldShare(); });
    expect(service.clipboard).toHaveBeenCalledTimes(copies);
    act(() => { service.auth?.({ user: { id: nextUid } }); }); await drain();
    expect(result.current.profile.research_interests).not.toBe(FIELDS.research_interests);
    remote = { ...BASE, name: 'Second owner', research_interests: 'Second owner interests' }; revision = 1;
    held.resolve(row()); await drain();
    const copied = await copy(result.current);
    expect(copied?.research_interests).toBe('Second owner interests');
    expect(copied?.research_interests).not.toBe(FIELDS.research_interests);
    expect(JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE) ?? 'null')?.research_interests).toBe('Second owner interests');
    expect(service.commit).not.toHaveBeenCalled();
  });
});
