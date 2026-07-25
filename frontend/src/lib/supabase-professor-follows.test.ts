/*
 * Professor follow persistence (migration 022). Follows are cloud rows only —
 * they must survive the device and ride the cross-device merge (023) — so the
 * client contract is strict: reads throw rather than fake an empty list, and
 * writes throw rather than pretend the toggle changed.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const {
  mockFrom,
  mockGetSession,
  mockInsert,
  mockSelectEq,
  mockSelectOrder,
  mockSelectRange,
  mockDeleteFirstEq,
  mockDeleteSecondEq,
} = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key';
  return {
    mockFrom: vi.fn(),
    mockGetSession: vi.fn(),
    mockInsert: vi.fn(),
    mockSelectEq: vi.fn(),
    mockSelectOrder: vi.fn(),
    mockSelectRange: vi.fn(),
    mockDeleteFirstEq: vi.fn(),
    mockDeleteSecondEq: vi.fn(),
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
  followProfessor,
  isCanonicalProfessorId,
  listProfessorFollows,
  unfollowProfessor,
} from './supabase';

const UID = '11111111-1111-4111-8111-111111111111';
const PROFESSOR_ID = 'prof:v1:uiuc:11111111111111111111';

beforeEach(() => {
  localStorage.clear();
  mockFrom.mockReset();
  mockGetSession.mockReset().mockResolvedValue({
    data: { session: { user: { id: UID, is_anonymous: true } } },
  });
  mockInsert.mockReset().mockResolvedValue({ error: null });
  mockSelectEq.mockReset().mockReturnValue({ order: mockSelectOrder });
  mockSelectOrder.mockReset().mockReturnValue({ range: mockSelectRange });
  mockSelectRange.mockReset().mockResolvedValue({
    data: [{
      professor_id: PROFESSOR_ID,
      professor_name: 'Jane Doe',
      school: 'uiuc',
      created_at: '2026-07-20T00:00:00Z',
    }],
    error: null,
  });
  mockDeleteFirstEq.mockReset().mockReturnValue({ eq: mockDeleteSecondEq });
  mockDeleteSecondEq.mockReset().mockResolvedValue({ error: null });
  mockFrom.mockImplementation(() => ({
    select: vi.fn().mockReturnValue({ eq: mockSelectEq }),
    insert: mockInsert,
    delete: vi.fn().mockReturnValue({ eq: mockDeleteFirstEq }),
  }));
});

describe('isCanonicalProfessorId', () => {
  it.each([
    [PROFESSOR_ID, true],
    ['prof:v1:uiuc:UPPER111111111111111', false],
    ['prof:v1:uiuc:short', false],
    ['faculty-uiuc-ada', false],
    [null, false],
    [42, false],
  ])('%s -> %s', (value, expected) => {
    expect(isCanonicalProfessorId(value)).toBe(expected);
  });
});

describe('listProfessorFollows', () => {
  it('loads the current identity\'s follows with display fields', async () => {
    await expect(listProfessorFollows()).resolves.toEqual([{
      professorId: PROFESSOR_ID,
      professorName: 'Jane Doe',
      school: 'uiuc',
      createdAt: '2026-07-20T00:00:00Z',
    }]);

    expect(mockFrom).toHaveBeenCalledWith('professor_follows');
    expect(mockSelectEq).toHaveBeenCalledWith('device_id', UID);
  });

  it('loads every ordered page of a large follow list', async () => {
    const professorId = (index: number) => (
      `prof:v1:uiuc:${index.toString(16).padStart(20, '0')}`
    );
    const row = (index: number) => ({
      professor_id: professorId(index), professor_name: null, school: null,
      created_at: '2026-07-20T00:00:00Z',
    });
    mockSelectRange
      .mockResolvedValueOnce({
        data: Array.from({ length: 1000 }, (_, index) => row(index)),
        error: null,
      })
      .mockResolvedValueOnce({ data: [row(1000)], error: null });

    const follows = await listProfessorFollows();

    expect(follows).toHaveLength(1001);
    expect(follows[0].professorName).toBeNull();
    expect(mockSelectOrder).toHaveBeenNthCalledWith(1, 'professor_id', { ascending: true });
    expect(mockSelectRange).toHaveBeenNthCalledWith(1, 0, 999);
    expect(mockSelectRange).toHaveBeenNthCalledWith(2, 1000, 1999);
  });

  it('rejects the whole read when a later page fails', async () => {
    mockSelectRange
      .mockResolvedValueOnce({
        data: Array.from({ length: 1000 }, (_, index) => ({
          professor_id: `prof:v1:uiuc:${index.toString(16).padStart(20, '0')}`,
          professor_name: null, school: null, created_at: '',
        })),
        error: null,
      })
      .mockResolvedValueOnce({ data: null, error: { message: 'follow page 2 failed' } });

    await expect(listProfessorFollows()).rejects.toThrow('follow page 2 failed');
  });

  it('throws instead of turning a failed read into a false empty state', async () => {
    mockSelectRange.mockResolvedValue({ data: null, error: { message: 'read denied' } });

    await expect(listProfessorFollows()).rejects.toThrow('read denied');
  });
});

describe('followProfessor / unfollowProfessor', () => {
  it('inserts an owner-derived follow with display denormalizations', async () => {
    await expect(
      followProfessor(PROFESSOR_ID, 'Jane Doe', 'uiuc'),
    ).resolves.toBeUndefined();

    expect(mockInsert).toHaveBeenCalledWith({
      device_id: UID,
      professor_id: PROFESSOR_ID,
      professor_name: 'Jane Doe',
      school: 'uiuc',
    });
  });

  it('treats a duplicate follow as idempotent success for safe retries', async () => {
    mockInsert.mockResolvedValueOnce({
      error: { code: '23505', message: 'duplicate key value' },
    });

    await expect(followProfessor(PROFESSOR_ID)).resolves.toBeUndefined();
  });

  it('deletes only the current identity\'s selected professor', async () => {
    await expect(unfollowProfessor(PROFESSOR_ID)).resolves.toBeUndefined();

    expect(mockDeleteFirstEq).toHaveBeenCalledWith('device_id', UID);
    expect(mockDeleteSecondEq).toHaveBeenCalledWith('professor_id', PROFESSOR_ID);
  });

  it.each([
    'prof:v1:UIUC:11111111111111111111',
    'prof:v1:uiuc:too-short',
    `prof:v1:${'a'.repeat(49)}:11111111111111111111`,
    'faculty-uiuc-ada',
  ])('rejects malformed professor id %s before a database call', async (professorId) => {
    await expect(followProfessor(professorId)).rejects.toThrow(/faculty profile tracking id/i);
    await expect(unfollowProfessor(professorId)).rejects.toThrow(/faculty profile tracking id/i);
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('surfaces insert and delete failures so the toggle cannot lie', async () => {
    mockInsert.mockResolvedValueOnce({ error: { message: 'insert failed' } });
    await expect(followProfessor(PROFESSOR_ID)).rejects.toThrow('insert failed');

    mockDeleteSecondEq.mockResolvedValueOnce({ error: { message: 'delete failed' } });
    await expect(unfollowProfessor(PROFESSOR_ID)).rejects.toThrow('delete failed');
  });
});
