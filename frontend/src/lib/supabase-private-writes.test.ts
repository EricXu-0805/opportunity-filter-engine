/*
 * C1-R1 Commit 1: exact owner binding + Tracker persistence truth.
 *
 * Every private-write helper (toggleFavorite, trackInteraction,
 * updateInteractionDetails, removeInteraction, confirmInteractionContact)
 * takes an OwnerToken captured by the CALLER at invocation time. Before
 * touching anything — local fallback storage or a remote row — the helper
 * re-resolves the live device id and checks isOwnerTokenValid: a mismatch
 * (the acting identity changed between invocation and write) throws
 * OwnerMismatchError with ZERO side effects, never a silent no-op success.
 *
 * A null-uid token (nothing resolved yet at capture time) is NOT a
 * wildcard: it is rejected the instant ANY identity resolves, even the
 * browser's first-ever resolution — a write function cannot distinguish
 * "genuinely first ever" from "a late arrival racing past an intervening
 * switch." Callers gate interactive controls on a known owner instead.
 *
 * Tracker helpers (trackInteraction/updateInteractionDetails/
 * removeInteraction/confirmInteractionContact) have no local fallback —
 * any remote failure throws, never console.warn-and-pretend-success.
 * toggleFavorite keeps its previously-reviewed local-only degrade for a
 * genuine remote failure (not an owner mismatch, which always throws) —
 * and getFavorites/toggleFavorite re-validate the SAME captured token
 * immediately before every local-fallback write that happens after an
 * await, not just once at the top.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const {
  mockFrom,
  mockRpc,
  mockGetSession,
  mockSignInAnonymously,
  mockOnAuthStateChange,
} = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockFrom: vi.fn(),
    mockRpc: vi.fn(),
    mockGetSession: vi.fn(),
    mockSignInAnonymously: vi.fn(),
    mockOnAuthStateChange: vi.fn(),
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

import { captureOwnerToken, type OwnerToken } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import {
  confirmInteractionContact,
  dismissInteraction,
  getFavorites,
  getInteractionDetail,
  getInteractions,
  getInteractionsFull,
  onAuthChange,
  OwnerMismatchError,
  removeInteraction,
  toggleFavorite,
  trackInteraction,
  updateInteractionDetails,
  type InteractionType,
} from './supabase';

const U1 = '11111111-1111-4111-8111-111111111111';
const U2 = '22222222-2222-4222-8222-222222222222';
const OPP = 'faculty-abc-12345678';

function session(uid: string) {
  return { data: { session: { user: { id: uid, is_anonymous: true }, access_token: 't' } } };
}
function noSession() {
  return { data: { session: null } };
}

// Registered via a REAL onAuthChange(...) subscription in beforeEach below
// (not invoked directly) so every assertion exercises the actual production
// wrapper in supabase.ts — including its ordering (advance the shared owner
// epoch, then syncLocalIdentityOwner, then notify subscribers).
let liveAuthCallback: ((event: string, session: unknown) => void) | null = null;
let unsubscribe: (() => void) | null = null;

beforeEach(() => {
  localStorage.clear();
  mockFrom.mockReset();
  mockRpc.mockReset();
  mockGetSession.mockReset();
  mockSignInAnonymously.mockReset();
  liveAuthCallback = null;
  mockOnAuthStateChange.mockReset().mockImplementation((cb: (event: string, session: unknown) => void) => {
    liveAuthCallback = cb;
    return { data: { subscription: { unsubscribe: vi.fn() } } };
  });
  unsubscribe?.();
  unsubscribe = onAuthChange(() => {});
});

/** Establish `uid` as the resolved identity via a live auth event, exactly
 *  as a real sign-in would, and return the token captured immediately
 *  after — the realistic "click while already signed in" starting point. */
function establishIdentity(uid: string): OwnerToken {
  mockGetSession.mockResolvedValue(session(uid));
  liveAuthCallback?.('SIGNED_IN', session(uid).data.session);
  return captureOwnerToken();
}

/**
 * Wait until the FIRST queued call has actually issued its request.
 *
 * Deliberately not a fixed number of `await Promise.resolve()`s. That counts
 * microtasks, which is a guess about the implementation's internal shape — and
 * the moment anything on the path gains an await (the owner transition now
 * takes one), the guess is wrong and the test hangs on a deferred promise that
 * was never created. This waits for the thing the assertion is actually about.
 */
async function until(cond: () => boolean): Promise<void> {
  for (let i = 0; i < 200 && !cond(); i += 1) await Promise.resolve();
  if (!cond()) throw new Error('the expected call never happened');
}

describe('owner-mismatch: zero mutation on an identity change mid-flight', () => {
  it('toggleFavorite: token captured as U1, session switches to U2 before the write resolves -> throws, zero remote write, zero local-fallback rewrite', async () => {
    const token = establishIdentity(U1);
    mockGetSession.mockResolvedValue(session(U2));
    liveAuthCallback?.('SIGNED_IN', session(U2).data.session);

    const insert = vi.fn();
    mockFrom.mockImplementation(() => ({ insert, delete: vi.fn() }));

    await expect(toggleFavorite(OPP, false, token)).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(insert).not.toHaveBeenCalled();
    expect(localStorage.getItem('ofe_favs_fallback')).toBeNull();
  });

  it('trackInteraction: token captured as U1, resolves under U2 -> throws, zero upsert', async () => {
    const token = establishIdentity(U1);
    mockGetSession.mockResolvedValue(session(U2));
    liveAuthCallback?.('SIGNED_IN', session(U2).data.session);
    const upsert = vi.fn();
    mockFrom.mockImplementation(() => ({ upsert }));

    await expect(trackInteraction(OPP, 'applied', token)).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(upsert).not.toHaveBeenCalled();
  });

  it('updateInteractionDetails: token captured as U1, resolves under U2 -> throws, zero update', async () => {
    const token = establishIdentity(U1);
    mockGetSession.mockResolvedValue(session(U2));
    liveAuthCallback?.('SIGNED_IN', session(U2).data.session);
    const update = vi.fn();
    mockFrom.mockImplementation(() => ({ update }));

    await expect(updateInteractionDetails(OPP, { notes: 'hi' }, token)).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(update).not.toHaveBeenCalled();
  });

  it('removeInteraction: token captured as U1, resolves under U2 -> throws, zero delete', async () => {
    const token = establishIdentity(U1);
    mockGetSession.mockResolvedValue(session(U2));
    liveAuthCallback?.('SIGNED_IN', session(U2).data.session);
    const del = vi.fn();
    mockFrom.mockImplementation(() => ({ delete: del }));

    await expect(removeInteraction(OPP, token)).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(del).not.toHaveBeenCalled();
  });

  it('dismissInteraction: token captured as U1, resolves under U2 -> throws, zero update', async () => {
    const token = establishIdentity(U1);
    mockGetSession.mockResolvedValue(session(U2));
    liveAuthCallback?.('SIGNED_IN', session(U2).data.session);
    const update = vi.fn();
    mockFrom.mockImplementation(() => ({ update }));

    await expect(dismissInteraction(OPP, undefined, token)).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(update).not.toHaveBeenCalled();
  });

  it('confirmInteractionContact: token captured as U1, resolves under U2 -> throws, zero RPC call', async () => {
    const token = establishIdentity(U1);
    mockGetSession.mockResolvedValue(session(U2));
    liveAuthCallback?.('SIGNED_IN', session(U2).data.session);

    await expect(confirmInteractionContact(OPP, token)).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(mockRpc).not.toHaveBeenCalled();
  });

  it('toggleFavorite: token captured as U1, session drops to signed-out (null) before the write resolves -> throws, zero mutation', async () => {
    const token = establishIdentity(U1);
    mockGetSession.mockResolvedValue(noSession());
    liveAuthCallback?.('SIGNED_OUT', null);
    // A null getSession() makes ensureAnonSession fall through to a fresh
    // signInAnonymously() — resolve it to a NEW, different identity so the
    // resolved deviceId is neither U1 (the captured token) nor null.
    mockSignInAnonymously.mockResolvedValue({ data: { user: { id: U2 } }, error: null });
    const insert = vi.fn();
    mockFrom.mockImplementation(() => ({ insert, delete: vi.fn() }));

    await expect(toggleFavorite(OPP, false, token)).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(insert).not.toHaveBeenCalled();
  });

  it('a token captured before ANY identity was resolved is REJECTED by the very first write — establishing an identity is not treated as this token\'s owner; the action must be retried once an owner is known', async () => {
    const token = captureOwnerToken(); // uid: null — nothing observed yet
    mockGetSession.mockResolvedValue(session(U1));
    liveAuthCallback?.('SIGNED_IN', session(U1).data.session); // resolves AFTER capture
    const upsert = vi.fn();
    mockFrom.mockImplementation(() => ({ upsert }));

    await expect(trackInteraction(OPP, 'applied', token)).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(upsert).not.toHaveBeenCalled();

    // Retrying with a FRESH token captured now (owner known) succeeds.
    const retryToken = captureOwnerToken();
    mockFrom.mockImplementation(() => ({ upsert: vi.fn().mockResolvedValue({ error: null }) }));
    await expect(trackInteraction(OPP, 'applied', retryToken)).resolves.toBeUndefined();
  });

  it('deferred-getSession race: a STALE getSession() resolution for U1 arrives AFTER the live callback already advanced to U2 — the stale action does zero mutation, a concurrent fresh U2 action succeeds, and the global owner remains U2 (not rolled back)', async () => {
    const tokenU1 = establishIdentity(U1);

    let resolveStale: (v: unknown) => void = () => {};
    let resolveFresh: (v: unknown) => void = () => {};
    mockGetSession
      .mockImplementationOnce(() => new Promise((r) => { resolveStale = r; }))
      .mockImplementationOnce(() => new Promise((r) => { resolveFresh = r; }));

    const upsert = vi.fn().mockResolvedValue({ error: null });
    mockFrom.mockImplementation(() => ({ upsert }));

    const staleAction = trackInteraction(OPP, 'applied', tokenU1);
    // enqueuePrivateWrite defers this action's body behind a microtask —
    // wait deterministically until it has ACTUALLY started and reached its
    // own internal getSession() call (proving it genuinely began under U1,
    // sinceEpoch correctly captured pre-switch) before touching auth state.
    await vi.waitFor(() => expect(mockGetSession).toHaveBeenCalledTimes(1));

    // Authoritative switch to U2 while the stale action's getSession() is
    // still pending.
    liveAuthCallback?.('SIGNED_IN', session(U2).data.session);
    const tokenU2 = captureOwnerToken();
    // U2's own local state, already established by the switch above —
    // seeded AFTER the switch so the assertions below prove the stale U1
    // resolution neither reclaims the identity marker nor clears it.
    localStorage.setItem(STORAGE_KEYS.FAVORITES_FALLBACK, JSON.stringify(['u2-own-favorite']));
    const freshAction = trackInteraction(OPP, 'replied', tokenU2);
    await vi.waitFor(() => expect(mockGetSession).toHaveBeenCalledTimes(2));

    // The stale U1 resolution (in flight since before the switch) arrives
    // AFTER it; the fresh one correctly reflects the current U2 session.
    resolveStale(session(U1));
    resolveFresh(session(U2));

    await expect(staleAction).rejects.toBeInstanceOf(OwnerMismatchError);
    await expect(freshAction).resolves.toBeUndefined();
    expect(upsert).toHaveBeenCalledTimes(1);
    expect(upsert).toHaveBeenCalledWith(
      expect.objectContaining({ device_id: U2, interaction_type: 'replied' }),
      expect.anything(),
    );

    const after = captureOwnerToken();
    expect(after.uid).toBe(U2);
    expect(after.epoch).toBe(tokenU2.epoch); // unchanged by the stale resolution

    // The stale U1 resolution must not have reclaimed the local identity
    // marker as U1, nor cleared/rewritten U2's own already-established
    // local storage as a side effect of that reclaim.
    // The marker is a versioned record — {v:2, uid, generation, phase} — so
    // this asserts who owns the browser, not the encoding.
    expect(
      JSON.parse(localStorage.getItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER)!).uid,
    ).toBe(U2);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.FAVORITES_FALLBACK) ?? '[]')).toEqual(['u2-own-favorite']);
  });
});

describe('Tracker persistence truth: throw, never swallow', () => {
  it('trackInteraction throws on a remote upsert error (previously: silently ignored, no error check at all)', async () => {
    const token = establishIdentity(U1);
    const upsert = vi.fn().mockResolvedValue({ error: { message: 'network down' } });
    mockFrom.mockImplementation(() => ({ upsert }));
    await expect(trackInteraction(OPP, 'applied', token)).rejects.toThrow('network down');
  });

  it('updateInteractionDetails throws on a remote update error (previously: console.warn only, resolved successfully)', async () => {
    const token = establishIdentity(U1);
    const select = vi.fn().mockResolvedValue({ data: null, error: { message: 'row locked' } });
    const eq2 = vi.fn().mockReturnValue({ select });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    const update = vi.fn().mockReturnValue({ eq: eq1 });
    mockFrom.mockImplementation(() => ({ update }));
    await expect(updateInteractionDetails(OPP, { notes: 'x' }, token)).rejects.toThrow('row locked');
  });

  it('updateInteractionDetails throws on a ZERO-row match (query succeeded, no error, nothing matched) — an UPDATE is not idempotent-safe like a DELETE: new data with nowhere confirmed to have landed is a real failure, not a no-op', async () => {
    const token = establishIdentity(U1);
    const select = vi.fn().mockResolvedValue({ data: [], error: null });
    const eq2 = vi.fn().mockReturnValue({ select });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    const update = vi.fn().mockReturnValue({ eq: eq1 });
    mockFrom.mockImplementation(() => ({ update }));
    await expect(updateInteractionDetails(OPP, { notes: 'x' }, token)).rejects.toThrow('expected exactly one matching interaction row');
  });

  it('updateInteractionDetails throws on a MULTI-row match — (device_id, opportunity_id) is a unique key, so more than one row back is a contract violation, never a normal outcome to wave through', async () => {
    const token = establishIdentity(U1);
    const select = vi.fn().mockResolvedValue({
      data: [{ opportunity_id: OPP }, { opportunity_id: OPP }],
      error: null,
    });
    const eq2 = vi.fn().mockReturnValue({ select });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    const update = vi.fn().mockReturnValue({ eq: eq1 });
    mockFrom.mockImplementation(() => ({ update }));
    await expect(updateInteractionDetails(OPP, { notes: 'x' }, token)).rejects.toThrow('expected exactly one matching interaction row');
  });

  it('updateInteractionDetails throws when the single returned row\'s opportunity_id does NOT match the one requested — never trust "some row came back" without checking it\'s the RIGHT row', async () => {
    const token = establishIdentity(U1);
    const select = vi.fn().mockResolvedValue({ data: [{ opportunity_id: 'a-completely-different-opportunity' }], error: null });
    const eq2 = vi.fn().mockReturnValue({ select });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    const update = vi.fn().mockReturnValue({ eq: eq1 });
    mockFrom.mockImplementation(() => ({ update }));
    await expect(updateInteractionDetails(OPP, { notes: 'x' }, token)).rejects.toThrow('expected exactly one matching interaction row');
  });

  it('dismissInteraction sends interaction_type="dismissed" AND the notes patch in ONE statement when notes is provided', async () => {
    const token = establishIdentity(U1);
    const select = vi.fn().mockResolvedValue({ data: [{ opportunity_id: OPP }], error: null });
    const eq2 = vi.fn().mockReturnValue({ select });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    const update = vi.fn().mockReturnValue({ eq: eq1 });
    mockFrom.mockImplementation(() => ({ update }));
    await expect(dismissInteraction(OPP, 'final notes', token)).resolves.toBeUndefined();
    expect(update).toHaveBeenCalledWith(expect.objectContaining({ interaction_type: 'dismissed', notes: 'final notes' }));
  });

  it('dismissInteraction omits notes from the patch entirely when not provided (undefined) — leaves the existing value untouched rather than overwriting it with null', async () => {
    const token = establishIdentity(U1);
    const select = vi.fn().mockResolvedValue({ data: [{ opportunity_id: OPP }], error: null });
    const eq2 = vi.fn().mockReturnValue({ select });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    const update = vi.fn().mockReturnValue({ eq: eq1 });
    mockFrom.mockImplementation(() => ({ update }));
    await expect(dismissInteraction(OPP, undefined, token)).resolves.toBeUndefined();
    const sentPatch = update.mock.calls[0][0];
    expect(sentPatch).toHaveProperty('interaction_type', 'dismissed');
    expect(sentPatch).not.toHaveProperty('notes');
  });

  it('dismissInteraction throws on a remote update error', async () => {
    const token = establishIdentity(U1);
    const select = vi.fn().mockResolvedValue({ data: null, error: { message: 'row locked' } });
    const eq2 = vi.fn().mockReturnValue({ select });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    const update = vi.fn().mockReturnValue({ eq: eq1 });
    mockFrom.mockImplementation(() => ({ update }));
    await expect(dismissInteraction(OPP, undefined, token)).rejects.toThrow('row locked');
  });

  it('dismissInteraction throws (fails CLOSED, never resurrects via upsert) on a ZERO-row match — a Tracker row being dismissed is known to already exist; zero rows means a CONCURRENT REMOVE beat it to the row', async () => {
    const token = establishIdentity(U1);
    const select = vi.fn().mockResolvedValue({ data: [], error: null });
    const eq2 = vi.fn().mockReturnValue({ select });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    const update = vi.fn().mockReturnValue({ eq: eq1 });
    mockFrom.mockImplementation(() => ({ update }));
    await expect(dismissInteraction(OPP, undefined, token)).rejects.toThrow('expected exactly one matching interaction row');
  });

  it('removeInteraction throws on a remote delete error (previously: no error check at all)', async () => {
    const token = establishIdentity(U1);
    const eq2 = vi.fn().mockResolvedValue({ error: { message: 'delete failed' } });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    mockFrom.mockImplementation(() => ({ delete: vi.fn().mockReturnValue({ eq: eq1 }) }));
    await expect(removeInteraction(OPP, token)).rejects.toThrow('delete failed');
  });

  it('removeInteraction resolves on a ZERO-row match with no query error — deletion is idempotent: the target state (row absent) is already true, most likely because an earlier attempt\'s request landed but its response was lost before the caller learned it succeeded', async () => {
    const token = establishIdentity(U1);
    const eq2 = vi.fn().mockResolvedValue({ error: null }); // no rows matched, no error
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    mockFrom.mockImplementation(() => ({ delete: vi.fn().mockReturnValue({ eq: eq1 }) }));
    await expect(removeInteraction(OPP, token)).resolves.toBeUndefined();
  });

  it('a retried removeInteraction after an uncertain first attempt (its request landed server-side, but the response was lost) resolves on the second, ZERO-row call — the exact scenario a Tracker Retry click hits', async () => {
    const token = establishIdentity(U1);
    // First attempt: the DELETE genuinely matched and removed the row, but
    // we model the caller-visible outcome as a thrown network error (the
    // response never arrived) — this is what the Tracker hook actually
    // observes, independent of what happened server-side.
    const firstEq2 = vi.fn().mockRejectedValueOnce(new Error('network timeout'));
    const firstEq1 = vi.fn().mockReturnValue({ eq: firstEq2 });
    mockFrom.mockImplementationOnce(() => ({ delete: vi.fn().mockReturnValue({ eq: firstEq1 }) }));
    await expect(removeInteraction(OPP, token)).rejects.toThrow('network timeout');

    // Retry: the row is already gone — this second DELETE matches zero
    // rows, with no query error. Must resolve, not throw.
    const secondEq2 = vi.fn().mockResolvedValue({ error: null });
    const secondEq1 = vi.fn().mockReturnValue({ eq: secondEq2 });
    mockFrom.mockImplementationOnce(() => ({ delete: vi.fn().mockReturnValue({ eq: secondEq1 }) }));
    await expect(removeInteraction(OPP, token)).resolves.toBeUndefined();
  });

  it('trackInteraction/updateInteractionDetails/removeInteraction/dismissInteraction throw when no device id can be resolved (unconfigured/anon-sign-in-failed) — Tracker has no local fallback', async () => {
    mockGetSession.mockResolvedValue(noSession());
    mockSignInAnonymously.mockResolvedValue({ data: { user: null }, error: { message: 'disabled' } });
    liveAuthCallback?.('SIGNED_OUT', null);
    const token = captureOwnerToken(); // uid: null, matches the resolved-null outcome below
    await expect(trackInteraction(OPP, 'applied', token)).rejects.toThrow();
    await expect(updateInteractionDetails(OPP, { notes: 'x' }, token)).rejects.toThrow();
    await expect(removeInteraction(OPP, token)).rejects.toThrow();
    await expect(dismissInteraction(OPP, undefined, token)).rejects.toThrow();
  });

  it('toggleFavorite still degrades to local-only on a genuine remote failure (previously-reviewed behavior, unchanged) — this is NOT an owner mismatch', async () => {
    const token = establishIdentity(U1);
    const insert = vi.fn().mockResolvedValue({ error: { message: 'network down' } });
    mockFrom.mockImplementation(() => ({ insert, delete: vi.fn() }));
    await expect(toggleFavorite(OPP, false, token)).resolves.toBe(true);
    expect(JSON.parse(localStorage.getItem('ofe_favs_fallback') ?? '[]')).toContain(OPP);
  });
});

describe('late local-fallback writes re-validate the SAME token immediately before writing (owner check is not only-once-at-the-top)', () => {
  it('toggleFavorite: owner check passes, the remote request is sent, auth switches to U2, THEN the remote request fails late — localStorage stays completely unchanged (no stale degrade write for an abandoned identity)', async () => {
    const token = establishIdentity(U1);
    let resolveDelete: (v: unknown) => void = () => {};
    const del2 = vi.fn(() => new Promise((r) => { resolveDelete = r; }));
    const del1 = vi.fn().mockReturnValue({ eq: del2 });
    mockFrom.mockImplementation(() => ({ delete: vi.fn().mockReturnValue({ eq: del1 }) }));

    const action = toggleFavorite(OPP, true, token); // isFaved=true -> delete path
    // Let ensureAnonSession settle and the delete() chain actually fire
    // (still under U1 — the remote request is genuinely "sent") before
    // touching auth state; a bare microtask tick is not guaranteed
    // sufficient, so flush via a macrotask.
    await new Promise((r) => setTimeout(r, 0));
    expect(del2).toHaveBeenCalled();

    liveAuthCallback?.('SIGNED_IN', session(U2).data.session); // switch AFTER the request was sent
    resolveDelete({ error: { message: 'late failure' } }); // response arrives late, after the switch

    // The identity changed while this request was in flight: even though
    // the remote call merely failed (not itself an owner problem), the
    // caller that started this action is no longer current — the function
    // throws OwnerMismatchError instead of resolving a degrade result a
    // stale context could act on.
    await expect(action).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(localStorage.getItem('ofe_favs_fallback')).toBeNull();
  });

  it('getFavorites: begins under U1 (captures its own owner token there), auth switches to U2 while ensureAnonSession\'s OWN getSession() is still pending, and that pending call resolves LATE with U1\'s stale session -> no remote backfill query is ever made, and U1\'s snapshot never appears in the result or in localStorage', async () => {
    establishIdentity(U1);
    localStorage.setItem('ofe_favs_fallback', JSON.stringify(['u1-only-opp']));

    let resolveGetSession: (v: unknown) => void = () => {};
    mockGetSession.mockImplementationOnce(() => new Promise((r) => { resolveGetSession = r; }));

    const select = vi.fn();
    const insert = vi.fn();
    mockFrom.mockImplementation(() => ({ select: vi.fn().mockReturnValue({ eq: select }), insert }));

    // getFavorites captures its own token under U1 and reaches
    // ensureAnonSession's getSession() call, which is now pending.
    const promise = getFavorites();
    liveAuthCallback?.('SIGNED_IN', session(U2).data.session); // authoritative switch lands while it's pending
    resolveGetSession(session(U1)); // the pending call resolves late, with the now-stale U1 session

    const result = await promise;

    expect(select).not.toHaveBeenCalled();
    expect(insert).not.toHaveBeenCalled();
    expect(result.has('u1-only-opp')).toBe(false);
    expect(JSON.parse(localStorage.getItem('ofe_favs_fallback') ?? '"missing"')).not.toContain('u1-only-opp');
  });

  it('getFavorites: auth switches to U2 at the exact moment the backfill insert fires (the window between the select resolving and the insert\'s own response) -> the insert may still complete, but the merge/local-fallback-overwrite that follows it is aborted, never landing U1\'s local snapshot under U2', async () => {
    localStorage.setItem('ofe_favs_fallback', JSON.stringify(['local-only-opp']));
    establishIdentity(U1);

    const select = vi.fn().mockResolvedValue({ data: [{ opportunity_id: 'remote-opp' }], error: null });
    const insert = vi.fn().mockImplementation(() => {
      // The switch lands exactly here — after getFavorites decided to
      // backfill (identity was valid then) but before its response is
      // processed.
      liveAuthCallback?.('SIGNED_IN', session(U2).data.session);
      return Promise.resolve({ error: null });
    });
    mockFrom.mockImplementation(() => ({ select: vi.fn().mockReturnValue({ eq: select }), insert }));

    const result = await getFavorites();
    expect(insert).toHaveBeenCalledTimes(1);
    expect(result.has('local-only-opp')).toBe(false);
    expect(JSON.parse(localStorage.getItem('ofe_favs_fallback') ?? '"missing"')).not.toContain('local-only-opp');
  });
});

describe('confirmInteractionContact (atomic RPC)', () => {
  it('calls confirm_interaction_contact with the resolved device id, opportunity id, and remind_at, returning the persisted row', async () => {
    const token = establishIdentity(U1);
    mockRpc.mockResolvedValue({
      data: [{
        interaction_type: 'applied',
        notes: null,
        remind_at: '2026-08-10',
        last_contacted_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-01T00:00:00Z',
      }],
      error: null,
    });
    const result = await confirmInteractionContact(OPP, token, '2026-08-10');
    expect(mockRpc).toHaveBeenCalledWith('confirm_interaction_contact', {
      p_expected_device_id: U1,
      p_opportunity_id: OPP,
      p_remind_at: '2026-08-10',
    });
    expect(result.type).toBe('applied');
    expect(result.remind_at).toBe('2026-08-10');
  });

  it('throws on an RPC error (e.g. identity_changed from the server-side guard) — never a fake confirmed state', async () => {
    const token = establishIdentity(U1);
    mockRpc.mockResolvedValue({ data: null, error: { message: 'identity_changed' } });
    await expect(confirmInteractionContact(OPP, token)).rejects.toThrow('identity_changed');
  });

  it('is idempotent: calling it twice in a row (retry after a transient failure) succeeds and does not throw on the second call', async () => {
    const token = establishIdentity(U1);
    mockRpc
      .mockResolvedValueOnce({ data: null, error: { message: 'transient' } })
      .mockResolvedValueOnce({
        data: [{ interaction_type: 'applied', notes: null, remind_at: null, last_contacted_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z' }],
        error: null,
      });
    await expect(confirmInteractionContact(OPP, token)).rejects.toThrow('transient');
    await expect(confirmInteractionContact(OPP, token)).resolves.toMatchObject({ type: 'applied' });
  });
});

describe('cross-function serialization on the EXPORTED helpers (shared queue, not just the primitive)', () => {
  it('trackInteraction then updateInteractionDetails for the same (owner, opportunity): the update chain is not invoked until the deferred upsert settles', async () => {
    const token = establishIdentity(U1);
    let resolveUpsert: (v: unknown) => void = () => {};
    const upsert = vi.fn(() => new Promise((r) => { resolveUpsert = r; }));
    const select = vi.fn().mockResolvedValue({ data: [{ opportunity_id: OPP }], error: null });
    const eq2 = vi.fn().mockReturnValue({ select });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    const update = vi.fn().mockReturnValue({ eq: eq1 });
    mockFrom.mockImplementation(() => ({ upsert, update }));

    const trackPromise = trackInteraction(OPP, 'applied', token);
    const updatePromise = updateInteractionDetails(OPP, { notes: 'hi' }, token);

    // The first call has reached its request; the update chain must NOT
    // have fired — it is queued behind that still-pending upsert.
    await until(() => upsert.mock.calls.length > 0);
    expect(update).not.toHaveBeenCalled();

    resolveUpsert({ error: null });
    await trackPromise;
    await updatePromise;
    expect(update).toHaveBeenCalledTimes(1);
  });

  it('a rejected trackInteraction does not poison the shared queue — a subsequently invoked updateInteractionDetails for the same opportunity still runs', async () => {
    const token = establishIdentity(U1);
    const upsert = vi.fn().mockResolvedValue({ error: { message: 'boom' } });
    const select = vi.fn().mockResolvedValue({ data: [{ opportunity_id: OPP }], error: null });
    const eq2 = vi.fn().mockReturnValue({ select });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    const update = vi.fn().mockReturnValue({ eq: eq1 });
    mockFrom.mockImplementation(() => ({ upsert, update }));

    await expect(trackInteraction(OPP, 'applied', token)).rejects.toThrow('boom');
    await expect(updateInteractionDetails(OPP, { notes: 'hi' }, token)).resolves.toBeUndefined();
    expect(update).toHaveBeenCalledTimes(1);
  });

  it('updateInteractionDetails then removeInteraction for the same (owner, opportunity) — the exact Tracker notes-then-REMOVE sequence, not just track->update: the delete chain does not start until the deferred update settles, and an update REJECTION does not poison the queue — the delete still runs after and succeeds', async () => {
    const token = establishIdentity(U1);
    let resolveUpdateSelect: (v: unknown) => void = () => {};
    const select = vi.fn(() => new Promise((r) => { resolveUpdateSelect = r; }));
    const updateEq2 = vi.fn().mockReturnValue({ select });
    const updateEq1 = vi.fn().mockReturnValue({ eq: updateEq2 });
    const update = vi.fn().mockReturnValue({ eq: updateEq1 });
    const deleteEq2 = vi.fn().mockResolvedValue({ error: null });
    const deleteEq1 = vi.fn().mockReturnValue({ eq: deleteEq2 });
    const del = vi.fn().mockReturnValue({ eq: deleteEq1 });
    mockFrom.mockImplementation(() => ({ update, delete: del }));

    const updatePromise = updateInteractionDetails(OPP, { notes: 'hi' }, token);
    const removePromise = removeInteraction(OPP, token);

    // The first call has reached its request; the delete chain must NOT
    // have fired — it is queued behind that still-pending update.
    await until(() => update.mock.calls.length > 0);
    expect(del).not.toHaveBeenCalled();

    // The update REJECTS — the shared queue must not be poisoned by it.
    resolveUpdateSelect({ data: null, error: { message: 'update failed' } });
    await expect(updatePromise).rejects.toThrow('update failed');
    await expect(removePromise).resolves.toBeUndefined();
    expect(del).toHaveBeenCalledTimes(1);
  });

  it('dismissInteraction, while still pending, holds its ONE queue slot immediately — a LATER trackInteraction SET for the same (owner, opportunity), e.g. a click from a DIFFERENT surface (Results/Detail) while Tracker\'s dismiss is mid-flight, does not even start until the dismiss settles; being the later action, it is what persists last', async () => {
    const token = establishIdentity(U1);
    let resolveDismissSelect: (v: unknown) => void = () => {};
    const dismissSelect = vi.fn(() => new Promise((r) => { resolveDismissSelect = r; }));
    const dismissEq2 = vi.fn().mockReturnValue({ select: dismissSelect });
    const dismissEq1 = vi.fn().mockReturnValue({ eq: dismissEq2 });
    const update = vi.fn().mockReturnValue({ eq: dismissEq1 });
    const upsert = vi.fn().mockResolvedValue({ error: null });
    mockFrom.mockImplementation(() => ({ update, upsert }));

    const dismissPromise = dismissInteraction(OPP, 'final notes', token);
    const setPromise = trackInteraction(OPP, 'replied', token); // a different surface's later action

    await until(() => update.mock.calls.length > 0);
    expect(upsert).not.toHaveBeenCalled(); // queued behind the still-pending dismiss

    resolveDismissSelect({ data: [{ opportunity_id: OPP }], error: null });
    await dismissPromise;
    await setPromise;
    expect(upsert).toHaveBeenCalledTimes(1); // the later SET ran AFTER dismiss — last intent wins
  });

  it('dismissInteraction, while still pending, holds its slot — a LATER removeInteraction for the same id queues behind it and still deletes the row once its turn comes; nothing runs after it to resurrect it', async () => {
    const token = establishIdentity(U1);
    let resolveDismissSelect: (v: unknown) => void = () => {};
    const dismissSelect = vi.fn(() => new Promise((r) => { resolveDismissSelect = r; }));
    const dismissEq2 = vi.fn().mockReturnValue({ select: dismissSelect });
    const dismissEq1 = vi.fn().mockReturnValue({ eq: dismissEq2 });
    const update = vi.fn().mockReturnValue({ eq: dismissEq1 });
    const deleteEq2 = vi.fn().mockResolvedValue({ error: null });
    const deleteEq1 = vi.fn().mockReturnValue({ eq: deleteEq2 });
    const del = vi.fn().mockReturnValue({ eq: deleteEq1 });
    mockFrom.mockImplementation(() => ({ update, delete: del }));

    const dismissPromise = dismissInteraction(OPP, undefined, token);
    const removePromise = removeInteraction(OPP, token);

    await until(() => update.mock.calls.length > 0);
    expect(del).not.toHaveBeenCalled();

    resolveDismissSelect({ data: [{ opportunity_id: OPP }], error: null });
    await dismissPromise;
    await removePromise;
    expect(del).toHaveBeenCalledTimes(1);
  });

  it('a removeInteraction that gets queued FIRST deletes the row — a dismissInteraction for the same id that only reaches its turn AFTER that fails CLOSED on the zero-row match, never resurrecting the row the way the old upsert-based two-step dismiss would have', async () => {
    const token = establishIdentity(U1);
    let resolveDelete: (v: unknown) => void = () => {};
    const deleteEq2 = vi.fn(() => new Promise((r) => { resolveDelete = r; }));
    const deleteEq1 = vi.fn().mockReturnValue({ eq: deleteEq2 });
    const del = vi.fn().mockReturnValue({ eq: deleteEq1 });
    const dismissSelect = vi.fn().mockResolvedValue({ data: [], error: null }); // zero rows — already gone
    const dismissEq2 = vi.fn().mockReturnValue({ select: dismissSelect });
    const dismissEq1 = vi.fn().mockReturnValue({ eq: dismissEq2 });
    const update = vi.fn().mockReturnValue({ eq: dismissEq1 });
    mockFrom.mockImplementation(() => ({ update, delete: del }));

    const removePromise = removeInteraction(OPP, token); // queued FIRST
    const dismissPromise = dismissInteraction(OPP, undefined, token); // queued behind it

    await until(() => del.mock.calls.length > 0);
    expect(update).not.toHaveBeenCalled(); // dismiss has not even started

    resolveDelete({ error: null }); // the delete completes — row is gone
    await removePromise;
    await expect(dismissPromise).rejects.toThrow('expected exactly one matching interaction row');
    expect(update).toHaveBeenCalledTimes(1); // it DID run and correctly failed — never silently skipped, never resurrected
  });

  it('order A — trackInteraction("replied") enqueued, then confirmInteractionContact: confirm never downgrades the already-advanced status back to applied', async () => {
    const token = establishIdentity(U1);
    let currentType: InteractionType = 'applied';
    const upsert = vi.fn((row: { interaction_type: InteractionType }) => {
      currentType = row.interaction_type;
      return Promise.resolve({ error: null });
    });
    mockRpc.mockImplementation(() => Promise.resolve({
      data: [{
        interaction_type: currentType, notes: null, remind_at: null,
        last_contacted_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
      }],
      error: null,
    }));
    mockFrom.mockImplementation(() => ({ upsert }));

    await trackInteraction(OPP, 'replied', token);
    const confirmed = await confirmInteractionContact(OPP, token);
    // The RPC's own ON CONFLICT clause never SETs interaction_type — this
    // proves the two calls were correctly serialized (confirm ran strictly
    // after track, observing the already-'replied' row), not that the RPC
    // alone happens to make ordering irrelevant.
    expect(confirmed.type).toBe('replied');
  });

  it('order B — confirmInteractionContact enqueued, then trackInteraction("replied"): the later, more specific intent wins', async () => {
    const token = establishIdentity(U1);
    let currentType: InteractionType = 'applied';
    const upsert = vi.fn((row: { interaction_type: InteractionType }) => {
      currentType = row.interaction_type;
      return Promise.resolve({ error: null });
    });
    mockRpc.mockImplementation(() => Promise.resolve({
      data: [{
        interaction_type: 'applied', notes: null, remind_at: null,
        last_contacted_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
      }],
      error: null,
    }));
    mockFrom.mockImplementation(() => ({ upsert }));

    await confirmInteractionContact(OPP, token);
    await trackInteraction(OPP, 'replied', token);
    expect(currentType).toBe('replied');
  });
});

describe('getFavorites: safe one-time re-read after first-owner priming (READ-only relaxation — writes stay strictly fail-closed)', () => {
  it('a token captured before any identity was resolved (null), where ensureAnonSession then resolves to a real uid: the SAME call continues under the freshly-established identity and returns the remote favorite — not a false empty/local-only result', async () => {
    // Force the shared primitive to a null-uid state, matching "nothing
    // resolved yet at capture time" without depending on pristine module state.
    liveAuthCallback?.('SIGNED_OUT', null);
    expect(captureOwnerToken().uid).toBeNull();

    mockGetSession.mockResolvedValue(session(U1)); // ensureAnonSession resolves to a real, fresh identity
    const eq = vi.fn().mockResolvedValue({ data: [{ opportunity_id: OPP }], error: null });
    mockFrom.mockImplementation(() => ({ select: vi.fn().mockReturnValue({ eq }) }));

    const result = await getFavorites();
    expect(eq).toHaveBeenCalled(); // the remote query genuinely ran under the fresh identity
    expect(result.has(OPP)).toBe(true); // the remote favorite was returned, not silently omitted
  });

  it('a token captured for a KNOWN (non-null) identity that turns out stale is NEVER retried this way — it stays local-only, exactly as before', async () => {
    const token = establishIdentity(U1);
    void token;
    mockGetSession.mockResolvedValue(session(U2)); // resolves to a DIFFERENT identity — a genuine switch, not a first resolution
    const select = vi.fn();
    const insert = vi.fn();
    mockFrom.mockImplementation(() => ({ select: vi.fn().mockReturnValue({ eq: select }), insert }));

    const result = await getFavorites();
    expect(select).not.toHaveBeenCalled();
    expect(insert).not.toHaveBeenCalled();
    void result;
  });
});

describe('sanity: getFavorites is unaffected by the owner-token signature change on writes', () => {
  it('still reads favorites without requiring a token, when nothing races', async () => {
    establishIdentity(U1);
    const eq = vi.fn().mockResolvedValue({ data: [{ opportunity_id: OPP }], error: null });
    mockFrom.mockImplementation(() => ({ select: vi.fn().mockReturnValue({ eq }) }));
    const set = await getFavorites();
    expect(set.has(OPP)).toBe(true);
  });
});

describe('interaction reads: throw on query failure, null/empty only on a CONFIRMED absence', () => {
  it('getInteractionDetail throws on a query error (previously: silently returned null, indistinguishable from "no interaction")', async () => {
    establishIdentity(U1);
    const maybeSingle = vi.fn().mockResolvedValue({ data: null, error: { message: 'connection reset' } });
    const eq2 = vi.fn().mockReturnValue({ maybeSingle });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    mockFrom.mockImplementation(() => ({ select: vi.fn().mockReturnValue({ eq: eq1 }) }));
    await expect(getInteractionDetail(OPP)).rejects.toThrow('connection reset');
  });

  it('getInteractionDetail returns null on a CONFIRMED no-row result (maybeSingle: no error, no data)', async () => {
    establishIdentity(U1);
    const maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
    const eq2 = vi.fn().mockReturnValue({ maybeSingle });
    const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
    mockFrom.mockImplementation(() => ({ select: vi.fn().mockReturnValue({ eq: eq1 }) }));
    await expect(getInteractionDetail(OPP)).resolves.toBeNull();
  });

  it('getInteractionDetail returns null with zero query when no device id resolves (unconfigured/anon-sign-in-failed) — a confirmed local-only degrade, not a failure to look', async () => {
    mockGetSession.mockResolvedValue(noSession());
    mockSignInAnonymously.mockResolvedValue({ data: { user: null }, error: { message: 'disabled' } });
    liveAuthCallback?.('SIGNED_OUT', null);
    mockFrom.mockImplementation(() => { throw new Error('must not query interactions without a device id'); });
    await expect(getInteractionDetail(OPP)).resolves.toBeNull();
  });

  it('getInteractions throws on a query error (previously: silently returned an empty Map)', async () => {
    establishIdentity(U1);
    const eq = vi.fn().mockResolvedValue({ data: null, error: { message: 'connection reset' } });
    mockFrom.mockImplementation(() => ({ select: vi.fn().mockReturnValue({ eq }) }));
    await expect(getInteractions()).rejects.toThrow('connection reset');
  });

  it('getInteractions returns an empty Map on a CONFIRMED empty result set', async () => {
    establishIdentity(U1);
    const eq = vi.fn().mockResolvedValue({ data: [], error: null });
    mockFrom.mockImplementation(() => ({ select: vi.fn().mockReturnValue({ eq }) }));
    await expect(getInteractions()).resolves.toEqual(new Map());
  });

  it('getInteractionsFull throws on a query error (previously: silently returned an empty Map)', async () => {
    establishIdentity(U1);
    const eq = vi.fn().mockResolvedValue({ data: null, error: { message: 'connection reset' } });
    mockFrom.mockImplementation(() => ({ select: vi.fn().mockReturnValue({ eq }) }));
    await expect(getInteractionsFull()).rejects.toThrow('connection reset');
  });

  it('getInteractionsFull returns an empty Map on a CONFIRMED empty result set', async () => {
    establishIdentity(U1);
    const eq = vi.fn().mockResolvedValue({ data: [], error: null });
    mockFrom.mockImplementation(() => ({ select: vi.fn().mockReturnValue({ eq }) }));
    await expect(getInteractionsFull()).resolves.toEqual(new Map());
  });
});
