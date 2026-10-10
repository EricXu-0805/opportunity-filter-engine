import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from '@/lib/supabase';
import type { ProfileData } from '@/lib/types';

const service = vi.hoisted(() => ({
  auth: null as null | ((state: { user: { id: string } | null; isAnonymous?: boolean }) => void),
  load: vi.fn<() => Promise<LoadedProfile>>(),
  confirm: vi.fn<() => Promise<string | null>>(),
  commit: vi.fn<(intent: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>(),
  params: new URLSearchParams(), router: { push: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() },
}));
vi.mock('next/navigation', () => ({ useRouter: () => service.router, useSearchParams: () => service.params }));
vi.mock('@/lib/api', () => ({ parseGitHubProfile: vi.fn() }));
vi.mock('@/lib/match-cache', () => ({ clearMatchCache: vi.fn(() => true) }));
// Transport only. Reconciliation, the journal, owner capabilities and the
// browser's owner marker are real, and the tab that opened the sign-in link is
// a second module realm over the same storage and the same Web Locks.
vi.mock('@/lib/supabase', () => ({
  loadProfile: () => service.load(),
  getDeviceId: () => service.confirm(),
  commitProfilePatch: (intent: ProfilePatchIntent) => service.commit(intent),
  getStorageStatus: () => ({ status: 'synced', error: null }),
  onAuthChange: (callback: typeof service.auth) => { service.auth = callback; return () => { service.auth = null; }; },
}));
import { useProfileForm } from './use-profile-form';
import { DEFAULT_PROFILE } from './types';
import {
  advanceOwnerEpoch, captureOwnerToken, isOwnerTokenValid, OwnerNotReadyError, OwnerScopedLoadError, syncLocalIdentityOwner,
} from '@/lib/identity-owner';
import { resetProfileDirtyLedger } from '@/lib/profile-sync';
import { resetJournalLaneForTests } from '@/lib/profile-journal';
import { STORAGE_KEYS } from '@/lib/storage-keys';

const t = (key: string) => key;
const GUEST_ROW: ProfileData = { ...DEFAULT_PROFILE, name: 'Guest in this tab', college: 'Engineering', major: 'Physics',
  grade: 'Freshman', research_interests: 'Guest draft' };
const ACCOUNT_ROW: ProfileData = { ...DEFAULT_PROFILE, name: 'Account owner', college: 'Engineering', major: 'Computer Science',
  grade: 'Junior', research_interests: 'Account interest' };
let sequence = 0;
let guest: string;
let account: string;
let rows: Map<string, { profile: ProfileData; revision: number }>;

/** loadProfile's owner discipline: its token is taken BEFORE its own session
 *  check, which re-runs the owner sync, and a token that was not valid when
 *  the read started is refused even when that check confirmed the namespace. */
async function load(): Promise<LoadedProfile> {
  const token = captureOwnerToken();
  await syncLocalIdentityOwner(token.uid);
  if (!isOwnerTokenValid(token, token.uid)) throw new OwnerScopedLoadError(token, new OwnerNotReadyError());
  const row = token.uid ? rows.get(token.uid) : undefined;
  return row ? { source: 'cloud', profile: { ...structuredClone(row.profile) }, revision: row.revision, token }
    : { source: 'cloud-absent', profile: null, revision: 0, token };
}
/** getDeviceId: that same session check on its own. */
async function confirm(): Promise<string | null> {
  const { uid } = captureOwnerToken();
  await syncLocalIdentityOwner(uid);
  return uid;
}
async function apply(intent: ProfilePatchIntent): Promise<ProfilePatchOutcome> {
  const row = rows.get(intent.token.uid!)!;
  if (intent.expectedRevision !== row.revision) {
    return { status: 'conflict', profile: { ...structuredClone(row.profile) }, revision: row.revision };
  }
  row.profile = { ...row.profile, ...intent.patch }; row.revision += 1;
  return { status: 'saved', profile: { ...structuredClone(row.profile) }, revision: row.revision };
}
async function drain() {
  for (let pass = 0; pass < 4; pass += 1) {
    await act(async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); });
  }
}
async function tick(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); await drain();
}

/** A guest's Home with the guest's own row on it. */
async function guestHome() {
  const hook = renderHook(() => useProfileForm(t));
  act(() => { service.auth?.({ user: { id: guest }, isAnonymous: true }); }); await drain();
  expect(hook.result.current.hydrationState).toBe('ready');
  expect(hook.result.current.profile.name).toBe(GUEST_ROW.name);
  return hook;
}
/** Another tab exchanged the sign-in link, and its session is announced here
 *  while its Flow B hand-off still defers this browser's transition: the merge
 *  grant is stashed and the marker still names the guest. */
async function accountArrivesFromOtherTab() {
  localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, JSON.stringify({ token: 'grant', minted_at: Date.now() }));
  await act(async () => {
    advanceOwnerEpoch(account);
    expect(await syncLocalIdentityOwner(account), 'the transition is deferred').toBe(false);
    service.auth?.({ user: { id: account }, isAnonymous: false });
  });
  await drain();
}
/** That tab redeems the grant, claims the guest's namespace for the account
 *  and forgets the guest row's revision, as /auth/callback does. */
async function otherTabFinishes() {
  vi.resetModules();
  const owner = await import('@/lib/identity-owner');
  const sync = await import('@/lib/profile-sync');
  localStorage.removeItem(STORAGE_KEYS.MERGE_GRANT);
  owner.advanceOwnerEpoch(account);
  expect(await owner.syncLocalIdentityOwner(account, { claim: true })).toBe(true);
  expect(await sync.forgetMergedGuestRevision(owner.captureOwnerToken())).toBe(true);
}

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  service.auth = null; service.params = new URLSearchParams();
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  sequence += 1;
  guest = `other-tab-guest-${sequence}`;
  account = `other-tab-account-${sequence}`;
  rows = new Map([
    [guest, { profile: structuredClone(GUEST_ROW), revision: 1 }],
    [account, { profile: structuredClone(ACCOUNT_ROW), revision: 1 }],
  ]);
  advanceOwnerEpoch(null); advanceOwnerEpoch(guest); await syncLocalIdentityOwner(guest);
  expect(isOwnerTokenValid(captureOwnerToken(), guest)).toBe(true);
  service.load.mockReset().mockImplementation(load);
  service.confirm.mockReset().mockImplementation(confirm);
  service.commit.mockReset().mockImplementation(apply);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('Home left open while another tab signs this browser in to an account', () => {
  it('loads the account row on the first Retry once that tab has finished, and saves only what was typed here', async () => {
    const { result } = await guestHome();
    await accountArrivesFromOtherTab();
    expect(result.current.hydrationState).toBe('failed');
    expect(result.current.profile.name, 'the guest row left the screen with the guest').toBe(DEFAULT_PROFILE.name);
    act(() => { result.current.update('research_interests', 'Typed after the switch'); }); await drain();
    await otherTabFinishes();

    const reads = service.load.mock.calls.length;
    act(() => { result.current.retryProfileLoad(); }); await drain();
    expect(result.current.hydrationState, 'one Retry, not two').toBe('ready');
    expect(service.load).toHaveBeenCalledTimes(reads + 1);
    expect(result.current.profile).toMatchObject({
      name: ACCOUNT_ROW.name, major: ACCOUNT_ROW.major, research_interests: 'Typed after the switch',
    });
    expect(result.current.viewSnapshot?.token).toEqual(captureOwnerToken());
    expect(service.commit).not.toHaveBeenCalled();

    await tick(1500);
    expect(service.commit).toHaveBeenCalledOnce();
    const [intent] = service.commit.mock.calls[0];
    expect(intent.token, 'sent under the account, not the screen it was typed on').toEqual(captureOwnerToken());
    expect(intent.expectedRevision).toBe(1);
    expect(intent.patch).toEqual({ research_interests: 'Typed after the switch' });
    expect(result.current.saveStatus).toBe('saved');
    expect(rows.get(account)!.profile).toEqual({ ...ACCOUNT_ROW, research_interests: 'Typed after the switch' });
    expect(rows.get(guest)!.profile).toEqual(GUEST_ROW);
  });

  it('reads nothing and reports no failed save for an edit made during the hand-off; the next edit after it loads the account row', async () => {
    const { result } = await guestHome();
    await accountArrivesFromOtherTab();
    const reads = service.load.mock.calls.length;
    act(() => { result.current.update('research_interests', 'Typed during the hand-off'); }); await drain();
    expect(service.load, 'no read while the marker still names the guest').toHaveBeenCalledTimes(reads);
    expect(service.confirm).not.toHaveBeenCalled();
    expect(result.current.saveStatus, 'nothing was attempted, so nothing failed').not.toBe('error');
    expect(result.current.hydrationState).toBe('failed');
    expect(result.current.profile.research_interests).toBe('Typed during the hand-off');

    await otherTabFinishes();
    act(() => { result.current.update('research_interests', 'Typed once that tab was done'); }); await drain();
    expect(result.current.hydrationState).toBe('ready');
    expect(service.confirm).toHaveBeenCalledOnce();
    expect(service.load).toHaveBeenCalledTimes(reads + 1);
    expect(result.current.profile).toMatchObject({ name: ACCOUNT_ROW.name, research_interests: 'Typed once that tab was done' });
    await tick(1500);
    expect(service.commit).toHaveBeenCalledOnce();
    expect(service.commit.mock.calls[0][0].patch).toEqual({ research_interests: 'Typed once that tab was done' });
    expect(rows.get(account)!.profile).toEqual({ ...ACCOUNT_ROW, research_interests: 'Typed once that tab was done' });
  });

  it('says the account arrived from another tab while that refusal stands, and stops once the account row loads', async () => {
    const { result } = await guestHome();
    expect(result.current.signedInElsewhere).toBe(false);
    await accountArrivesFromOtherTab();
    expect(result.current.signedInElsewhere).toBe(true);
    await otherTabFinishes();
    act(() => { result.current.retryProfileLoad(); });
    expect(result.current.hydrationState).toBe('loading');
    expect(result.current.signedInElsewhere, 'not while the read runs').toBe(false);
    await drain();
    expect(result.current.hydrationState).toBe('ready');
    expect(result.current.signedInElsewhere).toBe(false);
  });

  it('keeps the plain failure for a read that failed after the switch: wording, no read on edit, and an error on edit', async () => {
    const { result } = await guestHome();
    service.load.mockImplementationOnce(async () => { throw new OwnerScopedLoadError(captureOwnerToken(), new Error('offline')); });
    await act(async () => {
      advanceOwnerEpoch(account);
      expect(await syncLocalIdentityOwner(account)).toBe(true);
      service.auth?.({ user: { id: account }, isAnonymous: false });
    });
    await drain();
    expect(result.current.hydrationState).toBe('failed');
    const reads = service.load.mock.calls.length;
    act(() => { result.current.update('research_interests', 'Typed while offline'); }); await drain();
    expect(result.current.saveStatus).toBe('error');
    expect(service.load).toHaveBeenCalledTimes(reads);
    expect(service.confirm).not.toHaveBeenCalled();
    expect(result.current.signedInElsewhere).toBe(false);
  });

  it('gives a tab first opened during the hand-off the plain wording, and its first Retry still loads the account row', async () => {
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, JSON.stringify({ token: 'grant', minted_at: Date.now() }));
    advanceOwnerEpoch(account);
    expect(await syncLocalIdentityOwner(account)).toBe(false);
    const { result } = renderHook(() => useProfileForm(t));
    act(() => { service.auth?.({ user: { id: account }, isAnonymous: false }); }); await drain();
    expect(result.current.hydrationState).toBe('failed');
    const wording = result.current.signedInElsewhere;
    await otherTabFinishes();
    act(() => { result.current.retryProfileLoad(); }); await drain();
    expect(result.current.hydrationState).toBe('ready');
    expect(result.current.profile.name).toBe(ACCOUNT_ROW.name);
    expect(service.commit).not.toHaveBeenCalled();
    expect(wording, 'this tab never showed anybody else').toBe(false);
  });
});
