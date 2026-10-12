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
// Only transport is replaced: the coordinator, the journal, the owner
// capabilities and Home's own save handling are the real ones.
vi.mock('@/lib/supabase', () => ({
  loadProfile: (signal?: AbortSignal) => service.load(signal),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: typeof service.auth) => { service.auth = callback; return () => { service.auth = null; }; },
}));
import { useProfileForm } from './use-profile-form';
import { DEFAULT_PROFILE } from './types';
import { advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { HOME_FORM_WRITER, hydrateProfile, readProfileSyncEnvelope, recordProfileIntent, resetProfileDirtyLedger } from '@/lib/profile-sync';
import { readOutstandingOps, resetJournalLaneForTests, startDocumentForTests } from '@/lib/profile-journal';

// Edits a screen that is gone left unsent in the journal: a closed tab's, or
// the Home form's that in-app navigation unmounted.
const ROW: ProfileData = { ...DEFAULT_PROFILE, name: 'Account owner', college: 'Engineering',
  major: 'Computer Science', grade: 'Junior', research_interests: 'Account research' };
const t = (key: string) => key;
// One row per account, behind the real RPC's rules: a revision check, and a
// repeat of a patch the row already holds answered as unchanged.
let rows: Map<string, { profile: ProfileData; revision: number }>;
let uid: string;
let sequence = 0;
const rowOf = (owner: string) => rows.get(owner)!;
function read(): LoadedProfile {
  const token = captureOwnerToken();
  const row = rowOf(token.uid!);
  return { source: 'cloud', profile: structuredClone(row.profile) as unknown as Record<string, unknown>, revision: row.revision, token };
}
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  const row = rowOf(intent.token.uid!);
  const answer = () => structuredClone(row.profile) as unknown as Record<string, unknown>;
  const merged = { ...row.profile, ...intent.patch } as ProfileData;
  if (JSON.stringify(merged) === JSON.stringify(row.profile)
    && (row.revision === intent.expectedRevision || row.revision === intent.expectedRevision + 1)) {
    return { status: 'already-saved', profile: answer(), revision: row.revision };
  }
  if (intent.expectedRevision !== row.revision) return { status: 'conflict', profile: answer(), revision: row.revision };
  row.profile = merged; row.revision += 1;
  return { status: 'saved', profile: answer(), revision: row.revision };
}
const sends = () => service.commit.mock.calls.map(([intent]) => ({ uid: intent.token.uid, patch: intent.patch }));
const sentKeys = () => sends().flatMap(({ patch }) => Object.keys(patch));
async function drain() {
  for (let pass = 0; pass < 4; pass += 1) {
    await act(async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); });
  }
}
async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); await drain();
}
function nothingOutstanding() {
  expect(readProfileSyncEnvelope()?.pending ?? null, 'no outbox entry').toBeNull();
  expect(readOutstandingOps(), 'no journal operation').toEqual({ ok: true, value: [] });
}
async function mount(owner = uid) {
  const form = renderHook(() => useProfileForm(t));
  act(() => { service.auth?.({ user: { id: owner } }); }); await drain();
  expect(form.result.current.hydrationState).toBe('ready');
  return form;
}
/** A Home form whose load is held open until `respond`. */
async function mountLoading(owner = uid) {
  let respond: () => void = () => {};
  service.load.mockImplementationOnce(() => new Promise<LoadedProfile>((resolve) => { respond = () => resolve(read()); }));
  const form = renderHook(() => useProfileForm(t));
  act(() => { service.auth?.({ user: { id: owner } }); }); await drain();
  expect(form.result.current.hydrationState).toBe('loading');
  return { form, respond: async () => { act(() => { respond(); }); await drain(); } };
}

/** A profile check (focus) whose read is held open until the returned call. */
async function holdProfileCheck(form: Awaited<ReturnType<typeof mount>>) {
  let release: () => void = () => {};
  service.load.mockImplementationOnce(() => new Promise<LoadedProfile>((resolve) => { release = () => resolve(read()); }));
  act(() => { window.dispatchEvent(new Event('focus')); });
  await drain();
  expect(form.result.current.profileRefreshStatus).toBe('checking');
  return () => release();
}
/** An edit typed while a profile check holds saving, then Home is left. */
async function leaveWithJournalOnlyEdit() {
  const first = await mount();
  const release = await holdProfileCheck(first);
  act(() => { first.result.current.setProfile((p) => ({ ...p, college: 'Liberal Arts' })); });
  await tick(2000);
  expect(sends(), 'the check holds the save while it runs').toEqual([]);
  first.unmount();
  await drain();
  release();
  await drain();
  expect(sends(), 'leaving Home writes the journal only').toEqual([]);
  const ops = readOutstandingOps();
  expect(ops.ok && ops.value.map((op) => op.fields.map((f) => f.key))).toEqual([['college']]);
}

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.auth = null; service.params = new URLSearchParams();
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  uid = `home-leftover-${++sequence}`;
  advanceOwnerEpoch(null); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  expect(isOwnerTokenValid(captureOwnerToken(), uid)).toBe(true);
  rows = new Map([[uid, { profile: structuredClone(ROW), revision: 3 }]]);
  service.load.mockReset().mockImplementation(async () => read());
  service.commit.mockReset().mockImplementation(apply);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('a first load', () => {
  it('sends a closed tab\'s edit and one typed during the load once, and does not then report a failure', async () => {
    // The closed tab: an edit recorded against the row, never sent.
    await hydrateProfile();
    expect(recordProfileIntent({ ...ROW, college: 'Liberal Arts' }, ['college'], captureOwnerToken(),
      { writer: HOME_FORM_WRITER, observedBase: { profile: ROW, revision: 3 } })).toBe(true);
    startDocumentForTests('other'); resetProfileDirtyLedger();

    const { form, respond } = await mountLoading();
    // A field the row does not have, so this edit's unknown base is no question.
    act(() => { form.result.current.setProfile((p) => ({ ...p, linkedin_url: 'https://linkedin.com/in/owner' })); });
    await respond();
    expect(sends(), 'the load sends both').toEqual([
      { uid, patch: { college: 'Liberal Arts', linkedin_url: 'https://linkedin.com/in/owner' } },
    ]);
    // The autosave that edit armed fires with nothing left to send.
    await tick(1600);
    expect(sentKeys().sort(), 'and nothing goes out twice').toEqual(['college', 'linkedin_url']);
    expect(form.result.current.saveStatus, 'everything typed is saved').toBe('saved');
    expect(form.result.current.canRetrySync).toBe(false);
    expect(rowOf(uid)).toMatchObject({ revision: 4, profile: { college: 'Liberal Arts', linkedin_url: 'https://linkedin.com/in/owner' } });
    nothingOutstanding();
  });
});

// In-app navigation away from Home and back unmounts the form and mounts a new
// one in the SAME page load.
describe('a Home form remounted in the same page load', () => {
  it('sends an edit the form it replaced left in the journal, without another keystroke', async () => {
    await leaveWithJournalOnlyEdit();
    const second = await mount();
    expect(second.result.current.profile.college, 'the edit is on the form').toBe('Liberal Arts');
    expect(sends(), 'and the load itself sends it').toEqual([{ uid, patch: { college: 'Liberal Arts' } }]);
    expect(rowOf(uid)).toMatchObject({ revision: 4, profile: { college: 'Liberal Arts' } });
    expect(second.result.current.saveStatus).toBe('saved');
    nothingOutstanding();
    // Idle past the autosave and the next profile check: nothing else goes out.
    await tick(5000);
    expect(sends()).toHaveLength(1);
  });

  it('sends nothing when another tab already delivered the edit while this one was away', async () => {
    await leaveWithJournalOnlyEdit();
    // The other tab's write landed; its acknowledgement has not reached the
    // journal yet, so the operation is still outstanding here.
    rowOf(uid).profile = { ...rowOf(uid).profile, college: 'Liberal Arts' }; rowOf(uid).revision = 4;
    const second = await mount();
    expect(second.result.current.profile.college).toBe('Liberal Arts');
    await tick(5000);
    expect(sends(), 'a value the row already holds is not sent again').toEqual([]);
    expect(rowOf(uid).revision).toBe(4);
    expect(second.result.current.saveStatus).not.toBe('error');
  });

  it("does not send the old form's edit for another account", async () => {
    await leaveWithJournalOnlyEdit();
    const other = `${uid}-other`;
    rows.set(other, { profile: { ...structuredClone(ROW), name: 'Other account' }, revision: 7 });
    advanceOwnerEpoch(other); await syncLocalIdentityOwner(other);
    const second = await mount(other);
    expect(second.result.current.profile).toMatchObject({ name: 'Other account', college: 'Engineering' });
    await tick(5000);
    expect(sends(), 'nothing is sent under the other account').toEqual([]);
    expect(rowOf(other)).toMatchObject({ revision: 7, profile: { college: 'Engineering' } });
    expect(rowOf(uid)).toMatchObject({ revision: 3, profile: { college: 'Engineering' } });
  });

  it('sends its own edit typed during the load once, together with what the old form left', async () => {
    await leaveWithJournalOnlyEdit();
    const { form, respond } = await mountLoading();
    act(() => { form.result.current.setProfile((p) => ({ ...p, linkedin_url: 'https://linkedin.com/in/owner' })); });
    await respond();
    await tick(1600);
    expect(sentKeys().sort(), 'each edit goes out once').toEqual(['college', 'linkedin_url']);
    expect(form.result.current.saveStatus).toBe('saved');
    expect(rowOf(uid)).toMatchObject({ revision: 4, profile: { college: 'Liberal Arts', linkedin_url: 'https://linkedin.com/in/owner' } });
    nothingOutstanding();
  });

  it('reports the save the form it replaced still had in flight, and sends it once', async () => {
    const first = await mount();
    let land: () => void = () => {};
    service.commit.mockImplementationOnce((intent) => new Promise((resolve) => { land = () => resolve(apply(intent)); }));
    act(() => { first.result.current.setProfile((p) => ({ ...p, college: 'Liberal Arts' })); });
    await tick(2000);
    expect(sends(), 'the autosave is in flight').toHaveLength(1);
    first.unmount();
    await drain();
    const second = await mount();
    expect(second.result.current.profile.college).toBe('Liberal Arts');
    act(() => { land(); });
    await drain();
    expect(sends(), 'nothing is sent behind it').toHaveLength(1);
    expect(rowOf(uid)).toMatchObject({ revision: 4, profile: { college: 'Liberal Arts' } });
    expect(second.result.current.saveStatus, 'a write that landed is not reported as failed').toBe('saved');
    expect(second.result.current.canRetrySync).toBe(false);
    nothingOutstanding();
    await tick(5000);
    expect(sends()).toHaveLength(1);
  });
});
