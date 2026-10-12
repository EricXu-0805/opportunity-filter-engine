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
import { useProfileForm } from './use-profile-form';
import { DEFAULT_PROFILE } from './types';
import { PROFILE_REFRESH_INTERVAL_MS } from '@/lib/use-profile-refresh';
import { advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { resetProfileDirtyLedger } from '@/lib/profile-sync';
import { resetJournalLaneForTests } from '@/lib/profile-journal';

const BASE: ProfileData = { ...DEFAULT_PROFILE, name: 'Alex', home_school: 'uiuc', institution: 'UIUC',
  college: 'Engineering', major: 'Computer Science', grade: 'Junior', research_interests: 'Original research' };
const t = (key: string) => key;
// One server row per account, so an identity switch reads and writes its own.
const rows = new Map<string, { profile: ProfileData; revision: number }>();
let network = true;
let uid: string;
let sequence = 0;
function row(): LoadedProfile {
  const token = captureOwnerToken();
  const held = rows.get(token.uid ?? '');
  return held ? { source: 'cloud', profile: { ...structuredClone(held.profile) }, revision: held.revision, token }
    : { source: 'cloud-absent', profile: null, revision: 0, token };
}
function publish(owner: string, patch: Partial<ProfileData>) {
  const held = rows.get(owner)!;
  rows.set(owner, { profile: { ...held.profile, ...patch }, revision: held.revision + 1 });
}
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  // A browser that is offline never reaches the server at all.
  if (!network) return { status: 'transport-error', message: 'Failed to fetch' };
  const held = rows.get(intent.token.uid ?? '');
  if (!held) return { status: 'missing', reason: 'absent' };
  if (intent.expectedRevision !== held.revision) return { status: 'conflict', profile: { ...structuredClone(held.profile) }, revision: held.revision };
  rows.set(intent.token.uid!, { profile: { ...held.profile, ...intent.patch }, revision: held.revision + 1 });
  return { status: 'saved', profile: { ...structuredClone(rows.get(intent.token.uid!)!.profile) }, revision: held.revision + 1 };
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
  expect(hook.result.current.profile.major).toBe(BASE.major);
  return hook;
}
function goOffline() {
  network = false;
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
  act(() => { window.dispatchEvent(new Event('offline')); });
}
function setVisibility(value: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value });
}
/** The browser is back: `online`, and the tab coming back to the front with it. */
async function reconnect(events: readonly ('online' | 'visibilitychange')[] = ['online', 'visibilitychange']) {
  network = true;
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
  act(() => {
    for (const event of events) {
      if (event === 'online') window.dispatchEvent(new Event('online'));
      else document.dispatchEvent(new Event('visibilitychange'));
    }
  });
  await drain();
}
/** Edits a field while offline and lets the autosave fail on the network. */
async function failOffline(result: { current: ReturnType<typeof useProfileForm> }, text: string) {
  goOffline();
  const before = service.commit.mock.calls.length;
  act(() => { result.current.update('research_interests', text); }); await tick(1500);
  expect(service.commit).toHaveBeenCalledTimes(before + 1);
  expect(result.current.saveStatus).toBe('cloud-failed');
  expect(result.current.canRetrySync).toBe(true);
}
beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.auth = null; service.params = new URLSearchParams();
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  uid = `home-reconnect-${++sequence}`;
  advanceOwnerEpoch(null); advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid);
  expect(isOwnerTokenValid(captureOwnerToken(), uid)).toBe(true);
  rows.clear(); rows.set(uid, { profile: structuredClone(BASE), revision: 1 }); network = true;
  service.load.mockReset().mockImplementation(async () => row());
  service.commit.mockReset().mockImplementation(apply);
  setVisibility('visible');
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('Home resends an offline edit when the browser reconnects', () => {
  it('sends the failed edit once on reconnect, through the revision-checked save, and reports it saved', async () => {
    const { result } = await start();
    await failOffline(result, 'Typed on a train');
    expect(rows.get(uid)).toMatchObject({ revision: 1, profile: { research_interests: 'Original research' } });

    // `online` and the tab returning to the front arrive together: one resend.
    await reconnect();
    expect(service.commit).toHaveBeenCalledTimes(2);
    const resend = service.commit.mock.calls[1][0];
    expect(resend.expectedRevision).toBe(1);
    expect(resend.patch).toEqual({ research_interests: 'Typed on a train' });
    expect(resend.token.uid).toBe(uid);
    expect(rows.get(uid)).toMatchObject({ revision: 2, profile: { ...BASE, research_interests: 'Typed on a train' } });
    expect(result.current.saveStatus).toBe('saved');
    expect(result.current.canRetrySync).toBe(false);

    // Nothing is owed any more, so later reconnects and reads send nothing.
    await reconnect();
    await tick(PROFILE_REFRESH_INTERVAL_MS + 2000);
    expect(service.commit).toHaveBeenCalledTimes(2);
  });

  it('resends when only the tab returning to the front says the browser is online again', async () => {
    const { result } = await start();
    await failOffline(result, 'Typed with the tab in the background');
    setVisibility('hidden');
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    await drain();
    expect(service.commit).toHaveBeenCalledTimes(1);

    setVisibility('visible');
    await reconnect(['visibilitychange']);
    expect(service.commit).toHaveBeenCalledTimes(2);
    expect(service.commit.mock.calls[1][0].patch).toEqual({ research_interests: 'Typed with the tab in the background' });
    expect(result.current.saveStatus).toBe('saved');
  });

  it('makes one resend per reconnect, not a retry loop, when the network is still failing', async () => {
    const { result } = await start();
    await failOffline(result, 'Typed on a flaky connection');
    // The browser says it is online, but requests still fail.
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
    act(() => { window.dispatchEvent(new Event('online')); document.dispatchEvent(new Event('visibilitychange')); });
    await drain();
    expect(service.commit).toHaveBeenCalledTimes(2);
    expect(result.current.saveStatus).toBe('cloud-failed');
    expect(result.current.canRetrySync).toBe(true);
    await tick(PROFILE_REFRESH_INTERVAL_MS * 2 + 2000);
    expect(service.commit).toHaveBeenCalledTimes(2);

    // The next real reconnect is a new chance, and it lands.
    await reconnect(['online']);
    expect(service.commit).toHaveBeenCalledTimes(3);
    expect(rows.get(uid)?.profile.research_interests).toBe('Typed on a flaky connection');
    expect(result.current.saveStatus).toBe('saved');
  });

  it('resends once the profile check is back, when the last check had failed by the time the browser reconnected', async () => {
    // Wi-Fi with no internet behind it: the browser says it is online, and
    // every request fails, the profile check as well as the save.
    service.load.mockImplementation(async () => {
      if (!network) throw new Error('Failed to fetch');
      return row();
    });
    const { result } = await start();
    network = false;
    act(() => { result.current.update('research_interests', 'Typed on the train'); }); await tick(1500);
    expect(result.current.saveStatus).toBe('cloud-failed');
    // The student switches tabs and back: the resend and the check both fail.
    setVisibility('hidden');
    act(() => { document.dispatchEvent(new Event('visibilitychange')); }); await drain();
    setVisibility('visible');
    act(() => { document.dispatchEvent(new Event('visibilitychange')); }); await drain();
    expect(result.current.profileRefreshStatus).toBe('failed');
    expect(result.current.saveStatus).toBe('cloud-failed');
    const before = service.commit.mock.calls.length;

    // The Wi-Fi drops and cellular connects.
    goOffline();
    await reconnect(['online']);
    expect(result.current.profileRefreshStatus).toBe('ready');
    expect(service.commit).toHaveBeenCalledTimes(before + 1);
    expect(service.commit.mock.calls[before][0]).toMatchObject({
      expectedRevision: 1, patch: { research_interests: 'Typed on the train' },
    });
    expect(rows.get(uid)).toMatchObject({ revision: 2, profile: { research_interests: 'Typed on the train' } });
    expect(result.current.saveStatus).toBe('saved');
    expect(result.current.canRetrySync).toBe(false);
  });

  it('makes one more attempt when the connection comes back again while a failing resend is in flight', async () => {
    const { result } = await start();
    await failOffline(result, 'Typed on a flapping connection');
    let failInFlight!: () => void;
    service.commit.mockImplementationOnce(() => new Promise((resolve) => {
      failInFlight = () => resolve({ status: 'transport-error', message: 'Failed to fetch' });
    }));
    await reconnect(['online']);
    expect(service.commit).toHaveBeenCalledTimes(2);

    // The connection drops and returns before that request has an answer.
    goOffline();
    await reconnect(['online']);
    expect(service.commit, 'nothing is sent beside the request in flight').toHaveBeenCalledTimes(2);
    await act(async () => { failInFlight(); });
    await drain();
    expect(service.commit).toHaveBeenCalledTimes(3);
    expect(service.commit.mock.calls[2][0]).toMatchObject({
      expectedRevision: 1, patch: { research_interests: 'Typed on a flapping connection' },
    });
    expect(rows.get(uid)).toMatchObject({ revision: 2, profile: { research_interests: 'Typed on a flapping connection' } });
    expect(result.current.saveStatus).toBe('saved');

    await tick(PROFILE_REFRESH_INTERVAL_MS + 2000);
    expect(service.commit).toHaveBeenCalledTimes(3);
  });

  it('still reports a conflict, and never overwrites, when another device saved the field first', async () => {
    const { result } = await start();
    await failOffline(result, 'Typed offline on the laptop');
    // The phone's save reaches the server just ahead of the resend — after
    // anything this tab could have read on reconnecting — so only the
    // revision check on the resend itself can catch it.
    service.commit.mockImplementationOnce(async (intent) => {
      publish(uid, { research_interests: 'Saved on the phone meanwhile' });
      return apply(intent);
    });

    await reconnect();
    const resend = service.commit.mock.calls[1]?.[0];
    expect(resend, 'the reconnect resends the edit').toBeDefined();
    expect(resend.expectedRevision).toBe(1);
    expect(resend.patch).toEqual({ research_interests: 'Typed offline on the laptop' });
    expect(result.current.saveStatus).toBe('conflict');
    expect(result.current.conflicts).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: 'research_interests', remote: 'Saved on the phone meanwhile' }),
    ]));
    expect(result.current.profile.research_interests).toBe('Typed offline on the laptop');
    await tick(PROFILE_REFRESH_INTERVAL_MS + 2000);
    await reconnect();
    expect(rows.get(uid)).toMatchObject({ revision: 2, profile: { research_interests: 'Saved on the phone meanwhile' } });
    expect(service.commit.mock.calls.slice(2).every(([intent]) => !('research_interests' in intent.patch)),
      'the locked field is never sent again on its own').toBe(true);
  });

  it('resends only the current identity\'s own edit after the account changed', async () => {
    const { result } = await start();
    await failOffline(result, 'First account typed offline');
    const first = uid;

    const second = `home-reconnect-other-${sequence}`;
    rows.set(second, { profile: { ...structuredClone(BASE), name: 'Sam' }, revision: 4 });
    await act(async () => { advanceOwnerEpoch(second); await syncLocalIdentityOwner(second); });
    act(() => { service.auth?.({ user: { id: second } }); }); await drain();
    expect(result.current.profile.name).toBe('Sam');
    expect(result.current.saveStatus).not.toBe('cloud-failed');

    // The second account's own offline edit fails too.
    goOffline();
    act(() => { result.current.update('major', 'Physics'); }); await tick(1500);
    expect(result.current.saveStatus).toBe('cloud-failed');
    const before = service.commit.mock.calls.length;

    await reconnect();
    const sent = service.commit.mock.calls.slice(before).map(([intent]) => intent);
    expect(sent).toHaveLength(1);
    expect(sent[0].token.uid).toBe(second);
    expect(sent[0].expectedRevision).toBe(4);
    expect(sent[0].patch).toEqual({ major: 'Physics' });
    expect(service.commit.mock.calls.every(([intent]) => intent.token.uid === first
      || !('research_interests' in intent.patch)), 'the first account\'s text never goes out as the second').toBe(true);
    expect(rows.get(first)).toMatchObject({ revision: 1, profile: { research_interests: 'Original research' } });
    expect(rows.get(second)).toMatchObject({ revision: 5, profile: { name: 'Sam', major: 'Physics' } });
  });
});
