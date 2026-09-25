import { useState } from 'react';
import { useProfileAction, profileActionKey } from './use-profile-action';
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ProfileData } from './types';

const mocks = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://profile-refresh.test';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-only';
  return { getSession: vi.fn(), signIn: vi.fn(), read: vi.fn(), from: vi.fn(), rpc: vi.fn(),
    selects: [] as { signal?: AbortSignal }[] };
});
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({
  auth: { getSession: mocks.getSession, signInAnonymously: mocks.signIn,
    onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })) },
  from: mocks.from, rpc: mocks.rpc,
}) }));
import { PROFILE_REFRESH_DEADLINE_MS, PROFILE_REFRESH_INTERVAL_MS, useProfileRefresh, type ProfileActionReceipt } from './use-profile-refresh';
import { advanceOwnerEpoch, captureOwnerToken, enterLocalOnlyMode, isOwnerTokenValid, PRIVATE_STORAGE_LOCK,
  readUserScopedRaw, syncLocalIdentityOwner } from './identity-owner';
import { hydrateProfile, readProfileSyncEnvelope, recordProfileIntent, resetProfileDirtyLedger, stageProfilePatch } from './profile-sync';
import { loadProfile } from './supabase';
import { readOutstandingOps, resetJournalLaneForTests } from './profile-journal';
import { STORAGE_KEYS } from './storage-keys';

const OWNER = 'refresh-owner';
const BASE: ProfileData = { institution: 'UIUC', home_school: 'uiuc', college: 'Engineering', major: 'CS',
  grade: 'Junior', is_international: false, research_interests: 'robotics', skills: [], search_weight: 50 };
function deferred<T>() {
  let resolve!: (value: T) => void; let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const session = (uid = captureOwnerToken().uid) => ({ data: { session: uid ? { user: { id: uid } } : null } });
const row = (profile: ProfileData = BASE, revision = 1) => ({ data: { profile_data: profile, revision }, error: null });
const mirror = () => JSON.parse(readUserScopedRaw(STORAGE_KEYS.PROFILE) ?? 'null');
// Drain controlled promise/React work, without advancing the deadline or polling
// against a wider timeout. Pending auth/query promises are released explicitly.
async function drain() { await act(async () => { for (let i = 0; i < 35; i += 1) await Promise.resolve(); }); }
async function refresh(result: { current: ReturnType<typeof useProfileRefresh> }) {
  let outcome = false;
  await act(async () => { outcome = await result.current.refresh(); });
  return outcome;
}
function event(type: string) { act(() => { window.dispatchEvent(new Event(type)); }); }
async function moveOwner(uid: string) {
  await act(async () => { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); });
  await drain();
}

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  mocks.getSession.mockReset().mockImplementation(async () => session());
  mocks.signIn.mockReset(); mocks.read.mockReset().mockResolvedValue(row()); mocks.rpc.mockReset(); mocks.selects = [];
  mocks.from.mockReset().mockImplementation((table: string) => {
    expect(table).toBe('profiles');
    return { select: (columns: string) => {
      expect(columns).toBe('profile_data, revision');
      return { eq: (key: string, uid: string) => {
        expect(key).toBe('id'); expect(uid).toBe(captureOwnerToken().uid);
        const selected: { signal?: AbortSignal } = {};
        const query = {
          abortSignal: (signal: AbortSignal) => { selected.signal = signal; return query; },
          maybeSingle: () => {
            mocks.selects.push(selected);
            return Promise.resolve(mocks.read()); // Deliberately ignore abort at transport level.
          },
        };
        return query;
      } };
    } };
  });
  resetProfileDirtyLedger(); resetJournalLaneForTests();
  advanceOwnerEpoch(null); advanceOwnerEpoch(OWNER); await syncLocalIdentityOwner(OWNER);
  expect(isOwnerTokenValid(captureOwnerToken(), OWNER)).toBe(true);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); });

describe('owner-scoped read-only cloud refresh', () => {
  it('projects legacy skills identically into the action receipt and accepted render, without changing the CAS baseline', async () => {
    const legacy = { ...BASE, skills: ['Python'] } as unknown as ProfileData;
    mocks.read.mockResolvedValue(row(legacy, 7));
    const accepted = vi.fn(); const execute = vi.fn();
    const { result } = renderHook(() => {
      const [profile, setProfile] = useState<ProfileData | null>(null);
      const refresh = useProfileRefresh(true, (loaded) => { accepted(loaded); setProfile(loaded.profile); });
      const action = useProfileAction<string>({ isOpen: true, profile, profileAvailable: !!profile, scopeKey: 'legacy-target', editRevision: 0,
        refresh, readiness: refresh.status === 'checking' ? 'waiting' : refresh.status === 'ready' ? 'ready' : 'blocked', execute });
      return { profile, refresh, action };
    });
    await drain(); expect(result.current.profile?.skills).toEqual([{ name: 'Python', level: 'beginner' }]);
    act(() => result.current.action.request('generate')); await drain();
    expect(execute).toHaveBeenCalledExactlyOnceWith('generate'); expect(result.current.action.busy).toBe(false);
    const value: { receipt: ProfileActionReceipt | null } = { receipt: null };
    await act(async () => { value.receipt = await result.current.refresh.checkForAction!(); });
    expect(profileActionKey(value.receipt?.profile ?? null)).toBe(profileActionKey(result.current.profile));
    expect(accepted).toHaveBeenLastCalledWith(expect.objectContaining({ baseProfile: legacy, revision: 7, token: captureOwnerToken() }));
    expect(mirror()?.skills).toEqual(['Python']); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('returns and accepts the actual reconciled candidate with revision, frozen source and no writes', async () => {
    await hydrateProfile();
    expect(recordProfileIntent({ ...BASE, major: 'Unsent draft' }, ['major'], captureOwnerToken())).toBe(true);
    mocks.read.mockResolvedValue(row({ ...BASE, grade: 'Senior' }, 2));
    const accepted = vi.fn(); const { result } = renderHook(() => useProfileRefresh(true, accepted)); await drain();
    let receipt: Awaited<ReturnType<NonNullable<typeof result.current.checkForAction>>> = null;
    await act(async () => { receipt = await result.current.checkForAction!(); });
    expect(receipt).toMatchObject({ revision: 2, source: 'cloud', profile: { major: 'Unsent draft', grade: 'Senior' } });
    expect(accepted).toHaveBeenLastCalledWith(expect.objectContaining({ revision: 2,
      profile: expect.objectContaining({ major: 'Unsent draft', grade: 'Senior' }),
      baseProfile: expect.objectContaining({ major: 'CS', grade: 'Senior' }) }));
    expect(Object.isFrozen(receipt)).toBe(true); expect(Object.isFrozen(receipt!.profile)).toBe(true);
    expect(mocks.rpc).not.toHaveBeenCalled();
  });
  it('shares one in-flight action check with refresh but a later action reads again', async () => {
    const query = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(query.promise);
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    const first = result.current.checkForAction!(); const second = result.current.checkForAction!();
    expect(first).toBe(second); const refreshed = result.current.refresh();
    query.resolve(row()); await drain(); const receipt = await first;
    expect(await refreshed).toBe(true); expect(receipt?.source).toBe('cloud'); expect(mocks.selects).toHaveLength(1);
    const next: { value: ProfileActionReceipt | null } = { value: null };
    await act(async () => { next.value = await result.current.checkForAction!(); });
    expect(next.value?.checkId).toBeGreaterThan(receipt!.checkId); expect(mocks.selects).toHaveLength(2);
  });

  it('waits while disabled, then reconciles a fresh row without a cloud mutation', async () => {
    const { result, rerender } = renderHook(({ enabled }) => useProfileRefresh(enabled), { initialProps: { enabled: false } });
    await drain(); expect(mocks.getSession).not.toHaveBeenCalled(); expect(await refresh(result)).toBe(false);
    rerender({ enabled: true }); await drain();
    expect(result.current.status).toBe('ready'); expect(mirror()).toEqual(BASE);
    expect(readProfileSyncEnvelope()?.confirmed?.revision).toBe(1);
    expect(mocks.selects).toHaveLength(1); expect(mocks.selects[0].signal).toBeInstanceOf(AbortSignal);
    expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('does not expose an old ready receipt for even one render when re-enabled', async () => {
    const seen: string[] = [];
    const { result, rerender } = renderHook(({ enabled }) => {
      const value = useProfileRefresh(enabled); seen.push(value.status); return value;
    }, { initialProps: { enabled: true } });
    await drain(); expect(result.current.status).toBe('ready');
    rerender({ enabled: false });
    const query = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(query.promise);
    seen.length = 0; rerender({ enabled: true }); await drain();
    expect(seen).not.toContain('ready'); expect(result.current.status).toBe('checking');
    query.resolve(row()); await drain(); expect(result.current.status).toBe('ready');
  });

  it('settles the first unresolved owner after ensureAnonSession establishes its namespace', async () => {
    advanceOwnerEpoch(null); localStorage.clear();
    mocks.getSession.mockResolvedValue(session(OWNER));
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    expect(captureOwnerToken().uid).toBe(OWNER); expect(result.current.status).toBe('ready');
    expect(mirror()).toEqual(BASE); expect(mocks.selects.length).toBeLessThanOrEqual(2);
    expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('rejects already cancelled reads before auth, query, or local reconciliation', async () => {
    const controller = new AbortController(); controller.abort('private cancellation reason');
    for (const read of [loadProfile, hydrateProfile]) {
      await expect(read(controller.signal)).rejects.toMatchObject({ name: 'AbortError', message: 'Profile read cancelled' });
    }
    expect(mocks.getSession).not.toHaveBeenCalled(); expect(mocks.selects).toHaveLength(0);
    expect(readProfileSyncEnvelope()).toBeNull(); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('deduplicates an event storm in flight, but each later focus/visible/online event reads again', async () => {
    const pending = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    let one!: Promise<boolean>; let two!: Promise<boolean>;
    act(() => { one = result.current.refresh(); two = result.current.refresh(); });
    expect(one).toBe(two); event('focus'); event('online');
    act(() => { document.dispatchEvent(new Event('visibilitychange')); }); await drain();
    expect(mocks.selects).toHaveLength(1); pending.resolve(row()); await drain(); expect(await one).toBe(true);
    event('focus'); await drain(); expect(mocks.selects).toHaveLength(2);
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    act(() => { document.dispatchEvent(new Event('visibilitychange')); }); await drain(); expect(mocks.selects).toHaveLength(2);
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    act(() => { document.dispatchEvent(new Event('visibilitychange')); }); await drain(); expect(mocks.selects).toHaveLength(3);
    event('online'); await drain(); expect(mocks.selects).toHaveLength(4); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('keeps the previous mirror on failure, then explicitly retries without leaking server error text', async () => {
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    mocks.read.mockResolvedValueOnce({ data: null, error: { message: 'PRIVATE server payload' } });
    expect(await refresh(result)).toBe(false); expect(result.current.status).toBe('failed'); expect(mirror()).toEqual(BASE);
    expect(Object.keys(result.current).sort()).toEqual(['checkForAction', 'refresh', 'status']);
    mocks.read.mockResolvedValueOnce(row({ ...BASE, major: 'Physics' }, 2));
    expect(await refresh(result)).toBe(true); expect(result.current.status).toBe('ready'); expect(mirror().major).toBe('Physics');
    expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('settles a hung auth lookup at the deadline; retry does not wait for or send a query from its late receipt', async () => {
    const auth = deferred<ReturnType<typeof session>>(); mocks.getSession.mockReturnValueOnce(auth.promise);
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    expect(mocks.selects).toHaveLength(0);
    await act(async () => { await vi.advanceTimersByTimeAsync(PROFILE_REFRESH_DEADLINE_MS); });
    expect(result.current.status).toBe('failed');
    expect(await refresh(result)).toBe(true); expect(mocks.selects).toHaveLength(1);
    auth.resolve(session()); await drain(); expect(mocks.selects).toHaveLength(1); expect(mirror()).toEqual(BASE);
  });

  it('retires an uncooperative SELECT and its late row; retry is a fresh request', async () => {
    const query = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(query.promise);
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    await act(async () => { await vi.advanceTimersByTimeAsync(PROFILE_REFRESH_DEADLINE_MS); });
    expect(result.current.status).toBe('failed'); expect(mocks.selects[0].signal?.aborted).toBe(true);
    mocks.read.mockResolvedValueOnce(row({ ...BASE, major: 'Fresh' }, 2));
    expect(await refresh(result)).toBe(true);
    query.resolve(row({ ...BASE, major: 'LATE PRIVATE ROW' }, 99)); await drain();
    expect(mirror().major).toBe('Fresh'); expect(readProfileSyncEnvelope()?.confirmed?.revision).toBe(2);
    expect(mocks.selects).toHaveLength(2); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('does not let an expired attempt mark a synchronously started retry as failed', async () => {
    const old = deferred<ReturnType<typeof row>>(); const next = deferred<ReturnType<typeof row>>();
    mocks.read.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    act(() => {
      vi.advanceTimersByTime(PROFILE_REFRESH_DEADLINE_MS);
      window.dispatchEvent(new Event('focus')); // Before the abort rejection microtask runs.
    });
    await drain(); expect(result.current.status).toBe('checking'); expect(mocks.selects).toHaveLength(2);
    next.resolve(row()); await drain(); expect(result.current.status).toBe('ready');
    old.reject(new Error('late rejection')); await drain(); expect(result.current.status).toBe('ready');
  });

  it('does not inherit an unrelated hung legacy loadProfile dedup entry', async () => {
    const held = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(held.promise);
    const legacy = loadProfile(); await drain(); expect(mocks.selects).toHaveLength(1);
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    expect(result.current.status).toBe('ready'); expect(mocks.selects).toHaveLength(2);
    held.resolve(row({ ...BASE, major: 'Legacy receipt' })); await legacy;
    expect(mirror()).toEqual(BASE); // loadProfile itself never mirrors.
  });

  it('cancels while reconciliation waits for a lock and never publishes after that lock is released', async () => {
    const query = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(query.promise);
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    const gate = deferred<void>();
    const lock = navigator.locks.request(PRIVATE_STORAGE_LOCK, { mode: 'exclusive' }, () => gate.promise);
    query.resolve(row({ ...BASE, major: 'CANCELLED UNDER LOCK' })); await drain();
    expect(mirror()).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(PROFILE_REFRESH_DEADLINE_MS); });
    expect(result.current.status).toBe('failed');
    gate.resolve(); await lock; await drain(); expect(mirror()).toBeNull(); expect(readProfileSyncEnvelope()).toBeNull();
    expect(await refresh(result)).toBe(true); expect(mirror()).toEqual(BASE);
  });

  it.each(['different-owner', 'same-uid-new-epoch'] as const)('retires the old attempt on %s and rejects its late success', async (mode) => {
    const query = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(query.promise);
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    mocks.read.mockResolvedValue(row({ ...BASE, major: 'Current capability' }, 2));
    if (mode === 'same-uid-new-epoch') act(() => { advanceOwnerEpoch(null); });
    await moveOwner(mode === 'different-owner' ? 'other-refresh-owner' : OWNER);
    expect(mocks.selects[0].signal?.aborted).toBe(true); expect(result.current.status).toBe('ready');
    query.resolve(row({ ...BASE, major: 'Old capability' }, 99)); await drain();
    expect(result.current.status).toBe('ready'); expect(mirror().major).toBe('Current capability'); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it.each(['unmount', 'disable'] as const)('aborts on %s without a late mirror update or future event read', async (mode) => {
    const query = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(query.promise);
    const { result, unmount, rerender } = renderHook(({ enabled }) => useProfileRefresh(enabled), { initialProps: { enabled: true } });
    await drain();
    if (mode === 'unmount') unmount(); else rerender({ enabled: false });
    expect(mocks.selects[0].signal?.aborted).toBe(true);
    query.resolve(row({ ...BASE, major: 'Gone screen' })); await drain(); event('focus'); event('online'); await drain();
    expect(mirror()).toBeNull(); expect(mocks.selects).toHaveLength(1); expect(await result.current.refresh()).toBe(false);
  });

  it('reconciles an unrelated cloud update while preserving an unsent journal operation, without flushing it', async () => {
    await hydrateProfile();
    expect(recordProfileIntent({ ...BASE, major: 'Local draft' }, ['major'], captureOwnerToken())).toBe(true);
    const before = readOutstandingOps();
    mocks.read.mockResolvedValue(row({ ...BASE, grade: 'Senior' }, 2));
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    expect(result.current.status).toBe('ready'); expect(mirror()).toMatchObject({ major: 'Local draft', grade: 'Senior' });
    expect(readOutstandingOps()).toEqual(before); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('exposes a same-field cloud conflict without choosing a side or sending local edits', async () => {
    await hydrateProfile();
    expect(recordProfileIntent({ ...BASE, major: 'Local draft' }, ['major'], captureOwnerToken())).toBe(true);
    mocks.rpc.mockResolvedValueOnce({ data: null, error: { message: 'offline' } });
    await stageProfilePatch({ ...BASE, major: 'Local draft' }, ['major'], captureOwnerToken());
    expect(readProfileSyncEnvelope()?.pending).not.toBeNull();
    mocks.rpc.mockClear();
    mocks.read.mockResolvedValue(row({ ...BASE, major: 'Other device' }, 2));
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    expect(result.current.status).toBe('conflict'); expect(await refresh(result)).toBe(false);
    const journal = readOutstandingOps(); expect(journal.ok && journal.value.length).toBeGreaterThan(0);
    expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('exposes failed local reconciliation instead of claiming the new row is ready', async () => {
    await hydrateProfile();
    const previous = mirror(); const originalSet = localStorage.setItem.bind(localStorage);
    vi.spyOn(localStorage, 'setItem').mockImplementation((key, value) => {
      if (key.includes(STORAGE_KEYS.PROFILE_SYNC)) throw new Error('quota');
      originalSet(key, value);
    });
    mocks.read.mockResolvedValue(row({ ...BASE, major: 'Unrecorded revision' }, 2));
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    expect(result.current.status).toBe('failed'); expect(mirror()).toEqual(previous); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('reports an explicitly established local-only realm without claiming cloud freshness', async () => {
    advanceOwnerEpoch(null); localStorage.clear(); expect(enterLocalOnlyMode()).toBe(true);
    mocks.getSession.mockResolvedValue({ data: { session: null } });
    mocks.signIn.mockResolvedValue({ data: { session: null }, error: { message: 'offline' } });
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    expect(result.current.status).toBe('local-only'); expect(await refresh(result)).toBe(true);
    expect(mocks.selects).toHaveLength(0); expect(mocks.rpc).not.toHaveBeenCalled();
  });
});


describe('continuous foreground profile checks', () => {
  const interval = PROFILE_REFRESH_INTERVAL_MS;
  async function tick(milliseconds: number) {
    await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
    await drain();
  }
  function visibility(value: 'hidden' | 'visible') {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value });
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
  }
  function connectivity(value: boolean) {
    Object.defineProperty(navigator, 'onLine', { configurable: true, value });
    event(value ? 'online' : 'offline');
  }

  it('uses one timer from read completion, preserving ready throughout an unchanged automatic check', async () => {
    const initial = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(initial.promise);
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    await tick(5000); initial.resolve(row()); await drain();
    expect(result.current.status).toBe('ready');
    await tick(interval - 1); expect(mocks.selects).toHaveLength(1);
    const automatic = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(automatic.promise);
    await tick(1); expect(mocks.selects).toHaveLength(2); expect(result.current.status).toBe('ready');
    event('focus'); event('online'); await drain(); expect(mocks.selects).toHaveLength(2);
    await tick(5000); expect(result.current.status).toBe('ready');
    automatic.resolve(row()); await drain();
    await tick(interval - 1); expect(mocks.selects).toHaveLength(2);
    await tick(1); expect(mocks.selects).toHaveLength(3); expect(result.current.status).toBe('ready');
    expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it.each(['refresh', 'checkForAction'] as const)('promotes the in-flight automatic read for explicit %s without returning old readiness', async (method) => {
    const accepted = vi.fn(); const { result } = renderHook(() => useProfileRefresh(true, accepted)); await drain();
    const automatic = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(automatic.promise);
    await tick(interval); expect(mocks.selects).toHaveLength(2); expect(result.current.status).toBe('ready');
    let outcome!: Promise<boolean | ProfileActionReceipt | null>; let settled = false;
    act(() => { outcome = result.current[method]!(); void outcome.then(() => { settled = true; }); });
    await drain(); expect(result.current.status).toBe('checking'); expect(settled).toBe(false);
    const shared = result.current.checkForAction!(); expect(mocks.selects).toHaveLength(2);
    automatic.resolve(row({ ...BASE, major: 'Latest checked' }, 2)); await drain();
    expect((await shared)?.profile?.major).toBe('Latest checked'); expect(settled).toBe(true);
    expect(await outcome).toEqual(method === 'refresh' ? true : await shared);
    expect(accepted).toHaveBeenCalledTimes(2); expect(result.current.status).toBe('ready');
    expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it.each(['hidden', 'offline'] as const)('suspends the timer and focus reads while %s, then checks immediately on return', async (mode) => {
    const { result } = renderHook(() => useProfileRefresh(true)); await drain(); await tick(interval - 1);
    if (mode === 'hidden') visibility('hidden'); else connectivity(false);
    event('focus'); await tick(interval * 2); expect(mocks.selects).toHaveLength(1);
    expect(result.current.status).toBe('ready');
    if (mode === 'hidden') visibility('visible'); else connectivity(true);
    await drain(); expect(mocks.selects).toHaveLength(2);
    await tick(interval - 1); expect(mocks.selects).toHaveLength(2);
    await tick(1); expect(mocks.selects).toHaveLength(3);
  });

  it.each(['focus', 'visible', 'online'] as const)('keeps an already usable state quiet during a held %s event read', async (trigger) => {
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    const held = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(held.promise);
    if (trigger === 'visible') { visibility('hidden'); visibility('visible'); }
    else if (trigger === 'online') { connectivity(false); connectivity(true); }
    else event('focus');
    await drain(); expect(mocks.selects).toHaveLength(2); expect(result.current.status).toBe('ready');
    held.resolve(row()); await drain(); expect(result.current.status).toBe('ready');
  });

  it.each(['hidden', 'offline'] as const)('finishes an already active read while %s without scheduling another until resume', async (mode) => {
    const accepted = vi.fn(); const { result } = renderHook(() => useProfileRefresh(true, accepted)); await drain();
    const held = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(held.promise);
    await tick(interval);
    if (mode === 'hidden') visibility('hidden'); else connectivity(false);
    expect(mocks.selects[1].signal?.aborted).toBe(false); expect(result.current.status).toBe('ready');
    held.resolve(row({ ...BASE, major: 'Already requested' }, 2)); await drain();
    expect(accepted).toHaveBeenCalledTimes(2); expect(mirror().major).toBe('Already requested');
    await tick(interval * 2); expect(mocks.selects).toHaveLength(2);
    if (mode === 'hidden') visibility('visible'); else connectivity(true);
    await drain(); expect(mocks.selects).toHaveLength(3);
  });

  it('restarts the interval after an explicit read instead of retaining the previous automatic deadline', async () => {
    const { result } = renderHook(() => useProfileRefresh(true)); await drain(); await tick(30_000);
    expect(await refresh(result)).toBe(true); expect(mocks.selects).toHaveLength(2);
    await tick(30_000); expect(mocks.selects).toHaveLength(2);
    await tick(30_000); expect(mocks.selects).toHaveLength(3);
  });

  it('retires a held automatic read across a same-uid persistent generation change and accepts only the new generation', async () => {
    const accepted = vi.fn(); const { result } = renderHook(() => useProfileRefresh(true, accepted)); await drain();
    const origin = captureOwnerToken(); const held = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(held.promise);
    await tick(interval);
    const marker = JSON.parse(localStorage.getItem('ofe_local_identity_owner')!);
    mocks.read.mockResolvedValue(row({ ...BASE, major: 'New generation' }, 2));
    await act(async () => {
      localStorage.setItem('ofe_local_identity_owner', JSON.stringify({ ...marker, generation: marker.generation + 1, phase: 'switching' }));
      await syncLocalIdentityOwner(origin.uid!);
      // Another tab's marker transition delivers a native storage event;
      // jsdom setItem in this same document does not dispatch one.
      window.dispatchEvent(new StorageEvent('storage', { key: 'ofe_local_identity_owner' }));
    }); await drain();
    expect(captureOwnerToken()).toMatchObject({ uid: origin.uid, epoch: origin.epoch, generation: origin.generation + 1 });
    expect(mocks.selects[1].signal?.aborted).toBe(true); expect(result.current.status).toBe('ready');
    held.resolve(row({ ...BASE, major: 'Retired generation' }, 99)); await drain();
    expect(mirror().major).toBe('New generation'); expect(accepted).toHaveBeenCalledTimes(2);
    expect(accepted).toHaveBeenLastCalledWith(expect.objectContaining({ token: captureOwnerToken() }));
    await tick(interval); expect(mocks.selects).toHaveLength(4); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it.each(['disable', 'unmount'] as const)('removes the completed-read timer on %s', async (mode) => {
    const { rerender, unmount } = renderHook(({ enabled }) => useProfileRefresh(enabled), { initialProps: { enabled: true } });
    await drain(); await tick(interval - 1);
    if (mode === 'disable') rerender({ enabled: false }); else unmount();
    await tick(interval * 2); event('focus'); event('online'); await drain();
    expect(mocks.selects).toHaveLength(1); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('retires the previous owner timer and starts the next interval only after the new owner read completes', async () => {
    const { result } = renderHook(() => useProfileRefresh(true)); await drain(); await tick(30_000);
    const current = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(current.promise);
    await moveOwner('foreground-owner-b'); expect(mocks.selects).toHaveLength(2);
    await tick(5000); current.resolve(row({ ...BASE, major: 'Owner B' }, 2)); await drain();
    await tick(25_000); expect(mocks.selects).toHaveLength(2); expect(result.current.status).toBe('ready');
    await tick(35_000); expect(mocks.selects).toHaveLength(3); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('withdraws ready on automatic failure, keeps the mirror, and retries after the next completed-read interval', async () => {
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    mocks.read.mockResolvedValueOnce({ data: null, error: { message: 'PRIVATE failure' } });
    await tick(interval); expect(result.current.status).toBe('failed'); expect(mirror()).toEqual(BASE);
    mocks.read.mockResolvedValueOnce(row({ ...BASE, major: 'Recovered' }, 2));
    await tick(interval); expect(result.current.status).toBe('ready'); expect(mirror().major).toBe('Recovered');
    expect(mocks.selects).toHaveLength(3); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('retains the deadline for background reads and rejects their late content before the next periodic retry', async () => {
    const accepted = vi.fn(); const { result } = renderHook(() => useProfileRefresh(true, accepted)); await drain();
    const old = deferred<ReturnType<typeof row>>(); mocks.read.mockReturnValueOnce(old.promise);
    await tick(interval); expect(result.current.status).toBe('ready');
    await tick(PROFILE_REFRESH_DEADLINE_MS); expect(result.current.status).toBe('failed');
    expect(mocks.selects[1].signal?.aborted).toBe(true);
    old.resolve(row({ ...BASE, major: 'Retired automatic row' }, 99)); await drain();
    expect(accepted).toHaveBeenCalledTimes(1); expect(mirror()).toEqual(BASE);
    await tick(interval - 1); expect(mocks.selects).toHaveLength(2);
    await tick(1); expect(mocks.selects).toHaveLength(3); expect(result.current.status).toBe('ready');
  });

  it('accepts an actual periodic update and deletion without writing or retaining an old profile receipt', async () => {
    const accepted = vi.fn(); const { result } = renderHook(() => useProfileRefresh(true, accepted)); await drain();
    mocks.read.mockResolvedValueOnce(row({ ...BASE, major: 'Changed remotely' }, 2));
    await tick(interval); expect(accepted).toHaveBeenLastCalledWith(expect.objectContaining({ profile: { ...BASE, major: 'Changed remotely' }, revision: 2 }));
    mocks.read.mockResolvedValueOnce({ data: null, error: null });
    await tick(interval); expect(result.current.status).toBe('ready');
    expect(accepted).toHaveBeenLastCalledWith(expect.objectContaining({ profile: null, source: 'cloud-absent' }));
    expect(mirror()).toBeNull(); expect(mocks.rpc).not.toHaveBeenCalled();
  });

  it('preserves unsent journal edits on periodic updates and surfaces staged conflicts without a write', async () => {
    const { result } = renderHook(() => useProfileRefresh(true)); await drain();
    expect(recordProfileIntent({ ...BASE, major: 'Local draft' }, ['major'], captureOwnerToken())).toBe(true);
    const pending = readOutstandingOps(); mocks.read.mockResolvedValueOnce(row({ ...BASE, grade: 'Senior' }, 2));
    await tick(interval); expect(mirror()).toMatchObject({ major: 'Local draft', grade: 'Senior' });
    expect(readOutstandingOps()).toEqual(pending); expect(result.current.status).toBe('ready');
    mocks.rpc.mockResolvedValueOnce({ data: null, error: { message: 'offline' } });
    await stageProfilePatch({ ...BASE, grade: 'Senior', major: 'Local draft' }, ['major'], captureOwnerToken());
    mocks.rpc.mockClear(); mocks.read.mockResolvedValueOnce(row({ ...BASE, grade: 'Senior', major: 'Remote conflict' }, 3));
    await tick(interval); expect(result.current.status).toBe('conflict');
    const journal = readOutstandingOps(); expect(journal.ok && journal.value.length).toBeGreaterThan(0);
    expect(mocks.rpc).not.toHaveBeenCalled();
  });
});
