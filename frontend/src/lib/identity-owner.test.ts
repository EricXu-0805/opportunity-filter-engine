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

import { describe, expect, it } from 'vitest';

import {
  MERGE_GRANT_MAX_AGE_MS,
  syncLocalIdentityOwner,
  USER_SCOPED_KEYS,
  USER_SCOPED_PREFIXES,
} from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';

const MARKER = STORAGE_KEYS.LOCAL_IDENTITY_OWNER;
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
  it('covers the known private keys and never the auth session or marker', () => {
    expect(USER_SCOPED_KEYS).toContain(STORAGE_KEYS.PROFILE);
    expect(USER_SCOPED_KEYS).toContain(STORAGE_KEYS.CUSTOM_IMPORTS);
    expect(USER_SCOPED_KEYS).toContain(STORAGE_KEYS.FAVORITES_FALLBACK);
    // W10b: the school confirmation is an account-level decision — the next
    // uid on this browser must confirm their own campus.
    expect(USER_SCOPED_KEYS).toContain(STORAGE_KEYS.SCHOOL_CONFIRMED);
    // W15: an unsent feedback draft is user-written content (often personal
    // detail) — the next account on this browser must never inherit it.
    expect(USER_SCOPED_KEYS).toContain(STORAGE_KEYS.FEEDBACK_DRAFT);
    expect(USER_SCOPED_PREFIXES).toContain(STORAGE_KEYS.TAILOR_DRAFT_PREFIX);
    expect(USER_SCOPED_KEYS).not.toContain('ofe_auth');
    expect(USER_SCOPED_KEYS).not.toContain(MARKER);
    expect(USER_SCOPED_KEYS).not.toContain(STORAGE_KEYS.MERGE_GRANT);
    expect(USER_SCOPED_KEYS).not.toContain(STORAGE_KEYS.LOCALE);
    expect(USER_SCOPED_KEYS).not.toContain(STORAGE_KEYS.ONBOARDING_SEEN);
  });
});

describe('claim path (no marker — deploy-day migration)', () => {
  it('records the uid and keeps every existing value byte-for-byte', () => {
    const seeded = { ...seedUserScopedValues(), ...seedDeviceScopedValues() };

    syncLocalIdentityOwner('uid-a');

    expect(localStorage.getItem(MARKER)).toBe('uid-a');
    for (const [key, value] of Object.entries(seeded)) {
      expect(localStorage.getItem(key)).toBe(value);
    }
  });

  it('ignores a null/undefined uid (mid-sign-out limbo)', () => {
    seedUserScopedValues();

    syncLocalIdentityOwner(null);
    syncLocalIdentityOwner(undefined);

    expect(localStorage.getItem(MARKER)).toBeNull();
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).not.toBeNull();
  });
});

describe('no-op path (marker matches)', () => {
  it('touches nothing when the same uid syncs again', () => {
    const seeded = seedUserScopedValues();
    localStorage.setItem(MARKER, 'uid-a');

    syncLocalIdentityOwner('uid-a');

    for (const [key, value] of Object.entries(seeded)) {
      expect(localStorage.getItem(key)).toBe(value);
    }
  });
});

describe('clear path (marker differs)', () => {
  it('clears the registry incl. prefix keys, keeps device keys, updates the marker', () => {
    seedUserScopedValues();
    const device = seedDeviceScopedValues();
    localStorage.setItem(MARKER, 'uid-a');

    syncLocalIdentityOwner('uid-b');

    expect(localStorage.getItem(MARKER)).toBe('uid-b');
    for (const key of USER_SCOPED_KEYS) {
      expect(localStorage.getItem(key)).toBeNull();
    }
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
    for (const [key, value] of Object.entries(device)) {
      expect(localStorage.getItem(key)).toBe(value);
    }
  });

  it('notifies same-tab storage listeners for each cleared key', () => {
    localStorage.setItem(STORAGE_KEYS.CUSTOM_IMPORTS, '[]');
    localStorage.setItem(MARKER, 'uid-a');
    const seen: (string | null)[] = [];
    const listener = (e: Event) => { seen.push((e as StorageEvent).key); };
    window.addEventListener('storage', listener);

    syncLocalIdentityOwner('uid-b');

    window.removeEventListener('storage', listener);
    expect(seen).toContain(STORAGE_KEYS.CUSTOM_IMPORTS);
  });

  it('is idempotent — a second clear for the same switch changes nothing', () => {
    seedUserScopedValues();
    localStorage.setItem(MARKER, 'uid-a');

    syncLocalIdentityOwner('uid-b');
    syncLocalIdentityOwner('uid-b');

    expect(localStorage.getItem(MARKER)).toBe('uid-b');
  });

  it('defers the clear while a FRESH Flow B merge grant is stashed', () => {
    const seeded = seedUserScopedValues();
    localStorage.setItem(MARKER, 'uid-a');
    const grant = JSON.stringify({ token: 'grant-token', minted_at: Date.now() });
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, grant);

    // The SIGNED_IN event outruns /auth/callback's grant redemption; the
    // sync must leave both the values AND the marker alone so the
    // callback's post-redeem sync makes the real claim/clear decision.
    syncLocalIdentityOwner('uid-b');

    expect(localStorage.getItem(MARKER)).toBe('uid-a');
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBe(grant);
    for (const [key, value] of Object.entries(seeded)) {
      expect(localStorage.getItem(key)).toBe(value);
    }

    // Grant consumed (redeemPendingMerge clears it on a definitive
    // verdict), redemption failed → the plain re-sync now clears.
    localStorage.removeItem(STORAGE_KEYS.MERGE_GRANT);
    syncLocalIdentityOwner('uid-b');
    expect(localStorage.getItem(MARKER)).toBe('uid-b');
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

  it('does NOT defer for a grant older than MERGE_GRANT_MAX_AGE_MS — removes it and clears', () => {
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
    syncLocalIdentityOwner('uid-b');

    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
    expect(localStorage.getItem(MARKER)).toBe('uid-b');
    for (const key of USER_SCOPED_KEYS) {
      expect(localStorage.getItem(key)).toBeNull();
    }
  });

  it('does NOT defer for an unparseable JSON grant slot (garbage can never redeem)', () => {
    seedUserScopedValues();
    localStorage.setItem(MARKER, 'uid-a');
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, '{not-json');

    syncLocalIdentityOwner('uid-b');

    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
    expect(localStorage.getItem(MARKER)).toBe('uid-b');
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBeNull();
  });
});

describe('merge-claim path ({ claim: true })', () => {
  it('rewrites the marker to the new uid and keeps all values', () => {
    const seeded = seedUserScopedValues();
    localStorage.setItem(MARKER, 'anon-uid');

    syncLocalIdentityOwner('account-uid', { claim: true });

    expect(localStorage.getItem(MARKER)).toBe('account-uid');
    for (const [key, value] of Object.entries(seeded)) {
      expect(localStorage.getItem(key)).toBe(value);
    }
  });

  it('claims even while the (already-redeemed) grant is still present', () => {
    localStorage.setItem(STORAGE_KEYS.CUSTOM_IMPORTS, '[]');
    localStorage.setItem(MARKER, 'anon-uid');
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, 'grant-token');

    syncLocalIdentityOwner('account-uid', { claim: true });

    expect(localStorage.getItem(MARKER)).toBe('account-uid');
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
    const restore = installStorage({ getItem: boom });
    try {
      expect(() => syncLocalIdentityOwner('uid-a')).not.toThrow();
    } finally {
      restore();
    }
  });

  it('does not throw when setItem/removeItem fail mid-clear', () => {
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
      expect(store.get(MARKER)).toBe('uid-a');
      expect(store.get(STORAGE_KEYS.PROFILE)).toBe('profile-json');
    } finally {
      restore();
    }
  });
});
