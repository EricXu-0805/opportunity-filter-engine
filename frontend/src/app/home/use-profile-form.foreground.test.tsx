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
import { HOME_FORM_WRITER, hydrateProfile, readProfileSyncEnvelope, resetProfileDirtyLedger, stageProfilePatch, type ProfileConflict } from '@/lib/profile-sync';
import { readOutstandingOps, resetJournalLaneForTests, startDocumentForTests } from '@/lib/profile-journal';
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

  it('keeps a course edit made during a read of replacement source text, with its names, and takes the new résumé', async () => {
    remote = { ...BASE, resume_text: 'Original exact resume source', coursework: ['Original course'],
      experience_entries: [], resume_master: null };
    const { result } = await start(); const held = await holdPeriodic();
    const mine = [{ name: 'My course edit', status: 'completed' as const, source: 'manual' as const }];
    act(() => { result.current.update('courses', mine); });
    publish({ resume_text: 'Replacement cloud resume source', coursework: ['Cloud replacement course'] });
    held.resolve(row()); await drain();
    // Courses are not part of the résumé (checklist M13): the course edit
    // keeps both course keys, and the résumé read is taken whole.
    expect(result.current.profile).toMatchObject({ resume_text: 'Replacement cloud resume source',
      courses: mine, coursework: ['My course edit'], experience_entries: [], resume_master: null });
    expect(result.current.viewSnapshot?.renderedProfile).toMatchObject({ resume_text: 'Replacement cloud resume source', courses: mine, coursework: ['My course edit'] });
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

/** Another tab's edit, in the journal as that tab writes it: its own lineage,
 *  made against the row at revision 1, written after everything on disk.
 *  Without a clock it is what a build from before journal clocks wrote. */
function otherTabEdit(key: keyof ProfileData, value: unknown, lineage = 'tab-b', clocked = true) {
  const ops = readOutstandingOps();
  const clock = Math.max(0, ...(ops.ok ? ops.value.map((o) => o.clock ?? 0) : [])) + 1;
  const opId = crypto.randomUUID();
  localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_${opId}`, JSON.stringify({
    opId, originId: lineage, lineage,
    fields: [{ key, base: { present: true, value: BASE[key] }, desired: { present: true, value } }],
    baseRevision: 1, writer: HOME_FORM_WRITER, mode: 'set', seq: 1, ...(clocked ? { clock } : {}),
  }));
}
/** The other tab types `value` and saves it after a phone has saved another
 *  value: its save comes back a conflict, and the question is open there. */
async function otherTabSavesIntoAConflict(value: string, lineage = 'tab-b', clocked = true) {
  otherTabEdit('research_interests', value, lineage, clocked);
  publish({ research_interests: 'Saved on the phone' });
  expect(await stageProfilePatch({ ...BASE, research_interests: value }, ['research_interests'],
    captureOwnerToken(), { allowCreate: true }))
    .toMatchObject({ status: 'conflict', conflictKeys: ['research_interests'] });
}
const sentSince = (from: number) => service.commit.mock.calls.slice(from).map(([i]) => [i.expectedRevision, i.patch]);
/** The other tab's "Keep what I typed" for `question`, as its receipt is written. */
function otherTabKeeps(question: ProfileConflict, value: unknown) {
  const ops = readOutstandingOps();
  const clock = Math.max(0, ...(ops.ok ? ops.value.map((o) => o.clock ?? 0) : [])) + 1;
  const opId = crypto.randomUUID();
  localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_${opId}`, JSON.stringify({
    opId, originId: 'tab-b', lineage: 'tab-b',
    fields: [{ key: question.key, base: { present: true, value: question.remote }, desired: { present: true, value } }],
    baseRevision: question.remoteRevision, writer: 'default', mode: 'resolve',
    resolves: question.candidates.flatMap((c) => c.opIds), decisions: { [question.key]: 'local' }, seq: 2, clock,
  }));
}

// Checklist M102 (review M80 r5 probes X and T3b; review M102a S1, L1, U1;
// review M102b H3). Every tab of an account shares the outbox and the journal.
describe('Home in a tab that typed nothing, beside a tab whose edit is in dispute', () => {
  it('asks too, shows the value the other tab typed, and keeps that value, never its own old one', async () => {
    const { result } = await start();
    await otherTabSavesIntoAConflict('Typed in the other tab');
    act(() => { window.dispatchEvent(new Event('focus')); }); await drain();
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);
    expect(result.current.saveStatus).toBe('conflict');
    expect(result.current.profile.research_interests, 'the shared working copy, not its old drawing')
      .toBe('Typed in the other tab');

    const sends = service.commit.mock.calls.length;
    act(() => { result.current.keepMyChanges(); }); await tick(2000);
    expect(sentSince(sends)).toEqual([[2, { research_interests: 'Typed in the other tab' }]]);
    expect(remote?.research_interests).toBe('Typed in the other tab');
    expect(result.current.conflicts).toEqual([]);
  });

  it('asks after the tab that typed is gone, and Generate does not go ahead while it is open', async () => {
    const { result } = await start();
    await otherTabSavesIntoAConflict('Typed in the other tab');
    await tick(PROFILE_REFRESH_INTERVAL_MS);
    act(() => { window.dispatchEvent(new Event('focus')); }); await drain();
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);

    service.router.push.mockClear();
    await act(async () => { await result.current.handleSubmit(); }); await drain();
    expect(service.router.push).not.toHaveBeenCalled();
    expect(result.current.saveStatus).toBe('conflict');
    expect(remote?.research_interests).toBe('Saved on the phone');
  });

  it('opened after two other tabs typed different values, asks, keeps neither, says why, and writes nothing over a newer saved value', async () => {
    otherTabEdit('research_interests', 'Typed in tab B', 'tab-b');
    otherTabEdit('research_interests', 'Typed in tab C', 'tab-c');
    const { result } = await start();
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);
    publish({ research_interests: 'Saved on the phone' });
    act(() => { window.dispatchEvent(new Event('focus')); }); await drain();
    expect(result.current.profile.research_interests, 'the saved row, not the one drawn at load').toBe('Saved on the phone');

    const sends = service.commit.mock.calls.length;
    act(() => { result.current.keepMyChanges(); }); await tick(2000);
    expect(sentSince(sends)).toEqual([]);
    expect(remote?.research_interests).toBe('Saved on the phone');
    expect(result.current.saveStatus).toBe('conflict-several-typed');
    expect(result.current.conflicts.map((c) => c.key), 'still open, to answer where it was typed')
      .toEqual(['research_interests']);
  });

  it('keeps what an earlier build\'s tab typed, never this tab\'s old value', async () => {
    const { result } = await start();
    await otherTabSavesIntoAConflict('Typed in an earlier build\'s tab', 'tab-old', false);
    act(() => { window.dispatchEvent(new Event('focus')); }); await drain();
    expect(result.current.profile.research_interests).toBe('Typed in an earlier build\'s tab');
    const sends = service.commit.mock.calls.length;
    act(() => { result.current.keepMyChanges(); }); await tick(2000);
    expect(sentSince(sends)).toEqual([[2, { research_interests: 'Typed in an earlier build\'s tab' }]]);
    expect(remote?.research_interests).toBe('Typed in an earlier build\'s tab');
  });

  it('shows what the other tab kept when its answer met the phone again, not the value it drew before', async () => {
    // Review M102a Z1: the question that is left has no operation behind it.
    const { result } = await start();
    await otherTabSavesIntoAConflict('Typed in the other tab');
    const first = readProfileSyncEnvelope()?.pending;
    expect(first?.lockedKeys).toEqual(['research_interests']);
    const asked = (await hydrateProfile()).conflicts;
    otherTabKeeps(asked[0], 'Typed in the other tab');
    publish({ research_interests: 'Saved on the phone again' });
    expect((await stageProfilePatch({ ...(remote as ProfileData), research_interests: 'Typed in the other tab' },
      ['research_interests'], captureOwnerToken())).status).toBe('conflict');
    act(() => { window.dispatchEvent(new Event('focus')); }); await drain();
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);
    expect(result.current.profile.research_interests, 'what the other tab kept, not this tab\'s old drawing')
      .toBe('Typed in the other tab');
    const sends = service.commit.mock.calls.length;
    act(() => { result.current.keepMyChanges(); }); await tick(2000);
    expect(sentSince(sends).map(([, patch]) => patch), 'never this tab\'s old value')
      .not.toContainEqual({ research_interests: BASE.research_interests });
    expect(remote?.research_interests).not.toBe(BASE.research_interests);
  });

  it('opened again in the same page, asks it too and shows the value the other tab typed', async () => {
    const first = await start();
    await otherTabSavesIntoAConflict('Typed in the other tab');
    first.unmount();
    const { result } = await start();
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);
    expect(result.current.saveStatus).toBe('conflict');
    expect(result.current.profile.research_interests).toBe('Typed in the other tab');
  });

  it('still asks, as before, about an edit that was already waiting when it loaded', async () => {
    // A tab that has since closed (or crashed before answering) leaves its
    // question to the next page the person opens.
    await hydrateProfile();
    await otherTabSavesIntoAConflict('Typed in a tab that is gone');
    startDocumentForTests('other'); resetProfileDirtyLedger();
    const { result } = await start();
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);
    expect(result.current.saveStatus).toBe('conflict');
    expect(result.current.profile.research_interests).toBe('Typed in a tab that is gone');
    act(() => { result.current.keepMyChanges(); }); await drain();
    expect(remote?.research_interests).toBe('Typed in a tab that is gone');
    expect(result.current.conflicts).toEqual([]);
  });

  it('sends an edit of its own but says conflict, keeps Retry, and does not let Generate go ahead while the question is open', async () => {
    const { result } = await start();
    await otherTabSavesIntoAConflict('Typed in the other tab');
    act(() => { result.current.update('grade', 'Senior'); }); await tick(2000);
    // The save redraws the other tab's interests here, which arms one more
    // save (refused by the server, as on 5181e8e8); its answer is in by now.
    await tick(2000);
    expect(remote).toMatchObject({ grade: 'Senior', research_interests: 'Saved on the phone' });
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);
    expect(result.current.saveStatus).toBe('conflict');
    expect(result.current.canRetrySync).toBe(true);

    service.router.push.mockClear();
    await act(async () => { await result.current.handleSubmit(); }); await drain();
    expect(service.router.push).not.toHaveBeenCalled();
    expect(remote?.research_interests, 'nothing of this tab\'s is written over it').toBe('Saved on the phone');
  });

  it('does not call its own edit saved while a second conflict left it unsent: Retry stays and the next profile check sends it', async () => {
    // Review M102b H3: the row moves on an untouched field (one rebase), then
    // on the other tab's field, which spends the rebase.
    const { result } = await start();
    otherTabEdit('research_interests', 'Typed in the other tab');
    service.commit.mockImplementationOnce(async (intent) => { publish({ name: 'Name from the phone' }); return apply(intent); });
    service.commit.mockImplementationOnce(async (intent) => { publish({ research_interests: 'Phone interests' }); return apply(intent); });
    act(() => { result.current.update('grade', 'Senior'); }); await tick(1600);
    expect(remote?.grade, 'not sent yet').toBe('Junior');
    expect(result.current.saveStatus).not.toBe('saved');
    expect(result.current.canRetrySync).toBe(true);
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);
    await tick(PROFILE_REFRESH_INTERVAL_MS);
    expect(remote?.grade).toBe('Senior');
    expect(result.current.saveStatus).toBe('conflict');
  });

  it('answering its own question leaves the other tab\'s question on screen, and says conflict', async () => {
    const { result } = await start();
    act(() => { result.current.update('major', 'My major'); });
    publish({ major: 'Phone major' }); await tick(1600);
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['major']);
    otherTabEdit('research_interests', 'Typed in the other tab');
    publish({ research_interests: 'Saved on the phone' });
    const theirs = await stageProfilePatch({ ...BASE, research_interests: 'Typed in the other tab' },
      ['research_interests'], captureOwnerToken(), { allowCreate: true });
    expect(theirs.status === 'conflict' && theirs.conflictKeys).toContain('research_interests');
    act(() => { window.dispatchEvent(new Event('focus')); }); await drain();
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['major', 'research_interests']);

    act(() => { result.current.keepMyChanges(['major']); }); await tick(1600);
    expect(remote).toMatchObject({ major: 'My major', research_interests: 'Saved on the phone' });
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);
    expect(result.current.saveStatus).toBe('conflict');
  });

  it('sends its own edit left unsent by a reload beside two other tabs\' question, and still says conflict, not saved', async () => {
    const first = await start();
    service.commit.mockImplementationOnce(async () => ({ status: 'transport-error', message: 'Failed to fetch' }));
    act(() => { first.result.current.update('grade', 'Senior'); }); await tick(1600);
    expect(first.result.current.saveStatus).toBe('cloud-failed');
    otherTabEdit('research_interests', 'Typed in tab B', 'tab-b');
    otherTabEdit('research_interests', 'Typed in tab C', 'tab-c');
    first.unmount();
    startDocumentForTests('reload'); resetProfileDirtyLedger();

    const { result } = await start(); await tick(100);
    expect(remote?.grade, 'the load sends what it left unsent').toBe('Senior');
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);
    expect(result.current.saveStatus, 'the interests are still in question').toBe('conflict');
    service.router.push.mockClear();
    await act(async () => { await result.current.handleSubmit(); }); await drain();
    expect(service.router.push).not.toHaveBeenCalled();
  });
});

describe('Home answering inside a typing burst', () => {
  it('"Keep what I typed" keeps every keystroke typed so far', async () => {
    // Review M102b H1: the last keystrokes of a burst are on screen only
    // until the typing pauses.
    const { result } = await start();
    act(() => { result.current.update('research_interests', 'Mine'); });
    publish({ research_interests: 'Phone' });
    const held = deferred<ProfilePatchOutcome>();
    service.commit.mockImplementationOnce(() => held.promise);
    await tick(1500);
    act(() => { result.current.update('research_interests', 'Mine a'); });
    held.resolve({ status: 'conflict', profile: { ...structuredClone(remote!) }, revision });
    await drain();
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);
    act(() => { result.current.update('research_interests', 'Mine ab'); });
    act(() => { result.current.keepMyChanges(); }); await drain();
    expect(sentSince(0).at(-1)).toEqual([2, { research_interests: 'Mine ab' }]);
    expect(remote?.research_interests).toBe('Mine ab');
    expect(result.current.profile.research_interests).toBe('Mine ab');
    await tick(5000);
    expect(remote?.research_interests).toBe('Mine ab');
    expect(result.current.conflicts).toEqual([]);
  });
});

describe('Home edit chains settled by one save', () => {
  it('a college switch, a major pick and another college switch leave nothing that a reload sends over a newer profile', async () => {
    const first = await start();
    act(() => { first.result.current.update('college', 'LAS'); });
    act(() => { first.result.current.update('major', 'Physics'); });
    act(() => { first.result.current.update('college', 'Business'); });
    await tick(1500);
    expect(service.commit).toHaveBeenCalledOnce();
    expect(remote).toMatchObject({ college: 'Business', major: '', additional_majors: [] });
    expect(first.result.current.saveStatus).toBe('saved');
    const left = readOutstandingOps();
    expect.soft(left.ok && left.value, 'the save settles every edit of the chain').toEqual([]);

    // A phone moves college and major on, and then this tab reloads.
    publish({ college: 'Media', major: 'Film' });
    first.unmount();
    startDocumentForTests('reload'); resetProfileDirtyLedger();
    service.commit.mockClear();
    const second = renderHook(() => useProfileForm(t));
    act(() => { service.auth?.({ user: { id: uid } }); }); await drain();
    expect(second.result.current.hydrationState).toBe('ready');
    await tick(1500);
    expect.soft(second.result.current.profile, 'the phone\'s profile is shown').toMatchObject({ college: 'Media', major: 'Film' });
    expect.soft(service.commit.mock.calls.map(([intent]) => intent.patch), 'nothing old is sent').toEqual([]);
    expect.soft(second.result.current.conflicts, 'nobody is asked about their own saved edits').toEqual([]);
    // Whatever was asked, the student answers "Keep what I typed" (a no-op
    // when nothing was asked); the phone's profile must survive it.
    act(() => { second.result.current.keepMyChanges(); }); await tick(1500);
    expect(remote).toMatchObject({ college: 'Media', major: 'Film' });
    expect(revision).toBe(3);
  });
});
