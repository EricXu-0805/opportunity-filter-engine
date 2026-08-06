/*
 * ensureAnonSession/onAuthChange's identity-sync truthfulness — a fresh
 * independent audit found real gaps AFTER the original B1/B2 fixes landed:
 *
 * 1. A LATE anon-sign-in failure (resolves after TWO awaits) must not roll
 *    the shared global owner back to null if a live sign-in already took
 *    over while it was in flight — that would silently sign a real,
 *    already-authenticated U2 back out from under them.
 * 2. Marking storage 'synced' must depend on syncLocalIdentityOwner's OWN
 *    verified success, not just on the uid resolution being current — a
 *    failed-closed clear/marker-write must surface 'unknown', not a false
 *    'synced'. This applies to BOTH ensureAnonSession's own resolutions
 *    AND onAuthChange's live callback.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockGetSession, mockSignInAnonymously, mockOnAuthStateChange } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockGetSession: vi.fn(),
    mockSignInAnonymously: vi.fn(),
    mockOnAuthStateChange: vi.fn((_cb: (event: string, session: unknown) => void) => ({
      data: { subscription: { unsubscribe: vi.fn() } },
    })),
  };
});

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: mockGetSession,
      signInAnonymously: mockSignInAnonymously,
      onAuthStateChange: mockOnAuthStateChange,
    },
    from: vi.fn(),
    storage: { from: vi.fn() },
  }),
}));

import { getDeviceId, getStorageStatus, onAuthChange } from './supabase';
import {
  advanceOwnerEpoch,
  captureOwnerToken,
  isLocalOwnerReady,
  syncLocalIdentityOwner,
} from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';

beforeEach(() => {
  mockGetSession.mockReset();
  mockSignInAnonymously.mockReset();
  mockOnAuthStateChange.mockClear();
  localStorage.clear();
});

describe('ensureAnonSession — a stale anon-sign-in failure must not roll back a live sign-in', () => {
  it('does not reset the global owner to null when a live sign-in already took over while the anon attempt was in flight', async () => {
    mockGetSession.mockResolvedValueOnce({ data: { session: null } });
    let resolveAnon!: (v: { data: { user: { id: string } | null }; error: { message: string } | null }) => void;
    mockSignInAnonymously.mockReturnValueOnce(
      new Promise((resolve) => { resolveAnon = resolve; }),
    );

    const promise = getDeviceId(); // starts ensureAnonSession: getSession (resolved) -> signInAnonymously (pending)

    // A live sign-in completes WHILE the anon attempt is still in flight —
    // mirrors onAuthChange's own wrapper ordering.
    advanceOwnerEpoch('live-u2');
    await syncLocalIdentityOwner('live-u2');

    // The abandoned anon attempt finally resolves with an error.
    resolveAnon({ data: { user: null }, error: { message: 'network error' } });

    const result = await promise;

    expect(result).toBe('live-u2');
    expect(captureOwnerToken().uid).toBe('live-u2');
    expect(isLocalOwnerReady('live-u2')).toBe(true);
  });

  it('does not reset the global owner to null when a live sign-in already took over while a getSession-path anon attempt was in flight', async () => {
    // getSession resolves null (forcing the anon path); by the time
    // signInAnonymously ITSELF resolves successfully, a live event has
    // already taken over — this exercises the anon-success branch's own
    // staleness guard, not just the anon-error branch.
    mockGetSession.mockResolvedValueOnce({ data: { session: null } });
    let resolveAnon!: (v: { data: { user: { id: string } | null }; error: { message: string } | null }) => void;
    mockSignInAnonymously.mockReturnValueOnce(
      new Promise((resolve) => { resolveAnon = resolve; }),
    );

    const promise = getDeviceId();
    advanceOwnerEpoch('live-u3');
    await syncLocalIdentityOwner('live-u3');
    resolveAnon({ data: { user: { id: 'stale-anon-uid' } }, error: null });

    const result = await promise;

    expect(result).toBe('live-u3');
    expect(captureOwnerToken().uid).toBe('live-u3');
  });
});

describe('ensureAnonSession — marking synced must depend on sync\'s own verified success', () => {
  it('surfaces "unknown", not a false "synced", when the clear-then-claim fails to verify', async () => {
    // A prior owner's marker sits here; claiming a NEW uid requires a
    // clear of USER_SCOPED_KEYS first. Force ONE of those removals to
    // throw so clearUserScopedStorage() (and therefore syncLocalIdentityOwner)
    // fails closed.
    const store = new Map<string, string>();
    store.set(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, 'old-uid');
    store.set(STORAGE_KEYS.PROFILE, JSON.stringify({ x: 1 }));
    const original = window.localStorage;
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
        setItem: (k: string, v: string) => {
          // The marker write silently does not stick — the failure a claim can
          // only catch by reading it back.
          if (k === STORAGE_KEYS.LOCAL_IDENTITY_OWNER) return;
          store.set(k, v);
        },
        removeItem: (k: string) => { store.delete(k); },
        clear: () => store.clear(),
        key: (i: number) => Array.from(store.keys())[i] ?? null,
        get length() { return store.size; },
      },
      configurable: true,
    });

    try {
      mockGetSession.mockResolvedValueOnce({
        data: { session: { user: { id: 'new-uid' } } },
      });
      const result = await getDeviceId();

      expect(result).toBe('new-uid'); // the uid resolution itself is still true
      expect(getStorageStatus().status).not.toBe('synced');
      expect(isLocalOwnerReady('new-uid')).toBe(false); // local mirror unconfirmed
    } finally {
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
  });
});

describe('onAuthChange — the live callback itself must also gate "synced" on sync\'s own result', () => {
  it('surfaces "unknown" when the live callback\'s own clear-then-claim fails to verify', async () => {
    const store = new Map<string, string>();
    store.set(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, 'old-uid');
    store.set(STORAGE_KEYS.PROFILE, JSON.stringify({ x: 1 }));
    const original = window.localStorage;
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
        setItem: (k: string, v: string) => {
          // The marker write silently does not stick — the failure a claim can
          // only catch by reading it back.
          if (k === STORAGE_KEYS.LOCAL_IDENTITY_OWNER) return;
          store.set(k, v);
        },
        removeItem: (k: string) => { store.delete(k); },
        clear: () => store.clear(),
        key: (i: number) => Array.from(store.keys())[i] ?? null,
        get length() { return store.size; },
      },
      configurable: true,
    });

    try {
      let callback!: (event: string, session: unknown) => unknown;
      mockOnAuthStateChange.mockImplementationOnce((cb: (event: string, session: unknown) => unknown) => {
        callback = cb;
        return { data: { subscription: { unsubscribe: vi.fn() } } };
      });
      const states: unknown[] = [];
      onAuthChange((s) => states.push(s));
      await callback('SIGNED_IN', { user: { id: 'new-uid' }, is_anonymous: false, email: 'e@x.com' });

      expect(getStorageStatus().status).not.toBe('synced');
      expect(isLocalOwnerReady('new-uid')).toBe(false);
      expect(states).toHaveLength(1); // the subscriber is still notified with the real session
    } finally {
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
  });

  it('marks "synced" when the live callback\'s clear-then-claim succeeds', async () => {
    let callback!: (event: string, session: unknown) => unknown;
    mockOnAuthStateChange.mockImplementationOnce((cb: (event: string, session: unknown) => unknown) => {
      callback = cb;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    });
    onAuthChange(() => {});
    await callback('SIGNED_IN', { user: { id: 'clean-uid' }, is_anonymous: false, email: 'e@x.com' });

    expect(getStorageStatus().status).toBe('synced');
    expect(isLocalOwnerReady('clean-uid')).toBe(true);
  });

  it('a null-uid event (sign-out) immediately drops a lingering "synced" status to "unknown" — never leaves the previous identity\'s status showing', async () => {
    let callback!: (event: string, session: unknown) => unknown;
    mockOnAuthStateChange.mockImplementationOnce((cb: (event: string, session: unknown) => unknown) => {
      callback = cb;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    });
    onAuthChange(() => {});
    await callback('SIGNED_IN', { user: { id: 'signed-out-uid' }, is_anonymous: false, email: 'e@x.com' });
    expect(getStorageStatus().status).toBe('synced');

    await callback('SIGNED_OUT', null);
    expect(getStorageStatus().status).toBe('unknown');

    // A fresh uid resolving afterward (re-anon on sign-out) with a
    // successful sync correctly returns to 'synced'.
    await callback('SIGNED_IN', { user: { id: 'fresh-anon-uid' }, is_anonymous: true, email: null });
    expect(getStorageStatus().status).toBe('synced');
  });
});
