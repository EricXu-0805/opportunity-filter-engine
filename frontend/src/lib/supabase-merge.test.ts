/*
 * Flow B cross-device merge wiring (migrations 017 + 018).
 *
 * Covers the two client-side halves the SECURITY DEFINER SQL relies on:
 *   - mint (exercised through signInExistingEmail / signInExistingOAuth):
 *     an existing-account sign-in must stash a grant bound to the right
 *     email (email path) or to a device secret whose SHA-256 hash is all
 *     the server ever sees (OAuth path), stamped with minted_at so an
 *     abandoned stash can expire (W14), and minting must NEVER block
 *     sign-in.
 *   - redeemPendingMerge: verdict-based redeem on /auth/callback (W14).
 *     The token is kept until a DEFINITIVE server verdict — success, or a
 *     dead-grant error (expired/used/invalid/unbound). Transport failures
 *     get one immediate retry and otherwise KEEP the token for the next
 *     callback land, so a network blip can no longer permanently orphan
 *     the anonymous data. No redeem outcome may fail the sign-in.
 *
 * The SQL correctness (dedup, conflict rules, takeover/replay/expiry/
 * secret-binding refusal) is verified separately against real Postgres in
 * supabase/tests/flow_b_merge_test.sql.
 */

import { createHash } from 'node:crypto';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockRpc, mockSignInWithOtp, mockSignInWithOAuth } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockRpc: vi.fn(),
    mockSignInWithOtp: vi.fn(),
    mockSignInWithOAuth: vi.fn(),
  };
});

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      signInWithOtp: mockSignInWithOtp,
      signInWithOAuth: mockSignInWithOAuth,
      signInAnonymously: vi.fn().mockResolvedValue({
        data: { user: { id: 'anon-uid' } },
        error: null,
      }),
      onAuthStateChange: vi.fn(() => ({
        data: { subscription: { unsubscribe: vi.fn() } },
      })),
    },
    rpc: mockRpc,
    from: vi.fn(),
    storage: { from: vi.fn() },
  }),
}));

import {
  redeemPendingMerge,
  signInExistingEmail,
  signInExistingOAuth,
} from './supabase';
import { STORAGE_KEYS } from './storage-keys';

const REDIRECT = 'https://app.test/auth/callback';
const GRANT = 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d';

beforeEach(() => {
  mockRpc.mockReset();
  mockSignInWithOtp.mockReset();
  mockSignInWithOAuth.mockReset();
  mockSignInWithOtp.mockResolvedValue({ data: {}, error: null });
  mockSignInWithOAuth.mockResolvedValue({ data: {}, error: null });
  localStorage.clear();
});

describe('mint (via signInExistingEmail)', () => {
  it('mints a grant bound to the target email and stashes {token, minted_at}', async () => {
    mockRpc.mockResolvedValueOnce({ data: GRANT, error: null });
    const before = Date.now();

    const result = await signInExistingEmail('Eric@Illinois.edu', REDIRECT);

    expect(result.ok).toBe(true);
    expect(mockRpc).toHaveBeenCalledWith('mint_merge_grant', {
      p_target_email: 'eric@illinois.edu',
    });
    // W14: the stash is JSON with a minted_at stamp so identity-owner can
    // expire an abandoned hand-off instead of deferring clears forever.
    const raw = localStorage.getItem(STORAGE_KEYS.MERGE_GRANT);
    const stash = JSON.parse(raw!) as { token: string; minted_at: number };
    expect(stash.token).toBe(GRANT);
    expect(stash.minted_at).toBeGreaterThanOrEqual(before);
    expect(stash.minted_at).toBeLessThanOrEqual(Date.now());
    // mint happens BEFORE the redirect
    expect(mockSignInWithOtp).toHaveBeenCalled();
  });

  it('does not block sign-in when the mint RPC errors', async () => {
    mockRpc.mockResolvedValueOnce({ data: null, error: { message: 'boom' } });

    const result = await signInExistingEmail('eric@illinois.edu', REDIRECT);

    expect(result.ok).toBe(true);
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
    expect(mockSignInWithOtp).toHaveBeenCalled();
  });

  it('does not block sign-in when the mint RPC throws', async () => {
    mockRpc.mockRejectedValueOnce(new Error('network'));

    const result = await signInExistingEmail('eric@illinois.edu', REDIRECT);

    expect(result.ok).toBe(true);
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
    expect(mockSignInWithOtp).toHaveBeenCalled();
  });
});

describe('mint (via signInExistingOAuth) — device-secret binding', () => {
  it('does not mint a merge grant or start OAuth for frozen azure', async () => {
    const result = await signInExistingOAuth('azure', REDIRECT);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe('feature-disabled');
    expect(mockRpc).not.toHaveBeenCalled();
    expect(mockSignInWithOAuth).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
  });

  it('mints a secret-bound grant (null email + SHA-256 hash) and stashes {token, secret, minted_at}', async () => {
    mockRpc.mockResolvedValueOnce({ data: GRANT, error: null });
    const before = Date.now();

    const result = await signInExistingOAuth('google', REDIRECT);

    expect(result.ok).toBe(true);
    expect(mockRpc).toHaveBeenCalledTimes(1);
    const [fn, args] = mockRpc.mock.calls[0] as [string, { p_target_email: unknown; p_secret_hash: string }];
    expect(fn).toBe('mint_merge_grant');
    expect(args.p_target_email).toBeNull();
    expect(args.p_secret_hash).toMatch(/^[0-9a-f]{64}$/);

    const raw = localStorage.getItem(STORAGE_KEYS.MERGE_GRANT);
    const stash = JSON.parse(raw!) as { token: string; secret: string; minted_at: number };
    expect(stash.token).toBe(GRANT);
    expect(stash.secret).toMatch(/^[0-9a-f]{64}$/);
    expect(stash.minted_at).toBeGreaterThanOrEqual(before);
    expect(stash.minted_at).toBeLessThanOrEqual(Date.now());
    // Recompute the hash via node:crypto — independent of the SubtleCrypto
    // path under test — to pin "server stores sha256(secret), nothing else".
    expect(createHash('sha256').update(stash.secret).digest('hex')).toBe(args.p_secret_hash);
    // mint happens BEFORE the redirect
    expect(mockSignInWithOAuth).toHaveBeenCalled();
  });

  it('does not block sign-in when the mint RPC errors', async () => {
    mockRpc.mockResolvedValueOnce({ data: null, error: { message: 'boom' } });

    const result = await signInExistingOAuth('google', REDIRECT);

    expect(result.ok).toBe(true);
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
    expect(mockSignInWithOAuth).toHaveBeenCalled();
  });

  it('does not block sign-in when the mint RPC throws', async () => {
    mockRpc.mockRejectedValueOnce(new Error('network'));

    const result = await signInExistingOAuth('google', REDIRECT);

    expect(result.ok).toBe(true);
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
    expect(mockSignInWithOAuth).toHaveBeenCalled();
  });
});

describe('redeemPendingMerge', () => {
  // B3-B7 hardening: redeemPendingMerge now returns a discriminated outcome
  // ({kind:'none'|'success'|'failed'}) instead of MergeSummary|null, so a
  // caller can tell "nothing to merge" apart from "a grant existed but we
  // could not confirm what happened to it" — the two used to collapse into
  // the same `null`, and /auth/callback silently treated both as success.
  // The token is now cleared only once the outcome is CONFIRMED terminal
  // (a real response from the server, success or a definitive rejection);
  // a transport-level throw leaves it in place so a retry can safely
  // re-present it — migration 026 makes that replay idempotent.
  it('returns {kind:"none"} and makes no RPC call when there is no pending token', async () => {
    const res = await redeemPendingMerge();
    expect(res).toEqual({ kind: 'none' });
    expect(mockRpc).not.toHaveBeenCalled();
  });

  it('returns {kind:"failed"} (not "none") when reading the stashed grant itself throws (private-mode storage) — a real pending merge must never be silently discarded as "nothing to merge"', async () => {
    const original = window.localStorage;
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: () => { throw new Error('SecurityError: storage disabled'); },
        setItem: () => { throw new Error('SecurityError'); },
        removeItem: () => {},
        clear: () => {},
        key: () => null,
        get length() { return 0; },
      },
      configurable: true,
    });
    try {
      const res = await redeemPendingMerge();
      expect(res).toEqual({ kind: 'failed' });
      expect(mockRpc).not.toHaveBeenCalled();
    } finally {
      Object.defineProperty(window, 'localStorage', { value: original, configurable: true });
    }
  });

  it('redeems a pending token, maps the summary, and clears the token (success = definitive)', async () => {
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, GRANT);
    mockRpc.mockResolvedValueOnce({
      data: {
        merged: true,
        summary: { favorites: 2, interactions: 1, saved_searches: 3, attachments_not_moved: 1 },
      },
      error: null,
    });

    const res = await redeemPendingMerge();

    expect(mockRpc).toHaveBeenCalledWith('redeem_merge_grant', { p_token: GRANT });
    expect(res).toEqual({
      kind: 'success',
      summary: {
        merged: true,
        favorites: 2,
        interactions: 1,
        savedSearches: 3,
        attachmentsNotMoved: 1,
      },
    });
    // token consumed on success
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
  });

  it('redeems a W14 email-path JSON slot {token, minted_at} with p_token only', async () => {
    localStorage.setItem(
      STORAGE_KEYS.MERGE_GRANT,
      JSON.stringify({ token: GRANT, minted_at: Date.now() }),
    );
    mockRpc.mockResolvedValueOnce({
      data: { merged: true, summary: { favorites: 1 } },
      error: null,
    });

    const res = await redeemPendingMerge();

    expect(mockRpc).toHaveBeenCalledWith('redeem_merge_grant', { p_token: GRANT });
    expect(res.kind).toBe('success');
    expect(res.kind === 'success' && res.summary.merged).toBe(true);
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
  });

  // The four dead-grant RAISE strings from the redeem_merge_grant bodies
  // (migrations 017/0181/021/023). Each is a definitive verdict: the grant
  // can never be redeemed, so the token must be consumed.
  it.each([
    'redeem_merge_grant: invalid grant',
    'redeem_merge_grant: grant already used',
    'redeem_merge_grant: grant expired',
    'redeem_merge_grant: unbound grant is not redeemable',
  ])('clears the token and returns {kind:"none"} on the definitive verdict "%s"', async (message) => {
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, GRANT);
    mockRpc.mockResolvedValueOnce({ data: null, error: { message } });

    const res = await redeemPendingMerge();

    expect(res).toEqual({ kind: 'none' });
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
  });

  // Non-definitive RPC errors: the grant may still be alive server-side
  // ('not bound' = wrong account signed in — the right one can still redeem
  // within the 15-min TTL; 5xx/session errors say nothing about the grant).
  // {kind:'failed'} — a grant existed and its fate is unconfirmed.
  it.each([
    'redeem_merge_grant: grant not bound to this account',
    'redeem_merge_grant: grant not bound to this session',
    'redeem_merge_grant: no authenticated session',
    'upstream connect error or disconnect/reset before headers',
  ])('KEEPS the token and returns {kind:"failed"} on the non-definitive error "%s"', async (message) => {
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, GRANT);
    mockRpc.mockResolvedValueOnce({ data: null, error: { message } });

    const res = await redeemPendingMerge();

    expect(res).toEqual({ kind: 'failed' });
    // no verdict → the next /auth/callback land may retry
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBe(GRANT);
  });

  it('retries once when the RPC THROWS, and keeps the token when the retry also fails', async () => {
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, GRANT);
    mockRpc.mockRejectedValueOnce(new Error('network down'));
    mockRpc.mockRejectedValueOnce(new Error('network still down'));

    const res = await redeemPendingMerge();

    expect(res).toEqual({ kind: 'failed' });
    // exactly one bounded retry for this page load
    expect(mockRpc).toHaveBeenCalledTimes(2);
    // transport failure is NOT a verdict — the token survives so the next
    // callback land can redeem instead of orphaning the anon data forever
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBe(GRANT);
  });

  it('recovers when the immediate retry succeeds after a transport failure', async () => {
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, GRANT);
    mockRpc.mockRejectedValueOnce(new Error('network blip'));
    mockRpc.mockResolvedValueOnce({
      data: { merged: true, summary: { favorites: 2 } },
      error: null,
    });

    const res = await redeemPendingMerge();

    expect(mockRpc).toHaveBeenCalledTimes(2);
    expect(res.kind).toBe('success');
    expect(res.kind === 'success' && res.summary.favorites).toBe(2);
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
  });

  it('redeems a JSON {token, secret} slot by presenting the secret (OAuth path)', async () => {
    localStorage.setItem(
      STORAGE_KEYS.MERGE_GRANT,
      JSON.stringify({ token: GRANT, secret: 'device-secret-hex' }),
    );
    mockRpc.mockResolvedValueOnce({
      data: { merged: true, summary: { favorites: 1 } },
      error: null,
    });

    const res = await redeemPendingMerge();

    expect(mockRpc).toHaveBeenCalledWith('redeem_merge_grant', {
      p_token: GRANT,
      p_secret: 'device-secret-hex',
    });
    expect(res.kind).toBe('success');
    expect(res.kind === 'success' && res.summary.merged).toBe(true);
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
  });

  it('an OAuth-path transport failure also keeps the {token,secret} JSON slot intact for retry', async () => {
    const stash = JSON.stringify({ token: GRANT, secret: 'device-secret-hex' });
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, stash);
    // Both the call and its one bounded in-page retry fail.
    mockRpc.mockRejectedValueOnce(new Error('network down'));
    mockRpc.mockRejectedValueOnce(new Error('network down'));

    const res = await redeemPendingMerge();

    expect(res).toEqual({ kind: 'failed' });
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBe(stash);
  });

  it('returns {kind:"none"}, clears the slot, and makes no RPC on a malformed JSON slot', async () => {
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, '{not-json');

    const res = await redeemPendingMerge();

    expect(res).toEqual({ kind: 'none' });
    expect(mockRpc).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
  });

  it.each([
    JSON.stringify({ secret: 'device-secret-hex' }), // token missing
    JSON.stringify({ token: 42 }), // token not a string
    JSON.stringify({ token: GRANT, secret: 123 }), // secret present but not a string
  ])('returns {kind:"none"}, clears the slot, and makes no RPC on the unusable JSON slot %s', async (slot) => {
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, slot);

    const res = await redeemPendingMerge();

    expect(res).toEqual({ kind: 'none' });
    expect(mockRpc).not.toHaveBeenCalled();
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
  });

  it('maps a no-op merge (merged:false) to a zeroed summary', async () => {
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, GRANT);
    mockRpc.mockResolvedValueOnce({
      data: { merged: false, reason: 'same_device' },
      error: null,
    });

    const res = await redeemPendingMerge();

    expect(res).toEqual({
      kind: 'success',
      summary: {
        merged: false,
        favorites: 0,
        interactions: 0,
        savedSearches: 0,
        attachmentsNotMoved: 0,
      },
    });
    // an explicit no-op is still a definitive verdict — token consumed
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
  });
});
