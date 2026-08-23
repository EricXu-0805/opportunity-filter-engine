import { beforeEach, describe, it, expect, vi } from 'vitest';

const mockFrom = vi.fn();
const mockGetDeviceId = vi.fn();
const fetchMock = vi.fn();

vi.mock('./supabase', () => ({
  supabase: { from: (table: string) => mockFrom(table) },
  getDeviceId: () => mockGetDeviceId(),
}));

import {
  getTotalNewMatchCount,
  isValidDigestEmail,
  listSavedSearchDigests,
  listSavedSearches,
  saveSearch,
  setSavedSearchDigest,
  updateSavedSearch,
  removeSavedSearch,
  markSavedSearchSeen,
  savedSearchToUrl,
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
  last_run_at: '2026-05-24T02:00:00Z',
  last_result_ids: ['opp-a', 'opp-b'],
  new_match_ids: ['opp-b'],
};

beforeEach(() => {
  mockFrom.mockReset();
  mockGetDeviceId.mockReset();
  mockGetDeviceId.mockResolvedValue('test-device-id');
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
    const body = JSON.parse(String(init.body)) as { ids: string[] };
    return {
      ok: true,
      status: 200,
      json: async () => ({
        opportunities: body.ids.map((id) => ({ id })),
      }),
    };
  });
  vi.stubGlobal('fetch', fetchMock);
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
        last_run_at: '2026-05-24T02:00:00Z',
        last_result_ids: ['opp-a', 'opp-b'],
        new_match_ids: ['opp-b'],
      },
    ]);
  });

  it('defaults missing cron-output fields to null / empty arrays (pre-cron state)', async () => {
    const preCronRow = {
      ...SAMPLE_ROW,
      last_run_at: null,
      last_result_ids: null,
      new_match_ids: null,
    };
    mockFrom.mockReturnValue(makeQuery({ data: [preCronRow], error: null }));

    const result = await listSavedSearches();

    expect(result[0].last_run_at).toBeNull();
    expect(result[0].last_result_ids).toEqual([]);
    expect(result[0].new_match_ids).toEqual([]);
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

  it('removes hidden stale ids before they drive badges or highlights', async () => {
    mockFrom.mockReturnValue(makeQuery({
      data: [{
        ...SAMPLE_ROW,
        new_match_ids: ['visible-research', 'hidden-fellowship'],
      }],
      error: null,
    }));
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ opportunities: [{ id: 'visible-research' }] }),
    });

    const result = await listSavedSearches();

    expect(result[0].new_match_ids).toEqual(['visible-research']);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toEqual({
      ids: ['visible-research', 'hidden-fellowship'],
    });
  });

  it('keeps searches but clears transient new claims when visibility validation fails', async () => {
    mockFrom.mockReturnValue(makeQuery({ data: [SAMPLE_ROW], error: null }));
    fetchMock.mockRejectedValue(new Error('network unavailable'));

    const result = await listSavedSearches();

    expect(result).toHaveLength(1);
    expect(result[0].id).toBe(SAMPLE_ROW.id);
    expect(result[0].last_result_ids).toEqual(SAMPLE_ROW.last_result_ids);
    expect(result[0].new_match_ids).toEqual([]);
  });

  it('validates more than 200 ids in bounded API batches', async () => {
    const ids = Array.from({ length: 401 }, (_, index) => `opp-${index}`);
    mockFrom.mockReturnValue(makeQuery({
      data: [{ ...SAMPLE_ROW, new_match_ids: ids }],
      error: null,
    }));

    const result = await listSavedSearches();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls.map((call) => (
      JSON.parse(String(call[1].body)) as { ids: string[] }
    ).ids.length)).toEqual([200, 200, 1]);
    expect(result[0].new_match_ids).toEqual(ids);
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

describe('markSavedSearchSeen', () => {
  it('clears new_match_ids scoped to (device_id, id) and returns true on success', async () => {
    const q = makeQuery({ data: null, error: null });
    mockFrom.mockReturnValue(q);

    const ok = await markSavedSearchSeen('uuid-1');

    expect(ok).toBe(true);
    expect(mockFrom).toHaveBeenCalledWith('saved_searches');
    expect(q.update).toHaveBeenCalledWith({ new_match_ids: [] });
    expect(q.eq).toHaveBeenCalledWith('device_id', 'test-device-id');
    expect(q.eq).toHaveBeenCalledWith('id', 'uuid-1');
  });

  it('returns false without touching supabase when id is empty', async () => {
    const ok = await markSavedSearchSeen('');
    expect(ok).toBe(false);
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('returns false when getDeviceId is null', async () => {
    mockGetDeviceId.mockResolvedValue(null);
    const ok = await markSavedSearchSeen('uuid-1');
    expect(ok).toBe(false);
  });

  it('returns false and warns on update error', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({ data: null, error: { message: 'permission denied' } }));
    const ok = await markSavedSearchSeen('uuid-1');
    expect(ok).toBe(false);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe('savedSearchToUrl', () => {
  // R69-A: omit-sentinel for tab is 'high_priority' (was 'all'). Most tests
  // here use tab: 'high_priority' as a placeholder for "I'm testing a
  // different feature, give me the bare URL"; the dedicated tab test below
  // covers both halves of the round-trip explicitly.
  const EMPTY_FILTERS: SavedSearchFilters = {
    paid: '',
    intl: '',
    source: '',
    onCampus: '',
    deadline: '',
    minScore: 0,
  };

  it('returns bare /results when everything is at default', () => {
    expect(savedSearchToUrl({
      query: '',
      filters: EMPTY_FILTERS,
      sort_by: 'score',
      tab: 'high_priority',
    })).toBe('/results');
  });

  it('serialises query to ?q=', () => {
    expect(savedSearchToUrl({
      query: 'machine learning',
      filters: EMPTY_FILTERS,
      sort_by: 'score',
      tab: 'high_priority',
    })).toBe('/results?q=machine+learning');
  });

  it('serialises tab only when not the default "high_priority" (R69-A)', () => {
    // Non-default tabs round-trip.
    expect(savedSearchToUrl({
      query: '',
      filters: EMPTY_FILTERS,
      sort_by: 'score',
      tab: 'starred',
    })).toBe('/results?tab=starred');
    // The historic implicit default ('all') is now an explicit tab and
    // MUST round-trip so legacy saved searches don't silently snap to
    // the new high_priority default on apply.
    expect(savedSearchToUrl({
      query: '',
      filters: EMPTY_FILTERS,
      sort_by: 'score',
      tab: 'all',
    })).toBe('/results?tab=all');
    // The new omit-sentinel.
    expect(savedSearchToUrl({
      query: '',
      filters: EMPTY_FILTERS,
      sort_by: 'score',
      tab: 'high_priority',
    })).toBe('/results');
  });

  it('serialises sort only when not the default "score"', () => {
    expect(savedSearchToUrl({
      query: '',
      filters: EMPTY_FILTERS,
      sort_by: 'deadline',
      tab: 'high_priority',
    })).toBe('/results?sort=deadline');
    expect(savedSearchToUrl({
      query: '',
      filters: EMPTY_FILTERS,
      sort_by: 'score',
      tab: 'high_priority',
    })).toBe('/results');
  });

  it('maps filter fields to the URL keys /results actually reads (loc/dl/min)', () => {
    const url = savedSearchToUrl({
      query: '',
      filters: {
        paid: 'yes',
        intl: 'no',
        source: 'uiuc_faculty',
        onCampus: 'yes',
        deadline: '14',
        minScore: 70,
      },
      sort_by: 'score',
      tab: 'high_priority',
    });
    const params = new URLSearchParams(url.split('?')[1]);
    expect(params.get('paid')).toBe('yes');
    expect(params.get('intl')).toBe('no');
    expect(params.get('source')).toBe('uiuc_faculty');
    expect(params.get('loc')).toBe('yes');
    expect(params.get('dl')).toBe('14');
    expect(params.get('min')).toBe('70');
    expect(params.has('onCampus')).toBe(false);
    expect(params.has('deadline')).toBe(false);
    expect(params.has('minScore')).toBe(false);
  });

  it('elides minScore=0 (the unfiltered sentinel)', () => {
    expect(savedSearchToUrl({
      query: '',
      filters: { ...EMPTY_FILTERS, minScore: 0 },
      sort_by: 'score',
      tab: 'high_priority',
    })).toBe('/results');
  });

  it('combines tab + query + multiple filters in a single URL', () => {
    // tab: 'all' rather than 'high_priority' so the test still asserts
    // that a non-default tab survives serialisation alongside everything
    // else (mirrors the original intent of this test pre-R69-A).
    const url = savedSearchToUrl({
      query: 'NLP',
      filters: { paid: 'yes', intl: '', source: '', onCampus: '', deadline: '7', minScore: 60 },
      sort_by: 'deadline',
      tab: 'all',
    });
    const params = new URLSearchParams(url.split('?')[1]);
    expect(params.get('tab')).toBe('all');
    expect(params.get('q')).toBe('NLP');
    expect(params.get('paid')).toBe('yes');
    expect(params.get('dl')).toBe('7');
    expect(params.get('min')).toBe('60');
    expect(params.get('sort')).toBe('deadline');
  });

  describe('opts.highlight (R19 new-match ring)', () => {
    it('omits highlight when opts is undefined', () => {
      expect(savedSearchToUrl({
        query: '',
        filters: EMPTY_FILTERS,
        sort_by: 'score',
        tab: 'high_priority',
      })).toBe('/results');
    });

    it('omits highlight when opts.highlight is undefined', () => {
      expect(savedSearchToUrl({
        query: '',
        filters: EMPTY_FILTERS,
        sort_by: 'score',
        tab: 'high_priority',
      }, {})).toBe('/results');
    });

    it('omits highlight when opts.highlight is empty', () => {
      expect(savedSearchToUrl({
        query: '',
        filters: EMPTY_FILTERS,
        sort_by: 'score',
        tab: 'high_priority',
      }, { highlight: [] })).toBe('/results');
    });

    it('serialises a single ID', () => {
      const url = savedSearchToUrl({
        query: '',
        filters: EMPTY_FILTERS,
        sort_by: 'score',
        tab: 'high_priority',
      }, { highlight: ['opp-1'] });
      const params = new URLSearchParams(url.split('?')[1]);
      expect(params.get('highlight')).toBe('opp-1');
    });

    it('serialises multiple IDs as comma-joined and round-trips via URLSearchParams', () => {
      const url = savedSearchToUrl({
        query: '',
        filters: EMPTY_FILTERS,
        sort_by: 'score',
        tab: 'high_priority',
      }, { highlight: ['opp-a', 'opp-b', 'opp-c'] });
      const params = new URLSearchParams(url.split('?')[1]);
      expect(params.get('highlight')).toBe('opp-a,opp-b,opp-c');
      expect(params.get('highlight')!.split(',')).toEqual(['opp-a', 'opp-b', 'opp-c']);
    });

    it('coexists with other filters in the same URL', () => {
      const url = savedSearchToUrl({
        query: 'ml',
        filters: { ...EMPTY_FILTERS, paid: 'yes', intl: 'yes' },
        sort_by: 'score',
        tab: 'high_priority',
      }, { highlight: ['opp-x', 'opp-y'] });
      const params = new URLSearchParams(url.split('?')[1]);
      expect(params.get('q')).toBe('ml');
      expect(params.get('paid')).toBe('yes');
      expect(params.get('intl')).toBe('yes');
      expect(params.get('highlight')).toBe('opp-x,opp-y');
    });
  });

  describe('opts.savedSearchId (R20 ack target)', () => {
    it('omits savedSearchId when undefined', () => {
      const url = savedSearchToUrl({
        query: '',
        filters: EMPTY_FILTERS,
        sort_by: 'score',
        tab: 'high_priority',
      }, { highlight: ['opp-1'] });
      const params = new URLSearchParams(url.split('?')[1]);
      expect(params.has('savedSearchId')).toBe(false);
    });

    it('omits savedSearchId when empty string', () => {
      const url = savedSearchToUrl({
        query: '',
        filters: EMPTY_FILTERS,
        sort_by: 'score',
        tab: 'high_priority',
      }, { savedSearchId: '' });
      expect(url).toBe('/results');
    });

    it('emits savedSearchId when provided', () => {
      const url = savedSearchToUrl({
        query: '',
        filters: EMPTY_FILTERS,
        sort_by: 'score',
        tab: 'high_priority',
      }, { savedSearchId: 'uuid-abc' });
      const params = new URLSearchParams(url.split('?')[1]);
      expect(params.get('savedSearchId')).toBe('uuid-abc');
    });

    it('coexists with highlight + other filters', () => {
      const url = savedSearchToUrl({
        query: 'nlp',
        filters: { ...EMPTY_FILTERS, paid: 'yes' },
        sort_by: 'score',
        tab: 'high_priority',
      }, { highlight: ['opp-1', 'opp-2'], savedSearchId: 'uuid-xyz' });
      const params = new URLSearchParams(url.split('?')[1]);
      expect(params.get('q')).toBe('nlp');
      expect(params.get('paid')).toBe('yes');
      expect(params.get('highlight')).toBe('opp-1,opp-2');
      expect(params.get('savedSearchId')).toBe('uuid-xyz');
    });
  });
});

describe('getTotalNewMatchCount', () => {
  it('sums new_match_ids across all saved searches', async () => {
    mockFrom.mockReturnValue(makeQuery({
      data: [
        { ...SAMPLE_ROW, id: 'a', new_match_ids: ['x', 'y'] },
        { ...SAMPLE_ROW, id: 'b', new_match_ids: ['z'] },
        { ...SAMPLE_ROW, id: 'c', new_match_ids: [] },
      ],
      error: null,
    }));
    expect(await getTotalNewMatchCount()).toBe(3);
  });

  it('returns 0 when there are no saved searches', async () => {
    mockFrom.mockReturnValue(makeQuery({ data: [], error: null }));
    expect(await getTotalNewMatchCount()).toBe(0);
  });
});

describe('isValidDigestEmail', () => {
  it('accepts normal addresses', () => {
    expect(isValidDigestEmail('user@example.com')).toBe(true);
    expect(isValidDigestEmail('  eric.guoyi+tag@sub.example.io ')).toBe(true);
  });

  it('rejects malformed / empty / oversized addresses', () => {
    expect(isValidDigestEmail('')).toBe(false);
    expect(isValidDigestEmail('   ')).toBe(false);
    expect(isValidDigestEmail('not-an-email')).toBe(false);
    expect(isValidDigestEmail('a@b')).toBe(false);
    expect(isValidDigestEmail('a b@example.com')).toBe(false);
    expect(isValidDigestEmail(`${'x'.repeat(250)}@example.com`)).toBe(false);
  });
});

describe('listSavedSearchDigests', () => {
  it('maps rows to a Map keyed by search id', async () => {
    const q = makeQuery({
      data: [
        { id: 'a', digest_email: 'user@example.com', digest_opt_in: true },
        { id: 'b', digest_email: null, digest_opt_in: false },
      ],
      error: null,
    });
    mockFrom.mockReturnValue(q);

    const result = await listSavedSearchDigests();

    expect(mockFrom).toHaveBeenCalledWith('saved_searches');
    expect(q.eq).toHaveBeenCalledWith('device_id', 'test-device-id');
    expect(result?.get('a')).toEqual({ email: 'user@example.com', optIn: true });
    expect(result?.get('b')).toEqual({ email: '', optIn: false });
  });

  it('returns null when getDeviceId is null (signed out)', async () => {
    mockGetDeviceId.mockResolvedValue(null);
    expect(await listSavedSearchDigests()).toBeNull();
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('returns null quietly when migration 013 is unapplied', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({
      data: null,
      error: { message: 'column saved_searches.digest_email does not exist' },
    }));
    expect(await listSavedSearchDigests()).toBeNull();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it('returns null and warns on other errors', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({ data: null, error: { message: 'boom' } }));
    expect(await listSavedSearchDigests()).toBeNull();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe('setSavedSearchDigest', () => {
  it('stores a normalized opt-in and clears the unsubscribe stamp', async () => {
    const q = makeQuery({ data: null, error: null });
    mockFrom.mockReturnValue(q);

    const ok = await setSavedSearchDigest('uuid-1', {
      email: '  User@Example.COM ',
      optIn: true,
    });

    expect(ok).toBe(true);
    expect(q.update).toHaveBeenCalledWith({
      digest_email: 'user@example.com',
      digest_opt_in: true,
      digest_unsubscribed_at: null,
    });
    expect(q.eq).toHaveBeenCalledWith('device_id', 'test-device-id');
    expect(q.eq).toHaveBeenCalledWith('id', 'uuid-1');
  });

  it('never stores opt-in=true with an invalid email', async () => {
    const q = makeQuery({ data: null, error: null });
    mockFrom.mockReturnValue(q);

    const ok = await setSavedSearchDigest('uuid-1', { email: 'nope', optIn: true });

    expect(ok).toBe(true);
    const updated = q.update.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(updated.digest_opt_in).toBe(false);
    expect('digest_unsubscribed_at' in updated).toBe(false);
  });

  it('opt-out keeps the unsubscribe stamp untouched', async () => {
    const q = makeQuery({ data: null, error: null });
    mockFrom.mockReturnValue(q);

    await setSavedSearchDigest('uuid-1', { email: 'user@example.com', optIn: false });

    const updated = q.update.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(updated.digest_opt_in).toBe(false);
    expect('digest_unsubscribed_at' in updated).toBe(false);
  });

  it('returns false when getDeviceId is null', async () => {
    mockGetDeviceId.mockResolvedValue(null);
    expect(await setSavedSearchDigest('uuid-1', { email: 'a@b.co', optIn: true })).toBe(false);
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('returns false when the update errors', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({ data: null, error: { message: 'boom' } }));
    expect(await setSavedSearchDigest('uuid-1', { email: 'a@b.co', optIn: true })).toBe(false);
    warn.mockRestore();
  });
});
