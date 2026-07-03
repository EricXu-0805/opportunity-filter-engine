/*
 * Flow B cross-device merge wiring (migration 017).
 *
 * Covers the two client-side halves the SECURITY DEFINER SQL relies on:
 *   - mint (exercised through signInExistingEmail / signInExistingOAuth):
 *     an existing-account sign-in must stash a grant token bound to the
 *     right email, and minting must NEVER block sign-in.
 *   - redeemPendingMerge: one-shot redeem on /auth/callback, tolerant of
 *     expired/used/not-bound grants (they surface as an RPC error and must
 *     NOT fail the sign-in).
 *
 * The SQL correctness (dedup, conflict rules, takeover/replay/expiry
 * refusal) is verified separately against real Postgres in
 * supabase/tests/flow_b_merge_test.sql.
 */

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
  it('mints a grant bound to the target email and stashes the token', async () => {
    mockRpc.mockResolvedValueOnce({ data: GRANT, error: null });

    const result = await signInExistingEmail('Eric@Illinois.edu', REDIRECT);

    expect(result.ok).toBe(true);
    expect(mockRpc).toHaveBeenCalledWith('mint_merge_grant', {
      p_target_email: 'eric@illinois.edu',
    });
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBe(GRANT);
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

describe('mint (via signInExistingOAuth)', () => {
  it('mints an UNBOUND grant (email unknown before provider consent)', async () => {
    mockRpc.mockResolvedValueOnce({ data: GRANT, error: null });

    const result = await signInExistingOAuth('google', REDIRECT);

    expect(result.ok).toBe(true);
    expect(mockRpc).toHaveBeenCalledWith('mint_merge_grant', { p_target_email: null });
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBe(GRANT);
    expect(mockSignInWithOAuth).toHaveBeenCalled();
  });
});

describe('redeemPendingMerge', () => {
  it('returns null and makes no RPC call when there is no pending token', async () => {
    const res = await redeemPendingMerge();
    expect(res).toBeNull();
    expect(mockRpc).not.toHaveBeenCalled();
  });

  it('redeems a pending token, maps the summary, and clears the token (one-shot)', async () => {
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
      merged: true,
      favorites: 2,
      interactions: 1,
      savedSearches: 3,
      attachmentsNotMoved: 1,
    });
    // token consumed even on success
    expect(localStorage.getItem(STORAGE_KEYS.MERGE_GRANT)).toBeNull();
  });

  it('clears the token and returns null when the grant is rejected (expired/used/not-bound)', async () => {
    localStorage.setItem(STORAGE_KEYS.MERGE_GRANT, GRANT);
    mockRpc.mockResolvedValueOnce({
      data: null,
      error: { message: 'redeem_merge_grant: grant expired' },
    });

    const res = await redeemPendingMerge();

    expect(res).toBeNull();
    // one-shot: a rejected token must not be retried on the next callback land
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
      merged: false,
      favorites: 0,
      interactions: 0,
      savedSearches: 0,
      attachmentsNotMoved: 0,
    });
  });
});
