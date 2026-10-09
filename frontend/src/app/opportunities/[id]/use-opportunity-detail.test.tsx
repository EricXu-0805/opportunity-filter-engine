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

// identity-owner is NOT mocked: captureOwnerToken/OwnerMismatchError are the
// real primitives (module-singleton state, harmless to share across tests
// here since nothing asserts on specific uid/epoch values, only on whether
// a token was passed through and on real OwnerMismatchError instances).
import { OwnerMismatchError, advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { useOpportunityDetail, type SaveDetailsResult } from './use-opportunity-detail';

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

describe('useOpportunityDetail — ownerReady gates every private write', () => {
  it('starts false and only becomes true once getFavorites (which primes the shared owner primitive via its own ensureAnonSession call) has actually settled — not synchronously at hydration start', async () => {
    let resolveGetFavorites: ((s: Set<string>) => void) | undefined;
    mocks.getFavorites.mockImplementationOnce(() => new Promise((resolve) => { resolveGetFavorites = resolve; }));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    expect(result.current.ownerReady).toBe(false);
    // Still false while getFavorites is pending — hydration itself
    // (getAuthState resolving, interactionDetail fetch starting) does NOT
    // flip it.
    await Promise.resolve();
    expect(result.current.ownerReady).toBe(false);

    await act(async () => { resolveGetFavorites?.(new Set()); });
    expect(result.current.ownerReady).toBe(true);
  });

  it('before ownerReady is true, handleStar/handleTrack/saveDetails are no-ops: zero calls to any private-write helper', async () => {
    let resolveGetFavorites: ((s: Set<string>) => void) | undefined;
    mocks.getFavorites.mockImplementationOnce(() => new Promise((resolve) => { resolveGetFavorites = resolve; }));
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied' }); // so saveDetails' own `!interaction` guard isn't what blocks it

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interaction).toBe('applied'));
    expect(result.current.ownerReady).toBe(false); // getFavorites is still pending

    await act(async () => {
      await result.current.handleStar();
      await result.current.handleTrack('replied');
      await result.current.saveDetails({ notes: 'x' });
    });

    expect(mocks.toggleFavorite).not.toHaveBeenCalled();
    expect(mocks.trackInteraction).not.toHaveBeenCalled();
    expect(mocks.removeInteraction).not.toHaveBeenCalled();
    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled();

    await act(async () => { resolveGetFavorites?.(new Set()); });
    expect(result.current.ownerReady).toBe(true);
  });

  it('a rejected getFavorites leaves ownerReady false (a rejection gives no guarantee ensureAnonSession ever primed the shared primitive) — every write handler stays zero-write until a successful Retry primes it', async () => {
    mocks.getFavorites.mockRejectedValueOnce(new Error('network'));
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied' });

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteError).toBe(true));
    expect(result.current.ownerReady).toBe(false);

    await act(async () => {
      await result.current.handleStar();
      await result.current.handleTrack('replied');
      await result.current.saveDetails({ notes: 'x' });
    });
    expect(mocks.toggleFavorite).not.toHaveBeenCalled();
    expect(mocks.trackInteraction).not.toHaveBeenCalled();
    expect(mocks.removeInteraction).not.toHaveBeenCalled();
    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled();

    mocks.getFavorites.mockResolvedValueOnce(new Set());
    act(() => { result.current.retryFavoriteHydration(); });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleTrack('replied'); });
    expect(mocks.trackInteraction).toHaveBeenCalledTimes(1); // now primed, writes go through
  });
});

describe('useOpportunityDetail — a failed interaction read must never be treated as "no interaction"', () => {
  it('getInteractionDetail rejecting sets interactionError (not a silent null): status/notes actions stay disabled and attempt zero mutation', async () => {
    mocks.getInteractionDetail.mockRejectedValueOnce(new Error('network down'));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interactionError).toBe(true));
    expect(result.current.interactionLoading).toBe(false);
    expect(result.current.interactionDetail).toBeNull(); // NOT trustworthy — interactionError is the real signal

    await act(async () => {
      await result.current.handleTrack('applied'); // would silently overwrite a real 'replied' row if allowed through
      await result.current.saveDetails({ notes: 'x' });
    });
    expect(mocks.trackInteraction).not.toHaveBeenCalled();
    expect(mocks.removeInteraction).not.toHaveBeenCalled();
    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled();
  });

  it('retryInteractionHydration resolving the REAL advanced row (replied) surfaces the correct status, clears the error, and re-enables actions', async () => {
    mocks.getInteractionDetail
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ type: 'replied', notes: 'called already' });

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interactionError).toBe(true));

    act(() => { result.current.retryInteractionHydration(); });
    await waitFor(() => expect(result.current.interaction).toBe('replied'));
    expect(result.current.interactionError).toBe(false);
    expect(result.current.interactionDetail?.notes).toBe('called already');

    // Actions are now genuinely enabled and operate on the CORRECT (replied) status.
    mocks.trackInteraction.mockResolvedValueOnce(undefined);
    await act(async () => { await result.current.handleTrack('interviewing'); });
    expect(mocks.trackInteraction).toHaveBeenCalledWith('opp-1', 'interviewing', expect.anything());
  });

  it('retryInteractionHydration is a fail-closed no-op while a status write is in flight (mirrors retryFavoriteHydration)', async () => {
    mocks.getInteractionDetail.mockRejectedValueOnce(new Error('network down'));
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interactionError).toBe(true));

    act(() => { result.current.retryInteractionHydration(); }); // starts a retry — now loading
    expect(result.current.interactionLoading).toBe(true);
    const callsBefore = mocks.getInteractionDetail.mock.calls.length;

    act(() => { result.current.retryInteractionHydration(); }); // blocked: already loading
    expect(mocks.getInteractionDetail.mock.calls.length).toBe(callsBefore);
  });
});

describe('useOpportunityDetail — handleTrack is pessimistic: no fake persisted status', () => {
  it('does not present the new status as active until the write succeeds; statusSaving is true meanwhile', async () => {
    let resolveTrack: (() => void) | undefined;
    mocks.trackInteraction.mockImplementationOnce(() => new Promise<void>((resolve) => { resolveTrack = resolve; }));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    let trackPromise!: Promise<void>;
    act(() => { trackPromise = result.current.handleTrack('applied'); });
    expect(result.current.statusSaving).toBe(true);
    expect(result.current.interaction).toBeUndefined(); // NOT shown as active yet — write still in flight

    await act(async () => { resolveTrack?.(); await trackPromise; });
    expect(result.current.statusSaving).toBe(false);
    expect(result.current.interaction).toBe('applied'); // only now, after persistence succeeded
    expect(result.current.statusError).toBe(false);
  });

  it('on a thrown failure: interactionDetail stays at its last persisted value (never briefly showed the failed status), statusError is set, and retryTrack replays the same attempt and succeeds', async () => {
    mocks.trackInteraction
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(undefined);

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleTrack('applied'); });
    expect(result.current.statusError).toBe(true);
    expect(result.current.interaction).toBeUndefined(); // never flipped to 'applied'
    expect(result.current.statusSaving).toBe(false);

    await act(async () => { result.current.retryTrack(); });
    await waitFor(() => expect(result.current.interaction).toBe('applied'));
    expect(result.current.statusError).toBe(false);
    expect(mocks.trackInteraction).toHaveBeenCalledTimes(2);
    expect(mocks.trackInteraction).toHaveBeenNthCalledWith(2, 'opp-1', 'applied', expect.anything());
  });

  it('re-selecting the active status (untoggle) is also pessimistic: interactionDetail is only cleared after removeInteraction succeeds', async () => {
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied' });
    let resolveRemove: (() => void) | undefined;
    mocks.removeInteraction.mockImplementationOnce(() => new Promise<void>((resolve) => { resolveRemove = resolve; }));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interaction).toBe('applied'));

    let trackPromise!: Promise<void>;
    act(() => { trackPromise = result.current.handleTrack('applied'); }); // same type -> untoggle
    expect(result.current.statusSaving).toBe(true);
    expect(result.current.interaction).toBe('applied'); // still shown — remove not yet confirmed

    await act(async () => { resolveRemove?.(); await trackPromise; });
    expect(result.current.interactionDetail).toBeNull();
  });

  it('on a thrown removeInteraction failure, the status is NOT cleared (stays presented as persisted fact) and statusError is set', async () => {
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied' });
    mocks.removeInteraction.mockRejectedValueOnce(new Error('boom'));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interaction).toBe('applied'));

    await act(async () => { await result.current.handleTrack('applied'); });
    expect(result.current.statusError).toBe(true);
    expect(result.current.interaction).toBe('applied'); // untouched — the failed remove never took visual effect
  });

  it('an OwnerMismatchError from trackInteraction is NOT given special silent treatment while the generation is unchanged: it is a genuine failure for the context the user is still looking at — statusError is set, exactly like any other error', async () => {
    mocks.trackInteraction.mockRejectedValueOnce(new OwnerMismatchError());

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleTrack('applied'); });
    expect(result.current.statusError).toBe(true);
    expect(result.current.interaction).toBeUndefined(); // never flipped
  });

  it('an OwnerMismatchError IS dropped silently once the generation has genuinely changed (a real hydrate() already reset this view for a new target/identity) — the sole gate is generation, not the error type', async () => {
    let resolveTrack: ((e: unknown) => void) | undefined;
    mocks.trackInteraction.mockImplementationOnce(() => new Promise((_resolve, reject) => { resolveTrack = reject; }));

    const { result, rerender } = renderHook(
      ({ opp }) => useOpportunityDetail(opp),
      { initialProps: { opp: { id: 'opp-1', title: 'Test' } } },
    );
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    let trackPromise!: Promise<void>;
    act(() => { trackPromise = result.current.handleTrack('applied'); });
    expect(result.current.statusSaving).toBe(true);

    // A genuine target switch — bumps generationRef via a fresh hydrate().
    mocks.getFavorites.mockResolvedValueOnce(new Set());
    rerender({ opp: { id: 'opp-2', title: 'Test 2' } });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { resolveTrack?.(new OwnerMismatchError()); await trackPromise.catch(() => {}); });
    // The abandoned generation's failure must not touch the NEW target's state.
    expect(result.current.statusError).toBe(false);
    expect(result.current.statusSaving).toBe(false);
  });

  it('handleTrack passes an owner token as the third argument to trackInteraction/removeInteraction', async () => {
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleTrack('applied'); });
    expect(mocks.trackInteraction).toHaveBeenCalledWith(
      'opp-1', 'applied', expect.objectContaining({ epoch: expect.any(Number) }),
    );
  });

  it('while a status write is in flight, a second handleTrack call is a no-op (one mutation at a time)', async () => {
    let resolveTrack: (() => void) | undefined;
    mocks.trackInteraction.mockImplementationOnce(() => new Promise<void>((resolve) => { resolveTrack = resolve; }));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    let first!: Promise<void>;
    act(() => { first = result.current.handleTrack('applied'); });
    act(() => { void result.current.handleTrack('replied'); }); // ignored — a save is already in flight
    expect(mocks.trackInteraction).toHaveBeenCalledTimes(1);

    await act(async () => { resolveTrack?.(); await first; });
  });

  it('retryTrack replays the EXACT same op (SET, same type) rather than re-deriving from current state, and clears statusError on success', async () => {
    mocks.trackInteraction.mockRejectedValueOnce(new Error('transient'));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleTrack('interviewing'); });
    expect(result.current.statusError).toBe(true);
    expect(result.current.interaction).toBeUndefined(); // rolled back / never shown

    // No other status intent has been issued since — retry must call the
    // SAME helper (trackInteraction, not removeInteraction) with the SAME type.
    mocks.trackInteraction.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryTrack(); });
    await waitFor(() => expect(result.current.statusError).toBe(false));
    expect(mocks.trackInteraction).toHaveBeenCalledTimes(2);
    expect(mocks.trackInteraction).toHaveBeenNthCalledWith(2, 'opp-1', 'interviewing', expect.anything());
    expect(mocks.removeInteraction).not.toHaveBeenCalled();
    expect(result.current.interaction).toBe('interviewing');
  });

  it('a NEW status intent invalidates a stale failure — there is no lingering stale retry left to click', async () => {
    mocks.trackInteraction.mockRejectedValueOnce(new Error('transient'));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleTrack('interviewing'); });
    expect(result.current.statusError).toBe(true);

    // A fresh direct click (not a retry) for a DIFFERENT status — must
    // clear the old failure immediately, before this new attempt settles.
    mocks.trackInteraction.mockImplementation(() => new Promise<void>(() => {})); // never settles
    act(() => { void result.current.handleTrack('replied'); });
    expect(result.current.statusError).toBe(false);
  });

  it('retryTrack on a failed REMOVE (untoggle) replays removeInteraction again, never trackInteraction — a toggle re-derivation would invert it', async () => {
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied' });
    mocks.removeInteraction.mockRejectedValueOnce(new Error('transient'));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interaction).toBe('applied'));

    await act(async () => { await result.current.handleTrack('applied'); }); // same as current -> untoggle/remove
    expect(result.current.statusError).toBe(true);
    expect(result.current.interaction).toBe('applied'); // never cleared — the failed remove had no visual effect
    expect(mocks.removeInteraction).toHaveBeenCalledTimes(1);

    mocks.removeInteraction.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryTrack(); });
    await waitFor(() => expect(result.current.statusError).toBe(false));
    expect(mocks.removeInteraction).toHaveBeenCalledTimes(2);
    expect(mocks.trackInteraction).not.toHaveBeenCalled(); // never inverted into a SET
    expect(result.current.interactionDetail).toBeNull();
  });
});

// saveDetails writes a reminder date only for a target the reminders cron
// would actually send for. The bare { id, title } used everywhere else in
// this file has no truth envelope, which resolves to a posture of `unknown` —
// the fail-closed answer, and the right default for every test that is not
// about reminder dates. The suites below ARE about reminder dates, so they
// pass a canonical live listing.
const LIVE_LISTING_TARGET = {
  id: 'opp-1',
  title: 'Test',
  source_type: 'campus_program',
  record_kind: 'listing',
  target_truth: {
    listing_state: 'open', reference_only: false, actionable: true,
    accepting_state: 'accepting', reason_code: null,
    verified_at: null, expires_at: null,
  },
} as const;

// The two shapes reminders are set on, both live: the cron would send for
// either while the student is still waiting for an answer.
const LIVE_FACULTY_TARGET = {
  id: 'opp-1',
  title: 'Prof. Rivera',
  source_type: 'faculty_research',
  record_kind: 'faculty_contact',
  target_truth: {
    listing_state: 'unknown', reference_only: false, actionable: true,
    accepting_state: 'unknown', reason_code: null,
    verified_at: null, expires_at: null,
  },
} as const;

describe('useOpportunityDetail — a recorded reply offers no reminder (M49)', () => {
  it.each([
    ['live listing', 'applied', 'replied', LIVE_LISTING_TARGET],
    ['live listing', 'applied', 'interviewing', LIVE_LISTING_TARGET],
    ['live faculty contact', 'contacted', 'replied', LIVE_FACULTY_TARGET],
    ['live faculty contact', 'contacted', 'interviewing', LIVE_FACULTY_TARGET],
  ] as const)(
    'a %s moved from %s to %s gets no date written through saveDetails, while notes and a clear still are',
    async (_label, from, to, target) => {
      mocks.getInteractionDetail.mockResolvedValueOnce({ type: from });
      mocks.trackInteraction.mockResolvedValueOnce(undefined);

      const { result } = renderHook(() => useOpportunityDetail(target));
      await waitFor(() => expect(result.current.interaction).toBe(from));
      await act(async () => { await result.current.handleTrack(to); });

      expect(result.current.interaction).toBe(to);

      // The cron no longer sends for the status it lands on. The detail
      // panel's own write path: the date is stripped, the notes in the same
      // patch still travel, and clearing a date stays allowed.
      await act(async () => {
        await result.current.saveDetails({ notes: 'they replied', remind_at: '2030-01-08' });
      });
      expect(mocks.updateInteractionDetails)
        .toHaveBeenCalledWith('opp-1', { notes: 'they replied' }, expect.anything());
      mocks.updateInteractionDetails.mockClear();
      await act(async () => { await result.current.saveDetails({ remind_at: null }); });
      expect(mocks.updateInteractionDetails)
        .toHaveBeenCalledWith('opp-1', { remind_at: null }, expect.anything());
    },
  );
});

describe('useOpportunityDetail — identityGeneration keys the caller\'s remount of TrackerPanel', () => {
  it('bumps on a real identity transition, not on a same-uid re-observation', async () => {
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    const initial = result.current.identityGeneration;

    // A same-identity re-observation (e.g. TOKEN_REFRESHED) is not a real transition.
    await act(async () => { authChangeCallback?.({ session: null, user: null, isAnonymous: true, email: null }); });
    // (default identity in this suite is anonymous/null; re-emitting the
    // SAME null identity must not bump the generation)
    expect(result.current.identityGeneration).toBe(initial);

    mocks.getFavorites.mockResolvedValueOnce(new Set());
    mocks.getInteractionDetail.mockResolvedValueOnce(null);
    await act(async () => { authChangeCallback?.({ session: {}, user: { id: 'u2' }, isAnonymous: false, email: null }); });
    await waitFor(() => expect(result.current.identityGeneration).toBe(initial + 1));
  });
});

describe('useOpportunityDetail — saveDetails is pessimistic: no fake "Saved"', () => {
  it('does not update interactionDetail until updateInteractionDetails succeeds', async () => {
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied' });
    let resolveUpdate: (() => void) | undefined;
    mocks.updateInteractionDetails.mockImplementationOnce(() => new Promise<void>((resolve) => { resolveUpdate = resolve; }));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interaction).toBe('applied'));

    let savePromise!: Promise<SaveDetailsResult>;
    act(() => { savePromise = result.current.saveDetails({ notes: 'draft' }); });
    expect(result.current.interactionDetail?.notes).toBeUndefined();

    await act(async () => { resolveUpdate?.(); await savePromise; });
    expect(result.current.interactionDetail?.notes).toBe('draft');
  });

  it('rejects on a thrown persistence failure (so TrackerPanel can show an honest error instead of "Saved"), and interactionDetail is left unchanged — the caller\'s own draft input is untouched by this hook entirely', async () => {
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied', notes: 'old notes' });
    mocks.updateInteractionDetails.mockRejectedValueOnce(new Error('network down'));

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interaction).toBe('applied'));

    await expect(act(async () => {
      await result.current.saveDetails({ notes: 'new notes' });
    })).rejects.toThrow('network down');
    expect(result.current.interactionDetail?.notes).toBe('old notes'); // never updated

    // Retry (the caller re-invoking saveDetails, e.g. from a Retry button) succeeds.
    mocks.updateInteractionDetails.mockResolvedValueOnce(undefined);
    await act(async () => { await result.current.saveDetails({ notes: 'new notes' }); });
    expect(result.current.interactionDetail?.notes).toBe('new notes');
  });

  it('an OwnerMismatchError from updateInteractionDetails is NOT given special silent treatment while the generation is unchanged: it rejects exactly like any other failure, and interactionDetail is left unchanged', async () => {
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied', notes: 'old' });
    mocks.updateInteractionDetails.mockRejectedValueOnce(new OwnerMismatchError());

    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interaction).toBe('applied'));

    await expect(act(async () => {
      await result.current.saveDetails({ notes: 'new' });
    })).rejects.toBeInstanceOf(OwnerMismatchError);
    expect(result.current.interactionDetail?.notes).toBe('old');
  });

  it('an OwnerMismatchError from updateInteractionDetails IS swallowed (does not reject) once the generation has genuinely changed', async () => {
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied', notes: 'old' });
    let rejectUpdate: ((e: unknown) => void) | undefined;
    mocks.updateInteractionDetails.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectUpdate = reject; }));

    const { result, rerender } = renderHook(
      ({ opp }) => useOpportunityDetail(opp),
      { initialProps: { opp: { id: 'opp-1', title: 'Test' } } },
    );
    await waitFor(() => expect(result.current.interaction).toBe('applied'));

    let savePromise!: Promise<SaveDetailsResult>;
    act(() => { savePromise = result.current.saveDetails({ notes: 'new' }); });

    mocks.getFavorites.mockResolvedValueOnce(new Set());
    mocks.getInteractionDetail.mockResolvedValueOnce(null);
    rerender({ opp: { id: 'opp-2', title: 'Test 2' } });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => {
      rejectUpdate?.(new OwnerMismatchError());
      const result = await savePromise.catch(() => { throw new Error('should not reject for an abandoned generation'); });
      expect(result).toEqual({ status: 'abandoned' });
    });
  });

  it('is a no-op when there is no interaction yet — never fabricates an "applied" status via a notes/reminder save', async () => {
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    let saveResult!: SaveDetailsResult;
    await act(async () => { saveResult = await result.current.saveDetails({ notes: 'x' }); });
    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled();
    expect(saveResult).toEqual({ status: 'abandoned' });
  });
});

describe('useOpportunityDetail — saveDetails is the last gate before a reminder is written', () => {
  const CLOSED_TARGET = {
    ...LIVE_LISTING_TARGET,
    target_truth: {
      listing_state: 'closed', reference_only: false, actionable: false,
      accepting_state: 'not_accepting', reason_code: 'listing_closed',
      verified_at: null, expires_at: null,
    },
  } as const;

  it('a same-id target that closed under the page refuses a new date but still saves the notes beside it', async () => {
    // The closure test. `saveDetails` reads the truth envelope, so a deps
    // array of [opp.id] would judge this against the posture captured at
    // mount — the record's id never changed, only its truth did.
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied' });
    mocks.updateInteractionDetails.mockResolvedValue(undefined);

    const { result, rerender } = renderHook(
      ({ opp }) => useOpportunityDetail(opp),
      { initialProps: { opp: LIVE_LISTING_TARGET as { id: string; title: string } } },
    );
    await waitFor(() => expect(result.current.interaction).toBe('applied'));

    // Live: the date is written.
    await act(async () => {
      await result.current.saveDetails({ remind_at: '2030-01-01' });
    });
    expect(mocks.updateInteractionDetails)
      .toHaveBeenCalledWith('opp-1', { remind_at: '2030-01-01' }, expect.anything());

    mocks.updateInteractionDetails.mockClear();
    rerender({ opp: CLOSED_TARGET as { id: string; title: string } });

    // Closed: the date is stripped, the notes in the same patch survive.
    await act(async () => {
      await result.current.saveDetails({ notes: 'still mine', remind_at: '2030-02-02' });
    });
    expect(mocks.updateInteractionDetails)
      .toHaveBeenCalledWith('opp-1', { notes: 'still mine' }, expect.anything());
    expect(mocks.updateInteractionDetails.mock.calls[0][1]).not.toHaveProperty('remind_at');

    // And clearing is still allowed — dropping a date the student set is
    // never what this gate prevents.
    mocks.updateInteractionDetails.mockClear();
    await act(async () => { await result.current.saveDetails({ remind_at: null }); });
    expect(mocks.updateInteractionDetails)
      .toHaveBeenCalledWith('opp-1', { remind_at: null }, expect.anything());
  });

  it('a date-only patch on a closed target writes nothing at all', async () => {
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'applied' });
    mocks.updateInteractionDetails.mockResolvedValue(undefined);

    const { result } = renderHook(() => useOpportunityDetail(CLOSED_TARGET));
    await waitFor(() => expect(result.current.interaction).toBe('applied'));

    let outcome: { status: string } | undefined;
    await act(async () => {
      outcome = await result.current.saveDetails({ remind_at: '2030-01-01' });
    });

    expect(mocks.updateInteractionDetails).not.toHaveBeenCalled();
    // Reported as abandoned, so no caller shows "Saved" for a no-op.
    expect(outcome).toEqual({ status: 'abandoned' });
  });
});

describe('useOpportunityDetail — a confirmed contact reaches the page', () => {
  beforeEach(async () => {
    advanceOwnerEpoch('contact-owner'); await syncLocalIdentityOwner('contact-owner');
    mocks.getAuthState.mockResolvedValue({ session: null, user: { id: 'contact-owner' }, isAnonymous: true, email: null });
  });
  it('adopts the row the cold-email dialog wrote', async () => {
    // The dialog writes the contact row and owns that write. This page's own
    // read runs on mount and on a real identity change only, and closing a
    // modal is neither — so before this, TrackerPanel kept saying "Pick a
    // status above first" and kept the notes box disabled for a contact the
    // product had just recorded.
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interactionLoading).toBe(false));

    act(() => {
      result.current.noteContactConfirmed({
        type: 'contacted',
        last_contacted_at: '2026-09-03T12:00:00.000Z',
      } as never);
    });

    await waitFor(() => expect(result.current.interaction).toBe('contacted'));
    expect(result.current.interactionDetail).toMatchObject({ type: 'contacted' });
  });

  it('clears an authoritative missing summary and refreshes contact history', async () => {
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interactionLoading).toBe(false));

    await waitFor(() => expect(result.current.interactionLoading).toBe(false));
    act(() => result.current.noteContactConfirmed({ type: 'replied', notes: 'old server row' }));
    expect(result.current.interaction).toBe('replied');
    const revision = result.current.contactHistoryRevision;
    act(() => result.current.noteContactConfirmed(null));
    expect(result.current.interactionDetail).toBeNull();
    expect(result.current.contactHistoryRevision).toBe(revision + 1);
  });
});


describe('detail public sharing', () => {
  it.each(['native', 'clipboard'])('strips private result-return context from %s sharing', async (mode) => {
    window.history.replaceState({}, '', '/opportunities/opp-1?returnSession=private-ticket&returnTo=%2Fresults%3Fq%3Dprivate#anchor');
    const share = vi.fn().mockResolvedValue(undefined);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'share', { configurable: true, value: mode === 'native' ? share : undefined });
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.favoriteLoading).toBe(false));
    await act(async () => result.current.handleShare());
    if (mode === 'native') expect(share).toHaveBeenCalledWith({ title: 'Test', url: 'http://localhost:3000/opportunities/opp-1' });
    else expect(writeText).toHaveBeenCalledWith('http://localhost:3000/opportunities/opp-1');
  });
});


describe('useOpportunityDetail — status changes are not contact confirmations', () => {
  beforeEach(async () => {
    advanceOwnerEpoch('contact-owner'); await syncLocalIdentityOwner('contact-owner');
    mocks.getAuthState.mockResolvedValue({ session: null, user: { id: 'contact-owner' }, isAnonymous: true, email: null });
  });
  const statuses = ['contacted', 'applied', 'replied', 'interviewing', 'rejected', 'dismissed'] as const;
  const contactDate = '2026-08-21T15:30:00.000Z';

  it.each(statuses)('does not invent a contact date when selecting %s', async (status) => {
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interactionLoading).toBe(false));
    await act(async () => { await result.current.handleTrack(status); });
    expect(result.current.interaction).toBe(status);
    expect(result.current.interactionDetail?.last_contacted_at).toBeUndefined();
    expect(mocks.trackInteraction).toHaveBeenCalledWith('opp-1', status, expect.anything());
  });

  it.each(statuses)('preserves a confirmed contact date and notes when changing to %s', async (status) => {
    const initial = { type: status === 'applied' ? 'replied' : 'applied', last_contacted_at: contactDate,
      notes: 'Keep the reply context', remind_at: '2026-10-01' };
    mocks.getInteractionDetail.mockResolvedValueOnce(initial);
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interactionLoading).toBe(false));
    await act(async () => { await result.current.handleTrack(status); });
    expect(result.current.interactionDetail).toEqual({ ...initial, type: status });
  });

  it('preserves the actual date through a failed status change and its successful retry', async () => {
    mocks.getInteractionDetail.mockResolvedValueOnce({ type: 'contacted', last_contacted_at: contactDate });
    mocks.trackInteraction.mockRejectedValueOnce(new Error('offline'));
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interactionLoading).toBe(false));
    await act(async () => { await result.current.handleTrack('interviewing'); });
    expect(result.current.statusError).toBe(true);
    expect(result.current.interactionDetail).toEqual({ type: 'contacted', last_contacted_at: contactDate });
    act(() => result.current.retryTrack());
    await waitFor(() => expect(result.current.statusSaving).toBe(false));
    expect(result.current.statusError).toBe(false);
    expect(result.current.interactionDetail).toEqual({ type: 'interviewing', last_contacted_at: contactDate });
    expect(mocks.trackInteraction).toHaveBeenCalledTimes(2);
  });

  it('keeps a real contact receipt that arrives while a status change is pending', async () => {
    let resolveSave!: () => void;
    mocks.trackInteraction.mockImplementationOnce(() => new Promise<void>(resolve => { resolveSave = resolve; }));
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-1', title: 'Test' }));
    await waitFor(() => expect(result.current.interactionLoading).toBe(false));
    let saving!: Promise<void>;
    act(() => { saving = result.current.handleTrack('replied'); });
    act(() => result.current.noteContactConfirmed({ type: 'contacted', last_contacted_at: contactDate }));
    await act(async () => { resolveSave(); await saving; });
    expect(result.current.interactionDetail).toEqual({ type: 'replied', last_contacted_at: contactDate });
  });
});

describe.each([
  { kind: 'contact', callback: 'noteContactConfirmed', revision: 'contactHistoryRevision', otherRevision: 'applicationHistoryRevision' },
  { kind: 'application', callback: 'noteApplicationConfirmed', revision: 'applicationHistoryRevision', otherRevision: 'contactHistoryRevision' },
] as const)('detail $kind receipt scopes and pending work', ({ callback, revision, otherRevision }) => {
  beforeEach(async () => {
    advanceOwnerEpoch('receipt-A'); await syncLocalIdentityOwner('receipt-A');
    mocks.getAuthState.mockResolvedValue({ session: null, user: { id: 'receipt-A' }, isAnonymous: true, email: null });
  });
  it('refreshes history for each unchanged replay without changing timestamps', async () => {
    const record = { type: 'replied' as const, updated_at: '2026-01-01T00:00:00Z', notes: 'saved' };
    mocks.getInteractionDetail.mockResolvedValue(record);
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-A', title: 'A' }));
    await waitFor(() => expect(result.current.interactionLoading).toBe(false));
    const initial = result.current[revision];
    const otherInitial = result.current[otherRevision];
    act(() => result.current[callback](record));
    act(() => result.current[callback](record));
    expect(result.current[revision]).toBe(initial + 2);
    expect(result.current[otherRevision]).toBe(otherInitial);
    expect(result.current.interactionDetail).toEqual(record);
  });
  it.each([null, { type: 'contacted' as const }])('a late hydration cannot replace an authoritative receipt %#', async record => {
    let finish!: (value: { type: string }) => void;
    mocks.getInteractionDetail.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-A', title: 'A' }));
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    act(() => result.current[callback](record));
    await act(async () => { finish({ type: 'replied' }); });
    expect(result.current.interactionDetail).toEqual(record);
    expect(result.current.interactionLoading).toBe(false);
  });
  it.each(['status', 'notes'] as const)('a late %s save cannot resurrect an authoritative missing summary', async kind => {
    mocks.getInteractionDetail.mockResolvedValue({ type: 'replied', notes: 'saved note' });
    let finish!: () => void;
    (kind === 'status' ? mocks.trackInteraction : mocks.updateInteractionDetails).mockReturnValueOnce(new Promise<void>(resolve => { finish = resolve; }));
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-A', title: 'A' }));
    await waitFor(() => expect(result.current.interactionLoading).toBe(false));
    let saving!: Promise<unknown>;
    act(() => { saving = kind === 'status' ? result.current.handleTrack('interviewing') : result.current.saveDetails({ notes: 'pending note' }); });
    act(() => result.current[callback](null));
    expect(result.current.interactionDetail).toBeNull();
    await act(async () => { finish(); await saving; });
    expect(result.current.interactionDetail).toBeNull();
    expect(result.current.statusSaving).toBe(false);
  });
  it('rejects a retained target callback after a target change', async () => {
    const { result, rerender } = renderHook(({ id }) => useOpportunityDetail({ id, title: id }), { initialProps: { id: 'opp-A' } });
    await waitFor(() => expect(result.current.interactionLoading).toBe(false));
    const old = result.current[callback];
    rerender({ id: 'opp-B' });
    await waitFor(() => expect(result.current.interactionLoading).toBe(false));
    const initialRevision = result.current[revision];
    act(() => old({ type: 'replied' }));
    expect(result.current.interactionDetail).toBeNull();
    expect(result.current[revision]).toBe(initialRevision);
  });
  it('rejects a retained owner callback even before the parent receives an auth event', async () => {
    const { result } = renderHook(() => useOpportunityDetail({ id: 'opp-A', title: 'A' }));
    await waitFor(() => expect(result.current.interactionLoading).toBe(false));
    const old = result.current[callback]; const initialRevision = result.current[revision];
    advanceOwnerEpoch('receipt-B'); await syncLocalIdentityOwner('receipt-B');
    act(() => old({ type: 'replied' }));
    expect(result.current.interactionDetail).toBeNull();
    expect(result.current[revision]).toBe(initialRevision);
  });
});
