/*
 * loadProfile / ensureAnonSession (via getDeviceId) — R1 checkpoints 4/5.
 *
 * loadProfile's ORIGINAL bug: it captured its owner token BEFORE calling
 * ensureAnonSession, then validated the resolved device id against that
 * SAME pre-ensure token. For the browser's first-ever resolution the
 * pre-ensure token is uid:null, which can never equal a real resolved uid —
 * so the very first loadProfile() call on a fresh browser always returned
 * null, even though ensureAnonSession itself succeeded. The fix mirrors
 * getFavorites' established pattern: on a null-uid mismatch, re-capture a
 * fresh token and re-validate against the CURRENT state before continuing.
 *
 * ensureAnonSession's B1/B2 (reviewed, not modified this round): a stale
 * getSession()/signInAnonymously() resolution that loses a race against a
 * live onAuthChange event must never return the stale uid or mark 'synced'
 * for it; an unconfigured Supabase / a confirmed anonymous-sign-in failure
 * must only report 'local-only' once the local-only realm is actually
 * confirmed established (marker genuinely null), never merely attempted.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const {
  mockFrom,
  mockGetSession,
  mockSignInAnonymously,
  mockOnAuthStateChange,
  mockRpc,
} = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockFrom: vi.fn(),
    mockGetSession: vi.fn(),
    mockSignInAnonymously: vi.fn(),
    mockOnAuthStateChange: vi.fn(),
    mockRpc: vi.fn(),
  };
});

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: mockGetSession,
      signInAnonymously: mockSignInAnonymously,
      onAuthStateChange: mockOnAuthStateChange,
    },
    from: mockFrom,
    rpc: mockRpc,
    storage: { from: vi.fn() },
  }),
}));

import {
  advanceOwnerEpoch,
  captureOwnerToken,
  isOwnerScopedLoadError,
  OwnerScopedLoadError,
  syncLocalIdentityOwner,
} from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import {
  commitProfilePatch,
  getDeviceId,
  getStorageStatus,
  loadProfile,
  onAuthChange,
  OwnerNotReadyError,
} from './supabase';

const U1 = '11111111-1111-4111-8111-111111111111';
const U2 = '22222222-2222-4222-8222-222222222222';

function session(uid: string) {
  return { data: { session: { user: { id: uid, is_anonymous: true }, access_token: 't' } } };
}
function noSession() {
  return { data: { session: null } };
}

let liveAuthCallback: ((event: string, session: unknown) => void) | null = null;
let unsubscribe: (() => void) | null = null;

beforeEach(() => {
  localStorage.clear();
  mockFrom.mockReset();
  mockGetSession.mockReset();
  mockSignInAnonymously.mockReset();
  mockRpc.mockReset();
  liveAuthCallback = null;
  mockOnAuthStateChange.mockReset().mockImplementation((cb: (event: string, session: unknown) => void) => {
    liveAuthCallback = cb;
    return { data: { subscription: { unsubscribe: vi.fn() } } };
  });
  unsubscribe?.();
  unsubscribe = onAuthChange(() => {});
});

// loadProfile's in-flight dedup map deletes its own entry via a REAL
// setTimeout(...,0) after the promise settles (see supabase.ts) — never
// flushed by a plain `await`. Without draining it here, a later test that
// happens to land on the SAME (uid, epoch) dedup key before that timeout
// fires would incorrectly hit the PRIOR test's cached promise instead of
// exercising its own mocked SELECT.
afterEach(() => new Promise((r) => setTimeout(r, 0)));

// Post-027 every stored row carries a revision; a row without one is a
// FAILED read (see loadProfile), so the default here mirrors production
// rather than leaving it out. A test that cares pins its own.
function selectChain(data: unknown, error: unknown = null) {
  if (data && typeof data === 'object' && 'profile_data' in (data as object)) {
    data = { revision: 1, ...(data as Record<string, unknown>) };
  }
  const maybeSingle = vi.fn().mockResolvedValue({ data, error });
  const eq = vi.fn().mockReturnValue({ maybeSingle });
  return { select: vi.fn().mockReturnValue({ eq }) };
}

function profileVersionsTable(error: unknown = null) {
  return { insert: vi.fn().mockResolvedValue({ error }) };
}

describe('loadProfile: first-ever (null->uid) resolution', () => {
  it('a fresh browser with no identity resolved yet successfully loads the profile once ensureAnonSession resolves — the original bug returned null unconditionally here', async () => {
    expect(captureOwnerToken().uid).toBeNull();
    mockGetSession.mockResolvedValue(session(U1));
    mockFrom.mockImplementation(() => selectChain({ profile_data: { home_school: 'uiuc' } }));

    const result = await loadProfile();

    expect(result.source).toBe('cloud');
    expect(result.profile).toEqual({ home_school: 'uiuc' });
    expect(result.revision).toBe(1);
  });

  it('reports a CONFIRMED-absent row as such, and does NOT substitute the local mirror', async () => {
    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, U1);
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({ home_school: 'local-fallback' }));
    mockGetSession.mockResolvedValue(session(U1));
    mockFrom.mockImplementation(() => selectChain(null, null));

    const result = await loadProfile();

    // Pre-CAS this returned the mirror, which made "the cloud has no row"
    // indistinguishable from "the cloud has this row" — and the caller could
    // then neither create it nor reconcile it. The coordinator does that
    // reconciliation now, and it needs the honest answer.
    expect(result.source).toBe('cloud-absent');
    expect(result.profile).toBeNull();
    expect(result.revision).toBe(0);
  });

  it('a row WITHOUT a usable revision is a failed read, not a blind-writable profile', async () => {
    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, U1);
    mockGetSession.mockResolvedValue(session(U1));
    // A backend that has not applied migration 027.
    mockFrom.mockImplementation(() => ({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({ data: { profile_data: { a: 1 } }, error: null }),
        }),
      }),
    }));

    await expect(loadProfile()).rejects.toThrow('no usable revision');
  });
});

describe('loadProfile: identity moves on mid-flight', () => {
  it('U1 pending, U2 takes over globally before the SELECT resolves -> the U1-started call REJECTS (never U2\'s data, and never a null that reads as "no profile")', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);

    let resolveGetSession: (v: unknown) => void = () => {};
    mockGetSession.mockImplementationOnce(() => new Promise((r) => { resolveGetSession = r; }));
    mockFrom.mockImplementation(() => selectChain({ profile_data: { home_school: 'u2-data' } }));

    const promise = loadProfile();
    await liveAuthCallback?.('SIGNED_IN', session(U2).data.session); // authoritative switch while pending
    resolveGetSession(session(U1)); // stale resolution arrives late

    await expect(promise).rejects.toBeInstanceOf(OwnerNotReadyError);
  });

  it('U1 -> null -> U1 (same uid, but a genuinely different epoch): the ORIGINAL promise captured at the first U1 epoch drops even though the uid looks unchanged; a fresh loadProfile() call under the new epoch succeeds', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    const staleToken = captureOwnerToken();

    let resolveGetSession: (v: unknown) => void = () => {};
    mockGetSession.mockImplementationOnce(() => new Promise((r) => { resolveGetSession = r; }));
    mockFrom.mockImplementation(() => selectChain({ profile_data: { home_school: 'current-epoch' } }));

    const stalePromise = loadProfile();
    // Full cycle: U1 -> null -> U1 again, each a real transition (epoch bumps
    // both times even though the uid returns to U1).
    await liveAuthCallback?.('SIGNED_OUT', null);
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    resolveGetSession(session(U1)); // the stale call's own getSession() finally resolves

    // Same uid, different epoch: still an unattributable read, so it
    // rejects rather than reporting "no profile".
    await expect(stalePromise).rejects.toBeInstanceOf(OwnerNotReadyError);

    const freshToken = captureOwnerToken();
    expect(freshToken.epoch).not.toBe(staleToken.epoch);
    mockGetSession.mockResolvedValue(session(U1));
    const freshResult = await loadProfile();
    expect(freshResult.profile).toEqual({ home_school: 'current-epoch' });
  });
});

describe('loadProfile: a real SELECT error is not the same as a confirmed-absent row', () => {
  it('throws (does not silently fall back to local/default) on a real query error', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, U1);
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({ home_school: 'local-fallback' }));
    mockGetSession.mockResolvedValue(session(U1));
    mockFrom.mockImplementation(() => selectChain(null, { message: 'connection reset' }));

    await expect(loadProfile()).rejects.toThrow('connection reset');
  });

  it('reports a CONFIRMED-absent row (maybeSingle: data null, error null) rather than conflating it with a real error', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, U1);
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({ home_school: 'local-fallback' }));
    mockGetSession.mockResolvedValue(session(U1));
    mockFrom.mockImplementation(() => selectChain(null, null));

    const result = await loadProfile();

    expect(result.source).toBe('cloud-absent');
    expect(result.profile).toBeNull();
  });
});

/**
 * A read that resolved this browser's FIRST identity inside itself, and then
 * failed, is not the same as a read abandoned because somebody else took the
 * browser over. Only the first can be reported to the person looking at the
 * screen, so the failure has to say which identity it belongs to.
 *
 * Trust comes from the production guard, never from a shape: this asserts the
 * failure IS one and narrows it, so `ownerToken` below is only ever read off
 * a genuine capability.
 */
function scopedCapability(err: unknown): OwnerScopedLoadError {
  expect(isOwnerScopedLoadError(err),
    'the failure is a real scoped capability, not an object shaped like one')
    .toBe(true);
  return err as OwnerScopedLoadError;
}

/** For NEGATIVE cases only: what an object CLAIMS, without trusting it. */
function claimedOwnerToken(err: unknown): unknown {
  return (err as { ownerToken?: unknown } | null | undefined)?.ownerToken;
}

function caught(p: Promise<unknown>): Promise<unknown> {
  return p.then(() => null, (e) => e);
}

describe('loadProfile: a failure after the first resolution names the identity it belongs to', () => {
  it('LP1: a SELECT error carries exactly the identity the read itself resolved', async () => {
    advanceOwnerEpoch(null);
    expect(captureOwnerToken().uid, 'nobody is signed in yet').toBeNull();
    mockGetSession.mockResolvedValue(session(U1));
    mockFrom.mockImplementation(() => selectChain(null, { message: 'connection reset' }));

    const err = await caught(loadProfile());
    expect(err, 'the read really failed').toBeTruthy();

    // The identity the read resolved for itself, read back from the shared
    // primitive it advanced.
    const resolved = captureOwnerToken();
    expect(resolved.uid, 'which is the one it resolved').toBe(U1);
    expect(scopedCapability(err).ownerToken,
      'carrying that exact capability').toEqual(resolved);
  });

  it('LP2: an unusable revision is the same kind of failure, and names the same identity', async () => {
    advanceOwnerEpoch(null);
    expect(captureOwnerToken().uid, 'nobody is signed in yet').toBeNull();
    mockGetSession.mockResolvedValue(session(U1));
    mockFrom.mockImplementation(() => ({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({
            data: { profile_data: { a: 1 } }, error: null,
          }),
        }),
      }),
    }));

    const err = await caught(loadProfile());
    const resolved = captureOwnerToken();
    expect(String((err as Error)?.message), 'it is still the same complaint')
      .toContain('no usable revision');
    expect(scopedCapability(err).ownerToken, 'to the identity that read')
      .toEqual(resolved);
  });

  it('LP5: a SELECT that REJECTS outright is scoped the same way, complaint intact', async () => {
    advanceOwnerEpoch(null);
    expect(captureOwnerToken().uid, 'nobody is signed in yet').toBeNull();
    mockGetSession.mockResolvedValue(session(U1));
    // Not a returned `{ error }` — the request itself rejects, which is what
    // a dropped connection actually looks like.
    mockFrom.mockImplementation(() => ({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockRejectedValue(new Error('network down')),
        }),
      }),
    }));

    const err = await caught(loadProfile());
    const resolved = captureOwnerToken();

    expect(resolved.uid, 'the read resolved its own first identity').toBe(U1);
    expect(scopedCapability(err).ownerToken, 'carrying that exact capability')
      .toEqual(resolved);
    const carried = `${(err as Error)?.message} ${String((err as { cause?: Error })?.cause?.message ?? '')}`;
    expect(carried, 'and the original complaint survives').toContain('network down');
  });

  /** A SELECT the test settles by hand, with a handshake for its issue. */
  function heldSelect() {
    let announce!: () => void;
    const issued = new Promise<void>((resolve) => { announce = resolve; });
    let finish!: (v: { data: unknown; error: unknown }) => void;
    const maybeSingle = vi.fn(() => new Promise((resolve) => {
      finish = resolve as (v: { data: unknown; error: unknown }) => void;
      announce();
    }));
    const eq = vi.fn().mockReturnValue({ maybeSingle });
    return {
      chain: { select: vi.fn().mockReturnValue({ eq }) },
      issued,
      settle: (v: { data: unknown; error: unknown }) => finish(v),
    };
  }

  it('LP6: a failure that is ALREADY scoped comes back as the very same object', async () => {
    advanceOwnerEpoch(null);
    mockGetSession.mockResolvedValue(session(U1));
    // Raised by something further down that already knew whose read this was
    // — a different identity, deliberately, so a re-wrap would be visible.
    const original = new OwnerScopedLoadError(
      { uid: 'deeper-layer-uid', epoch: 42, generation: 0 },
      new Error('deeper failure'),
    );
    mockFrom.mockImplementation(() => ({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockRejectedValue(original),
        }),
      }),
    }));

    const err = await caught(loadProfile());

    expect(err, 'the very same failure, unrepackaged').toBe(original);
    expect(scopedCapability(err).ownerToken, 'still naming who it was raised for')
      .toEqual({ uid: 'deeper-layer-uid', epoch: 42, generation: 0 });
  });

  /** A browser that can no longer keep its own ownership marker — private
   *  mode, a full quota, another tab's sweep. Reads pass through; the marker
   *  is gone and cannot be written back, so the realm is never confirmed. */
  function markerUnwritable() {
    const real = window.localStorage;
    real.removeItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER);
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => real.getItem(k),
        setItem: (k: string, v: string) => {
          if (k === STORAGE_KEYS.LOCAL_IDENTITY_OWNER) throw new Error('quota');
          real.setItem(k, v);
        },
        removeItem: (k: string) => real.removeItem(k),
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    return () => Object.defineProperty(
      window, 'localStorage', { configurable: true, value: real },
    );
  }

  it('LP-prefirst-realm: a first resolution whose realm cannot be confirmed is still theirs', async () => {
    advanceOwnerEpoch(null);
    expect(captureOwnerToken().uid, 'nobody is signed in yet').toBeNull();
    mockGetSession.mockResolvedValue(session(U1));
    // The check that notices this happens BEFORE any SELECT goes out.
    const restore = markerUnwritable();
    mockFrom.mockImplementation(() => selectChain({ profile_data: {} }));

    try {
      const err = await caught(loadProfile());
      const resolved = captureOwnerToken();
      expect(resolved.uid, 'the identity really did resolve').toBe(U1);
      expect(scopedCapability(err).ownerToken,
        'and the failure is theirs, named as theirs').toEqual(resolved);
      expect((err as Error).cause, 'with the reason kept')
        .toBeInstanceOf(OwnerNotReadyError);
    } finally {
      restore();
    }
  });

  it('LP-known-realm: a KNOWN owner whose realm fails before the SELECT is also theirs', async () => {
    // An identity already established, so the pre-ensure token is non-null.
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    await syncLocalIdentityOwner(U1);
    const known = captureOwnerToken();
    expect(known.uid, 'this read starts with a known owner').toBe(U1);
    mockGetSession.mockResolvedValue(session(U1));
    const restore = markerUnwritable();
    mockFrom.mockImplementation(() => selectChain({ profile_data: {} }));

    try {
      const err = await caught(loadProfile());
      expect(scopedCapability(err).ownerToken,
        'the same person, and the failure is theirs').toEqual(known);
      expect((err as Error).cause, 'with the reason kept')
        .toBeInstanceOf(OwnerNotReadyError);
    } finally {
      restore();
    }
  });

  it('LP-current-realm: the same owner with unconfirmed local data gets a SCOPED failure', async () => {
    advanceOwnerEpoch(null);
    expect(captureOwnerToken().uid, 'nobody is signed in yet').toBeNull();
    mockGetSession.mockResolvedValue(session(U1));
    const held = heldSelect();
    mockFrom.mockImplementation(() => held.chain);

    const promise = loadProfile();
    await held.issued;
    const resolved = captureOwnerToken();
    expect(resolved.uid, 'the read resolved its own first identity').toBe(U1);

    // NOBODY takes over. What goes is this browser's proof that its local
    // data belongs to U1 — another tab's sweep, a marker that cannot be read
    // back. Same person, same epoch, unusable storage.
    localStorage.removeItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER);
    held.settle({ data: { profile_data: { home_school: 'uiuc' }, revision: 1 }, error: null });

    const err = await caught(promise);
    expect(scopedCapability(err).ownerToken,
      "their own unusable browser is their failure, named as theirs")
      .toEqual(resolved);
    expect((err as Error).cause,
      'with the reason it could not be trusted kept').toBeInstanceOf(OwnerNotReadyError);
  });

  it('LP4: a takeover AFTER the read resolved its own identity is still not-ready', async () => {
    advanceOwnerEpoch(null);
    expect(captureOwnerToken().uid, 'nobody is signed in yet').toBeNull();
    mockGetSession.mockResolvedValue(session(U1));
    const held = heldSelect();
    mockFrom.mockImplementation(() => held.chain);

    const promise = loadProfile();
    await held.issued;
    // The read has already promoted its own first identity by this point —
    // this is the window the new wrapper must NOT mistake for its own.
    const resolved = captureOwnerToken();
    expect(resolved.uid, 'the read resolved this browser\'s first identity').toBe(U1);

    // Only NOW does somebody else authoritatively take the browser over.
    await liveAuthCallback?.('SIGNED_IN', session(U2).data.session);
    held.settle({ data: { profile_data: { home_school: 'u2-data' }, revision: 1 }, error: null });

    const err = await caught(promise);
    expect(err, 'the read is abandoned, not reported').toBeInstanceOf(OwnerNotReadyError);
    expect(claimedOwnerToken(err),
      'and it is scoped to nobody — least of all the new owner').toBeUndefined();
    expect(captureOwnerToken().uid, 'the browser belongs to somebody else now').toBe(U2);
    expect(resolved.uid, 'and the identity that read is not them').not.toBe(U2);
  });

  it('LP3: an external takeover is not-ready, and is never tagged as the new owner', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    let resolveGetSession: (v: unknown) => void = () => {};
    mockGetSession.mockImplementationOnce(() => new Promise((r) => { resolveGetSession = r; }));
    mockFrom.mockImplementation(() => selectChain({ profile_data: { home_school: 'u2-data' } }));

    const promise = loadProfile();
    await liveAuthCallback?.('SIGNED_IN', session(U2).data.session);
    resolveGetSession(session(U1));

    const err = await caught(promise);
    expect(err, 'the read is abandoned').toBeInstanceOf(OwnerNotReadyError);
    expect(claimedOwnerToken(err),
      'and it claims nobody — least of all the identity that took over')
      .toBeUndefined();
  });
});

describe('loadProfile: dedup', () => {
  it('two concurrent calls for the SAME (uid, epoch) collapse onto a single SELECT', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    let resolveGetSession: (v: unknown) => void = () => {};
    mockGetSession.mockImplementationOnce(() => new Promise((r) => { resolveGetSession = r; }));
    const chain = selectChain({ profile_data: { home_school: 'dedup' } });
    mockFrom.mockImplementation(() => chain);

    const p1 = loadProfile();
    const p2 = loadProfile();
    resolveGetSession(session(U1));

    const [r1, r2] = await Promise.all([p1, p2]);
    expect(r1.profile).toEqual({ home_school: 'dedup' });
    expect(r2.profile).toEqual({ home_school: 'dedup' });
    expect(mockFrom).toHaveBeenCalledTimes(1);
  });
});

describe('ensureAnonSession (via getDeviceId): B1 stale-drop', () => {
  it('a stale getSession() resolution for U1 arriving after a live switch to U2 does not return U1, and does not mark storage synced for the stale observation', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);

    let resolveStale: (v: unknown) => void = () => {};
    mockGetSession.mockImplementationOnce(() => new Promise((r) => { resolveStale = r; }));

    const stalePromise = getDeviceId();
    await liveAuthCallback?.('SIGNED_IN', session(U2).data.session); // authoritative switch while pending
    resolveStale(session(U1));

    const result = await stalePromise;
    expect(result).toBe(U2); // returns the CURRENT global owner, not the stale U1
    expect(captureOwnerToken().uid).toBe(U2);
  });
});

describe('ensureAnonSession (via getDeviceId): B2 confirmed local-only degrade', () => {
  it('a confirmed anonymous sign-in failure marks storage local-only only once the local-only realm is actually established (no prior account marker)', async () => {
    mockGetSession.mockResolvedValue(noSession());
    mockSignInAnonymously.mockResolvedValue({ data: { user: null }, error: { message: 'Anonymous sign-ins are disabled' } });

    const result = await getDeviceId();

    expect(result).toBeNull();
    expect(getStorageStatus().status).toBe('local-only');
  });

  it('does NOT mark local-only when a real prior account already claims this browser (marker non-null) — the confirmed-degrade realm must refuse to paper over real data', async () => {
    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, U1);
    await liveAuthCallback?.('SIGNED_OUT', null); // establish the null owner window first
    mockGetSession.mockResolvedValue(noSession());
    mockSignInAnonymously.mockResolvedValue({ data: { user: null }, error: { message: 'Anonymous sign-ins are disabled' } });

    const result = await getDeviceId();

    expect(result).toBeNull();
    expect(getStorageStatus().status).not.toBe('local-only');
  });
});

describe('commitProfilePatch: the only write path', () => {
  function rpcOk(payload: Record<string, unknown>) {
    return vi.fn().mockResolvedValue({ data: payload, error: null });
  }

  it('sends the patch, the expected revision and the ORIGIN uid — and nothing else', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    mockGetSession.mockResolvedValue(session(U1));
    const rpc = rpcOk({ status: 'applied', revision: 8, profile: { major: 'ECE' } });
    mockRpc.mockImplementation(rpc);

    const outcome = await commitProfilePatch({
      expectedRevision: 7,
      patch: { major: 'ECE' },
      token: captureOwnerToken(),
      mutationId: 'm1',
    });

    expect(rpc).toHaveBeenCalledWith('commit_profile_patch_cas', {
      p_expected_device_id: U1,
      p_expected_revision: 7,
      p_patch: { major: 'ECE' },
    });
    expect(outcome).toEqual({ status: 'saved', revision: 8, profile: { major: 'ECE' } });
    // No direct table write anywhere: the RPC does the row AND its history.
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('maps unchanged -> already-saved, conflict -> conflict, missing -> missing', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    mockGetSession.mockResolvedValue(session(U1));
    const token = captureOwnerToken();
    const call = (patch: Record<string, unknown>) => commitProfilePatch({
      expectedRevision: 7, patch, token, mutationId: 'm',
    });

    mockRpc.mockResolvedValueOnce({ data: { status: 'unchanged', revision: 8, profile: { a: 1 } }, error: null });
    expect(await call({ a: 1 })).toEqual({ status: 'already-saved', revision: 8, profile: { a: 1 } });

    mockRpc.mockResolvedValueOnce({ data: { status: 'conflict', revision: 9, profile: { a: 2 } }, error: null });
    expect(await call({ a: 1 })).toEqual({ status: 'conflict', revision: 9, profile: { a: 2 } });

    mockRpc.mockResolvedValueOnce({ data: { status: 'missing', reason: 'merged_away' }, error: null });
    expect(await call({ a: 1 })).toEqual({ status: 'missing', reason: 'merged_away' });
  });

  it('an unknown status, an unknown missing reason, or a revision below 1 is MALFORMED, never a success', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    mockGetSession.mockResolvedValue(session(U1));
    const token = captureOwnerToken();
    const call = () => commitProfilePatch({
      expectedRevision: 7, patch: { a: 1 }, token, mutationId: 'm',
    });

    mockRpc.mockResolvedValueOnce({ data: { status: 'quarantined' }, error: null });
    expect((await call()).status).toBe('malformed');

    mockRpc.mockResolvedValueOnce({ data: { status: 'missing', reason: 'legal_hold' }, error: null });
    expect((await call()).status).toBe('malformed');

    mockRpc.mockResolvedValueOnce({ data: { status: 'applied', revision: 0, profile: { a: 1 } }, error: null });
    expect((await call()).status).toBe('malformed');

    // A JSON array is not a profile.
    mockRpc.mockResolvedValueOnce({ data: { status: 'applied', revision: 2, profile: [] }, error: null });
    expect((await call()).status).toBe('malformed');

    // ... and a null one is not either.
    mockRpc.mockResolvedValueOnce({ data: { status: 'applied', revision: 2, profile: null }, error: null });
    expect((await call()).status).toBe('malformed');
  });

  it('refuses to send an empty patch or a nonsense revision — without a round trip', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    mockGetSession.mockResolvedValue(session(U1));
    const token = captureOwnerToken();

    expect((await commitProfilePatch({ expectedRevision: 7, patch: {}, token, mutationId: 'm' })).status)
      .toBe('malformed');
    expect((await commitProfilePatch({ expectedRevision: -1, patch: { a: 1 }, token, mutationId: 'm' })).status)
      .toBe('malformed');
    expect(mockRpc).not.toHaveBeenCalled();
  });

  it('a stale token abandons BEFORE any request', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    const stale = captureOwnerToken();
    await liveAuthCallback?.('SIGNED_IN', session(U2).data.session);
    mockGetSession.mockResolvedValue(session(U2));

    const outcome = await commitProfilePatch({
      expectedRevision: 7, patch: { a: 1 }, token: stale, mutationId: 'm',
    });
    expect(outcome).toEqual({ status: 'abandoned' });
    expect(mockRpc).not.toHaveBeenCalled();
  });

  it('an identity switch DURING the request abandons the outcome instead of reporting it', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    mockGetSession.mockResolvedValue(session(U1));
    const token = captureOwnerToken();
    let release!: (v: unknown) => void;
    mockRpc.mockImplementationOnce(() => new Promise((r) => { release = r as never; }));

    const promise = commitProfilePatch({
      expectedRevision: 7, patch: { a: 1 }, token, mutationId: 'm',
    });
    for (let i = 0; i < 30 && mockRpc.mock.calls.length === 0; i += 1) await Promise.resolve();
    await liveAuthCallback?.('SIGNED_IN', session(U2).data.session);
    release({ data: { status: 'applied', revision: 8, profile: { a: 1 } }, error: null });

    expect(await promise).toEqual({ status: 'abandoned' });
  });

  it('a token whose owner MOVED ON is abandoned, before any network call', async () => {
    // The other half of the distinction below: this one really is somebody
    // else's write, and it must never reach the wire.
    const stale = captureOwnerToken();
    advanceOwnerEpoch('someone-else');
    await syncLocalIdentityOwner('someone-else');

    const outcome = await commitProfilePatch({
      expectedRevision: 7, patch: { a: 1 }, token: stale, mutationId: 'm',
    });
    expect(outcome.status).toBe('abandoned');
    expect(mockRpc).not.toHaveBeenCalled();
    expect(mockSignInAnonymously).not.toHaveBeenCalled();
  });

  it('reports local-only (never a failure) when there is no cloud backend', async () => {
    mockGetSession.mockResolvedValue(noSession());
    mockSignInAnonymously.mockResolvedValue({ data: { user: null }, error: { message: 'disabled' } });

    const outcome = await commitProfilePatch({
      expectedRevision: 7, patch: { a: 1 }, token: captureOwnerToken(), mutationId: 'm',
    });
    expect(outcome.status).toBe('local-only');
    expect(mockRpc).not.toHaveBeenCalled();
  });

  it('a transport error is retriable, not a silent success', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    mockGetSession.mockResolvedValue(session(U1));
    mockRpc.mockResolvedValue({ data: null, error: { message: 'permission denied' } });

    const outcome = await commitProfilePatch({
      expectedRevision: 7, patch: { a: 1 }, token: captureOwnerToken(), mutationId: 'm',
    });
    expect(outcome).toEqual({ status: 'transport-error', message: 'permission denied' });
  });
});

describe('commitProfilePatch: one serialization domain for the whole profile row', () => {
  it('a second write for the same owner does not start until the first has settled — whichever screen it came from', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    mockGetSession.mockResolvedValue(session(U1));
    const token = captureOwnerToken();

    let releaseFirst!: (v: unknown) => void;
    mockRpc
      .mockImplementationOnce(() => new Promise((r) => { releaseFirst = r as never; }))
      .mockResolvedValueOnce({ data: { status: 'applied', revision: 9, profile: { b: 2 } }, error: null });

    const first = commitProfilePatch({ expectedRevision: 7, patch: { a: 1 }, token, mutationId: 'm1' });
    const second = commitProfilePatch({ expectedRevision: 8, patch: { b: 2 }, token, mutationId: 'm2' });

    for (let i = 0; i < 30; i += 1) await Promise.resolve();
    expect(mockRpc).toHaveBeenCalledTimes(1); // the second is still queued

    releaseFirst({ data: { status: 'applied', revision: 8, profile: { a: 1 } }, error: null });
    const [a, b] = await Promise.all([first, second]);
    expect(a.status).toBe('saved');
    expect(b.status).toBe('saved');
    expect(mockRpc).toHaveBeenCalledTimes(2);
  });
});


describe('loadProfile: an unverified read is an error, never an empty profile', () => {
  it('rejects (does not return null) while a Flow-B grant keeps local ownership blocked, then reads the real row once it clears', async () => {
    // The documented deferral: a stashed merge grant means the guest's
    // local data must not be cleared yet, so ownership for this uid stays
    // BLOCKED even though the identity itself is perfectly current.
    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, U2);
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, 'grant-token');
    mockGetSession.mockResolvedValue(session(U1));
    mockFrom.mockImplementation(() => selectChain({ profile_data: { major: 'CS', resume_text: 'rich row' } }));

    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    expect(getStorageStatus().status).toBe('unknown');

    // Still a rejection, never a null that would read as "no profile" — and
    // now it says whose it is: the identity itself is perfectly current, so
    // this is U1's own read failing on a browser that cannot yet vouch for
    // its data, not a read abandoned to nobody.
    const blocked = await caught(loadProfile());
    expect(scopedCapability(blocked).ownerToken, "named as U1's own")
      .toMatchObject({ uid: U1 });
    expect((blocked as Error).cause, 'for the reason it always was')
      .toBeInstanceOf(OwnerNotReadyError);
    expect(mockFrom).not.toHaveBeenCalled();

    // The callback redeems the grant; the next observation of the SAME uid
    // clears and claims for real.
    localStorage.removeItem(STORAGE_KEYS.MERGE_GRANT);
    await liveAuthCallback?.('TOKEN_REFRESHED', session(U1).data.session);
    expect(getStorageStatus().status).toBe('synced');

    await expect(loadProfile()).resolves.toMatchObject({
      source: 'cloud',
      profile: { major: 'CS', resume_text: 'rich row' },
    });
  });

  it('rejects when the identity changes DURING the row SELECT, rather than reporting no profile', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    mockGetSession.mockResolvedValue(session(U1));
    let resolveSelect!: (v: { data: unknown; error: unknown }) => void;
    const maybeSingle = vi.fn().mockReturnValue(new Promise((r) => { resolveSelect = r as never; }));
    mockFrom.mockImplementation(() => ({
      select: vi.fn().mockReturnValue({ eq: vi.fn().mockReturnValue({ maybeSingle }) }),
    }));

    const promise = loadProfile();
    for (let i = 0; i < 30 && maybeSingle.mock.calls.length === 0; i += 1) await Promise.resolve();
    expect(maybeSingle).toHaveBeenCalledTimes(1);
    await liveAuthCallback?.('SIGNED_IN', session(U2).data.session); // switch mid-SELECT
    resolveSelect({ data: { profile_data: { major: 'U1 major' } }, error: null });

    await expect(promise).rejects.toBeInstanceOf(OwnerNotReadyError);
  });

  it('reports cloud-absent (not a row, not an error) for a CONFIRMED-absent row once ownership is verified', async () => {
    await liveAuthCallback?.('SIGNED_IN', session(U1).data.session);
    mockGetSession.mockResolvedValue(session(U1));
    mockFrom.mockImplementation(() => selectChain(null));

    await expect(loadProfile()).resolves.toMatchObject({ source: 'cloud-absent', profile: null });
  });
});
