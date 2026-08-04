/*
 * useFavoritesData (W14):
 *   - truthful zero states: a failed load sets loadError (never a silent
 *     empty list) and retry() refetches;
 *   - cross-tab uid isolation via useAuthUid: a REAL identity switch clears
 *     Account A's list and refetches under B, while the initial null→uid
 *     resolution is absorbed (no double fetch of the mount load).
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

const mockGetFavorites = vi.fn();
const mockGetOpportunitiesByIds = vi.fn();
// Captured so tests can emit auth events (cross-tab uid switches).
let authCallback: ((s: { user: { id: string } | null }) => void) | null = null;

vi.mock('@/lib/supabase', () => ({
  getFavorites: () => mockGetFavorites(),
  toggleFavorite: vi.fn(() => Promise.resolve(false)),
  onAuthChange: (cb: (s: { user: { id: string } | null }) => void) => {
    authCallback = cb;
    return () => { authCallback = null; };
  },
}));

vi.mock('@/lib/api', () => ({
  getOpportunitiesByIds: (...args: unknown[]) => mockGetOpportunitiesByIds(...args),
}));

vi.mock('@/lib/custom-imports', () => ({
  removeCustomImport: vi.fn(),
}));

import { useFavoritesData } from './use-favorites-data';

beforeEach(() => {
  vi.clearAllMocks();
  authCallback = null;
  mockGetFavorites.mockResolvedValue(new Set(['opp-a']));
  mockGetOpportunitiesByIds.mockImplementation((ids: string[]) =>
    Promise.resolve(ids.map((id) => ({ id, title: `Opp ${id}` }))),
  );
});

describe('useFavoritesData — truthful zero states', () => {
  it('loads the server list and reports no error', async () => {
    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.loadError).toBe(false);
    expect(result.current.serverOpportunities.map((o) => o.id)).toEqual(['opp-a']);
  });

  it('sets loadError on failure and retry() refetches', async () => {
    mockGetFavorites.mockRejectedValueOnce(new Error('offline'));

    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.loadError).toBe(true);
    expect(result.current.serverOpportunities).toHaveLength(0);

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.loadError).toBe(false);
    expect(result.current.serverOpportunities.map((o) => o.id)).toEqual(['opp-a']);
    expect(mockGetFavorites).toHaveBeenCalledTimes(2);
  });
});

describe('useFavoritesData — cross-tab uid isolation', () => {
  it('absorbs the initial null→uid resolution without a double fetch', async () => {
    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mockGetFavorites).toHaveBeenCalledTimes(1);

    act(() => authCallback?.({ user: { id: 'anon-a' } }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mockGetFavorites).toHaveBeenCalledTimes(1);
  });

  it('clears the list and refetches under the new identity on a real uid switch', async () => {
    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => authCallback?.({ user: { id: 'anon-a' } }));
    expect(result.current.serverOpportunities.map((o) => o.id)).toEqual(['opp-a']);

    // Account B has a different set of favorites.
    mockGetFavorites.mockResolvedValue(new Set(['opp-b']));
    act(() => authCallback?.({ user: { id: 'account-b' } }));

    // The switch clears Account A's rows synchronously (loading again)…
    expect(result.current.loading).toBe(true);
    expect(result.current.serverOpportunities).toHaveLength(0);

    // …and the refetch renders Account B's data.
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.serverOpportunities.map((o) => o.id)).toEqual(['opp-b']);
    expect(mockGetFavorites).toHaveBeenCalledTimes(2);
  });
});
