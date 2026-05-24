import { beforeEach, describe, it, expect, vi } from 'vitest';

const mockFrom = vi.fn();
const mockGetDeviceId = vi.fn();

vi.mock('./supabase', () => ({
  supabase: { from: (table: string) => mockFrom(table) },
  getDeviceId: () => mockGetDeviceId(),
}));

import {
  listSavedSearches,
  saveSearch,
  updateSavedSearch,
  removeSavedSearch,
  type SavedSearchFilters,
} from './saved-searches';

// The supabase-js query builder is chainable + thenable: each method
// returns the same builder, and awaiting it (or calling .single()) yields
// { data, error }. This helper builds a mock that matches that shape so
// the wrapper can call .select().eq().order() / .insert().select().single() /
// .update().eq().eq() / .delete().eq().eq() — only the terminal await /
// single() result actually matters.
function makeQuery(result: { data?: unknown; error?: { message: string } | null }) {
  const builder = {
    select: vi.fn((..._args: unknown[]) => builder),
    insert: vi.fn((..._args: unknown[]) => builder),
    update: vi.fn((..._args: unknown[]) => builder),
    delete: vi.fn((..._args: unknown[]) => builder),
    eq: vi.fn((..._args: unknown[]) => builder),
    order: vi.fn((..._args: unknown[]) => Promise.resolve(result)),
    single: vi.fn(() => Promise.resolve(result)),
    then: (onFulfilled: (v: typeof result) => unknown) =>
      Promise.resolve(result).then(onFulfilled),
  };
  return builder;
}

const SAMPLE_FILTERS: SavedSearchFilters = {
  paid: 'yes',
  intl: '',
  source: '',
  onCampus: '',
  deadline: '7',
  minScore: 60,
};

const SAMPLE_ROW = {
  id: 'uuid-1',
  name: 'Paid + Urgent',
  query: 'machine learning',
  filters_json: SAMPLE_FILTERS,
  sort_by: 'deadline' as const,
  tab: 'all',
  created_at: '2026-05-24T00:00:00Z',
  updated_at: '2026-05-24T01:00:00Z',
};

beforeEach(() => {
  mockFrom.mockReset();
  mockGetDeviceId.mockReset();
  mockGetDeviceId.mockResolvedValue('test-device-id');
});

describe('listSavedSearches', () => {
  it('returns mapped rows on success, sorted by updated_at desc', async () => {
    const q = makeQuery({ data: [SAMPLE_ROW], error: null });
    mockFrom.mockReturnValue(q);

    const result = await listSavedSearches();

    expect(mockFrom).toHaveBeenCalledWith('saved_searches');
    expect(q.eq).toHaveBeenCalledWith('device_id', 'test-device-id');
    expect(q.order).toHaveBeenCalledWith('updated_at', { ascending: false });
    expect(result).toEqual([
      {
        id: 'uuid-1',
        name: 'Paid + Urgent',
        query: 'machine learning',
        filters: SAMPLE_FILTERS,
        sort_by: 'deadline',
        tab: 'all',
        created_at: '2026-05-24T00:00:00Z',
        updated_at: '2026-05-24T01:00:00Z',
      },
    ]);
  });

  it('returns [] when getDeviceId yields null (signed-out / failed auth)', async () => {
    mockGetDeviceId.mockResolvedValue(null);
    const result = await listSavedSearches();
    expect(result).toEqual([]);
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('returns [] when the query errors', async () => {
    mockFrom.mockReturnValue(makeQuery({ data: null, error: { message: 'boom' } }));
    const result = await listSavedSearches();
    expect(result).toEqual([]);
  });

  it('returns [] gracefully when the table does not exist yet (pre-migration)', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({
      data: null,
      error: { message: 'relation "saved_searches" does not exist' },
    }));
    const result = await listSavedSearches();
    expect(result).toEqual([]);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe('saveSearch', () => {
  it('inserts a row and returns the mapped record', async () => {
    const q = makeQuery({ data: SAMPLE_ROW, error: null });
    mockFrom.mockReturnValue(q);

    const result = await saveSearch({
      name: 'Paid + Urgent',
      query: 'machine learning',
      filters: SAMPLE_FILTERS,
      sort_by: 'deadline',
      tab: 'all',
    });

    expect(q.insert).toHaveBeenCalledWith(expect.objectContaining({
      device_id: 'test-device-id',
      name: 'Paid + Urgent',
      query: 'machine learning',
      filters_json: SAMPLE_FILTERS,
      sort_by: 'deadline',
      tab: 'all',
    }));
    expect(result?.id).toBe('uuid-1');
  });

  it('defaults sort_by=score, tab=all, query="" when caller omits them', async () => {
    const q = makeQuery({ data: SAMPLE_ROW, error: null });
    mockFrom.mockReturnValue(q);

    await saveSearch({ name: 'Bare', filters: SAMPLE_FILTERS });

    expect(q.insert).toHaveBeenCalledWith(expect.objectContaining({
      query: '',
      sort_by: 'score',
      tab: 'all',
    }));
  });

  it('trims name and rejects empty / whitespace-only names', async () => {
    const result = await saveSearch({ name: '   ', filters: SAMPLE_FILTERS });
    expect(result).toBeNull();
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('truncates names longer than 80 chars to match the table CHECK constraint', async () => {
    const q = makeQuery({ data: SAMPLE_ROW, error: null });
    mockFrom.mockReturnValue(q);

    await saveSearch({ name: 'x'.repeat(120), filters: SAMPLE_FILTERS });

    const inserted = q.insert.mock.calls[0]?.[0] as { name: string };
    expect(inserted.name.length).toBe(80);
  });

  it('returns null when getDeviceId is null', async () => {
    mockGetDeviceId.mockResolvedValue(null);
    const result = await saveSearch({ name: 'X', filters: SAMPLE_FILTERS });
    expect(result).toBeNull();
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('returns null and warns on insert error', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({ data: null, error: { message: 'constraint violation' } }));
    const result = await saveSearch({ name: 'X', filters: SAMPLE_FILTERS });
    expect(result).toBeNull();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe('updateSavedSearch', () => {
  it('patches only the provided fields and stamps updated_at', async () => {
    const q = makeQuery({ data: null, error: null });
    mockFrom.mockReturnValue(q);

    const ok = await updateSavedSearch('uuid-1', { name: 'renamed' });

    expect(ok).toBe(true);
    expect(q.update).toHaveBeenCalledTimes(1);
    const patch = q.update.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(patch.name).toBe('renamed');
    expect(patch.updated_at).toBeDefined();
    expect(patch.filters_json).toBeUndefined();
    expect(patch.query).toBeUndefined();
    expect(q.eq).toHaveBeenCalledWith('device_id', 'test-device-id');
    expect(q.eq).toHaveBeenCalledWith('id', 'uuid-1');
  });

  it('rejects empty name without dispatching the update', async () => {
    const ok = await updateSavedSearch('uuid-1', { name: '   ' });
    expect(ok).toBe(false);
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('returns false when getDeviceId is null', async () => {
    mockGetDeviceId.mockResolvedValue(null);
    const ok = await updateSavedSearch('uuid-1', { query: 'x' });
    expect(ok).toBe(false);
  });

  it('returns false and warns on update error', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({ data: null, error: { message: 'permission denied' } }));
    const ok = await updateSavedSearch('uuid-1', { query: 'x' });
    expect(ok).toBe(false);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe('removeSavedSearch', () => {
  it('deletes the row scoped to (device_id, id) and returns true on success', async () => {
    const q = makeQuery({ data: null, error: null });
    mockFrom.mockReturnValue(q);

    const ok = await removeSavedSearch('uuid-1');

    expect(ok).toBe(true);
    expect(q.delete).toHaveBeenCalled();
    expect(q.eq).toHaveBeenCalledWith('device_id', 'test-device-id');
    expect(q.eq).toHaveBeenCalledWith('id', 'uuid-1');
  });

  it('returns false when getDeviceId is null', async () => {
    mockGetDeviceId.mockResolvedValue(null);
    const ok = await removeSavedSearch('uuid-1');
    expect(ok).toBe(false);
  });

  it('returns false and warns on delete error', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({ data: null, error: { message: 'not found' } }));
    const ok = await removeSavedSearch('uuid-1');
    expect(ok).toBe(false);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
