/*
 * submitFeedback cloud-write contract (W15, migration 026).
 *
 * The pin that matters: a duplicate-key insert (Postgres 23505 on the
 * feedback_client_token_uniq partial index) means the ticket from an earlier
 * attempt ALREADY EXISTS — the response to that attempt was lost, not the
 * write. Reporting a failure there would push the user into a third attempt
 * over a ticket we already hold, so the client re-reads the existing row and
 * returns its id as a SUCCESS. Mirrors the toggleFavorite / followProfessor
 * 23505 contract.
 *
 * The other pin: success is only claimed on a CONFIRMED insert, and the
 * returned id is the real ticket UUID (026's feedback_select_own is what
 * lets the RETURNING clause come back at all).
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const {
  mockFrom,
  mockGetSession,
  mockSignInAnonymously,
  mockInsert,
  mockInsertSingle,
  mockReadSelect,
  mockMaybeSingle,
} = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockFrom: vi.fn(),
    mockGetSession: vi.fn(),
    mockSignInAnonymously: vi.fn(),
    mockInsert: vi.fn(),
    mockInsertSingle: vi.fn(),
    mockReadSelect: vi.fn(),
    mockMaybeSingle: vi.fn(),
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

import { submitFeedback } from './supabase';

const UID = '11111111-1111-4111-8111-111111111111';
const TICKET_ID = '7c9e6679-7425-40de-944b-e07fc1f90ae7';
const TOKEN = 'token-abc';

// Filters applied by the duplicate re-read, in call order.
let readFilters: Array<[string, unknown]>;

function baseInput() {
  return {
    message: 'the search box eats my query',
    email: 'me@x.edu',
    category: 'bug' as const,
    subject: 'search',
    clientToken: TOKEN,
    props: { path: '/results' },
  };
}

beforeEach(() => {
  localStorage.clear();
  readFilters = [];

  mockGetSession.mockReset().mockResolvedValue({
    data: { session: { user: { id: UID, is_anonymous: true } } },
  });
  mockSignInAnonymously.mockReset().mockResolvedValue({
    data: { user: { id: UID } },
    error: null,
  });

  mockInsertSingle.mockReset().mockResolvedValue({ data: { id: TICKET_ID }, error: null });
  mockInsert.mockReset().mockReturnValue({ select: () => ({ single: mockInsertSingle }) });

  mockMaybeSingle.mockReset().mockResolvedValue({ data: { id: TICKET_ID }, error: null });
  mockReadSelect.mockReset().mockImplementation(() => {
    const chain = {
      eq: (column: string, value: unknown) => { readFilters.push([column, value]); return chain; },
      maybeSingle: mockMaybeSingle,
    };
    return chain;
  });

  mockFrom.mockReset().mockReturnValue({ insert: mockInsert, select: mockReadSelect });
});

describe('submitFeedback (happy path)', () => {
  it('writes the ticket columns and returns the server-assigned UUID', async () => {
    const result = await submitFeedback(baseInput());

    expect(result).toEqual({ ok: true, reason: 'created', id: TICKET_ID });
    expect(mockFrom).toHaveBeenCalledWith('feedback');
    expect(mockInsert).toHaveBeenCalledWith({
      device_id: UID,
      message: 'the search box eats my query',
      email: 'me@x.edu',
      category: 'bug',
      subject: 'search',
      client_token: TOKEN,
      props: { path: '/results' },
    });
  });

  it('normalises omitted optional fields to null rather than empty strings', async () => {
    const result = await submitFeedback({ message: 'just this' });

    expect(result.ok).toBe(true);
    expect(mockInsert).toHaveBeenCalledWith({
      device_id: UID,
      message: 'just this',
      email: null,
      category: null,
      subject: null,
      client_token: null,
      props: {},
    });
  });
});

describe('submitFeedback (23505 duplicate → idempotent success)', () => {
  it('re-reads the existing ticket and reports success with its id', async () => {
    mockInsertSingle.mockResolvedValueOnce({
      data: null,
      error: {
        code: '23505',
        message: 'duplicate key value violates unique constraint "feedback_client_token_uniq"',
      },
    });

    const result = await submitFeedback(baseInput());

    expect(result).toEqual({ ok: true, reason: 'duplicate', id: TICKET_ID });
    // Scoped to THIS submitter's token — never a bare token lookup.
    expect(readFilters).toEqual([['device_id', UID], ['client_token', TOKEN]]);
    // And it must not try the insert a second time.
    expect(mockInsert).toHaveBeenCalledTimes(1);
  });

  it('still reports success when the re-read fails — the row provably exists', async () => {
    mockInsertSingle.mockResolvedValueOnce({
      data: null,
      error: { code: '23505', message: 'duplicate key value' },
    });
    mockMaybeSingle.mockResolvedValueOnce({ data: null, error: { message: 'read blocked' } });

    const result = await submitFeedback(baseInput());

    expect(result).toEqual({ ok: true, reason: 'duplicate', id: null });
  });

  it('does NOT treat a tokenless 23505 as a duplicate ticket', async () => {
    // No client_token means the partial unique index cannot be the source, so
    // there is no existing ticket to point at — that is a real failure.
    mockInsertSingle.mockResolvedValueOnce({
      data: null,
      error: { code: '23505', message: 'duplicate key value' },
    });

    const result = await submitFeedback({ message: 'no token' });

    expect(result).toEqual({ ok: false, reason: 'error' });
    expect(readFilters).toEqual([]);
  });
});

describe('submitFeedback (failures)', () => {
  it('reports no-session when the anonymous session cannot be established', async () => {
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockSignInAnonymously.mockResolvedValue({
      data: { user: null },
      error: { message: 'Anonymous sign-ins are disabled' },
    });

    const result = await submitFeedback(baseInput());

    expect(result).toEqual({ ok: false, reason: 'no-session' });
    expect(mockInsert).not.toHaveBeenCalled();
  });

  it('reports error on any other insert failure', async () => {
    mockInsertSingle.mockResolvedValueOnce({
      data: null,
      error: { code: '42501', message: 'new row violates row-level security policy' },
    });

    const result = await submitFeedback(baseInput());

    expect(result).toEqual({ ok: false, reason: 'error' });
  });

  it('reports error when the insert returns no row (026 not applied — no SELECT policy)', async () => {
    mockInsertSingle.mockResolvedValueOnce({ data: null, error: null });

    const result = await submitFeedback(baseInput());

    // The retry then collides on the token and resolves to 'duplicate', so
    // the user converges on the truth instead of filing a second ticket.
    expect(result).toEqual({ ok: false, reason: 'error' });
  });
});
