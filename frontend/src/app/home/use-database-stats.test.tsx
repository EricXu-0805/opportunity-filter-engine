import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, renderHook, waitFor } from '@testing-library/react';

vi.mock('@/lib/api', () => ({ getStats: vi.fn() }));

import { getStats } from '@/lib/api';
import type { StatsResponse } from '@/lib/types';
import { useDatabaseStats } from './use-database-stats';

const response = (overrides: Partial<StatsResponse> = {}): StatsResponse => ({
  total: 1234, active: 1234, faculty_contact_total: 9876,
  paid_total: 0, international_friendly_total: 0,
  by_type: {}, by_source: {}, by_paid: {}, by_international: {},
  last_updated_at: '2026-09-20T12:00:00Z', ...overrides,
});

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe('homepage database statistics', () => {
  it('loads the two public API populations separately without adding them', async () => {
    vi.mocked(getStats).mockResolvedValue(response());
    const { result } = renderHook(() => useDatabaseStats());
    expect(result.current.status).toBe('loading');
    expect(result.current.oppCount).toBeNull();
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current).toEqual({
      oppCount: 1234, facultyCount: 9876,
      lastUpdated: '2026-09-20T12:00:00Z', status: 'ready',
    });
  });

  it('preserves a measured zero for either population', async () => {
    vi.mocked(getStats).mockResolvedValue(response({ total: 0, faculty_contact_total: 0 }));
    const { result } = renderHook(() => useDatabaseStats());
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.oppCount).toBe(0);
    expect(result.current.facultyCount).toBe(0);
  });

  it('does not invent a zero when an older server omits the faculty count', async () => {
    vi.mocked(getStats).mockResolvedValue(response({ faculty_contact_total: undefined, last_updated_at: undefined }));
    const { result } = renderHook(() => useDatabaseStats());
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.oppCount).toBe(1234);
    expect(result.current.facultyCount).toBeNull();
    expect(result.current.lastUpdated).toBeNull();
  });

  it('ends loading and reports unavailable when the public statistics request fails', async () => {
    vi.mocked(getStats).mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useDatabaseStats());
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current).toEqual({
      oppCount: null, facultyCount: null, lastUpdated: null, status: 'error',
    });
  });

  it.each([-1, Number.NaN, Number.POSITIVE_INFINITY, 0.5])(
    'does not advertise malformed counts (%s) as measurements', async (badCount) => {
      vi.mocked(getStats).mockResolvedValue(response({ total: badCount, faculty_contact_total: badCount }));
      const { result } = renderHook(() => useDatabaseStats());
      await waitFor(() => expect(result.current.status).toBe('error'));
      expect(result.current.oppCount).toBeNull();
      expect(result.current.facultyCount).toBeNull();
    },
  );
});
