/*
 * toggleFavorite cloud-write contract (W14).
 *
 * The pin that matters: a duplicate-key insert (Postgres 23505 — a
 * double-click or a retry of a request that actually landed) is an
 * IDEMPOTENT SUCCESS, not a failure. Pre-W14 it downgraded the storage
 * status to 'local-only', telling the user their favorite wasn't synced
 * when the cloud row provably exists (data-integrity audit item 10).
 * Mirrors the followProfessor 23505 contract.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockFrom, mockGetSession, mockInsert } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockFrom: vi.fn(),
    mockGetSession: vi.fn(),
    mockInsert: vi.fn(),
  };
});

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: mockGetSession,
      signInAnonymously: vi.fn(),
      onAuthStateChange: vi.fn(() => ({
        data: { subscription: { unsubscribe: vi.fn() } },
      })),
    },
    from: mockFrom,
    rpc: vi.fn(),
    storage: { from: vi.fn() },
  }),
}));

import { getStorageStatus, toggleFavorite } from './supabase';
import { STORAGE_KEYS } from './storage-keys';

const UID = '11111111-1111-4111-8111-111111111111';
const OPP_ID = 'opp-123';

function localMirror(): string[] {
  const raw = localStorage.getItem(STORAGE_KEYS.FAVORITES_FALLBACK);
  return raw ? (JSON.parse(raw) as string[]) : [];
}

beforeEach(() => {
  localStorage.clear();
  mockFrom.mockReset();
  mockGetSession.mockReset();
  mockInsert.mockReset();
  mockGetSession.mockResolvedValue({ data: { session: { user: { id: UID } } } });
  mockFrom.mockReturnValue({ insert: mockInsert });
});

describe('toggleFavorite (favoriting: insert path)', () => {
  it('inserts the row, keeps the local mirror, and reports synced', async () => {
    mockInsert.mockResolvedValueOnce({ error: null });

    const nowFaved = await toggleFavorite(OPP_ID, false);

    expect(nowFaved).toBe(true);
    expect(mockFrom).toHaveBeenCalledWith('favorites');
    expect(mockInsert).toHaveBeenCalledWith({ device_id: UID, opportunity_id: OPP_ID });
    expect(localMirror()).toContain(OPP_ID);
    expect(getStorageStatus()).toEqual({ status: 'synced', error: null });
  });

  it('treats a 23505 duplicate-key insert as idempotent success — NO local-only downgrade', async () => {
    mockInsert.mockResolvedValueOnce({
      error: {
        code: '23505',
        message: 'duplicate key value violates unique constraint "favorites_device_id_opportunity_id_key"',
      },
    });

    const nowFaved = await toggleFavorite(OPP_ID, false);

    // The cloud row already exists and the mirror already agrees: this is
    // the retry/double-click case, not a sync failure.
    expect(nowFaved).toBe(true);
    expect(localMirror()).toContain(OPP_ID);
    expect(getStorageStatus()).toEqual({ status: 'synced', error: null });
  });

  it('still reports local-only on a REAL insert failure', async () => {
    mockInsert.mockResolvedValueOnce({
      error: { code: '42501', message: 'permission denied for table favorites' },
    });

    const nowFaved = await toggleFavorite(OPP_ID, false);

    // Optimistic mirror stays (the local fallback is the honest state),
    // but the storage status must say the cloud write did not land.
    expect(nowFaved).toBe(true);
    expect(localMirror()).toContain(OPP_ID);
    expect(getStorageStatus()).toEqual({
      status: 'local-only',
      error: 'permission denied for table favorites',
    });
  });
});
