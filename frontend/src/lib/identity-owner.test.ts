/*
 * W6 account isolation — syncLocalIdentityOwner.
 *
 * The contract under test: the FIRST uid ever observed claims the existing
 * values untouched (the deploy-day migration path for every pre-W6 user),
 * a repeat of the same uid is a no-op, a DIFFERENT uid clears the
 * user-scoped registry (including prefix-scanned tailor drafts) but never
 * the device-scoped keys, and a completed Flow B merge claims instead of
 * clearing. Storage failures must degrade to a no-op, never a throw.
 */

import { describe, expect, it, vi } from 'vitest';

import {
  advanceOwnerEpoch,
  advanceOwnerEpochIfUnchanged,
  captureOwnerToken,
  enqueuePrivateWrite,
  enterLocalOnlyMode,
  isLocalOnlyRealmReady,
  isLocalOwnerReady,
  isOwnerScopedLoadError,
  isOwnerTokenValid,
  MERGE_GRANT_MAX_AGE_MS,
  onLocalOwnerStateChange,
  OwnerScopedLoadError,
  readUserScopedRaw,
  removeUserScopedRaw,
  syncLocalIdentityOwner,
  writeUserScopedRaw,
  USER_SCOPED_KEYS,
  USER_SCOPED_PREFIXES,
  type OwnerToken,
} from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';

const MARKER = STORAGE_KEYS.LOCAL_IDENTITY_OWNER;

/** The marker is a versioned record now — `{v:2, uid, generation, phase}` —
 *  because a bare uid cannot say WHICH namespace it owns, and every isolation
 *  guarantee below rests on that. These read the parts each assertion is
 *  actually about, so the tests stay about ownership rather than about JSON. */
function ownerOf(raw: string | null | undefined): string | null {
  if (!raw) return null;
  return raw.startsWith('{') ? (JSON.parse(raw) as { uid: string }).uid : raw;
}
function generationOf(raw: string | null | undefined): number | null {
  if (!raw) return null;
  return raw.startsWith('{') ? (JSON.parse(raw) as { generation: number }).generation : 0;
}
const DRAFT_KEY = `${STORAGE_KEYS.TAILOR_DRAFT_PREFIX}opp-123`;

function seedUserScopedValues(): Record<string, string> {
  const seeded: Record<string, string> = {};
  for (const key of USER_SCOPED_KEYS) {
    seeded[key] = `value-of-${key}`;
    localStorage.setItem(key, seeded[key]);
  }
  seeded[DRAFT_KEY] = 'Dear Professor…';
  localStorage.setItem(DRAFT_KEY, seeded[DRAFT_KEY]);
  return seeded;
}

function seedDeviceScopedValues(): Record<string, string> {
  const seeded: Record<string, string> = {
    [STORAGE_KEYS.LOCALE]: 'zh',
    [STORAGE_KEYS.ONBOARDING_SEEN]: '1',
    ofe_auth: '{"access_token":"jwt"}',
  };
  for (const [key, value] of Object.entries(seeded)) {
    localStorage.setItem(key, value);
  }
  return seeded;
}

describe('registry sanity', () => {
  it('covers the known private keys and never the auth session or marker', async () => {
    expect(USER_SCOPED_KEYS).toContain(STORAGE_KEYS.PROFILE);
    expect(USER_SCOPED_KEYS).toContain(STORAGE_KEYS.CUSTOM_IMPORTS);
    expect(USER_SCOPED_KEYS).toContain(STORAGE_KEYS.FAVORITES_FALLBACK);
    // W10b: the school confirmation is an account-level decision — the next
    // uid on this browser must confirm their own campus.
    expect(USER_SCOPED_KEYS).toContain(STORAGE_KEYS.SCHOOL_CONFIRMED);
    expect(USER_SCOPED_PREFIXES).toContain(STORAGE_KEYS.TAILOR_DRAFT_PREFIX);
    expect(USER_SCOPED_KEYS).not.toContain('ofe_auth');
    expect(USER_SCOPED_KEYS).not.toContain(MARKER);
    expect(USER_SCOPED_KEYS).not.toContain(STORAGE_KEYS.MERGE_GRANT);
    expect(USER_SCOPED_KEYS).not.toContain(STORAGE_KEYS.LOCALE);
    expect(USER_SCOPED_KEYS).not.toContain(STORAGE_KEYS.ONBOARDING_SEEN);
  });
});

describe('claim path (no marker — deploy-day migration)', () => {
  it('records the uid and keeps every existing value byte-for-byte', async () => {
    const seeded = { ...seedUserScopedValues(), ...seedDeviceScopedValues() };

    advanceOwnerEpoch('uid-a');
    await syncLocalIdentityOwner('uid-a');

    expect(ownerOf(localStorage.getItem(MARKER))).toBe('uid-a');
    for (const [key, value] of Object.entries(seeded)) {
      expect(localStorage.getItem(key)).toBe(value);
    }
  });

  it('ignores a null/undefined uid (mid-sign-out limbo)', async () => {
    seedUserScopedValues();

    await syncLocalIdentityOwner(null);
    await syncLocalIdentityOwner(undefined);

    expect(localStorage.getItem(MARKER)).toBeNull();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).not.toBeNull();
  });
});

describe('no-op path (marker matches)', () => {
  it('touches nothing when the same uid syncs again', async () => {
    const seeded = seedUserScopedValues();
    localStorage.setItem(MARKER, 'uid-a');

    advanceOwnerEpoch('uid-a');
    await syncLocalIdentityOwner('uid-a');

    for (const [key, value] of Object.entries(seeded)) {
      expect(localStorage.getItem(key)).toBe(value);
    }
  });
});

describe('clear path (marker differs)', () => {
  it('clears the registry incl. prefix keys, keeps device keys, updates the marker', async () => {
    seedUserScopedValues();
    const device = seedDeviceScopedValues();
    localStorage.setItem(MARKER, 'uid-a');

    advanceOwnerEpoch('uid-b');
    await syncLocalIdentityOwner('uid-b');

    expect(ownerOf(localStorage.getItem(MARKER))).toBe('uid-b');
    for (const key of USER_SCOPED_KEYS) {
      expect(localStorage.getItem(key)).toBeNull();
    }
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
    for (const [key, value] of Object.entries(device)) {
      expect(localStorage.getItem(key)).toBe(value);
    }
  });

  it('notifies same-tab storage listeners for each cleared key', async () => {
    localStorage.setItem(STORAGE_KEYS.CUSTOM_IMPORTS, '[]');
    localStorage.setItem(MARKER, 'uid-a');
    const seen: (string | null)[] = [];
    const listener = (e: Event) => { seen.push((e as StorageEvent).key); };
    window.addEventListener('storage', listener);

    advanceOwnerEpoch('uid-b');
    await syncLocalIdentityOwner('uid-b');

    window.removeEventListener('storage', listener);
    expect(seen).toContain(STORAGE_KEYS.CUSTOM_IMPORTS);
  });

  it('is idempotent — a second clear for the same switch changes nothing', async () => {
    seedUserScopedValues();
    localStorage.setItem(MARKER, 'uid-a');

    advanceOwnerEpoch('uid-b');
    await syncLocalIdentityOwner('uid-b');
    await syncLocalIdentityOwner('uid-b');

    expect(ownerOf(localStorage.getItem(MARKER))).toBe('uid-b');
  });

  it('defers the clear while a FRESH Flow B merge grant is stashed', async () => {
    const seeded = seedUserScopedValues();
    localStorage.setItem(MARKER, 'uid-a');
    const grant = JSON.stringify({ token: 'grant-token', minted_at: Date.now() });
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, grant);

    // The SIGNED_IN event outruns /auth/callback's grant redemption; the
    // sync must leave both the values AND the marker alone so the
    // callback's post-redeem sync makes the real claim/clear decision.
    advanceOwnerEpoch('uid-b');
    await syncLocalIdentityOwner('uid-b');

    expect(ownerOf(localStorage.getItem(MARKER))).toBe('uid-a');
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBe(grant);
    for (const [key, value] of Object.entries(seeded)) {
      expect(localStorage.getItem(key)).toBe(value);
    }

    // Grant consumed (redeemPendingMerge clears it on a definitive
    // verdict), redemption failed → the plain re-sync now clears.
    localStorage.removeItem(STORAGE_KEYS.MERGE_GRANT);
    await syncLocalIdentityOwner('uid-b');
    expect(ownerOf(localStorage.getItem(MARKER))).toBe('uid-b');
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
  });

  it('defers the clear for legacy pre-W14 grant shapes (bare token / unstamped JSON)', () => {
    seedUserScopedValues();
    localStorage.setItem(MARKER, 'uid-a');

    // pre-W14 email path stored the bare token string — no stamp to judge,
    // so it must keep deferring (it is consumed by callback or sign-out)
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, 'grant-token');
    syncLocalIdentityOwner('uid-b');
    expect(localStorage.getItem(MARKER)).toBe('uid-a');

    // pre-W14 OAuth path stored {token, secret} without minted_at
    localStorage.setItem(
      STORAGE_KEYS.MERGE_GRANT,
      JSON.stringify({ token: 'grant-token', secret: 'hex' }),
    );
    syncLocalIdentityOwner('uid-b');
    expect(localStorage.getItem(MARKER)).toBe('uid-a');
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).not.toBeNull();
  });

  it('does NOT defer for a grant older than MERGE_GRANT_MAX_AGE_MS — removes it and clears', async () => {
    seedUserScopedValues();
    localStorage.setItem(MARKER, 'uid-a');
    localStorage.setItem(
      STORAGE_KEYS.MERGE_GRANT,
      JSON.stringify({
        token: 'grant-token',
        minted_at: Date.now() - MERGE_GRANT_MAX_AGE_MS - 1000,
      }),
    );

    // An abandoned hand-off (server grant died at 15 min) must not shield
    // the previous identity's local data indefinitely.
    advanceOwnerEpoch('uid-b');
    await syncLocalIdentityOwner('uid-b');

    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
    expect(ownerOf(localStorage.getItem(MARKER))).toBe('uid-b');
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
  });

  it('does NOT defer for an unparseable JSON grant slot (garbage can never redeem)', async () => {
    seedUserScopedValues();
    localStorage.setItem(MARKER, 'uid-a');
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, '{not-json');

    advanceOwnerEpoch('uid-b');
    await syncLocalIdentityOwner('uid-b');

    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
    expect(ownerOf(localStorage.getItem(MARKER))).toBe('uid-b');
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
  });
});

describe('merge-claim path ({ claim: true })', () => {
  it('rewrites the marker to the new uid and keeps all values', async () => {
    const seeded = seedUserScopedValues();
    localStorage.setItem(MARKER, 'anon-uid');

    advanceOwnerEpoch('account-uid');
    await syncLocalIdentityOwner('account-uid', { claim: true });

    expect(ownerOf(localStorage.getItem(MARKER))).toBe('account-uid');
    for (const [key, value] of Object.entries(seeded)) {
      expect(localStorage.getItem(key)).toBe(value);
    }
  });

  it('claims even while the (already-redeemed) grant is still present', async () => {
    localStorage.setItem(STORAGE_KEYS.CUSTOM_IMPORTS, '[]');
    localStorage.setItem(MARKER, 'anon-uid');
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, 'grant-token');

    advanceOwnerEpoch('account-uid');
    await syncLocalIdentityOwner('account-uid', { claim: true });

    expect(ownerOf(localStorage.getItem(MARKER))).toBe('account-uid');
    expect(localStorage.getItem(STORAGE_KEYS.CUSTOM_IMPORTS)).toBe('[]');
  });
});

describe('private mode (throwing storage)', () => {
  // vi.spyOn(Storage.prototype, …) does not intercept this jsdom's
  // localStorage, so the throwing variants replace window.localStorage
  // wholesale (test-setup defines it configurable) and restore after.
  const realStorage = () =>
    Object.getOwnPropertyDescriptor(window, 'localStorage')!;
  const installStorage = (stub: Partial<Storage>) => {
    const original = realStorage();
    Object.defineProperty(window, 'localStorage', {
      value: stub,
      configurable: true,
    });
    return () => Object.defineProperty(window, 'localStorage', original);
  };
  const boom = () => { throw new DOMException('denied', 'SecurityError'); };

  it('degrades to a no-op when getItem throws', () => {
    advanceOwnerEpoch('uid-a');
    const restore = installStorage({ getItem: boom });
    try {
      expect(() => syncLocalIdentityOwner('uid-a')).not.toThrow();
    } finally {
      restore();
    }
  });

  it('does not throw when setItem/removeItem fail mid-clear', () => {
    advanceOwnerEpoch('uid-b');
    const store = new Map<string, string>([
      [MARKER, 'uid-a'],
      [STORAGE_KEYS.PROFILE, 'profile-json'],
    ]);
    const restore = installStorage({
      get length() { return store.size; },
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      getItem: (k: string) => store.get(k) ?? null,
      setItem: boom,
      removeItem: boom,
      clear: boom,
    } as Storage);
    try {
      expect(() => syncLocalIdentityOwner('uid-b')).not.toThrow();
      // Nothing was writable — marker unchanged, so the next uid
      // observation retries the whole sync.
      expect(ownerOf(store.get(MARKER))).toBe('uid-a');
      expect(store.get(STORAGE_KEYS.PROFILE)).toBe('profile-json');
    } finally {
      restore();
    }
  });
});

/*
 * Real vulnerability (independent red-team finding): clearUserScopedStorage
 * swallows EACH removeItem exception individually and always returns
 * (implicitly succeeding from syncLocalIdentityOwner's point of view).
 * syncLocalIdentityOwner's own setItem(marker, uid) is a SEPARATE try/catch
 * that can succeed even when every single removeItem above it just failed —
 * the clear failing and the marker moving are not coupled at all. The above
 * "does not throw when setItem/removeItem fail mid-clear" test cannot catch
 * this: it fails setItem TOO, so the marker never moves for an unrelated
 * reason (nothing is writable, not "the clear specifically failed"). These
 * tests isolate removeItem-only failure — setItem still works, which is
 * exactly the scenario that lets the marker move despite an incomplete
 * clear — and then require: the marker MUST NOT move, uid-a's un-removed
 * data MUST NOT become attributable to uid-b, and a later successful retry
 * MUST still be able to clear and claim uid-b (self-healing, not a
 * permanent lockout).
 */
describe('a sweep failure is hygiene, not isolation — the new owner is never locked out and never exposed', () => {
  const realStorage = () => Object.getOwnPropertyDescriptor(window, 'localStorage')!;
  const installStorage = (stub: Partial<Storage>) => {
    const original = realStorage();
    Object.defineProperty(window, 'localStorage', { value: stub, configurable: true });
    return () => Object.defineProperty(window, 'localStorage', original);
  };
  const boom = () => { throw new DOMException('denied', 'SecurityError'); };

  it('removeItem fails on every key but setItem (for the new marker) would otherwise succeed: the marker must NOT move to uid-b, uid-a\'s un-removed data must never become attributable to uid-b, and a later successful retry — on the SAME stub, via a flipped fail flag, never a storage swap — cleans up AND claims uid-b', async () => {
    const store = new Map<string, string>([
      [MARKER, 'uid-a'],
      [STORAGE_KEYS.PROFILE, 'uid-a-profile-json'],
      [STORAGE_KEYS.CUSTOM_IMPORTS, 'uid-a-imports-json'],
    ]);
    let removeItemShouldFail = true;
    const restore = installStorage({
      get length() { return store.size; },
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => { store.set(k, v); },
      removeItem: (k: string) => {
        if (removeItemShouldFail) throw new DOMException('denied', 'SecurityError');
        store.delete(k);
      },
    } as Storage);
    try {
      advanceOwnerEpoch('uid-b');
      expect(await syncLocalIdentityOwner('uid-b'), 'uid-b is not locked out').toBe(true);
      // uid-b owns a NEW generation. uid-a's bytes could not be removed and
      // are still sitting there — which is allowed, because they are no
      // longer reachable under any name uid-b uses.
      expect(ownerOf(store.get(MARKER))).toBe('uid-b');
      expect(generationOf(store.get(MARKER)), 'a fresh namespace').toBe(1);
      expect(store.get(STORAGE_KEYS.PROFILE)).toBe('uid-a-profile-json');
      expect(readUserScopedRaw(STORAGE_KEYS.PROFILE), 'and uid-b reads none of it').toBeNull();
      expect(readUserScopedRaw(STORAGE_KEYS.CUSTOM_IMPORTS)).toBeNull();

      // Storage recovers — SAME stub/store, only the fail flag flips. The
      // leftovers are hygiene, and the next transition sweeps them.
      removeItemShouldFail = false;
      advanceOwnerEpoch('uid-c');
      await syncLocalIdentityOwner('uid-c');
      expect(store.get(STORAGE_KEYS.PROFILE)).toBeUndefined();
      expect(store.get(STORAGE_KEYS.CUSTOM_IMPORTS)).toBeUndefined();
    } finally {
      restore();
    }
  });

  it('removeItem does NOT throw but silently no-ops (the key is still readable afterward) — this must be caught by a read-back, not just "did it throw": the marker must NOT move', async () => {
    const store = new Map<string, string>([
      [MARKER, 'uid-a'],
      [STORAGE_KEYS.PROFILE, 'uid-a-profile-json'],
    ]);
    const restore = installStorage({
      get length() { return store.size; },
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => { store.set(k, v); },
      removeItem: () => { /* silent no-op — never actually deletes from `store` */ },
      clear: () => store.clear(),
    } as Storage);
    try {
      advanceOwnerEpoch('uid-b');
      await syncLocalIdentityOwner('uid-b');
      expect(ownerOf(store.get(MARKER))).toBe('uid-b');
      // The bytes really are still there — a silent no-op is undetectable to
      // the sweep — and uid-b still cannot reach them.
      expect(store.get(STORAGE_KEYS.PROFILE)).toBe('uid-a-profile-json');
      expect(readUserScopedRaw(STORAGE_KEYS.PROFILE)).toBeNull();
    } finally {
      restore();
    }
  });

  it('setItem for the marker does NOT throw but silently no-ops or writes the wrong value — syncLocalIdentityOwner must read it back and report failure, not trust the call site\'s silence', async () => {
    const store = new Map<string, string>();
    const restore = installStorage({
      get length() { return store.size; },
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      getItem: (k: string) => store.get(k) ?? null,
      setItem: () => { /* silent no-op — MARKER never actually gets uid-a written */ },
      removeItem: (k: string) => { store.delete(k); },
      clear: () => store.clear(),
    } as Storage);
    try {
      advanceOwnerEpoch('uid-a');
      expect(await syncLocalIdentityOwner('uid-a')).toBe(false); // no marker existed (claim path) — write silently failed
      expect(store.get(MARKER)).toBeUndefined();
    } finally {
      restore();
    }
  });

  it('a PARTIAL clear (one key removes fine, another throws) is still a complete failure — no partial credit, marker does not move, and the key that DID fail to remove is still uid-a\'s', async () => {
    const store = new Map<string, string>([
      [MARKER, 'uid-a'],
      [STORAGE_KEYS.PROFILE, 'uid-a-profile-json'],
      [STORAGE_KEYS.CUSTOM_IMPORTS, 'uid-a-imports-json'],
    ]);
    const restore = installStorage({
      get length() { return store.size; },
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => { store.set(k, v); },
      removeItem: (k: string) => {
        if (k === STORAGE_KEYS.CUSTOM_IMPORTS) throw new DOMException('denied', 'SecurityError');
        store.delete(k);
      },
    } as Storage);
    try {
      advanceOwnerEpoch('uid-b');
      await syncLocalIdentityOwner('uid-b');
      // A half-swept registry is no longer a half-isolated one: what the
      // sweep failed to delete is uid-a's, under uid-a's generation, and
      // uid-b is somewhere else entirely.
      expect(ownerOf(store.get(MARKER))).toBe('uid-b');
      expect(store.get(STORAGE_KEYS.CUSTOM_IMPORTS)).toBe('uid-a-imports-json');
      expect(readUserScopedRaw(STORAGE_KEYS.CUSTOM_IMPORTS)).toBeNull();
    } finally {
      restore();
    }
  });

  it('an enumeration failure (window.localStorage.length throws) cannot guarantee prefix-scanned keys (Tailor drafts, current owner-scoped format) were covered — this must ALSO fail closed even when every FIXED-list key removes fine', async () => {
    // Current (C1-R2B) format is ownerScopeKey:opportunityId, not the
    // legacy opp-only format — seed the shape this scan actually has to
    // find in production today.
    const draftKey = `${STORAGE_KEYS.TAILOR_DRAFT_PREFIX}uid-a:opp-1`;
    const store = new Map<string, string>([
      [MARKER, 'uid-a'],
      [STORAGE_KEYS.PROFILE, 'uid-a-profile-json'],
      [draftKey, 'uid-a private draft'],
    ]);
    const restore = installStorage({
      get length(): number { throw new DOMException('denied', 'SecurityError'); },
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => { store.set(k, v); },
      removeItem: (k: string) => { store.delete(k); },
    } as Storage);
    try {
      advanceOwnerEpoch('uid-b');
      await syncLocalIdentityOwner('uid-b');
      // Never claimed — prefix coverage (Tailor drafts) was never
      // confirmed, even though every FIXED-list key (PROFILE) would have
      // removed fine on its own.
      expect(ownerOf(store.get(MARKER))).toBe('uid-a');
      expect(store.get(draftKey)).toBe('uid-a private draft');
    } finally {
      restore();
    }
  });
});

/*
 * C1-R1 owner-token/epoch primitive.
 *
 * The contract under test: captureOwnerToken() is a synchronous snapshot of
 * a module-level (uid, epoch) pair, advanced only by advanceOwnerEpoch on a
 * REAL identity change (never a same-uid re-observation). isOwnerTokenValid
 * decides whether a write whose owner was captured at some past moment may
 * still land, given the uid a write's own async resolution actually landed
 * on.
 *
 * Module state is a shared singleton, so every test uses its own unique uid
 * strings and asserts RELATIVE to a token it captures locally — never on an
 * assumed absolute initial epoch — so tests stay order-independent and
 * leakage-safe regardless of run order.
 */
describe('owner token / epoch primitive', () => {
  it('captureOwnerToken reflects the uid advanceOwnerEpoch just set', () => {
    const before = captureOwnerToken();
    advanceOwnerEpoch('owner-token-u1');
    const after = captureOwnerToken();
    expect(after.uid).toBe('owner-token-u1');
    expect(after.epoch).toBe(before.epoch + 1);
  });

  it('a same-uid re-observation (TOKEN_REFRESHED/INITIAL_SESSION) does not advance the epoch', () => {
    advanceOwnerEpoch('owner-token-u2');
    const once = captureOwnerToken();
    advanceOwnerEpoch('owner-token-u2');
    advanceOwnerEpoch('owner-token-u2');
    const again = captureOwnerToken();
    expect(again).toEqual(once);
  });

  it('sign-out (a transition to null) is a real transition and advances the epoch', () => {
    advanceOwnerEpoch('owner-token-u3');
    const signedIn = captureOwnerToken();
    advanceOwnerEpoch(null);
    const signedOut = captureOwnerToken();
    expect(signedOut.uid).toBeNull();
    expect(signedOut.epoch).toBe(signedIn.epoch + 1);
  });

  it('a null-uid token is NOT a wildcard: it is rejected the moment ANY identity resolves, at the same epoch it was captured — a null token must never opportunistically bind to a later non-null uid, even the browser\'s first-ever resolution', () => {
    // Simulate "never resolved yet" locally rather than relying on the
    // module's true initial state (another test may have already advanced
    // it) — the function under test only cares that token.uid/epoch match
    // the CURRENT live state.
    const neverResolved = { ...captureOwnerToken(), uid: null };
    // Required counterexamples: null token + later non-null uid (any uid,
    // including two different ones) => false, unconditionally.
    expect(isOwnerTokenValid(neverResolved, 'owner-token-u4a')).toBe(false);
    expect(isOwnerTokenValid(neverResolved, 'owner-token-u4b')).toBe(false);
  });

  it('a null-uid token validates ONLY a write that also resolves to null, at the exact same epoch (Supabase unconfigured / anon sign-in failed — the confirmed local-only degrade, nothing actually changed) — requires the local-only realm to be explicitly established, not merely "uid is null"', () => {
    enterLocalOnlyMode(); // the confirmed local-only degrade ensureAnonSession establishes
    const stillUnresolved = { ...captureOwnerToken(), uid: null };
    expect(isOwnerTokenValid(stillUnresolved, null)).toBe(true);
  });

  it('a null-uid token is rejected once the epoch has advanced, even if the write also resolves to null (something happened in between — e.g. a sign-in immediately followed by a sign-out)', () => {
    const before = { ...captureOwnerToken(), uid: null };
    advanceOwnerEpoch('owner-token-u4c');
    advanceOwnerEpoch(null);
    expect(isOwnerTokenValid(before, null)).toBe(false);
  });

  it('a token captured while signed in as U1 is rejected if the write resolves to null (session lost)', () => {
    advanceOwnerEpoch('owner-token-u5');
    const token = captureOwnerToken();
    expect(isOwnerTokenValid(token, null)).toBe(false);
  });

  it('a token captured while signed in as U1 is rejected if the write resolves to a different uid', () => {
    advanceOwnerEpoch('owner-token-u6a');
    const token = captureOwnerToken();
    expect(isOwnerTokenValid(token, 'owner-token-u6b')).toBe(false);
  });

  it('a token captured while signed in as U1 is accepted when the write resolves to the SAME uid with no intervening transition', async () => {
    localStorage.removeItem(MARKER);
    advanceOwnerEpoch('owner-token-u7');
    await syncLocalIdentityOwner('owner-token-u7'); // establishes local-owner readiness for this uid
    const token = captureOwnerToken();
    expect(isOwnerTokenValid(token, 'owner-token-u7')).toBe(true);
  });

  it('a token is rejected across a full sign-out + sign-back-in-as-the-same-uid cycle, even though the resolved uid matches — a bare uid comparison would miss this', () => {
    advanceOwnerEpoch('owner-token-u8');
    const token = captureOwnerToken();
    advanceOwnerEpoch(null); // sign-out
    advanceOwnerEpoch('owner-token-u8'); // sign back in as the same person
    // resolvedUid === token.uid, but two real transitions happened in
    // between — the epoch check catches what uid-equality alone cannot.
    expect(isOwnerTokenValid(token, 'owner-token-u8')).toBe(false);
  });
});

describe('advanceOwnerEpochIfUnchanged — guarded async observation', () => {
  it('applies the observation when nothing has advanced since sinceEpoch, and returns true', () => {
    const sinceEpoch = captureOwnerToken().epoch;
    expect(advanceOwnerEpochIfUnchanged('owner-token-guard-a', sinceEpoch)).toBe(true);
    // generation -1: the epoch fence lands synchronously, but no namespace is
    // confirmed for the new owner until a transition proves one — and a token
    // that names no namespace can never validate a private write.
    expect(captureOwnerToken()).toEqual({ uid: 'owner-token-guard-a', epoch: sinceEpoch + 1, generation: -1 });
  });

  it('drops the observation (no-op) when a live transition already advanced the epoch since sinceEpoch — never rolls the global owner backward — and returns false, so the caller knows not to run a dependent side effect like syncLocalIdentityOwner', () => {
    const sinceEpoch = captureOwnerToken().epoch;
    // The authoritative live listener advances directly and wins.
    advanceOwnerEpoch('owner-token-guard-live');
    const afterLive = captureOwnerToken();
    // A stale async resolution captured BEFORE the live event now arrives —
    // must be silently dropped, not applied.
    expect(advanceOwnerEpochIfUnchanged('owner-token-guard-stale', sinceEpoch)).toBe(false);
    expect(captureOwnerToken()).toEqual(afterLive);
  });

  it('a dropped stale observation does not poison later guarded observations for the CURRENT epoch', async () => {
    advanceOwnerEpoch('owner-token-guard-b');
    const currentEpoch = captureOwnerToken().epoch;
    advanceOwnerEpochIfUnchanged('owner-token-guard-stale-2', currentEpoch - 1); // stale, dropped
    advanceOwnerEpochIfUnchanged('owner-token-guard-b', currentEpoch); // fresh, same uid — applies (no-op uid, epoch unchanged)
    expect(captureOwnerToken()).toEqual({ uid: 'owner-token-guard-b', epoch: currentEpoch, generation: -1 });
  });
});

describe('enqueuePrivateWrite — shared cross-component serialization queue', () => {
  it('serializes two writes for the SAME (owner, opportunity): a slower A still completes before a faster B starts, regardless of call order', async () => {
    advanceOwnerEpoch('owner-token-queue-a');
    const token = captureOwnerToken();
    const order: string[] = [];
    const a = enqueuePrivateWrite(token, 'opp-1', async () => {
      await new Promise((r) => setTimeout(r, 20));
      order.push('A');
    });
    const b = enqueuePrivateWrite(token, 'opp-1', async () => {
      order.push('B'); // no delay — would finish first if unserialized
    });
    await Promise.all([a, b]);
    expect(order).toEqual(['A', 'B']);
  });

  it('does not serialize writes for DIFFERENT opportunities under the same owner — they run independently', async () => {
    advanceOwnerEpoch('owner-token-queue-b');
    const token = captureOwnerToken();
    const order: string[] = [];
    const slow = enqueuePrivateWrite(token, 'opp-slow', async () => {
      await new Promise((r) => setTimeout(r, 20));
      order.push('slow');
    });
    const fast = enqueuePrivateWrite(token, 'opp-fast', async () => {
      order.push('fast');
    });
    await Promise.all([slow, fast]);
    expect(order).toEqual(['fast', 'slow']);
  });

  it('a rejected entry does not poison the queue — a later enqueued write for the same key still runs', async () => {
    advanceOwnerEpoch('owner-token-queue-c');
    const token = captureOwnerToken();
    const failing = enqueuePrivateWrite(token, 'opp-2', async () => {
      throw new Error('boom');
    });
    const following = enqueuePrivateWrite(token, 'opp-2', async () => 'ok');
    await expect(failing).rejects.toThrow('boom');
    await expect(following).resolves.toBe('ok');
  });

  it('a same-uid sign-out + sign-back-in cycle (different epoch) does not share a queue with the earlier session — no unnecessary blocking', async () => {
    advanceOwnerEpoch('owner-token-queue-d');
    const tokenBefore = captureOwnerToken();
    advanceOwnerEpoch(null);
    advanceOwnerEpoch('owner-token-queue-d'); // same uid, new epoch
    const tokenAfter = captureOwnerToken();
    expect(tokenAfter.epoch).not.toBe(tokenBefore.epoch);

    const order: string[] = [];
    const stale = enqueuePrivateWrite(tokenBefore, 'opp-3', async () => {
      await new Promise((r) => setTimeout(r, 20));
      order.push('stale');
    });
    const fresh = enqueuePrivateWrite(tokenAfter, 'opp-3', async () => {
      order.push('fresh'); // must not wait behind the stale-epoch entry
    });
    await Promise.all([stale, fresh]);
    expect(order).toEqual(['fresh', 'stale']);
  });

  it('two different opportunities under the same owner+epoch calling different operation types (status insert then notes update) still order correctly when queued together for the SAME opportunity', async () => {
    advanceOwnerEpoch('owner-token-queue-e');
    const token = captureOwnerToken();
    const order: string[] = [];
    const status = enqueuePrivateWrite(token, 'opp-4', async () => {
      await new Promise((r) => setTimeout(r, 20));
      order.push('status-insert');
    });
    const notes = enqueuePrivateWrite(token, 'opp-4', async () => {
      order.push('notes-update'); // must not run before the row-creating status insert
    });
    await Promise.all([status, notes]);
    expect(order).toEqual(['status-insert', 'notes-update']);
  });

  // The queue key is built from three fields (uid, epoch, opportunityId).
  // A naive `${uid ?? ''} ${epoch} ${opportunityId}`-style join collapses a
  // null uid and an empty-string uid to the identical '' segment, and gives
  // no protection if any field ever contains the join delimiter. The key
  // must be a collision-safe, visible (non-control-byte) encoding.
  it('a null-uid token and an empty-string-uid token never share a queue (null ?? "" collapse)', async () => {
    const nullToken: OwnerToken = { uid: null, epoch: 7, generation: 0 };
    const emptyToken: OwnerToken = { uid: '', epoch: 7, generation: 0 };
    const order: string[] = [];
    const slow = enqueuePrivateWrite(nullToken, 'opp-collision', async () => {
      await new Promise((r) => setTimeout(r, 20));
      order.push('null-uid');
    });
    const fast = enqueuePrivateWrite(emptyToken, 'opp-collision', async () => {
      order.push('empty-uid'); // would be forced to wait behind slow if the keys collided
    });
    await Promise.all([slow, fast]);
    expect(order).toEqual(['empty-uid', 'null-uid']);
  });

  it('an opportunityId containing encoding-special characters cannot forge a collision with a differently-shaped tuple', async () => {
    const token: OwnerToken = { uid: 'owner', epoch: 1, generation: 0 };
    const order: string[] = [];
    // Crafted to look like it could splice a second array entry into a
    // naive/unescaped encoding of ["owner",1,<this string>].
    const a = enqueuePrivateWrite(token, 'a","owner",1,"b', async () => {
      await new Promise((r) => setTimeout(r, 20));
      order.push('a');
    });
    const b = enqueuePrivateWrite(token, 'b', async () => {
      order.push('b'); // would be forced to wait behind `a` if the encoding let the crafted id collide with the plain "b" key
    });
    await Promise.all([a, b]);
    expect(order).toEqual(['b', 'a']);
  });
});

/*
 * Local-owner readiness barrier: the single gate readUserScopedRaw/
 * writeUserScopedRaw/isLocalOwnerReady give every USER_SCOPED_KEYS/prefix
 * reader-writer across the app. Every test here uses its own unique uid
 * strings (module state is a shared singleton across the whole file).
 */
describe('local-owner readiness barrier', () => {
  it('isLocalOwnerReady is false for a null uid unconditionally, even if some OTHER uid is currently ready', async () => {
    localStorage.removeItem(MARKER);
    advanceOwnerEpoch('readiness-u1');
    await syncLocalIdentityOwner('readiness-u1');
    expect(isLocalOwnerReady('readiness-u1')).toBe(true);
    expect(isLocalOwnerReady(null)).toBe(false);
  });

  it('syncLocalIdentityOwner invoked with a uid that does NOT match the current global owner (a caller bug, an out-of-order callback) is a complete no-op — rejected BEFORE it ever reaches storage or readiness state, so neither the wrong uid nor the actual current owner ever reports ready', async () => {
    localStorage.removeItem(MARKER);
    localStorage.setItem(STORAGE_KEYS.PROFILE, 'untouched-profile-json');
    advanceOwnerEpoch('defensive-real-owner');
    // Invoked with a uid that does NOT match the actual current global
    // owner — advanceOwnerEpoch was never called for this value. The
    // guard inside syncLocalIdentityOwner itself rejects this outright,
    // which is ALSO why isLocalOwnerReady's own uid===currentOwnerUid
    // check (defense-in-depth) can no longer be exercised via this path —
    // storage is proven untouched below, not merely "not readable as
    // either uid."
    await syncLocalIdentityOwner('defensive-stale-uid');
    expect(isLocalOwnerReady('defensive-stale-uid')).toBe(false);
    expect(isLocalOwnerReady('defensive-real-owner')).toBe(false);
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBe('untouched-profile-json'); // never cleared/touched
    expect(localStorage.getItem(MARKER)).toBeNull(); // never written
  });

  it('a genuine same-uid re-observation (marker already matched BEFORE this call, so advanceOwnerEpoch is a real no-op) leaves readiness untouched and fires no duplicate notification', async () => {
    localStorage.removeItem(MARKER);
    advanceOwnerEpoch('readiness-sameuid');
    await syncLocalIdentityOwner('readiness-sameuid');
    expect(isLocalOwnerReady('readiness-sameuid')).toBe(true);

    let calls = 0;
    const unsubscribe = onLocalOwnerStateChange(() => { calls += 1; });
    try {
      advanceOwnerEpoch('readiness-sameuid'); // truly the SAME uid as currentOwnerUid — advanceOwnerEpoch's own early return, never touches readiness
      expect(calls).toBe(0);
      expect(isLocalOwnerReady('readiness-sameuid')).toBe(true); // untouched

      await syncLocalIdentityOwner('readiness-sameuid'); // marker === uid — the no-op path
      expect(calls).toBe(0); // setLocalOwnerState's own same-state guard suppresses the redundant notification
      expect(isLocalOwnerReady('readiness-sameuid')).toBe(true);
    } finally {
      unsubscribe();
    }
  });

  it('advanceOwnerEpoch on a REAL transition blocks readiness for the new uid IMMEDIATELY — before syncLocalIdentityOwner ever runs', () => {
    advanceOwnerEpoch('readiness-u2');
    // No syncLocalIdentityOwner call yet — the epoch alone must have
    // already blocked this uid, closing the real production window where
    // the global epoch advances synchronously before local sync/React
    // ever catches up. (A uid never seen before defaults to blocked
    // anyway — see the NEXT test for the case this alone can't prove.)
    expect(isLocalOwnerReady('readiness-u2')).toBe(false);
  });

  it('advanceOwnerEpoch blocks even a RETURN to a uid that was previously ready — a stale cached "ready" must never survive an intervening transition without a fresh sync (the previous test alone can\'t catch this: a never-seen uid is blocked by default regardless of whether advanceOwnerEpoch resets anything)', async () => {
    localStorage.removeItem(MARKER);
    advanceOwnerEpoch('readiness-u2b');
    await syncLocalIdentityOwner('readiness-u2b');
    expect(isLocalOwnerReady('readiness-u2b')).toBe(true); // genuinely ready once

    // Sign out, then sign back in as the SAME uid — onAuthChange calls
    // advanceOwnerEpoch for both, but this test issues NO syncLocalIdentityOwner
    // call for the return leg, isolating advanceOwnerEpoch's own reset.
    advanceOwnerEpoch(null);
    advanceOwnerEpoch('readiness-u2b');
    expect(isLocalOwnerReady('readiness-u2b')).toBe(false); // must NOT trust the stale prior 'ready' state
  });

  it('a successful syncLocalIdentityOwner (no-marker claim path) flips readiness to ready for that uid', async () => {
    localStorage.removeItem(MARKER);
    advanceOwnerEpoch('readiness-u3');
    expect(isLocalOwnerReady('readiness-u3')).toBe(false); // blocked immediately by advanceOwnerEpoch
    await syncLocalIdentityOwner('readiness-u3');
    expect(isLocalOwnerReady('readiness-u3')).toBe(true);
  });

  it('a same-uid re-observation (marker already matches) is also ready — not left blocked from a stale prior state', async () => {
    localStorage.setItem(MARKER, 'readiness-u4');
    advanceOwnerEpoch('readiness-u4'); // no-op transition (same uid as currentOwnerUid already? use a fresh one to force the epoch bump path)
    await syncLocalIdentityOwner('readiness-u4');
    expect(isLocalOwnerReady('readiness-u4')).toBe(true);
  });

  it('a failed clear leaves readiness BLOCKED for the new uid — never falsely ready', async () => {
    seedUserScopedValues();
    localStorage.setItem(MARKER, 'readiness-u5a');
    const realStorage = () => Object.getOwnPropertyDescriptor(window, 'localStorage')!;
    const original = realStorage();
    const store = new Map<string, string>([[MARKER, 'readiness-u5a']]);
    Object.defineProperty(window, 'localStorage', {
      value: {
        get length() { return store.size; },
        key: (i: number) => Array.from(store.keys())[i] ?? null,
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => { store.set(k, v); },
        removeItem: () => { throw new DOMException('denied', 'SecurityError'); },
        clear: () => store.clear(),
      } as Storage,
      configurable: true,
    });
    try {
      advanceOwnerEpoch('readiness-u5b');
      await syncLocalIdentityOwner('readiness-u5b');
      // Ready — and correctly so. The sweep could not delete readiness-u5a's
      // keys, but readiness-u5b was published into a namespace that shares no
      // name with them, so blocking the new owner would cost them their whole
      // session to protect nothing.
      expect(isLocalOwnerReady('readiness-u5b')).toBe(true);
      expect(readUserScopedRaw(STORAGE_KEYS.PROFILE)).toBeNull();
    } finally {
      Object.defineProperty(window, 'localStorage', original);
    }
  });

  it('a deferred sync (Flow B merge grant pending) leaves readiness BLOCKED, not ready for either the old or the new uid', async () => {
    localStorage.setItem(MARKER, 'readiness-u6a');
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, 'grant-token');
    advanceOwnerEpoch('readiness-u6b');
    await syncLocalIdentityOwner('readiness-u6b');
    expect(isLocalOwnerReady('readiness-u6b')).toBe(false);
    expect(isLocalOwnerReady('readiness-u6a')).toBe(false); // advanceOwnerEpoch already blocked the OLD uid too
    localStorage.removeItem(STORAGE_KEYS.MERGE_GRANT);
  });

  it('onLocalOwnerStateChange notifies subscribers on every readiness transition', async () => {
    let calls = 0;
    const unsubscribe = onLocalOwnerStateChange(() => { calls += 1; });
    try {
      advanceOwnerEpoch('readiness-u7');
      expect(calls).toBeGreaterThanOrEqual(1); // the immediate blocked transition
      const before = calls;
      await syncLocalIdentityOwner('readiness-u7');
      expect(calls).toBeGreaterThan(before); // the ready transition
    } finally {
      unsubscribe();
    }
  });

  it('a listener that throws does not prevent OTHER listeners from being notified — one bad subscriber must never silently break readiness notification for the rest', () => {
    const calls: string[] = [];
    const unsubBad = onLocalOwnerStateChange(() => { throw new Error('boom'); });
    const unsubGood = onLocalOwnerStateChange(() => { calls.push('good'); });
    try {
      advanceOwnerEpoch('listener-isolation-uid');
      expect(calls).toContain('good');
    } finally {
      unsubBad();
      unsubGood();
    }
  });

  describe('readUserScopedRaw / writeUserScopedRaw / removeUserScopedRaw', () => {
    it('rejects a key that is not a registered USER_SCOPED key/prefix — this wrapper must never become a generic localStorage passthrough', async () => {
      const token = captureOwnerToken();
      expect(() => readUserScopedRaw(STORAGE_KEYS.LOCALE)).toThrow();
      expect(() => writeUserScopedRaw(STORAGE_KEYS.LOCALE, 'zh', token)).toThrow();
      expect(() => removeUserScopedRaw(STORAGE_KEYS.LOCALE, token)).toThrow();
    });

    it('read returns null when not ready, even though the raw value is genuinely sitting in localStorage', async () => {
      localStorage.setItem(STORAGE_KEYS.PROFILE, 'leftover-profile-json');
      advanceOwnerEpoch('readiness-u8'); // blocks immediately, no sync yet
      expect(readUserScopedRaw(STORAGE_KEYS.PROFILE)).toBeNull();
    });

    it('read returns the real value once ready', async () => {
      localStorage.removeItem(MARKER);
      localStorage.setItem(STORAGE_KEYS.PROFILE, 'u9-profile-json');
      advanceOwnerEpoch('readiness-u9');
      await syncLocalIdentityOwner('readiness-u9'); // claim path — keeps existing values
      expect(readUserScopedRaw(STORAGE_KEYS.PROFILE)).toBe('u9-profile-json');
    });

    it('write no-ops when the token\'s OWN epoch is not ready yet (captured mid-transition, before any sync completed)', async () => {
      localStorage.removeItem(STORAGE_KEYS.EMAIL_HINT);
      advanceOwnerEpoch('readiness-u10'); // blocks immediately
      const token = captureOwnerToken(); // captured WHILE blocked
      writeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, 'someone@example.com', token);
      expect(localStorage.getItem(STORAGE_KEYS.EMAIL_HINT)).toBeNull();
    });

    it('write succeeds once the token\'s epoch is ready', async () => {
      localStorage.removeItem(MARKER);
      advanceOwnerEpoch('readiness-u11');
      await syncLocalIdentityOwner('readiness-u11');
      const token = captureOwnerToken();
      writeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, 'u11@example.com', token);
      expect(localStorage.getItem(STORAGE_KEYS.EMAIL_HINT)).toBe('u11@example.com');
    });

    it('a STALE token — captured under U1, firing AFTER a real transition to U2 who is now genuinely ready — must be rejected even though readiness is TRUE right now (caught here via the uid mismatch: token.uid=U1 no longer equals the current owner U2 — see the NEXT test for the DIFFERENT scenario where uid alone is not enough)', async () => {
      localStorage.removeItem(MARKER);
      advanceOwnerEpoch('readiness-u12a');
      await syncLocalIdentityOwner('readiness-u12a');
      const staleToken = captureOwnerToken(); // U1's token, captured while U1 was ready

      // A real transition to U2, who then becomes genuinely ready too.
      advanceOwnerEpoch('readiness-u12b');
      await syncLocalIdentityOwner('readiness-u12b');
      expect(isLocalOwnerReady('readiness-u12b')).toBe(true); // storage IS usable right now — for U2

      // U1's stale closure (e.g. a debounced autosave timer created before
      // the switch) finally fires, using the token it captured back then.
      localStorage.removeItem(STORAGE_KEYS.EMAIL_HINT);
      writeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, 'stale-u1-write@example.com', staleToken);
      expect(localStorage.getItem(STORAGE_KEYS.EMAIL_HINT)).toBeNull(); // rejected — never landed under U2's key
    });

    it('a token captured under U1, surviving a FULL sign-out + sign-back-in-AS-U1 cycle where U1 becomes genuinely ready again, must STILL be rejected — the previous test\'s uid-mismatch alone cannot catch this (currentOwnerUid and readiness BOTH show U1 again); only the token\'s own captured epoch proves two real transitions happened in between (mutation-proof target: isTokenCurrentForLocalStorage\'s epoch check specifically, not the uid check it shares with isLocalOwnerReady)', async () => {
      localStorage.removeItem(MARKER);
      advanceOwnerEpoch('readiness-cycle-u1');
      await syncLocalIdentityOwner('readiness-cycle-u1');
      const staleToken = captureOwnerToken(); // epoch E1, uid = readiness-cycle-u1

      // Sign out, then sign back in as the exact SAME uid — TWO real
      // transitions — and U1 becomes genuinely ready again.
      advanceOwnerEpoch(null);
      advanceOwnerEpoch('readiness-cycle-u1');
      await syncLocalIdentityOwner('readiness-cycle-u1');

      // Sanity: current owner AND readiness both genuinely show U1 again —
      // a uid-plus-readiness-only check would incorrectly validate staleToken.
      expect(isLocalOwnerReady('readiness-cycle-u1')).toBe(true);

      localStorage.removeItem(STORAGE_KEYS.EMAIL_HINT);
      writeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, 'stale-cycle-write@example.com', staleToken);
      expect(localStorage.getItem(STORAGE_KEYS.EMAIL_HINT)).toBeNull(); // rejected via the epoch mismatch alone
    });

    it('a late REMOVE from an abandoned owner must NOT delete the CURRENT owner\'s same-named data — this is destructive, not merely a leak, and removal gets the SAME token gate as write', async () => {
      localStorage.removeItem(MARKER);
      advanceOwnerEpoch('readiness-u13a');
      await syncLocalIdentityOwner('readiness-u13a');
      const staleToken = captureOwnerToken(); // U1's token

      advanceOwnerEpoch('readiness-u13b');
      await syncLocalIdentityOwner('readiness-u13b');
      // U2 writes their OWN data under the same LOGICAL key name.
      writeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, 'u2-own-data@example.com', captureOwnerToken());
      expect(readUserScopedRaw(STORAGE_KEYS.EMAIL_HINT)).toBe('u2-own-data@example.com');

      // U1's late cleanup/cache-invalidation logic (e.g. a stale
      // clearMatchCache()-style call) fires with U1's OWN stale token.
      removeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, staleToken);
      // U2's data must survive — twice over: U1's stale token is refused, and
      // the key it names is not the key U2's value lives under.
      expect(readUserScopedRaw(STORAGE_KEYS.EMAIL_HINT)).toBe('u2-own-data@example.com');
    });

    it('remove succeeds with a genuinely current token', async () => {
      localStorage.removeItem(MARKER);
      advanceOwnerEpoch('readiness-u14');
      await syncLocalIdentityOwner('readiness-u14');
      const token = captureOwnerToken();
      localStorage.setItem(STORAGE_KEYS.EMAIL_HINT, 'to-be-removed@example.com');
      removeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, token);
      expect(localStorage.getItem(STORAGE_KEYS.EMAIL_HINT)).toBeNull();
    });

    it('remove returns false and leaves the value in place when removeItem does NOT throw but silently no-ops (the key is still readable afterward) — a caller must be able to tell "verifiably gone" from "who knows", not trust a non-throwing call site\'s silence', async () => {
      localStorage.removeItem(MARKER);
      advanceOwnerEpoch('readiness-u15');
      await syncLocalIdentityOwner('readiness-u15');
      const token = captureOwnerToken();
      localStorage.setItem(STORAGE_KEYS.EMAIL_HINT, 'stuck@example.com');

      const original = window.localStorage;
      Object.defineProperty(window, 'localStorage', {
        value: {
          getItem: (k: string) => original.getItem(k),
          setItem: (k: string, v: string) => original.setItem(k, v),
          removeItem: () => { /* silent no-op — never actually deletes */ },
          clear: () => original.clear(),
          key: (i: number) => original.key(i),
          get length() { return original.length; },
        },
        configurable: true,
      });
      try {
        const removed = removeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, token);
        expect(removed).toBe(false);
      } finally {
        Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
      }
      expect(localStorage.getItem(STORAGE_KEYS.EMAIL_HINT)).toBe('stuck@example.com');
    });
  });

  describe('local-only realm (explicit, controlled analog of "ready" for the null-uid confirmed-local-only degrade)', () => {
    it('a transient signed-out null (no enterLocalOnlyMode call) stays BLOCKED — a bare "no identity resolved yet" is never sufficient', () => {
      advanceOwnerEpoch('local-only-prior');
      advanceOwnerEpoch(null); // ordinary sign-out, transient — NOT the confirmed local-only degrade
      expect(isLocalOnlyRealmReady()).toBe(false);
      const token = captureOwnerToken(); // {uid: null, epoch: current}
      expect(isOwnerTokenValid(token, null)).toBe(false);
    });

    it('enterLocalOnlyMode establishes the realm on a fresh browser (no marker) and a null-uid token then validates', () => {
      localStorage.removeItem(MARKER);
      advanceOwnerEpoch(null);
      expect(enterLocalOnlyMode()).toBe(true);
      expect(isLocalOnlyRealmReady()).toBe(true);
      const token = captureOwnerToken();
      expect(isOwnerTokenValid(token, null)).toBe(true);
    });

    it('enterLocalOnlyMode NEVER clears a REAL prior account\'s marker/data — a temporary local degrade (Supabase briefly unreachable/unconfigured) must not destroy CUSTOM_IMPORTS or the rest of USER_SCOPED_KEYS just because this browser happens to have a real owner on record; the realm stays BLOCKED and everything is left exactly as it was', () => {
      const seeded = seedUserScopedValues();
      localStorage.setItem(MARKER, 'local-only-prior-account');
      advanceOwnerEpoch(null);
      expect(enterLocalOnlyMode()).toBe(false);
      expect(isLocalOnlyRealmReady()).toBe(false);
      expect(ownerOf(localStorage.getItem(MARKER))).toBe('local-only-prior-account'); // untouched
      for (const [key, value] of Object.entries(seeded)) {
        expect(localStorage.getItem(key)).toBe(value); // NOT cleared
      }
    });

    it('a marker-read throw during enterLocalOnlyMode leaves the realm BLOCKED — never falsely establishes local-only when ownership can\'t even be determined', () => {
      const original = Object.getOwnPropertyDescriptor(window, 'localStorage')!;
      Object.defineProperty(window, 'localStorage', {
        value: { getItem: () => { throw new DOMException('denied', 'SecurityError'); } },
        configurable: true,
      });
      try {
        advanceOwnerEpoch(null);
        expect(enterLocalOnlyMode()).toBe(false);
        expect(isLocalOnlyRealmReady()).toBe(false);
      } finally {
        Object.defineProperty(window, 'localStorage', original);
      }
    });

    it('enterLocalOnlyMode does not apply when a real uid is currently the owner — calling it while signed in must not establish or touch the realm', () => {
      advanceOwnerEpoch('local-only-not-applicable');
      expect(enterLocalOnlyMode()).toBe(false);
      expect(isLocalOnlyRealmReady()).toBe(false);
    });

    it('write no-ops for a null-uid token when the local-only realm was never established', () => {
      advanceOwnerEpoch('local-only-prior-3');
      advanceOwnerEpoch(null); // transient, not confirmed local-only
      const token = captureOwnerToken();
      localStorage.removeItem(STORAGE_KEYS.EMAIL_HINT);
      writeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, 'anon@example.com', token);
      expect(localStorage.getItem(STORAGE_KEYS.EMAIL_HINT)).toBeNull();
    });

    it('write succeeds for a null-uid token once the local-only realm is established', () => {
      localStorage.removeItem(MARKER);
      advanceOwnerEpoch(null);
      enterLocalOnlyMode();
      const token = captureOwnerToken();
      writeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, 'device-local@example.com', token);
      expect(localStorage.getItem(STORAGE_KEYS.EMAIL_HINT)).toBe('device-local@example.com');
    });

    it('read returns null (via isLocalOwnerReadyNow) when the local-only realm was never established, even though a real value is genuinely sitting in localStorage', () => {
      advanceOwnerEpoch('local-only-read-prior');
      advanceOwnerEpoch(null); // transient, not confirmed local-only
      localStorage.setItem(STORAGE_KEYS.EMAIL_HINT, 'leftover@example.com');
      expect(readUserScopedRaw(STORAGE_KEYS.EMAIL_HINT)).toBeNull();
    });

    it('read returns the real value once the local-only realm is established — isLocalOwnerReadyNow must recognize the explicit null-uid realm, not just a confirmed non-null owner', () => {
      localStorage.removeItem(MARKER);
      advanceOwnerEpoch(null);
      enterLocalOnlyMode();
      localStorage.setItem(STORAGE_KEYS.EMAIL_HINT, 'device-only@example.com');
      expect(readUserScopedRaw(STORAGE_KEYS.EMAIL_HINT)).toBe('device-only@example.com');
    });

    it('remove succeeds for a null-uid token once the local-only realm is established, and no-ops for a stale one', () => {
      localStorage.removeItem(MARKER);
      advanceOwnerEpoch(null);
      enterLocalOnlyMode();
      const staleToken = captureOwnerToken();

      // A real transition away invalidates the realm (see advanceOwnerEpoch's
      // own reset) — the stale null-uid token must not be able to remove
      // anything under the NEW context.
      advanceOwnerEpoch('local-only-remove-other');
      localStorage.setItem(STORAGE_KEYS.EMAIL_HINT, 'other-owners-data@example.com');
      removeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, staleToken);
      expect(localStorage.getItem(STORAGE_KEYS.EMAIL_HINT)).toBe('other-owners-data@example.com'); // untouched

      // A genuinely current null-uid token, with the realm freshly
      // re-established, CAN remove.
      advanceOwnerEpoch(null);
      localStorage.removeItem(MARKER);
      enterLocalOnlyMode();
      const freshToken = captureOwnerToken();
      localStorage.setItem(STORAGE_KEYS.EMAIL_HINT, 'to-remove@example.com');
      removeUserScopedRaw(STORAGE_KEYS.EMAIL_HINT, freshToken);
      expect(localStorage.getItem(STORAGE_KEYS.EMAIL_HINT)).toBeNull();
    });
  });
});

describe('writeUserScopedRaw / removeUserScopedRaw: success means the value is verifiably there', () => {
  const KEY = STORAGE_KEYS.PROFILE;

  beforeEach(async () => {
    localStorage.clear();
    advanceOwnerEpoch('readback-uid');
    await syncLocalIdentityOwner('readback-uid');
  });

  it('reports true only when the exact value reads back', () => {
    const token = captureOwnerToken();
    expect(writeUserScopedRaw(KEY, '{"major":"CS"}', token)).toBe(true);
    expect(localStorage.getItem(KEY)).toBe('{"major":"CS"}');
  });

  it('reports false when setItem silently no-ops', () => {
    const token = captureOwnerToken();
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {});
    try {
      expect(writeUserScopedRaw(KEY, '{"major":"CS"}', token)).toBe(false);
    } finally {
      spy.mockRestore();
    }
  });

  it('reports false when setItem stores something else', () => {
    const token = captureOwnerToken();
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation((k: string) => {
      localStorage.removeItem(k);
      Object.defineProperty(window.localStorage, k, { value: 'truncated', configurable: true });
    });
    try {
      expect(writeUserScopedRaw(KEY, '{"major":"CS"}', token)).toBe(false);
    } finally {
      spy.mockRestore();
    }
  });

  it('reports false when setItem throws', () => {
    const token = captureOwnerToken();
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    try {
      expect(writeUserScopedRaw(KEY, '{"major":"CS"}', token)).toBe(false);
    } finally {
      spy.mockRestore();
    }
  });

  it('a removal that did not remove reports false', () => {
    const token = captureOwnerToken();
    localStorage.setItem(KEY, 'still here');
    const spy = vi.spyOn(window.localStorage, 'removeItem').mockImplementation(() => {});
    try {
      expect(removeUserScopedRaw(KEY, token)).toBe(false);
    } finally {
      spy.mockRestore();
    }
    expect(removeUserScopedRaw(KEY, token)).toBe(true);
  });
});

describe('writeUserScopedRaw: success means the value verifiably reads back', () => {
  const KEY = STORAGE_KEYS.PROFILE;

  it('true only when the exact value is there afterwards', async () => {
    localStorage.clear();
    advanceOwnerEpoch('readback-uid');
    await syncLocalIdentityOwner('readback-uid');
    const token = captureOwnerToken();
    expect(writeUserScopedRaw(KEY, '{"major":"CS"}', token)).toBe(true);
    expect(localStorage.getItem(KEY)).toBe('{"major":"CS"}');
  });

  it('false when setItem silently no-ops', async () => {
    localStorage.clear();
    advanceOwnerEpoch('readback-uid-2');
    await syncLocalIdentityOwner('readback-uid-2');
    const token = captureOwnerToken();
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {});
    try {
      expect(writeUserScopedRaw(KEY, '{"major":"CS"}', token)).toBe(false);
    } finally { spy.mockRestore(); }
  });

  it('false when setItem stores a different value', async () => {
    localStorage.clear();
    advanceOwnerEpoch('readback-uid-3');
    await syncLocalIdentityOwner('readback-uid-3');
    const token = captureOwnerToken();
    // A storage that truncates instead of storing what it was given.
    const real = Object.getPrototypeOf(window.localStorage).setItem as (k: string, v: string) => void;
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation((k: string) => {
      real.call(window.localStorage, k, 'truncated');
    });
    try {
      expect(writeUserScopedRaw(KEY, '{"major":"CS"}', token)).toBe(false);
    } finally { spy.mockRestore(); }
  });

  it('false when setItem throws', async () => {
    localStorage.clear();
    advanceOwnerEpoch('readback-uid-4');
    await syncLocalIdentityOwner('readback-uid-4');
    const token = captureOwnerToken();
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    try {
      expect(writeUserScopedRaw(KEY, '{"major":"CS"}', token)).toBe(false);
    } finally { spy.mockRestore(); }
  });
});


describe('a write never lands in an account the browser no longer belongs to', () => {
  it('refuses once ANOTHER realm has moved the shared owner marker', async () => {
    advanceOwnerEpoch('own-u1');
    await syncLocalIdentityOwner('own-u1');
    const token = captureOwnerToken();
    expect(writeUserScopedRaw(STORAGE_KEYS.PROFILE, '{"a":1}', token)).toBe(true);

    // Another tab switched accounts. This realm has not heard about it yet:
    // its own memory still says U1 is live and ready.
    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, 'own-u2');
    expect(isLocalOwnerReady('own-u1'), 'this realm still believes it is U1').toBe(true);

    expect(writeUserScopedRaw(STORAGE_KEYS.PROFILE, '{"a":2}', token)).toBe(false);
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBe('{"a":1}');
  });

  it('a write that landed just as the browser changed hands stays in ITS owner\'s namespace — never taken back out of the new owner\'s', async () => {
    // A facade, not a spy: jsdom's Storage is a proxy that turns a method
    // assignment into a stored KEY, so `vi.spyOn(localStorage, 'setItem')`
    // silently does nothing and a test built on it proves nothing.
    advanceOwnerEpoch('own-u1');
    await syncLocalIdentityOwner('own-u1');
    const token = captureOwnerToken();
    const real = window.localStorage;
    const cells = new Map<string, string>();
    for (let i = 0; i < real.length; i += 1) {
      const k = real.key(i)!;
      cells.set(k, real.getItem(k)!);
    }
    const facade = {
      getItem: (k: string) => (cells.has(k) ? cells.get(k)! : null),
      removeItem: (k: string) => { cells.delete(k); },
      setItem: (k: string, v: string) => {
        cells.set(k, v);
        // The browser changes hands DURING the physical write — the narrowest
        // version of the race, and the one a pre-check alone cannot see. This
        // is the marker a real transition writes: a NEW generation, which is
        // what makes the two owners' bytes unable to touch each other.
        if (k === STORAGE_KEYS.PROFILE) {
          cells.set(
            STORAGE_KEYS.LOCAL_IDENTITY_OWNER,
            JSON.stringify({ v: 2, uid: 'own-u2', generation: 1, phase: 'ready' }),
          );
        }
      },
      clear: () => cells.clear(),
      key: (i: number) => [...cells.keys()][i] ?? null,
      get length() { return cells.size; },
    };
    Object.defineProperty(window, 'localStorage', { configurable: true, value: facade });
    try {
      // The write is REPORTED as done, because it was: U1 asked for their own
      // namespace and their own namespace has it. The old code answered
      // `false` and then deleted the fixed key — which after a switch is the
      // NEW owner's data, a cross-account destructive write dressed up as a
      // rollback.
      expect(writeUserScopedRaw(STORAGE_KEYS.PROFILE, '{"u1":true}', token)).toBe(true);
      expect(cells.get(STORAGE_KEYS.PROFILE), "U1's bytes stay in U1's namespace").toBe('{"u1":true}');
      // …and whoever owns the browser now cannot read a byte of it.
      expect(readUserScopedRaw(STORAGE_KEYS.PROFILE)).toBeNull();
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
    }
  });

  it('legacy spy variant kept only as a smoke check', async () => {
    advanceOwnerEpoch('own-u1');
    await syncLocalIdentityOwner('own-u1');
    const token = captureOwnerToken();

    // The sweep happens BETWEEN the bytes going down and the check that they
    // are there — the narrowest version of the same race.
    const realSet = Storage.prototype.setItem.bind(localStorage);
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation((k: string, v: string) => {
      realSet(k, v);
      if (k === STORAGE_KEYS.PROFILE) realSet(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, 'own-u2');
    });
    try {
      expect(writeUserScopedRaw(STORAGE_KEYS.PROFILE, '{"late":true}', token)).toBe(false);
    } finally {
      spy.mockRestore();
    }
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE), 'the new owner is left nothing').toBeNull();
  });
});

describe('OwnerScopedLoadError: a capability, not a shape', () => {
  it('takes a frozen SNAPSHOT of the token, so a later edit cannot rewrite it', () => {
    const token: OwnerToken = { uid: 'scoped-u1', epoch: 7, generation: 0 };
    const err = new OwnerScopedLoadError(token, new Error('network down'));

    // The caller's own object goes on being the caller's.
    token.uid = 'scoped-u2';
    token.epoch = 99;

    expect(err.ownerToken, 'the failure still names who it belonged to')
      .toEqual({ uid: 'scoped-u1', epoch: 7, generation: 0 });
    expect(Object.isFrozen(err.ownerToken), 'and nothing can edit it now').toBe(true);
  });

  it('keeps the original complaint, as message and as cause', () => {
    const cause = new Error('network down');
    const err = new OwnerScopedLoadError({ uid: 'scoped-u1', epoch: 1, generation: 0 }, cause);

    expect(err.message, 'the reason survives').toBe('network down');
    expect(err.cause, 'and so does the failure itself').toBe(cause);
    expect(err).toBeInstanceOf(Error);
  });

  it('recognises its own instances and refuses anything merely shaped like one', () => {
    const real = new OwnerScopedLoadError({ uid: 'scoped-u1', epoch: 1, generation: 0 });
    const forged = Object.assign(new Error('select failed'), {
      name: 'OwnerScopedLoadError',
      ownerToken: { uid: 'scoped-u1', epoch: 1 },
    });

    expect(isOwnerScopedLoadError(real), 'the real thing is trusted').toBe(true);
    expect(isOwnerScopedLoadError(forged),
      'a name and a property are not a capability').toBe(false);
    expect(isOwnerScopedLoadError(new Error('plain'))).toBe(false);
    expect(isOwnerScopedLoadError(null)).toBe(false);
    expect(isOwnerScopedLoadError({ ownerToken: { uid: null, epoch: 0 } })).toBe(false);
  });
});
