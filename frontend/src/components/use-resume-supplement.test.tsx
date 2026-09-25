import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import type { ProfileData } from '@/lib/types';
const load = vi.fn<() => Promise<LoadedProfile>>();
const commit = vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>();
vi.mock('@/lib/supabase', () => ({ loadProfile: () => load(), commitProfilePatch: (intent: ProfilePatchIntent) => commit(intent) }));
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { createEmptyResumeMaster } from '@/lib/resume-master';
import { readOutstandingOps, resetJournalLaneForTests } from '@/lib/profile-journal';
import * as sync from '@/lib/profile-sync';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { useResumeSupplement } from './use-resume-supplement';
import type { SupplementDraft } from '@/lib/resume-supplement';

function profile(): ProfileData {
  return { institution: 'UIUC', home_school: 'uiuc', college: 'Grainger', major: 'CS', grade: 'Junior',
    is_international: false, research_interests: 'robotics', skills: [], search_weight: 50,
    resume_text: 'Exact original 中文🧪\nNot the project lead.', coursework: ['CS 225'], experience_entries: [],
    resume_master: { ...createEmptyResumeMaster('master'), activities: [{ id: 'activity', kind: 'project', details: [],
      title: { id: 'project-title', revision: 1, status: 'confirmed', value: 'Robot project', source: { kind: 'manual' } } }] } };
}
const draft = (): SupplementDraft => ({ entryId: 'stable-entry', activityId: 'activity',
  answers: { task: 'Built 中文 tooling\nI did not lead the team.', method: '', personalRole: '', outcome: '', outcomeBasis: '' }, selected: ['task'] });
const cloud = (p: ProfileData | null, revision = 7): LoadedProfile => ({ source: p ? 'cloud' : 'cloud-absent',
  profile: p as unknown as Record<string, unknown>, revision: p ? revision : 0, token: captureOwnerToken() });
const saved = (p: ProfileData, revision = 8): ProfilePatchOutcome => ({ status: 'saved', revision, profile: p as unknown as Record<string, unknown> });
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; };
let base: ProfileData;
beforeEach(async () => {
  load.mockReset(); commit.mockReset(); resetJournalLaneForTests(); sync.resetProfileDirtyLedger();
  advanceOwnerEpoch(null); advanceOwnerEpoch('supplement-owner'); await syncLocalIdentityOwner('supplement-owner');
  base = profile(); load.mockImplementation(async () => cloud(base));
  commit.mockImplementation(async (intent) => saved({ ...base, ...intent.patch } as ProfileData));
});
async function ready() {
  const accepted = vi.fn();
  const hook = renderHook(() => useResumeSupplement({ targetKey: 'target-a', onAcceptedProfile: accepted }));
  await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
  return { ...hook, accepted };
}

describe('resume supplement controller with the real profile coordinator', () => {
  it('does not load before opening and accepts a complete cloud view without writing', async () => {
    const hook = renderHook(({ enabled }) => useResumeSupplement({ enabled, targetKey: 'target' }), { initialProps: { enabled: false } });
    expect(load).not.toHaveBeenCalled(); expect(commit).not.toHaveBeenCalled();
    hook.rerender({ enabled: true });
    await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
    expect(hook.result.current.view).toMatchObject({ revision: 7, baseProfile: base, renderedProfile: base });
    expect(Object.isFrozen(hook.result.current.view?.renderedProfile)).toBe(true);
  });
  it('commits one complete four-field bundle and accepts an exact confirmed entry and activity reference', async () => {
    const { result, accepted } = await ready(); const before = result.current.view!;
    await act(async () => { await result.current.confirm(draft(), result.current.baseline('activity')!); });
    expect(result.current.phase).toBe('saved'); expect(result.current.confirmedEntryId).toBe('stable-entry');
    expect(commit).toHaveBeenCalledTimes(1);
    const intent = commit.mock.calls[0][0];
    expect(Object.keys(intent.patch).sort()).toEqual([...sync.RESUME_BUNDLE].sort());
    expect(intent.patch.resume_text).toBe(base.resume_text); expect(intent.patch.coursework).toEqual(base.coursework);
    expect(intent.patch.experience_entries).toEqual([{ id: 'stable-entry', revision: 1, status: 'confirmed',
      source: { kind: 'manual' }, text: 'Task: Built 中文 tooling\nI did not lead the team.' }]);
    expect((intent.patch.resume_master as ProfileData['resume_master'])?.activities[0].details).toEqual([{ id: 'stable-entry', revision: 1 }]);
    expect(before.renderedProfile).toEqual(base); expect(accepted).toHaveBeenCalledTimes(1);
    expect(accepted.mock.calls[0][1]).toBe(before); expect(accepted.mock.calls[0][0].baseProfile.experience_entries).toHaveLength(1);
  });
  it('records synchronously and a double click never records a second entry or sends a second request', async () => {
    const { result } = await ready(); const wait = deferred<ProfilePatchOutcome>(); commit.mockReturnValue(wait.promise);
    const against = result.current.baseline('activity')!; let pending!: Promise<unknown>;
    act(() => { pending = result.current.confirm(draft(), against); });
    const journal = readOutstandingOps(); expect(journal.ok && journal.value.length).toBe(1);
    await act(async () => { expect((await result.current.confirm(draft(), against))?.durable).toBe(false); });
    await waitFor(() => expect(commit).toHaveBeenCalledTimes(1));
    const desired = { ...base, ...commit.mock.calls[0][0].patch } as ProfileData;
    await act(async () => { wait.resolve(saved(desired)); await pending; });
    expect(result.current.phase).toBe('saved'); expect(commit).toHaveBeenCalledTimes(1);
  });
  it('reports journal failure as not durable and makes zero network writes', async () => {
    const { result } = await ready(); const realSet = localStorage.setItem.bind(localStorage);
    vi.spyOn(localStorage, 'setItem').mockImplementation((key, value) => {
      if (key.includes(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_`)) throw new Error('quota'); realSet(key, value);
    });
    let outcome: sync.ProfileActionOutcome | null = null;
    await act(async () => { outcome = await result.current.confirm(draft(), result.current.baseline('activity')!); });
    expect(outcome).toEqual({ durable: false, reason: 'record-failed' }); expect(commit).not.toHaveBeenCalled();
    expect(result.current.phase).toBe('save-error'); expect(result.current.operationLocked).toBe(false);
  });
  it('keeps a recorded offline intent and retry flushes the same journal operation only once', async () => {
    const { result } = await ready(); commit.mockResolvedValueOnce({ status: 'transport-error', message: 'offline' });
    await act(async () => { await result.current.confirm(draft(), result.current.baseline('activity')!); });
    expect(result.current.phase).toBe('recorded'); expect(result.current.operationLocked).toBe(true);
    const journal = readOutstandingOps(); expect(journal.ok && journal.value).toHaveLength(1);
    const first = commit.mock.calls[0][0];
    await act(async () => { await result.current.retryRecorded(); });
    expect(result.current.phase).toBe('saved'); expect(commit).toHaveBeenCalledTimes(2);
    expect(commit.mock.calls[1][0].patch).toEqual(first.patch);
    expect(result.current.view?.baseProfile?.experience_entries).toHaveLength(1);
  });
  it('does not treat an unrelated successful flush as this supplement being saved', async () => {
    const { result, accepted } = await ready(); commit.mockResolvedValue({ status: 'transport-error', message: 'offline' });
    await act(async () => { await result.current.confirm(draft(), result.current.baseline('activity')!); });
    vi.spyOn(sync, 'flushPendingProfileWrite').mockResolvedValue({ status: 'saved', revision: 8, profile: { ...base, major: 'Physics' } });
    await act(async () => { await result.current.retryRecorded(); });
    expect(result.current.phase).toBe('stale'); expect(result.current.operationLocked).toBe(true);
    expect(result.current.confirmedEntryId).toBeNull(); expect(accepted).not.toHaveBeenCalled();
  });
  it('requires the latest confirmed base as well as the success response, preserving a later deletion', async () => {
    const { result, accepted } = await ready();
    const original = sync.commitProfileAction;
    vi.spyOn(sync, 'commitProfileAction').mockImplementation(async (input) => {
      const outcome = await original(input);
      load.mockResolvedValue(cloud(base, 9)); await sync.hydrateProfile(); // another device already removed it
      return outcome;
    });
    await act(async () => { await result.current.confirm(draft(), result.current.baseline('activity')!); });
    expect(result.current.phase).toBe('stale'); expect(accepted).not.toHaveBeenCalled();
    expect(result.current.confirmedEntryId).toBeNull();
  });
  it.each(['resume_text', 'coursework', 'experience_entries', 'resume_master'] as const)(
    'rejects confirmation after a change to bundle member %s', async (key) => {
      const { result } = await ready(); const against = result.current.baseline('activity')!;
      const changed = structuredClone(base);
      if (key === 'resume_text') changed.resume_text = '';
      if (key === 'coursework') changed.coursework = ['Different course'];
      if (key === 'experience_entries') changed.experience_entries = [{ id: 'other', revision: 1, status: 'rejected', text: 'Other', source: { kind: 'manual' } }];
      if (key === 'resume_master') changed.resume_master!.activities = [];
      load.mockResolvedValue(cloud(changed, 8)); await sync.hydrateProfile();
      await act(async () => { await result.current.confirm(draft(), against); });
      expect(result.current.phase).toBe('stale'); expect(commit).not.toHaveBeenCalled();
    },
  );
  it('keeps the displayed CAS view for a race after comparison and surfaces the real bundle conflict', async () => {
    const { result, accepted } = await ready(); const against = result.current.baseline('activity')!;
    commit.mockResolvedValue({ status: 'conflict', revision: 8, profile: { ...base, resume_text: '' } as unknown as Record<string, unknown> });
    await act(async () => { await result.current.confirm(draft(), against); });
    expect(result.current.phase).toBe('conflict'); expect(accepted).not.toHaveBeenCalled();
    expect(commit.mock.calls[0][0].expectedRevision).toBe(7);
    expect(sync.readProfileSyncEnvelope()?.pending?.lockedKeys).toEqual(expect.arrayContaining([...sync.RESUME_BUNDLE]));
  });
  it('does not treat object-key reordering or unrelated profile edits as stale', async () => {
    const { result } = await ready(); const against = result.current.baseline('activity')!;
    const reordered = JSON.parse(JSON.stringify(base, (_key, value) => value && typeof value === 'object' && !Array.isArray(value)
      ? Object.fromEntries(Object.entries(value).reverse()) : value)) as ProfileData;
    reordered.major = 'Physics'; load.mockResolvedValue(cloud(reordered, 8)); await sync.hydrateProfile();
    commit.mockImplementation(async (intent) => saved({ ...reordered, ...intent.patch } as ProfileData, 9));
    await act(async () => { await result.current.confirm(draft(), against); });
    expect(result.current.phase).toBe('saved'); expect(result.current.view?.renderedProfile.major).toBe('Physics');
  });
  it('never creates a new profile from revision zero', async () => {
    load.mockResolvedValue(cloud(null)); const hook = renderHook(() => useResumeSupplement({ targetKey: 'a' }));
    await waitFor(() => expect(hook.result.current.phase).toBe('not-saved'));
    expect(hook.result.current.baseline('activity')).toBeNull(); expect(commit).not.toHaveBeenCalled();
  });
  it('keeps load failures distinct from an absent profile', async () => {
    load.mockRejectedValue(new Error('offline')); const hook = renderHook(() => useResumeSupplement({ targetKey: 'a' }));
    await waitFor(() => expect(hook.result.current.phase).toBe('load-error'));
    expect(hook.result.current.view).toBeNull(); expect(commit).not.toHaveBeenCalled();
  });
  it('ignores delayed hydration after owner retirement, including returning to the same uid', async () => {
    const wait = deferred<LoadedProfile>(); const old = cloud(base); load.mockReturnValue(wait.promise);
    const hook = renderHook(() => useResumeSupplement({ targetKey: 'a' }));
    await act(async () => { advanceOwnerEpoch('other-owner'); await syncLocalIdentityOwner('other-owner');
      advanceOwnerEpoch('supplement-owner'); await syncLocalIdentityOwner('supplement-owner'); wait.resolve(old); });
    expect(hook.result.current.view).toBeNull(); expect(hook.result.current.phase).not.toBe('ready');
  });
  it('retires a late save receipt after the owner changes', async () => {
    const { result, accepted } = await ready(); const wait = deferred<ProfilePatchOutcome>(); commit.mockReturnValue(wait.promise);
    let pending!: Promise<unknown>; act(() => { pending = result.current.confirm(draft(), result.current.baseline('activity')!); });
    await waitFor(() => expect(commit).toHaveBeenCalledOnce());
    const desired = { ...base, ...commit.mock.calls[0][0].patch } as ProfileData;
    load.mockReturnValue(new Promise(() => {})); // the new owner's unrelated read is still pending
    await act(async () => { advanceOwnerEpoch('other-owner'); await syncLocalIdentityOwner('other-owner'); wait.resolve(saved(desired)); await pending; });
    expect(result.current.view).toBeNull(); expect(accepted).not.toHaveBeenCalled();
  });
  it('retires a target context change until explicit acceptance and ignores the old load', async () => {
    const wait = deferred<LoadedProfile>(); const old = cloud(base); load.mockReturnValueOnce(wait.promise);
    const hook = renderHook(({ targetKey }) => useResumeSupplement({ targetKey }), { initialProps: { targetKey: 'a' } });
    const ownerScope = hook.result.current.ownerScopeKey; hook.rerender({ targetKey: 'a-updated' });
    expect(hook.result.current.phase).toBe('stale'); expect(hook.result.current.ownerScopeKey).toBe(ownerScope);
    await act(async () => { wait.resolve(old); }); expect(hook.result.current.phase).toBe('stale');
    expect(load).toHaveBeenCalledTimes(1); await act(async () => { await hook.result.current.acceptCurrent(); });
    expect(hook.result.current.phase).toBe('ready'); expect(hook.result.current.baseline('activity')?.targetKey).toBe('a-updated');
  });
  it.each(['recorded', 'inflight', 'unknown'] as const)('retains the original %s operation across target context changes', async (mode) => {
    const accepted = vi.fn();
    const hook = renderHook(({ targetKey }) => useResumeSupplement({ targetKey, onAcceptedProfile: accepted }), { initialProps: { targetKey: 'a' } });
    await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
    const wait = deferred<ProfilePatchOutcome>();
    if (mode === 'inflight') commit.mockReturnValueOnce(wait.promise);
    else commit.mockResolvedValueOnce({ status: 'transport-error', message: 'offline' });
    const realAction = sync.commitProfileAction;
    if (mode === 'unknown') vi.spyOn(sync, 'commitProfileAction').mockImplementationOnce(async (input) => {
      await realAction(input); throw new Error('receipt lost');
    });
    let pending!: Promise<unknown>;
    act(() => { pending = hook.result.current.confirm(draft(), hook.result.current.baseline('activity')!); });
    await waitFor(() => expect(commit).toHaveBeenCalledTimes(1));
    if (mode !== 'inflight') await act(async () => { await pending; });
    hook.rerender({ targetKey: 'a-updated' });
    expect(hook.result.current.phase).toBe('stale'); expect(hook.result.current.operationLocked).toBe(true);
    const desired = { ...base, ...commit.mock.calls[0][0].patch } as ProfileData;
    if (mode === 'inflight') await act(async () => { wait.resolve(saved(desired)); await pending; });
    expect(accepted).not.toHaveBeenCalled();
    await act(async () => { await hook.result.current.retryRecorded(); });
    expect(hook.result.current.phase).toBe('saved');
    expect(hook.result.current.view?.baseProfile?.experience_entries).toHaveLength(1);
    expect(hook.result.current.view?.baseProfile?.resume_master?.activities[0].details).toHaveLength(1);
    expect(accepted).not.toHaveBeenCalled(); // old target cannot update a new target overlay
    expect(commit).toHaveBeenCalledTimes(mode === 'inflight' ? 1 : 2);
  });
  it('rejects corrupt envelope reads before a confirmation without replacing the old raw data', async () => {
    const { result } = await ready(); const against = result.current.baseline('activity')!;
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, '{broken');
    await act(async () => { await result.current.confirm(draft(), against); });
    expect(result.current.phase).toBe('stale'); expect(commit).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC)).toBe('{broken');
  });
  it('treats quarantine failure as a read error and refuses the supplied profile', async () => {
    const hydrate = sync.hydrateProfile;
    vi.spyOn(sync, 'hydrateProfile').mockImplementation(async () => ({ ...await hydrate(), quarantineFailed: true }));
    const hook = renderHook(() => useResumeSupplement({ targetKey: 'a' }));
    await waitFor(() => expect(hook.result.current.phase).toBe('load-error'));
    expect(hook.result.current.view).toBeNull(); expect(hook.result.current.baseline('activity')).toBeNull();
  });
  it('retires same-uid generation replacement and never lets the old view commit', async () => {
    const { result } = await ready(); const against = result.current.baseline('activity')!;
    const token = captureOwnerToken();
    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, JSON.stringify({ v: 2, uid: token.uid, generation: token.generation + 1, phase: 'ready' }));
    await act(async () => { await syncLocalIdentityOwner(token.uid); window.dispatchEvent(new StorageEvent('storage')); });
    await act(async () => { await result.current.confirm(draft(), against); });
    expect(commit).not.toHaveBeenCalled(); expect(result.current.view?.token.generation).not.toBe(token.generation);
  });
  it('does not apply a late retry receipt after owner replacement', async () => {
    const { result, accepted } = await ready(); commit.mockResolvedValueOnce({ status: 'transport-error', message: 'offline' });
    await act(async () => { await result.current.confirm(draft(), result.current.baseline('activity')!); });
    const wait = deferred<sync.ProfileSaveResult>(); vi.spyOn(sync, 'flushPendingProfileWrite').mockReturnValue(wait.promise);
    const desired = { ...base, ...commit.mock.calls[0][0].patch } as ProfileData;
    let retry!: Promise<sync.ProfileSaveResult>; act(() => { retry = result.current.retryRecorded(); });
    load.mockReturnValue(new Promise(() => {}));
    await act(async () => { advanceOwnerEpoch('replacement'); await syncLocalIdentityOwner('replacement');
      wait.resolve({ status: 'saved', revision: 8, profile: desired }); await retry; });
    expect(result.current.view).toBeNull(); expect(accepted).not.toHaveBeenCalled();
  });
  it('releases an already-confirmed operation on explicit review after a later deletion', async () => {
    const { result } = await ready();
    await act(async () => { await result.current.confirm(draft(), result.current.baseline('activity')!); });
    expect(result.current.phase).toBe('saved');
    load.mockResolvedValue(cloud(base, 9));
    await act(async () => { await sync.hydrateProfile(); window.dispatchEvent(new StorageEvent('storage')); });
    expect(result.current.phase).toBe('stale');
    await act(async () => { await result.current.acceptCurrent(); });
    expect(result.current.phase).toBe('ready'); expect(result.current.operationLocked).toBe(false);
    expect(result.current.view?.renderedProfile.experience_entries).toEqual([]);
    expect(commit).toHaveBeenCalledTimes(1); // review does not replay or resurrect the acknowledged old operation
  });
  it('labels an unexpected commit rejection unknown and only retries the original flush', async () => {
    const { result } = await ready(); vi.spyOn(sync, 'commitProfileAction').mockRejectedValue(new Error('unexpected'));
    const flush = vi.spyOn(sync, 'flushPendingProfileWrite').mockResolvedValue({ status: 'blocked' });
    await act(async () => { expect(await result.current.confirm(draft(), result.current.baseline('activity')!)).toBeNull(); });
    expect(result.current.phase).toBe('save-unknown'); expect(result.current.operationLocked).toBe(true);
    await act(async () => { await result.current.retryRecorded(); });
    expect(flush).toHaveBeenCalledTimes(1); expect(result.current.phase).toBe('stale'); expect(commit).not.toHaveBeenCalled();
  });
  it('never reads or writes while the parent confirms that the profile is unavailable', async () => {
    const hook = renderHook(() => useResumeSupplement({ targetKey: 'a', profileAvailable: false }));
    expect(hook.result.current.phase).toBe('profile-unavailable');
    expect(hook.result.current.view).toBeNull(); expect(hook.result.current.baseline('activity')).toBeNull();
    await act(async () => { await hook.result.current.acceptCurrent(); expect(await hook.result.current.retryRecorded()).toEqual({ status: 'missing', reason: 'absent' }); });
    expect(load).not.toHaveBeenCalled(); expect(commit).not.toHaveBeenCalled();
  });
  it('rejects retained confirmation callbacks after absence and requires explicit fresh review after availability returns', async () => {
    const hook = renderHook(({ available }) => useResumeSupplement({ targetKey: 'a', profileAvailable: available }), { initialProps: { available: true } });
    await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
    const baseline = hook.result.current.baseline('activity')!; const confirm = hook.result.current.confirm;
    hook.rerender({ available: false });
    expect(hook.result.current.phase).toBe('profile-unavailable'); expect(hook.result.current.view).toBeNull();
    await act(async () => { expect(await confirm(draft(), baseline)).toEqual({ durable: false, reason: 'stale-view' }); });
    expect(commit).not.toHaveBeenCalled(); expect(readOutstandingOps()).toMatchObject({ ok: true, value: [] });
    hook.rerender({ available: true });
    expect(hook.result.current.phase).toBe('stale'); expect(hook.result.current.baseline('activity')).toBeNull();
    expect(load).toHaveBeenCalledTimes(1);
    base = { ...base, coursework: ['Current restored course'] }; load.mockResolvedValue(cloud(base, 8));
    await act(async () => { await hook.result.current.acceptCurrent(); });
    expect(hook.result.current.phase).toBe('ready'); expect(hook.result.current.view?.renderedProfile.coursework).toEqual(['Current restored course']);
    expect(hook.result.current.view).not.toBe(baseline.view); expect(commit).not.toHaveBeenCalled();
  });
  it('keeps a recorded operation identity but refuses its replay after confirmed whole-profile deletion', async () => {
    const hook = renderHook(({ available }) => useResumeSupplement({ targetKey: 'a', profileAvailable: available }), { initialProps: { available: true } });
    await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
    commit.mockResolvedValueOnce({ status: 'transport-error', message: 'offline' });
    await act(async () => { await hook.result.current.confirm(draft(), hook.result.current.baseline('activity')!); });
    expect(hook.result.current.phase).toBe('recorded');
    const journal = readOutstandingOps(); expect(journal.ok && journal.value).toHaveLength(1);
    load.mockResolvedValue(cloud(null)); await act(async () => { await sync.hydrateProfile(); });
    expect(sync.readProfileSyncEnvelope()?.tombstone?.reason).toBe('deleted');
    hook.rerender({ available: false });
    await act(async () => { expect(await hook.result.current.retryRecorded()).toEqual({ status: 'missing', reason: 'absent' }); });
    expect(hook.result.current.operationLocked).toBe(true); expect(hook.result.current.phase).toBe('profile-unavailable');
    expect(readOutstandingOps()).toEqual(journal); expect(commit).toHaveBeenCalledTimes(1);
    expect(sync.readProfileSyncEnvelope()?.tombstone?.reason).toBe('deleted');
  });
  it('cancels an old supplement read before its late row can repopulate the local mirror', async () => {
    const wait = deferred<LoadedProfile>(); const old = cloud(base); load.mockReturnValueOnce(wait.promise);
    const hook = renderHook(({ available }) => useResumeSupplement({ targetKey: 'a', profileAvailable: available }), { initialProps: { available: true } });
    expect(load).toHaveBeenCalledTimes(1);
    hook.rerender({ available: false }); hook.rerender({ available: true });
    await act(async () => { wait.resolve(old); });
    expect(hook.result.current.phase).toBe('stale'); expect(hook.result.current.view).toBeNull();
    expect(sync.readProfileSyncEnvelope()).toBeNull(); expect(commit).not.toHaveBeenCalled();
    await act(async () => { await hook.result.current.acceptCurrent(); });
    expect(hook.result.current.phase).toBe('ready'); expect(load).toHaveBeenCalledTimes(2);
  });
  it('does not revoke an already-sent CAS, but an absence/recovery cycle retires its old successful UI receipt', async () => {
    const accepted = vi.fn();
    const hook = renderHook(({ available }) => useResumeSupplement({ targetKey: 'a', profileAvailable: available, onAcceptedProfile: accepted }), { initialProps: { available: true } });
    await waitFor(() => expect(hook.result.current.phase).toBe('ready'));
    const wait = deferred<ProfilePatchOutcome>(); commit.mockReturnValueOnce(wait.promise);
    let pending!: Promise<unknown>; act(() => { pending = hook.result.current.confirm(draft(), hook.result.current.baseline('activity')!); });
    await waitFor(() => expect(commit).toHaveBeenCalledTimes(1));
    const desired = { ...base, ...commit.mock.calls[0][0].patch } as ProfileData;
    hook.rerender({ available: false }); hook.rerender({ available: true });
    await act(async () => { wait.resolve(saved(desired)); await pending; });
    expect(hook.result.current.phase).toBe('stale'); expect(hook.result.current.confirmedEntryId).toBeNull();
    expect(hook.result.current.operationLocked).toBe(true); expect(accepted).not.toHaveBeenCalled(); expect(commit).toHaveBeenCalledTimes(1);
    load.mockResolvedValue(cloud(desired, 8));
    await act(async () => { await hook.result.current.acceptCurrent(); });
    expect(hook.result.current.phase).toBe('saved'); expect(accepted).toHaveBeenCalledTimes(1);
    expect(hook.result.current.view?.baseProfile?.experience_entries).toHaveLength(1); expect(commit).toHaveBeenCalledTimes(1);
  });

});
