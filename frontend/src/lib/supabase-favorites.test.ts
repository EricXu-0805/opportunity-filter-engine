/*
 * toggleFavorite cloud-write contract (W14), under the owner-token model.
 *
 * The pin that matters: a duplicate-key insert (Postgres 23505 — a
 * double-click or a retry of a request that actually landed) is an
 * IDEMPOTENT SUCCESS, not a failure. Pre-W14 it downgraded the storage
 * status to 'local-only', telling the user their favorite wasn't synced
 * when the cloud row provably exists (data-integrity audit item 10).
 * Mirrors the followProfessor 23505 contract.
 *
 * Ported from W14's flat-helper harness onto this branch's capability
 * model: the browser is claimed for a real uid via the live auth wrapper,
 * every call carries the captured owner token, and the local mirror lives
 * in the owner-scoped namespace (readUserScopedRaw), not a bare key.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockFrom, mockGetSession, mockInsert, mockOnAuthStateChange } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockFrom: vi.fn(),
    mockGetSession: vi.fn(),
    mockInsert: vi.fn(),
    mockOnAuthStateChange: vi.fn(),
  };
});

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => ({
    auth: {
      getSession: mockGetSession,
      signInAnonymously: vi.fn(),
      onAuthStateChange: mockOnAuthStateChange,
    },
    from: mockFrom,
    rpc: vi.fn(),
    storage: { from: vi.fn() },
  }),
}));

import { captureOwnerToken, isLocalOwnerReady, readUserScopedRaw } from './identity-owner';
import { getStorageStatus, onAuthChange, toggleFavorite } from './supabase';
import { STORAGE_KEYS } from './storage-keys';

const UID = '11111111-1111-4111-8111-111111111111';
const OPP_ID = 'opp-123';

function localMirror(): string[] {
  const raw = readUserScopedRaw(STORAGE_KEYS.FAVORITES_FALLBACK);
  return raw ? (JSON.parse(raw) as string[]) : [];
}

function session(uid: string) {
  return { data: { session: { user: { id: uid, is_anonymous: true }, access_token: 't' } } };
}

let liveAuthCallback: ((event: string, session: unknown) => void) | null = null;
let unsubscribe: (() => void) | null = null;

beforeEach(async () => {
  localStorage.clear();
  mockFrom.mockReset();
  mockGetSession.mockReset();
  mockInsert.mockReset();
  liveAuthCallback = null;
  mockOnAuthStateChange.mockReset().mockImplementation((cb: (event: string, session: unknown) => void) => {
    liveAuthCallback = cb;
    return { data: { subscription: { unsubscribe: vi.fn() } } };
  });
  unsubscribe?.();
  unsubscribe = onAuthChange(() => {});
  mockGetSession.mockResolvedValue(session(UID));
  mockFrom.mockReturnValue({ insert: mockInsert });
  // Claimed via the REAL auth wrapper (epoch advance → owner sync → notify),
  // then settled: the owner transition inside is async, so wait until the
  // local realm is actually READY — a write issued before that is refused
  // by design, which is not what these tests are about.
  fireAuth('SIGNED_IN', session(UID).data.session);
  for (let i = 0; i < 200 && !isLocalOwnerReady(UID); i += 1) {
    await new Promise((r) => setTimeout(r, 0));
  }
  expect(isLocalOwnerReady(UID)).toBe(true);
});

function fireAuth(event: string, sess: unknown): void {
  if (!liveAuthCallback) throw new Error('auth wrapper never subscribed');
  liveAuthCallback(event, sess);
}

describe('toggleFavorite (favoriting: insert path)', () => {
  it('inserts the row, keeps the local mirror, and reports synced', async () => {
    mockInsert.mockResolvedValueOnce({ error: null });

    const nowFaved = await toggleFavorite(OPP_ID, false, captureOwnerToken());

    expect(nowFaved).toBe(true);
    expect(mockFrom).toHaveBeenCalledWith('favorites');
    expect(mockInsert).toHaveBeenCalledWith({ device_id: UID, opportunity_id: OPP_ID });
    // Fallback semantics: the local mirror is written only when the cloud
    // write did NOT land — a synced favorite lives in the cloud row.
    expect(localMirror()).toEqual([]);
    expect(getStorageStatus()).toEqual({ status: 'synced', error: null });
  });

  it('treats a 23505 duplicate-key insert as idempotent success — NO local-only downgrade', async () => {
    mockInsert.mockResolvedValueOnce({
      error: {
        code: '23505',
        message: 'duplicate key value violates unique constraint "favorites_device_id_opportunity_id_key"',
      },
    });

    const nowFaved = await toggleFavorite(OPP_ID, false, captureOwnerToken());

    // The cloud row already exists: this is the retry/double-click case,
    // not a sync failure — no fallback write, no local-only downgrade.
    expect(nowFaved).toBe(true);
    expect(localMirror()).toEqual([]);
    expect(getStorageStatus()).toEqual({ status: 'synced', error: null });
  });

  it('still reports local-only on a REAL insert failure', async () => {
    mockInsert.mockResolvedValueOnce({
      error: { code: '42501', message: 'permission denied for table favorites' },
    });

    const nowFaved = await toggleFavorite(OPP_ID, false, captureOwnerToken());

    // The fallback mirror takes the write (the honest local state), and
    // the storage status says the cloud write did not land.
    expect(nowFaved).toBe(true);
    expect(localMirror()).toContain(OPP_ID);
    expect(getStorageStatus()).toEqual({
      status: 'local-only',
      error: 'permission denied for table favorites',
    });
  });
});
