import { beforeEach, describe, it, expect, vi } from 'vitest';

const mockFrom = vi.fn();
const mockGetDeviceId = vi.fn();

vi.mock('./supabase', () => ({
  supabase: { from: (table: string) => mockFrom(table) },
  getDeviceId: () => mockGetDeviceId(),
}));

import { getMatchFeedback, setMatchFeedback } from './match-feedback';

// Same chainable + thenable query-builder mock as saved-searches.test.ts:
// every method returns the builder, awaiting it yields { data, error }.
function makeQuery(result: { data?: unknown; error?: { message: string } | null }) {
  const builder = {
    select: vi.fn((..._args: unknown[]) => builder),
    upsert: vi.fn((..._args: unknown[]) => builder),
    delete: vi.fn((..._args: unknown[]) => builder),
    eq: vi.fn((..._args: unknown[]) => builder),
    in: vi.fn((..._args: unknown[]) => builder),
    then: (onFulfilled: (v: typeof result) => unknown) =>
      Promise.resolve(result).then(onFulfilled),
  };
  return builder;
}

beforeEach(() => {
  mockFrom.mockReset();
  mockGetDeviceId.mockReset();
  mockGetDeviceId.mockResolvedValue('test-device-id');
});

describe('getMatchFeedback', () => {
  it('returns verdicts keyed by opportunity_id, scoped to (device_id, ids)', async () => {
    const q = makeQuery({
      data: [
        { opportunity_id: 'opp-1', verdict: 'up' },
        { opportunity_id: 'opp-2', verdict: 'down' },
      ],
      error: null,
    });
    mockFrom.mockReturnValue(q);

    const result = await getMatchFeedback(['opp-1', 'opp-2', 'opp-3']);

    expect(mockFrom).toHaveBeenCalledWith('match_feedback');
    expect(q.eq).toHaveBeenCalledWith('device_id', 'test-device-id');
    expect(q.in).toHaveBeenCalledWith('opportunity_id', ['opp-1', 'opp-2', 'opp-3']);
    expect(result.get('opp-1')).toBe('up');
    expect(result.get('opp-2')).toBe('down');
    expect(result.has('opp-3')).toBe(false);
  });

  it('returns an empty map without touching supabase when ids is empty', async () => {
    const result = await getMatchFeedback([]);
    expect(result.size).toBe(0);
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('returns an empty map when getDeviceId yields null (signed-out / failed auth)', async () => {
    mockGetDeviceId.mockResolvedValue(null);
    const result = await getMatchFeedback(['opp-1']);
    expect(result.size).toBe(0);
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('returns an empty map gracefully when the table does not exist yet (pre-migration)', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({
      data: null,
      error: { message: 'relation "match_feedback" does not exist' },
    }));
    const result = await getMatchFeedback(['opp-1']);
    expect(result.size).toBe(0);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it('returns an empty map and warns on other query errors', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({ data: null, error: { message: 'boom' } }));
    const result = await getMatchFeedback(['opp-1']);
    expect(result.size).toBe(0);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe('setMatchFeedback', () => {
  it('upserts the verdict with bucket + final_score on (device_id, opportunity_id)', async () => {
    const q = makeQuery({ data: null, error: null });
    mockFrom.mockReturnValue(q);

    const ok = await setMatchFeedback('opp-1', 'up', { bucket: 'high_priority', finalScore: 85 });

    expect(ok).toBe(true);
    expect(mockFrom).toHaveBeenCalledWith('match_feedback');
    expect(q.upsert).toHaveBeenCalledWith(
      expect.objectContaining({
        device_id: 'test-device-id',
        opportunity_id: 'opp-1',
        verdict: 'up',
        bucket: 'high_priority',
        final_score: 85,
      }),
      { onConflict: 'device_id,opportunity_id' },
    );
  });

  it('deletes the row scoped to (device_id, opportunity_id) when verdict is null', async () => {
    const q = makeQuery({ data: null, error: null });
    mockFrom.mockReturnValue(q);

    const ok = await setMatchFeedback('opp-1', null, { bucket: 'reach', finalScore: 42 });

    expect(ok).toBe(true);
    expect(q.delete).toHaveBeenCalled();
    expect(q.upsert).not.toHaveBeenCalled();
    expect(q.eq).toHaveBeenCalledWith('device_id', 'test-device-id');
    expect(q.eq).toHaveBeenCalledWith('opportunity_id', 'opp-1');
  });

  it('returns false when getDeviceId yields null', async () => {
    mockGetDeviceId.mockResolvedValue(null);
    const ok = await setMatchFeedback('opp-1', 'up', { bucket: 'reach', finalScore: 42 });
    expect(ok).toBe(false);
    expect(mockFrom).not.toHaveBeenCalled();
  });

  it('no-ops silently when the table does not exist yet (pre-migration)', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({
      data: null,
      error: { message: 'relation "match_feedback" does not exist' },
    }));
    const ok = await setMatchFeedback('opp-1', 'down', { bucket: 'reach', finalScore: 42 });
    expect(ok).toBe(false);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it('returns false and warns on other upsert errors', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockFrom.mockReturnValue(makeQuery({ data: null, error: { message: 'permission denied' } }));
    const ok = await setMatchFeedback('opp-1', 'down', { bucket: 'reach', finalScore: 42 });
    expect(ok).toBe(false);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
