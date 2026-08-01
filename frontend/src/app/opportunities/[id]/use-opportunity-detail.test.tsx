import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getFavorites: vi.fn(),
  toggleFavorite: vi.fn(),
  trackInteraction: vi.fn(),
  removeInteraction: vi.fn(),
  getInteractionDetail: vi.fn(),
  updateInteractionDetails: vi.fn(),
  getAuthState: vi.fn(),
  onAuthChange: vi.fn(),
  track: vi.fn(),
}));

vi.mock('@/lib/supabase', () => ({
  getFavorites: mocks.getFavorites,
  toggleFavorite: mocks.toggleFavorite,
  trackInteraction: mocks.trackInteraction,
  removeInteraction: mocks.removeInteraction,
  getInteractionDetail: mocks.getInteractionDetail,
  updateInteractionDetails: mocks.updateInteractionDetails,
  getAuthState: mocks.getAuthState,
  onAuthChange: mocks.onAuthChange,
}));

vi.mock('@/lib/analytics', () => ({ track: mocks.track }));

import { useOpportunityDetail } from './use-opportunity-detail';

type AuthCb = (state: { session: unknown; user: { id: string } | null; isAnonymous: boolean; email: string | null }) => void;
let authChangeCallback: AuthCb | null = null;

beforeEach(() => {
  mocks.getFavorites.mockReset();
  mocks.toggleFavorite.mockReset();
  mocks.trackInteraction.mockReset();
  mocks.removeInteraction.mockReset();
  mocks.getInteractionDetail.mockReset();
  mocks.updateInteractionDetails.mockReset();
  mocks.getAuthState.mockReset();
  mocks.onAuthChange.mockReset();
  mocks.track.mockReset();

  mocks.getFavorites.mockResolvedValue(new Set());
  mocks.getInteractionDetail.mockResolvedValue(null);
  mocks.getAuthState.mockResolvedValue({ session: null, user: null, isAnonymous: false, email: null });
  mocks.onAuthChange.mockImplementation((cb: AuthCb) => {
    authChangeCallback = cb;
    return () => { authChangeCallback = null; };
  });
  mocks.toggleFavorite.mockResolvedValue(true);
  mocks.trackInteraction.mockResolvedValue(undefined);
  mocks.removeInteraction.mockResolvedValue(undefined);
  mocks.updateInteractionDetails.mockResolvedValue(undefined);
});

describe('useOpportunityDetail — favorite hydration loading/error/retry', () => {
  it('exposes loading true, then false, on a normal hydration', async () => {
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    expect(result.current.favoriteLoading).toBe(true);
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));
    expect(result.current.favoriteError).toBe(false);
  });

  it('surfaces a hydration failure as a retryable error, not a false unfavorited-and-loaded state', async () => {
    mocks.getFavorites
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(new Set(['opp-1']));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteError).toBe(true));
    expect(result.current.favoriteLoading).toBe(false);

    act(() => { result.current.retryFavoriteHydration(); });
    expect(result.current.favoriteLoading).toBe(true);
    await waitFor(() => expect(result.current.isFavorited).toBe(true));
    expect(result.current.favoriteError).toBe(false);
  });

  it('retryFavoriteHydration is favorite-only: it never touches interactionDetail or modal/temp state', async () => {
    mocks.getFavorites
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(new Set(['opp-1']));
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied', notes: 'draft notes' });

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteError).toBe(true));
    expect(result.current.interactionDetail).toEqual({ type: 'applied', notes: 'draft notes' });

    act(() => {
      result.current.setEmailModalOpen(true);
      result.current.setChatDrawerOpen(true);
    });

    act(() => { result.current.retryFavoriteHydration(); });
    // Favorite-only: no second interaction fetch, no state touched outside favorite/*.
    expect(mocks.getInteractionDetail).toHaveBeenCalledTimes(1);
    expect(result.current.interactionDetail).toEqual({ type: 'applied', notes: 'draft notes' });
    expect(result.current.emailModalOpen).toBe(true);
    expect(result.current.chatDrawerOpen).toBe(true);

    await waitFor(() => expect(result.current.isFavorited).toBe(true));
    expect(result.current.favoriteError).toBe(false);
  });

  it('fails closed on a hydration failure: handleStar does not act on a fabricated false, until Retry succeeds', async () => {
    mocks.getFavorites
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(new Set());

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteError).toBe(true));

    await act(async () => { await result.current.handleStar(); });
    expect(mocks.toggleFavorite).not.toHaveBeenCalled();
    expect(result.current.isFavorited).toBe(false); // untouched — no optimistic flip on a fabricated base

    act(() => { result.current.retryFavoriteHydration(); });
    // favoriteError flips false synchronously inside retryFavoriteHydration —
    // wait on favoriteLoading instead, which only clears once the retry's
    // fetch actually resolves, so handleStar isn't attempted mid-fetch.
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));
    expect(result.current.favoriteError).toBe(false);

    await act(async () => { await result.current.handleStar(); });
    expect(mocks.toggleFavorite).toHaveBeenCalledTimes(1); // re-enabled after a successful retry
  });
});

describe('useOpportunityDetail — save-busy and thrown save errors', () => {
  it('is busy while saving, rolls back and shows a retryable error on a thrown save failure, then recovers on retry', async () => {
    mocks.toggleFavorite
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(true);

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));

    let savePromise!: Promise<void>;
    act(() => { savePromise = result.current.handleStar(); });
    expect(result.current.favoriteSaving).toBe(true);
    expect(result.current.isFavorited).toBe(true); // optimistic

    await act(async () => { await savePromise; });
    expect(result.current.favoriteSaving).toBe(false);
    expect(result.current.favoriteSaveError).toBe(true);
    expect(result.current.isFavorited).toBe(false); // rolled back

    await act(async () => { await result.current.handleStar(); });
    expect(result.current.favoriteSaveError).toBe(false);
    expect(result.current.isFavorited).toBe(true);
  });

  it('preserves the local-only fallback contract: a resolved toggleFavorite is never treated as an error', async () => {
    // toggleFavorite degrading to a local-only write still resolves (never
    // throws) — that must not be converted into a save error or a rollback.
    mocks.toggleFavorite.mockResolvedValueOnce(true);

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));

    await act(async () => { await result.current.handleStar(); });
    expect(result.current.favoriteSaveError).toBe(false);
    expect(result.current.isFavorited).toBe(true);
  });

  it('retryFavoriteHydration is a fail-closed no-op while a save is pending — it never races a fresh read against the in-flight write', async () => {
    let rejectSave: ((e: Error) => void) | undefined;
    mocks.toggleFavorite.mockImplementationOnce(
      () => new Promise((_resolve, reject) => { rejectSave = reject; }),
    );

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1); // the initial hydration

    let savePromise!: Promise<void>;
    act(() => { savePromise = result.current.handleStar(); }); // optimistic star, save in flight
    expect(result.current.favoriteSaving).toBe(true);
    expect(result.current.isFavorited).toBe(true);

    act(() => { result.current.retryFavoriteHydration(); }); // blocked: a save is in flight
    // No new read was issued, and nothing about the in-flight save's state moved.
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1);
    expect(result.current.favoriteLoading).toBe(false);
    expect(result.current.favoriteSaving).toBe(true);
    expect(result.current.isFavorited).toBe(true);

    // The save now settles on its own — since retry never bumped the
    // favorite generation, its own catch/finally still applies normally
    // (nothing here was orphaned by a blocked retry).
    await act(async () => {
      rejectSave?.(new Error('save failed'));
      await savePromise;
    });
    expect(result.current.favoriteSaving).toBe(false);
    expect(result.current.favoriteSaveError).toBe(true);
    expect(result.current.isFavorited).toBe(false); // rolled back by the save's own failure handling
  });

  it('clicking Retry repeatedly while its own fetch is still in flight only issues ONE fetch', async () => {
    let resolveRetry: ((s: Set<string>) => void) | undefined;
    mocks.getFavorites
      .mockRejectedValueOnce(new Error('network')) // initial load fails
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRetry = resolve; }));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteError).toBe(true));

    act(() => { result.current.retryFavoriteHydration(); });
    expect(mocks.getFavorites).toHaveBeenCalledTimes(2); // 1 initial + 1 retry
    expect(result.current.favoriteLoading).toBe(true);

    // Further clicks while the retry's own fetch is still pending are no-ops.
    act(() => { result.current.retryFavoriteHydration(); });
    act(() => { result.current.retryFavoriteHydration(); });
    expect(mocks.getFavorites).toHaveBeenCalledTimes(2);

    await act(async () => { resolveRetry?.(new Set()); });
    expect(result.current.favoriteLoading).toBe(false);
  });
});

describe('useOpportunityDetail — target reused across an opportunity-id switch (rerender)', () => {
  it('a stale favorites response for the abandoned target cannot overwrite the new target', async () => {
    let resolveA: ((s: Set<string>) => void) | undefined;
    mocks.getFavorites
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve; }))
      .mockResolvedValueOnce(new Set(['b']));

    const { result, rerender } = renderHook(
      ({ opp }) => useOpportunityDetail(opp),
      { initialProps: { opp: { id: 'a', title: 'A' } } },
    );
    await waitFor(() => expect(mocks.getFavorites).toHaveBeenCalledTimes(1));

    rerender({ opp: { id: 'b', title: 'B' } });
    await waitFor(() => expect(result.current.isFavorited).toBe(true)); // b's favorites resolved

    await act(async () => {
      resolveA?.(new Set(['a'])); // late response for the abandoned target a
    });
    expect(result.current.isFavorited).toBe(true); // still b's truth, not clobbered by the stale a response
  });

  it('eventually resets favorite/interaction/modal state for the new target', async () => {
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied' }).mockResolvedValueOnce(null);

    const { result, rerender } = renderHook(
      ({ opp }) => useOpportunityDetail(opp),
      { initialProps: { opp: { id: 'a', title: 'A' } } },
    );
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));
    mocks.getFavorites.mockResolvedValueOnce(new Set(['a']));
    act(() => { result.current.retryFavoriteHydration(); });
    await waitFor(() => expect(result.current.isFavorited).toBe(true));
    expect(result.current.interaction).toBe('applied');

    act(() => {
      result.current.setEmailModalOpen(true);
      result.current.setChatDrawerOpen(true);
    });

    rerender({ opp: { id: 'b', title: 'B' } });
    await waitFor(() => expect(result.current.emailModalOpen).toBe(false));
    expect(result.current.chatDrawerOpen).toBe(false);
    expect(result.current.isFavorited).toBe(false);
    await waitFor(() => expect(result.current.interaction).toBeUndefined());
  });
});

describe('useOpportunityDetail — auth identity transitions', () => {
  it('sign-out clears private state and re-hydrates for the new (anonymous) identity', async () => {
    mocks.getAuthState.mockResolvedValueOnce({
      session: {}, user: { id: 'user-1' }, isAnonymous: false, email: 'a@b.com',
    });
    mocks.getFavorites
      .mockResolvedValueOnce(new Set(['opp-1']))
      .mockResolvedValueOnce(new Set());

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.isFavorited).toBe(true));

    act(() => {
      result.current.setTailorOpen(true);
      result.current.setRenovationOpen(true);
    });
    expect(result.current.tailorOpen).toBe(true);
    expect(result.current.renovationOpen).toBe(true);

    act(() => {
      authChangeCallback?.({ session: null, user: null, isAnonymous: true, email: null });
    });
    // Reset is synchronous within the auth callback — the previous
    // account's favorite AND open modals must not remain visible even for
    // one render (a useEffect-driven reset would run after paint and could
    // flash U1's Tailor/Renovation modal with U2's freshly-loaded profile).
    expect(result.current.isFavorited).toBe(false);
    expect(result.current.favoriteLoading).toBe(true);
    expect(result.current.tailorOpen).toBe(false);
    expect(result.current.renovationOpen).toBe(false);

    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));
    expect(result.current.isFavorited).toBe(false);
  });

  it('a repeated event for the same identity preserves open Tailor/Renovation modal state (no flash, no close)', async () => {
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));

    act(() => {
      result.current.setTailorOpen(true);
      result.current.setRenovationOpen(true);
    });

    act(() => {
      // Default identity resolved at mount is null/anonymous — this repeats it.
      authChangeCallback?.({ session: null, user: null, isAnonymous: false, email: null });
    });

    expect(result.current.tailorOpen).toBe(true); // untouched
    expect(result.current.renovationOpen).toBe(true); // untouched
  });

  it('sign-in re-hydrates from the new account instead of keeping the anonymous device state', async () => {
    mocks.getFavorites
      .mockResolvedValueOnce(new Set())
      .mockResolvedValueOnce(new Set(['opp-1']));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));
    expect(result.current.isFavorited).toBe(false);

    act(() => {
      authChangeCallback?.({ session: {}, user: { id: 'user-1' }, isAnonymous: false, email: 'a@b.com' });
    });
    expect(result.current.favoriteLoading).toBe(true);

    await waitFor(() => expect(result.current.isFavorited).toBe(true));
  });

  it('a newer live auth event beats a late-resolving initial auth snapshot', async () => {
    let resolveInitialAuth: ((s: unknown) => void) | undefined;
    mocks.getAuthState.mockImplementationOnce(
      () => new Promise((resolve) => { resolveInitialAuth = resolve; }),
    );

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));

    // A live sign-in event arrives before the slow initial snapshot resolves.
    act(() => {
      authChangeCallback?.({ session: {}, user: { id: 'live-user' }, isAnonymous: false, email: 'a@b.com' });
    });
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1);

    // The stale snapshot now resolves with a DIFFERENT (signed-out) identity.
    await act(async () => {
      resolveInitialAuth?.({ session: null, user: null, isAnonymous: true, email: null });
    });

    // Must not have started a second hydration pass for the stale identity.
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1);
  });

  it('an onAuthChange event reporting the same identity as the initial snapshot is a no-op (no refetch/reset)', async () => {
    mocks.getAuthState.mockResolvedValueOnce({
      session: {}, user: { id: 'u1' }, isAnonymous: false, email: 'u1@x.com',
    });
    mocks.getFavorites.mockResolvedValueOnce(new Set(['opp-1']));
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied' });

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1);
    expect(result.current.interaction).toBe('applied');

    act(() => {
      // supabase also fires INITIAL_SESSION / TOKEN_REFRESHED with the SAME uid.
      authChangeCallback?.({ session: {}, user: { id: 'u1' }, isAnonymous: false, email: 'u1@x.com' });
    });

    expect(mocks.getFavorites).toHaveBeenCalledTimes(1); // no second hydration pass
    expect(mocks.getInteractionDetail).toHaveBeenCalledTimes(1);
    expect(result.current.interaction).toBe('applied');
    expect(result.current.isFavorited).toBe(true);
  });

  it('a repeated event for the same identity preserves interaction and modal/temp state', async () => {
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied' });

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));
    expect(result.current.interaction).toBe('applied');

    act(() => { result.current.setEmailModalOpen(true); });
    expect(result.current.emailModalOpen).toBe(true);

    act(() => {
      // Default identity resolved at mount is null/anonymous — this repeats it.
      authChangeCallback?.({ session: null, user: null, isAnonymous: false, email: null });
    });

    expect(result.current.emailModalOpen).toBe(true); // untouched
    expect(result.current.interaction).toBe('applied'); // untouched
  });

  it('a genuinely different identity (U1 -> U2) resets and re-hydrates, including clearing a previously-loaded interaction', async () => {
    mocks.getAuthState.mockResolvedValueOnce({
      session: {}, user: { id: 'u1' }, isAnonymous: false, email: 'u1@x.com',
    });
    mocks.getInteractionDetail
      .mockResolvedValueOnce({ type: 'applied' })
      .mockResolvedValueOnce(null);

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interaction).toBe('applied'));

    act(() => {
      authChangeCallback?.({ session: null, user: null, isAnonymous: true, email: null }); // u1 -> u2 (anonymous)
    });

    await waitFor(() => expect(mocks.getInteractionDetail).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.interactionDetail).toBeNull());
  });
});
