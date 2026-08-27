/*
 * requestConciergeApply / loadConciergeRequests — the cloud-write contract for
 * an opportunity-bound concierge request (migration 033).
 *
 * The pin that matters: a duplicate-key insert (Postgres 23505 on
 * waitlist_one_request_per_target) means this student ALREADY has a standing
 * request for this professor. That is exactly what the button claims to
 * achieve, so it is a success — reporting a failure would invite a second
 * click over a request we already hold. Mirrors the submitFeedback /
 * toggleFavorite 23505 contract.
 *
 * The other pin: an unreadable list comes back as null rather than an empty
 * set, so a caller can tell "you have asked for nothing" from "we could not
 * find out" and does not draw a fresh button over an existing request.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockFrom, mockGetSession, mockSignInAnonymously, mockInsert, mockSelect } =
  vi.hoisted(() => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
    return {
      mockFrom: vi.fn(),
      mockGetSession: vi.fn(),
      mockSignInAnonymously: vi.fn(),
      mockInsert: vi.fn(),
      mockSelect: vi.fn(),
    };
  });

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: mockGetSession,
      signInAnonymously: mockSignInAnonymously,
      onAuthStateChange: vi.fn(() => ({
        data: { subscription: { unsubscribe: vi.fn() } },
      })),
    },
    from: mockFrom,
    rpc: vi.fn(),
    storage: { from: vi.fn() },
  }),
}));

import { loadConciergeRequests, requestConciergeApply } from './supabase';

const UID = '11111111-1111-4111-8111-111111111111';
const OPP = 'faculty-ece-47919b71';

let listResult: { data: unknown; error: unknown };

beforeEach(() => {
  localStorage.clear();
  listResult = { data: [], error: null };

  mockGetSession.mockReset().mockResolvedValue({
    data: { session: { user: { id: UID, is_anonymous: true } } },
  });
  mockSignInAnonymously.mockReset().mockResolvedValue({
    data: { user: { id: UID } },
    error: null,
  });

  mockInsert.mockReset().mockResolvedValue({ error: null });
  mockSelect.mockReset().mockImplementation(() => {
    const chain = {
      eq: () => chain,
      not: () => Promise.resolve(listResult),
    };
    return chain;
  });
  mockFrom.mockReset().mockReturnValue({ insert: mockInsert, select: mockSelect });
});

describe('requestConciergeApply', () => {
  it('records which opportunity was asked about', async () => {
    const ok = await requestConciergeApply(OPP, 'me@illinois.edu');

    expect(ok).toBe(true);
    expect(mockFrom).toHaveBeenCalledWith('waitlist');
    expect(mockInsert).toHaveBeenCalledWith({
      device_id: UID,
      email: 'me@illinois.edu',
      intent: 'apply_for_me',
      opportunity_id: OPP,
      props: {},
    });
  });

  it('treats an existing request for the same target as success', async () => {
    mockInsert.mockResolvedValue({
      error: { code: '23505', message: 'duplicate key value' },
    });

    expect(await requestConciergeApply(OPP, 'me@illinois.edu')).toBe(true);
  });

  it('reports a real write failure as a failure', async () => {
    mockInsert.mockResolvedValue({
      error: { code: '42501', message: 'new row violates row-level security' },
    });

    expect(await requestConciergeApply(OPP, 'me@illinois.edu')).toBe(false);
  });

  it('sends no email rather than an empty one', async () => {
    await requestConciergeApply(OPP, '');

    expect(mockInsert).toHaveBeenCalledWith(
      expect.objectContaining({ email: null }),
    );
  });
});

describe('loadConciergeRequests', () => {
  it('returns the targets this student already asked about', async () => {
    listResult = { data: [{ opportunity_id: OPP }], error: null };

    const requested = await loadConciergeRequests();

    expect(requested).toEqual(new Set([OPP]));
  });

  it('answers null — not an empty set — when the read failed', async () => {
    listResult = { data: null, error: { message: 'network down' } };

    expect(await loadConciergeRequests()).toBeNull();
  });
});
