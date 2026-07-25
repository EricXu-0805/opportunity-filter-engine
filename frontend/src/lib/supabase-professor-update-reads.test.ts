/*
 * Professor update read cursors (migration 022). The cursor is UX sugar over
 * verified events: failures degrade to "briefly unread again", never to lost
 * or fabricated data — so reads return an empty map on error and writes warn
 * instead of throwing.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { mockFrom, mockGetSession, mockSelectEq, mockUpsert } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockFrom: vi.fn(),
    mockGetSession: vi.fn(),
    mockSelectEq: vi.fn(),
    mockUpsert: vi.fn(),
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

import {
  getProfessorUpdateReads,
  markProfessorUpdatesRead,
} from './supabase';

const UID = '11111111-1111-4111-8111-111111111111';
const PROFESSOR_ID = 'prof:v1:uiuc:11111111111111111111';
const EVENT_ID = 'prof-event:v1:aaaaaaaaaaaaaaaaaaaaaaaa';

beforeEach(() => {
  mockFrom.mockReset();
  mockGetSession.mockReset().mockResolvedValue({
    data: { session: { user: { id: UID, is_anonymous: true } } },
  });
  mockSelectEq.mockReset().mockResolvedValue({
    data: [{ professor_id: PROFESSOR_ID, last_read_event_id: EVENT_ID }],
    error: null,
  });
  mockUpsert.mockReset().mockResolvedValue({ error: null });
  mockFrom.mockImplementation(() => ({
    select: vi.fn().mockReturnValue({ eq: mockSelectEq }),
    upsert: mockUpsert,
  }));
});

describe('getProfessorUpdateReads', () => {
  it('returns the identity\'s cursors as a professor->event map', async () => {
    await expect(getProfessorUpdateReads()).resolves.toEqual(
      new Map([[PROFESSOR_ID, EVENT_ID]]),
    );

    expect(mockFrom).toHaveBeenCalledWith('professor_update_reads');
    expect(mockSelectEq).toHaveBeenCalledWith('device_id', UID);
  });

  it('degrades to an empty map on read failure (worst case: re-unread)', async () => {
    mockSelectEq.mockResolvedValueOnce({ data: null, error: { message: 'denied' } });

    await expect(getProfessorUpdateReads()).resolves.toEqual(new Map());
  });
});

describe('markProfessorUpdatesRead', () => {
  it('upserts owner-derived cursors keyed on (device, professor)', async () => {
    await markProfessorUpdatesRead([
      { professorId: PROFESSOR_ID, lastReadEventId: EVENT_ID },
    ]);

    expect(mockUpsert).toHaveBeenCalledTimes(1);
    const [rows, options] = mockUpsert.mock.calls[0];
    expect(options).toEqual({ onConflict: 'device_id,professor_id' });
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      device_id: UID,
      professor_id: PROFESSOR_ID,
      last_read_event_id: EVENT_ID,
    });
  });

  it('filters malformed entries and skips the write when none survive', async () => {
    await markProfessorUpdatesRead([
      { professorId: 'not-a-professor', lastReadEventId: EVENT_ID },
      { professorId: PROFESSOR_ID, lastReadEventId: 'not-an-event' },
    ]);

    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('warns instead of throwing on write failure', async () => {
    mockUpsert.mockResolvedValueOnce({ error: { message: 'write denied' } });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    await expect(
      markProfessorUpdatesRead([
        { professorId: PROFESSOR_ID, lastReadEventId: EVENT_ID },
      ]),
    ).resolves.toBeUndefined();

    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
