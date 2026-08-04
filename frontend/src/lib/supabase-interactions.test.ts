/*
 * W14 truthful zero-state / truthful-write contracts on the interactions
 * helpers:
 *
 *   - getInteractionsFull: an empty Map MEANS zero rows. Session-unavailable
 *     and query errors THROW (and flip the storage banner) instead of
 *     collapsing into a confident-looking empty Map — the dashboard/tracker
 *     error branches are reachable through the real lib now.
 *   - trackInteraction: the upsert result is checked; failure throws so
 *     callers revert optimistic status instead of flashing a false "Saved".
 *   - updateInteractionDetails: resolves true only when the UPDATE landed.
 *
 * Same module-boundary client mock as supabase-auth.test.ts: we test OUR
 * error contract, not Supabase's network behavior.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockGetSession, mockSignInAnonymously, mockFrom } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockGetSession: vi.fn(),
    mockSignInAnonymously: vi.fn(),
    mockFrom: vi.fn(),
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
    storage: { from: vi.fn() },
  }),
}));

import {
  getInteractionsFull,
  getStorageStatus,
  trackInteraction,
  updateInteractionDetails,
} from './supabase';

function sessionWithUid(uid: string) {
  return { data: { session: { user: { id: uid, is_anonymous: true } } } };
}

/** Wire the interactions table builder to resolve `result` for every verb. */
function stubInteractionsTable(result: { data?: unknown; error: { message: string } | null }) {
  const upsert = vi.fn(() => Promise.resolve(result));
  const update = vi.fn(() => ({ eq: vi.fn(() => ({ eq: vi.fn(() => Promise.resolve(result)) })) }));
  const select = vi.fn(() => ({ eq: vi.fn(() => Promise.resolve(result)) }));
  mockFrom.mockReturnValue({ select, upsert, update });
  return { upsert, update, select };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetSession.mockResolvedValue(sessionWithUid('dev-1'));
});

describe('getInteractionsFull — truthful zero states', () => {
  it('maps rows into InteractionRecords keyed by opportunity_id', async () => {
    stubInteractionsTable({
      data: [
        {
          opportunity_id: 'opp-1',
          interaction_type: 'applied',
          notes: 'emailed PI',
          remind_at: '2026-08-10',
          last_contacted_at: null,
          updated_at: '2026-08-01T00:00:00Z',
        },
      ],
      error: null,
    });

    const map = await getInteractionsFull();

    expect(map.size).toBe(1);
    expect(map.get('opp-1')).toEqual({
      type: 'applied',
      notes: 'emailed PI',
      remind_at: '2026-08-10',
      last_contacted_at: undefined,
      updated_at: '2026-08-01T00:00:00Z',
    });
  });

  it('returns an empty Map ONLY for genuinely zero rows', async () => {
    stubInteractionsTable({ data: [], error: null });
    const map = await getInteractionsFull();
    expect(map.size).toBe(0);
  });

  it('THROWS on a query error and flips storage status to local-only (never a fake empty Map)', async () => {
    stubInteractionsTable({ data: null, error: { message: 'RLS says no' } });

    await expect(getInteractionsFull()).rejects.toThrow(/RLS says no/);
    expect(getStorageStatus().status).toBe('local-only');
    expect(getStorageStatus().error).toBe('RLS says no');
  });

  it('THROWS session-unavailable when no session can be established', async () => {
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockSignInAnonymously.mockResolvedValue({
      data: { user: null },
      error: { message: 'anonymous sign-ins are disabled' },
    });

    await expect(getInteractionsFull()).rejects.toThrow('session-unavailable');
  });
});

describe('trackInteraction — truthful status writes', () => {
  it('resolves when the upsert succeeds', async () => {
    const { upsert } = stubInteractionsTable({ error: null });

    await expect(trackInteraction('opp-1', 'applied')).resolves.toBeUndefined();
    expect(upsert).toHaveBeenCalledWith(
      expect.objectContaining({
        device_id: 'dev-1',
        opportunity_id: 'opp-1',
        interaction_type: 'applied',
      }),
      { onConflict: 'device_id,opportunity_id' },
    );
  });

  it('THROWS when the upsert reports an error (callers revert their optimistic status)', async () => {
    stubInteractionsTable({ error: { message: 'constraint violated' } });

    await expect(trackInteraction('opp-1', 'applied')).rejects.toThrow(/constraint violated/);
  });

  it('THROWS session-unavailable instead of silently dropping the write', async () => {
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockSignInAnonymously.mockResolvedValue({
      data: { user: null },
      error: { message: 'anonymous sign-ins are disabled' },
    });

    await expect(trackInteraction('opp-1', 'applied')).rejects.toThrow('session-unavailable');
  });
});

describe('updateInteractionDetails — verified patch result', () => {
  it('returns true when the UPDATE succeeds', async () => {
    stubInteractionsTable({ error: null });
    await expect(updateInteractionDetails('opp-1', { notes: 'hi' })).resolves.toBe(true);
  });

  it('returns false when the UPDATE fails', async () => {
    stubInteractionsTable({ error: { message: 'nope' } });
    await expect(updateInteractionDetails('opp-1', { notes: 'hi' })).resolves.toBe(false);
  });

  it('returns false when no session is available (write never happened)', async () => {
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockSignInAnonymously.mockResolvedValue({
      data: { user: null },
      error: { message: 'anonymous sign-ins are disabled' },
    });

    await expect(updateInteractionDetails('opp-1', { notes: 'hi' })).resolves.toBe(false);
  });
});
