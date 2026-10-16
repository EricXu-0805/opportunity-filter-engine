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
// Only transport is replaced: the coordinator, journal, owner capabilities and
// Home's own save handling are the real ones.
vi.mock('@/lib/supabase', () => ({
  loadProfile: (signal?: AbortSignal) => service.load(signal),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: typeof service.auth) => { service.auth = callback; return () => { service.auth = null; }; },
}));
import { useProfileForm, type GuestRestoreCheck, type GuestRestoreOutcome } from './use-profile-form';
import { DEFAULT_PROFILE } from './types';
import { advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { HOME_FORM_WRITER, PROFILE_KEYS, readProfileSyncEnvelope, resetProfileDirtyLedger, stageProfilePatch } from '@/lib/profile-sync';
import { readOutstandingOps, resetJournalLaneForTests } from '@/lib/profile-journal';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { clearMatchCache } from '@/lib/match-cache';

const ACCOUNT: ProfileData = { ...DEFAULT_PROFILE, name: 'Account owner', home_school: 'uiuc', institution: 'UIUC',
  college: 'Engineering', major: 'Computer Science', grade: 'Junior', research_interests: 'Account research',
  resume_text: 'ACCOUNT OWNER RESUME: four years of embedded systems work',
  coursework: ['ECE 391', 'CS 374'], seeking_types: ['internship'], experience_level: 'advanced',
  include_cross_school: true, exploring: true, additional_majors: ['Mathematics'],
  linkedin_url: 'https://linkedin.com/in/account-owner', github_url: 'https://github.com/account-owner',
  scholar_url: 'https://scholar.google.com/citations?user=ACCOUNT' };
// What the merge saved in the account's history: a guest profile, as stored.
const GUEST = { ...DEFAULT_PROFILE, name: 'Guest', college: 'Engineering', major: 'Physics', grade: 'Freshman',
  research_interests: 'Guest research', skills: [{ name: 'Python', level: 'beginner' }], search_weight: 70 };
// What a fresh guest profile has in the fields this guest never set.
const UNSET_BY_GUEST = { resume_text: '', coursework: [], courses: [], seeking_types: ['research', 'summer_program'],
  experience_level: 'beginner', include_cross_school: false, exploring: false,
  linkedin_url: '', github_url: '', scholar_url: '', account_type: 'personal' };
const t = (key: string) => key;
let remote: ProfileData;
let revision: number;
let uid: string;
let sequence = 0;
function row(): LoadedProfile {
  return { source: 'cloud', profile: { ...structuredClone(remote) }, revision, token: captureOwnerToken() };
}
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  if (intent.expectedRevision !== revision) return { status: 'conflict', profile: { ...structuredClone(remote) }, revision };
  remote = { ...remote, ...intent.patch }; revision += 1;
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
async function start() {
  const hook = renderHook(() => useProfileForm(t));
  act(() => { service.auth?.({ user: { id: uid } }); }); await drain();
  expect(hook.result.current.hydrationState).toBe('ready');
  expect(hook.result.current.profile.name).toBe(ACCOUNT.name);
  return hook;
}
type Hook = { current: ReturnType<typeof useProfileForm> };
/** The archived row, as the notice reads it again for a restore. */
const readGuest = async (): Promise<Record<string, unknown>> => structuredClone(GUEST);
async function restore(result: Hook, owner = captureOwnerToken()) {
  let outcome: Promise<GuestRestoreOutcome> | null = null;
  act(() => { outcome = result.current.restoreArchivedProfile(owner, readGuest); });
  await drain();
  return outcome!;
}
/** What the read back found; 'failed' when it threw. */
async function confirm(result: Hook, owner = captureOwnerToken()) {
  let restored: Promise<GuestRestoreCheck | 'failed'> | null = null;
  act(() => {
    restored = result.current.confirmArchivedProfileRestored(structuredClone(GUEST), owner).catch(() => 'failed' as const);
  });
  await drain();
  return restored!;
}
// Nothing of a restore is ever left to send: no outbox entry, no journal
// operation.
function nothingPending() {
  expect(readProfileSyncEnvelope()?.pending ?? null).toBeNull();
  expect(readOutstandingOps()).toEqual({ ok: true, value: [] });
}
// Reconnecting, the autosave and Retry: everything that could send a save.
async function everyResend(result: Hook) {
  act(() => { window.dispatchEvent(new Event('online')); });
  await drain();
  await tick(5000);
  act(() => { result.current.retryCloudSave(); });
  await drain();
}
beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.auth = null; service.params = new URLSearchParams();
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  uid = `home-restore-guest-${++sequence}`;
  advanceOwnerEpoch(null); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  expect(isOwnerTokenValid(captureOwnerToken(), uid)).toBe(true);
  remote = structuredClone(ACCOUNT); revision = 3;
  service.load.mockReset().mockImplementation(async () => row());
  service.commit.mockReset().mockImplementation(apply);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

const { search_weight: ACCOUNT_WEIGHT, ...ACCOUNT_FIELDS } = ACCOUNT;
const RESTORED = { ...ACCOUNT, ...GUEST, ...UNSET_BY_GUEST };

describe('Home restores the guest profile a merge saved in the account history', () => {
  it('saves the whole archived profile in one revision-checked save, and changes the form only once the server saved it', async () => {
    const { result } = await start();
    let answer: (outcome: ProfilePatchOutcome) => void = () => {};
    service.commit.mockImplementationOnce((intent) => new Promise((resolve) => {
      answer = (outcome) => resolve(outcome);
      void apply(intent);
    }));
    let outcome: Promise<GuestRestoreOutcome> | null = null;
    act(() => { outcome = result.current.restoreArchivedProfile(captureOwnerToken(), readGuest); });
    await drain();

    // Sent: every profile field, against the revision on screen.
    expect(service.commit).toHaveBeenCalledOnce();
    const sent = service.commit.mock.calls[0][0];
    expect(sent.expectedRevision).toBe(3);
    expect(sent.token.uid).toBe(uid);
    expect(Object.keys(sent.patch).sort()).toEqual([...PROFILE_KEYS].sort());
    expect(sent.patch).toMatchObject({ ...GUEST, ...UNSET_BY_GUEST });
    // Until the server answers, the form is the account's and nothing of the
    // restore is pending anywhere.
    expect(result.current.profile).toMatchObject(ACCOUNT_FIELDS);
    expect(result.current.guestRestoreBlocker(captureOwnerToken())).toBe('saving');
    nothingPending();

    act(() => { answer({ status: 'saved', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision }); });
    await drain();
    expect(await outcome!).toBe('restored');
    expect(revision).toBe(4);
    expect(remote).toEqual(RESTORED);
    // The server's row, on the form as the stored state: every field of the
    // guest profile, none of the account's résumé, links or choices.
    expect(result.current.profile).toMatchObject({ ...GUEST, ...UNSET_BY_GUEST, search_weight: 70 });
    expect(result.current.searchWeight).toBe(70);
    expect(result.current.viewSnapshot?.revision).toBe(4);
    expect(readProfileSyncEnvelope()?.confirmed).toMatchObject({ revision: 4, profile: { name: 'Guest' } });
    expect(result.current.isArchivedProfileStored(structuredClone(GUEST), captureOwnerToken())).toBe(true);
    nothingPending();
    expect(result.current.guestRestoreBlocker(captureOwnerToken())).toBeNull();
    // Not sent again by the autosave, a reconnect or Retry.
    await everyResend(result);
    expect(service.commit).toHaveBeenCalledOnce();
  });

  it('holds an edit typed while the restore was in flight until it is answered, then asks about it rather than overwriting either side', async () => {
    // The review's probes P2 and P3: the typed save no longer goes out
    // beside the restore, so it cannot land first and turn the restore into a
    // conflict, nor be sent against a row the restore has already replaced.
    const { result } = await start();
    let answer: (outcome: ProfilePatchOutcome) => void = () => {};
    service.commit.mockImplementationOnce((intent) => new Promise((resolve) => {
      answer = (outcome) => resolve(outcome);
      void apply(intent);
    }));
    let outcome: Promise<GuestRestoreOutcome> | null = null;
    act(() => { outcome = result.current.restoreArchivedProfile(captureOwnerToken(), readGuest); });
    await drain();
    expect(result.current.guestRestoreHeld).toBe(true);
    act(() => { result.current.setProfile((profile) => ({ ...profile, research_interests: 'Typed while restoring' })); });
    await everyResend(result);
    expect(service.commit, 'the autosave, a reconnect and Retry all wait').toHaveBeenCalledOnce();
    expect(result.current.profile.research_interests).toBe('Typed while restoring');

    act(() => { answer({ status: 'saved', profile: structuredClone(remote) as unknown as Record<string, unknown>, revision }); });
    await drain();
    expect(await outcome!).toBe('restored');
    // The stored row comes in through the profile check, which keeps the
    // typed field; its save was made against the account's row, so it comes
    // back as a question instead of replacing the restored value.
    expect(result.current.profile).toMatchObject({ name: 'Guest', research_interests: 'Typed while restoring' });
    await tick(5000);
    expect(result.current.saveStatus).toBe('conflict');
    expect(result.current.conflicts.map((question) => question.key)).toEqual(['research_interests']);
    expect(remote).toEqual(RESTORED);
  });

  it('on a conflict writes nothing, leaves no guest value on the form, and shows the stored row to restore over', async () => {
    const { result } = await start();
    remote = { ...remote, major: 'Changed on the phone' }; revision = 4;

    expect(await restore(result)).toBe('conflict');
    expect(service.commit.mock.calls[0][0].expectedRevision).toBe(3);
    expect(remote).toEqual({ ...ACCOUNT, major: 'Changed on the phone' });
    expect(revision).toBe(4);
    // The account's profile as the server now holds it, and no question: the
    // restore was never an edit of the form's.
    expect(result.current.profile).toMatchObject({ ...ACCOUNT_FIELDS, major: 'Changed on the phone' });
    expect(result.current.viewSnapshot?.revision).toBe(4);
    expect(result.current.conflicts).toEqual([]);
    expect(result.current.saveStatus).not.toBe('conflict');
    nothingPending();
    await everyResend(result);
    expect(service.commit).toHaveBeenCalledOnce();

    // Restore is offered again, over that row.
    expect(result.current.guestRestoreBlocker(captureOwnerToken())).toBeNull();
    expect(await restore(result)).toBe('restored');
    expect(service.commit.mock.calls[1][0].expectedRevision).toBe(4);
    expect(remote).toEqual(RESTORED);
  });

  it.each([
    ['the row is gone', { status: 'missing', reason: 'absent' } as const],
    ['there is no backend', { status: 'local-only' } as const],
  ])('changes nothing when the save is refused because %s', async (_why, refusal) => {
    const { result } = await start();
    service.commit.mockImplementationOnce(async () => refusal);

    expect(await restore(result)).toBe('refused');
    expect(result.current.profile).toMatchObject(ACCOUNT_FIELDS);
    expect(result.current.searchWeight).toBe(ACCOUNT_WEIGHT);
    expect(result.current.viewSnapshot?.revision).toBe(3);
    nothingPending();
    await everyResend(result);
    expect(service.commit).toHaveBeenCalledOnce();
    expect(remote).toEqual(ACCOUNT);
  });

  it('after a save with no answer that the server did take, reads the stored profile back and shows it as restored', async () => {
    const { result } = await start();
    // The request reached the server; its answer was lost.
    service.commit.mockImplementationOnce(async (intent) => {
      await apply(intent);
      return { status: 'transport-error', message: 'Failed to fetch' };
    });

    expect(await restore(result)).toBe('unknown');
    expect(remote).toEqual(RESTORED);
    expect(result.current.profile, 'unchanged until it is known').toMatchObject(ACCOUNT_FIELDS);
    nothingPending();

    expect(await confirm(result)).toBe('restored');
    expect(result.current.profile).toMatchObject({ ...GUEST, ...UNSET_BY_GUEST });
    expect(result.current.viewSnapshot?.revision).toBe(4);
    nothingPending();
    await everyResend(result);
    expect(service.commit).toHaveBeenCalledOnce();
  });

  it('after a save with no answer that the server did not take, reads the stored profile back and changes nothing', async () => {
    const { result } = await start();
    service.commit.mockImplementationOnce(async () => ({ status: 'transport-error', message: 'Failed to fetch' }));

    expect(await restore(result)).toBe('unknown');
    // The read back fails at first: still unknown, and nothing changes.
    service.load.mockImplementationOnce(async () => { throw new Error('offline'); });
    expect(await confirm(result)).toBe('failed');
    expect(result.current.profile).toMatchObject(ACCOUNT_FIELDS);

    expect(await confirm(result)).toBe('notRestored');
    expect(result.current.profile).toMatchObject(ACCOUNT_FIELDS);
    expect(result.current.viewSnapshot?.revision).toBe(3);
    nothingPending();
    await everyResend(result);
    expect(service.commit).toHaveBeenCalledOnce();
    expect(remote).toEqual(ACCOUNT);
  });

  it('after a restore that did not save, the next edit sends only itself, and so does every later visit', async () => {
    // The review's probes A, B and D: nothing of a failed restore is on the
    // form or in the journal, so an edit cannot carry it and Keep has nothing
    // to set aside.
    const { result, unmount } = await start();
    service.commit.mockImplementationOnce(async () => ({ status: 'transport-error', message: 'Failed to fetch' }));
    expect(await restore(result)).toBe('unknown');
    expect(await confirm(result)).toBe('notRestored');

    act(() => { result.current.setProfile((profile) => ({ ...profile, research_interests: 'Typed after the restore failed' })); });
    await drain();
    await tick(5000);
    expect(service.commit).toHaveBeenCalledTimes(2);
    expect(Object.keys(service.commit.mock.calls[1][0].patch)).toEqual(['research_interests']);
    expect(remote).toEqual({ ...ACCOUNT, research_interests: 'Typed after the restore failed' });

    unmount();
    service.commit.mockClear();
    const next = await start();
    await everyResend(next.result);
    expect(service.commit).not.toHaveBeenCalled();
    expect(next.result.current.profile).toMatchObject({ ...ACCOUNT_FIELDS, research_interests: 'Typed after the restore failed' });
  });

  it('is not sent while offline, while a save of the form is waiting or unsent, or while a profile check holds the form', async () => {
    const { result } = await start();
    const owner = captureOwnerToken();
    const blocker = () => result.current.guestRestoreBlocker(owner);
    expect(blocker()).toBeNull();

    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
    expect(blocker()).toBe('offline');
    expect(await restore(result)).toBe('busy');
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });

    // An edit waiting for the autosave.
    act(() => { result.current.setProfile((profile) => ({ ...profile, grade: 'Senior' })); });
    await drain();
    expect(blocker()).toBe('saving');
    expect(await restore(result)).toBe('busy');
    // That save failing: it is unsent, and the resend sends it later.
    service.commit.mockImplementationOnce(async () => ({ status: 'transport-error', message: 'Failed to fetch' }));
    await tick(2000);
    expect(result.current.saveStatus).toBe('cloud-failed');
    expect(blocker()).toBe('saving');
    expect(await restore(result)).toBe('busy');
    act(() => { result.current.retryCloudSave(); });
    await drain();
    expect(result.current.saveStatus).toBe('saved');
    expect(blocker()).toBeNull();

    // A profile check that has not come back.
    service.load.mockImplementation(() => new Promise<LoadedProfile>(() => {}));
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    await drain();
    expect(result.current.profileRefreshStatus).toBe('checking');
    expect(blocker()).toBe('refreshing');
    expect(await restore(result)).toBe('busy');

    // Only the form's own save went out, never the restore.
    expect(service.commit.mock.calls.every(([sent]) => !Object.values(sent.patch).includes('Guest'))).toBe(true);
    expect(remote).toEqual({ ...ACCOUNT, grade: 'Senior' });
  });

  it('is not sent while another tab of this account has a save in the shared outbox', async () => {
    const { result } = await start();
    // Another tab (the results page's cross-school switch) staged a save that
    // has not been answered; this form knows nothing of it.
    service.commit.mockImplementationOnce(() => new Promise<ProfilePatchOutcome>(() => {}));
    void stageProfilePatch({ ...structuredClone(ACCOUNT), include_cross_school: false }, ['include_cross_school'], captureOwnerToken());
    await drain();
    expect(readProfileSyncEnvelope()?.pending).toBeTruthy();
    expect(result.current.saveStatus).toBe('idle');
    expect(result.current.guestRestoreBlocker(captureOwnerToken())).toBe('saving');
    expect(await restore(result)).toBe('busy');
    expect(service.commit).toHaveBeenCalledOnce();
    expect(service.commit.mock.calls[0][0].patch).toEqual({ include_cross_school: false });
  });

  it('sends none of the form\'s saves until a restore with no answer is read back, so the read-back finds the restore', async () => {
    // The review's probe E / P4: the server took the restore and its answer
    // was lost; while the read-back is slow, the student changes a field the
    // guest and account profiles share. Sent at once, that edit was rebased
    // onto the restored row with no question and saved, so the read-back
    // found neither the restore nor the account's row and said "not
    // restored" while the server held the guest profile.
    const { result } = await start();
    service.commit.mockImplementationOnce(async (intent) => {
      await apply(intent);
      return { status: 'transport-error', message: 'Failed to fetch' };
    });
    expect(await restore(result)).toBe('unknown');
    expect(remote).toEqual(RESTORED);
    expect(result.current.guestRestoreHeld).toBe(true);

    let release: () => void = () => {};
    service.load.mockImplementationOnce(() => new Promise<LoadedProfile>((resolve) => { release = () => resolve(row()); }));
    let check: Promise<GuestRestoreCheck | 'failed'> | null = null;
    act(() => {
      check = result.current.confirmArchivedProfileRestored(structuredClone(GUEST), captureOwnerToken()).catch(() => 'failed' as const);
    });
    await drain();
    expect(GUEST.college).toBe(ACCOUNT.college);
    act(() => { result.current.setProfile((profile) => ({ ...profile, college: 'Liberal Arts' })); });
    await everyResend(result);
    expect(service.commit, 'the edit waits in the journal').toHaveBeenCalledOnce();
    expect(revision).toBe(4);
    expect(result.current.profile.college).toBe('Liberal Arts');
    expect(result.current.guestRestoreBlocker(captureOwnerToken())).toBe('saving');

    act(() => { release(); });
    await drain();
    expect(await check!).toBe('restored');
    expect(result.current.guestRestoreHeld).toBe(false);
    // Then the edit goes out, against the restored row: the form and the
    // server hold the same profile, and a later check changes nothing.
    await tick(5000);
    expect(remote).toEqual({ ...RESTORED, college: 'Liberal Arts' });
    expect(result.current.profile).toMatchObject({ ...GUEST, ...UNSET_BY_GUEST, college: 'Liberal Arts' });
    expect(result.current.conflicts).toEqual([]);
    nothingPending();
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    await drain();
    expect(result.current.profile).toMatchObject({ ...GUEST, ...UNSET_BY_GUEST, college: 'Liberal Arts' });
    expect(result.current.viewSnapshot?.revision).toBe(revision);
  });

  it('holds an edit made offline after the read-back failed, and on reconnecting sends it only once the read-back found the restore', async () => {
    const { result } = await start();
    service.commit.mockImplementationOnce(async (intent) => {
      await apply(intent);
      return { status: 'transport-error', message: 'Failed to fetch' };
    });
    expect(await restore(result)).toBe('unknown');

    // Offline: the read-back fails, and so would any save.
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
    service.load.mockImplementation(async () => { throw new TypeError('Failed to fetch'); });
    service.commit.mockImplementation(async () => ({ status: 'transport-error', message: 'Failed to fetch' }));
    expect(await confirm(result)).toBe('failed');
    expect(result.current.guestRestoreHeld).toBe(true);
    act(() => { result.current.setProfile((profile) => ({ ...profile, college: 'Liberal Arts' })); });
    await tick(5000);
    act(() => { result.current.retryCloudSave(); });
    await drain();
    expect(service.commit, 'nothing is sent offline either').toHaveBeenCalledOnce();
    expect(result.current.saveStatus).not.toBe('cloud-failed');

    // Back online: the profile check and the resend run at once, and the
    // notice reads back again; only once that is done does the edit go out.
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
    service.load.mockImplementation(async () => row());
    service.commit.mockImplementation(apply);
    act(() => { window.dispatchEvent(new Event('online')); });
    await drain();
    await tick(2000);
    expect(service.commit, 'not sent while the outcome is unknown').toHaveBeenCalledOnce();
    expect(await confirm(result)).toBe('restored');
    await tick(5000);
    expect(remote).toEqual({ ...RESTORED, college: 'Liberal Arts' });
    expect(result.current.profile).toMatchObject({ ...GUEST, ...UNSET_BY_GUEST, college: 'Liberal Arts' });
    expect(result.current.conflicts).toEqual([]);
    nothingPending();
  });

  it('holds an edit typed while the archived row is read again, and sends the restore against the revision on screen', async () => {
    const { result } = await start();
    let found: (archived: Record<string, unknown>) => void = () => {};
    let outcome: Promise<GuestRestoreOutcome> | null = null;
    act(() => {
      outcome = result.current.restoreArchivedProfile(captureOwnerToken(),
        () => new Promise<Record<string, unknown>>((resolve) => { found = resolve; }));
    });
    await drain();
    act(() => { result.current.setProfile((profile) => ({ ...profile, research_interests: 'Typed while restoring' })); });
    await everyResend(result);
    expect(service.commit).not.toHaveBeenCalled();

    act(() => { found(structuredClone(GUEST)); });
    await drain();
    expect(await outcome!).toBe('restored');
    expect(service.commit.mock.calls[0][0].expectedRevision).toBe(3);
    // The typed edit goes out after it, made against the account's row, so
    // it comes back as a question rather than replacing the restored value.
    await tick(5000);
    expect(result.current.conflicts.map((question) => question.key)).toEqual(['research_interests']);
    expect(remote).toEqual(RESTORED);
  });

  it('after a save with no answer, shows the row another device saved meanwhile, so the form is what the server holds', async () => {
    const { result } = await start();
    service.commit.mockImplementationOnce(async (intent) => {
      await apply(intent);
      return { status: 'transport-error', message: 'Failed to fetch' };
    });
    expect(await restore(result)).toBe('unknown');
    // A phone saved over the restored row before it was read back.
    remote = { ...remote, major: 'Changed on the phone' }; revision += 1;

    expect(await confirm(result)).toBe('changed');
    expect(result.current.guestRestoreHeld).toBe(false);
    expect(result.current.profile).toMatchObject({ ...GUEST, ...UNSET_BY_GUEST, major: 'Changed on the phone' });
    expect(result.current.viewSnapshot?.revision).toBe(5);
    nothingPending();
    await everyResend(result);
    expect(service.commit).toHaveBeenCalledOnce();
  });

  it('does not say a save is pending when the last one landed and only what followed it failed', async () => {
    // Generate saved the profile and only clearing the match cache failed:
    // the status stays on 'error' with nothing unsent.
    remote = { ...structuredClone(ACCOUNT), github_url: '' };
    const { result } = await start();
    vi.mocked(clearMatchCache).mockReturnValueOnce(false);
    act(() => { result.current.setProfile((profile) => ({ ...profile, grade: 'Senior' })); });
    await act(async () => { await result.current.handleSubmit(); });
    await drain();
    expect(result.current.saveStatus).toBe('error');
    expect(remote.grade).toBe('Senior');
    nothingPending();
    expect(result.current.guestRestoreBlocker(captureOwnerToken())).toBeNull();
  });

  it('a tab that typed nothing, whose restore another open tab\'s edit collided with, asks too and keeps what that tab typed, never the account\'s earlier interests', async () => {
    // Checklist M102 (review M80 r5, T3b): the restore's answer is lost, and
    // while it is read back another tab of the account, open on revision 3,
    // types its interests.
    const { result } = await start();
    service.commit.mockImplementationOnce(async (intent) => {
      await apply(intent);
      return { status: 'transport-error', message: 'Failed to fetch' };
    });
    expect(await restore(result)).toBe('unknown');
    expect(remote).toEqual(RESTORED);
    const typed = 'Typed in the other tab during the restore';
    const ops = readOutstandingOps();
    const clock = Math.max(0, ...(ops.ok ? ops.value.map((o) => o.clock ?? 0) : [])) + 1;
    const opId = crypto.randomUUID();
    localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_${opId}`, JSON.stringify({
      opId, originId: 'tab-b', lineage: 'tab-b',
      fields: [{ key: 'research_interests', base: { present: true, value: ACCOUNT.research_interests },
        desired: { present: true, value: typed } }],
      baseRevision: 3, writer: HOME_FORM_WRITER, mode: 'set', seq: 1, clock,
    }));
    expect(await stageProfilePatch({ ...ACCOUNT, research_interests: typed }, ['research_interests'],
      captureOwnerToken(), { allowCreate: true }))
      .toMatchObject({ status: 'conflict', conflictKeys: ['research_interests'] });
    const sends = service.commit.mock.calls.length;

    expect(await confirm(result)).toBe('restored');
    await drain();
    expect(result.current.conflicts.map((c) => c.key)).toEqual(['research_interests']);
    expect(result.current.saveStatus).toBe('conflict');
    expect(result.current.profile, 'the restored profile, with the other tab\'s unsaved interests')
      .toMatchObject({ name: GUEST.name, major: GUEST.major, research_interests: typed });
    act(() => { result.current.keepMyChanges(); });
    await tick(5000);
    expect(service.commit.mock.calls.slice(sends).map(([intent]) => intent.patch),
      'what the other tab typed, never the account\'s earlier interests').toEqual([{ research_interests: typed }]);
    expect(remote).toMatchObject({ name: GUEST.name, major: GUEST.major, research_interests: typed });
    expect(result.current.conflicts).toEqual([]);
  });

  it('is refused for a profile read under a different identity', async () => {
    const { result } = await start();
    const other = { ...captureOwnerToken(), uid: 'someone-else' };

    expect(result.current.guestRestoreBlocker(other)).not.toBeNull();
    expect(await restore(result, other)).toBe('refused');
    expect(await confirm(result, other)).toBe('failed');
    expect(result.current.isArchivedProfileStored(structuredClone(GUEST), other)).toBe(false);
    expect(service.commit).not.toHaveBeenCalled();
    expect(result.current.profile).toMatchObject({ name: ACCOUNT.name, major: ACCOUNT.major });
    await tick(5000);
    expect(service.commit).not.toHaveBeenCalled();
  });
});
