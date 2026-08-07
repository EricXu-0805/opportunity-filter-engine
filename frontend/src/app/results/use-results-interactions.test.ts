import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getFavorites: vi.fn(),
  getInteractions: vi.fn(),
  toggleFavorite: vi.fn(),
  trackInteraction: vi.fn(),
  removeInteraction: vi.fn(),
  getAuthState: vi.fn(),
  onAuthChange: vi.fn(),
}));

vi.mock('@/lib/supabase', () => ({
  getFavorites: mocks.getFavorites,
  getInteractions: mocks.getInteractions,
  toggleFavorite: mocks.toggleFavorite,
  trackInteraction: mocks.trackInteraction,
  removeInteraction: mocks.removeInteraction,
  getAuthState: mocks.getAuthState,
  onAuthChange: mocks.onAuthChange,
}));

// identity-owner is NOT mocked — captureOwnerToken is the real primitive,
// used here only to prove a token is passed through (see
// use-opportunity-detail.test.tsx for the same convention). This hook's own
// identity-change detection is entirely driven by the mocked
// getAuthState/onAuthChange below, independent of identity-owner's global
// uid/epoch state.
import { useResultsInteractions } from './use-results-interactions';

type AuthCb = (state: { session: unknown; user: { id: string } | null; isAnonymous: boolean; email: string | null }) => void;
let authChangeCallback: AuthCb | null = null;

function authState(uid: string | null) {
  return { session: null, user: uid ? { id: uid } : null, isAnonymous: false, email: null };
}

beforeEach(() => {
  mocks.getFavorites.mockReset();
  mocks.getInteractions.mockReset();
  mocks.toggleFavorite.mockReset();
  mocks.trackInteraction.mockReset();
  mocks.removeInteraction.mockReset();
  mocks.getAuthState.mockReset();
  mocks.onAuthChange.mockReset();
  authChangeCallback = null;

  mocks.getFavorites.mockResolvedValue(new Set());
  mocks.getInteractions.mockResolvedValue(new Map());
  mocks.getAuthState.mockResolvedValue(authState(null));
  mocks.onAuthChange.mockImplementation((cb: AuthCb) => {
    authChangeCallback = cb;
    return () => { authChangeCallback = null; };
  });
  mocks.toggleFavorite.mockResolvedValue(true);
  mocks.trackInteraction.mockResolvedValue(undefined);
  mocks.removeInteraction.mockResolvedValue(undefined);
});

describe('useResultsInteractions — hydration', () => {
  it('ownerReady flips true only after getFavorites settles; favs/interactions populate from the resolved data', async () => {
    mocks.getFavorites.mockResolvedValue(new Set(['opp-1']));
    mocks.getInteractions.mockResolvedValue(new Map([['opp-2', 'applied']]));
    const { result } = renderHook(() => useResultsInteractions());
    expect(result.current.ownerReady).toBe(false);
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.favs.has('opp-1')).toBe(true);
    expect(result.current.interactions.get('opp-2')).toBe('applied');
    expect(result.current.interactionsLoading).toBe(false);
    expect(result.current.interactionsError).toBe(false);
  });

  it('a bulk interaction read failure sets interactionsError, never a silent empty map; retryInteractionsLoad recovers', async () => {
    mocks.getInteractions.mockRejectedValueOnce(new Error('network down'));
    mocks.getInteractions.mockResolvedValueOnce(new Map([['opp-9', 'interviewing']]));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.interactionsError).toBe(true));
    expect(result.current.interactionsLoading).toBe(false);

    await act(async () => { result.current.retryInteractionsLoad(); });
    await waitFor(() => expect(result.current.interactionsError).toBe(false));
    expect(result.current.interactions.get('opp-9')).toBe('interviewing');
  });
});

describe('useResultsInteractions — pre-ready gate', () => {
  it('handleToggleFav/handleTrackInteraction are zero-mutation no-ops before ownerReady/interactions have settled', async () => {
    let resolveFav: ((v: Set<string>) => void) | undefined;
    mocks.getFavorites.mockReturnValue(new Promise((r) => { resolveFav = r; }));
    let resolveInter: ((v: Map<string, string>) => void) | undefined;
    mocks.getInteractions.mockReturnValue(new Promise((r) => { resolveInter = r; }));

    const { result } = renderHook(() => useResultsInteractions());
    await act(async () => {
      await result.current.handleToggleFav('opp-1');
      await result.current.handleTrackInteraction('opp-1', 'applied');
    });
    expect(mocks.toggleFavorite).not.toHaveBeenCalled();
    expect(mocks.trackInteraction).not.toHaveBeenCalled();

    await act(async () => { resolveFav?.(new Set()); resolveInter?.(new Map()); });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
  });
});

describe('useResultsInteractions — handleToggleFav', () => {
  it('passes an owner token as the third argument, and optimistically flips before the write resolves', async () => {
    let resolveToggle: (() => void) | undefined;
    mocks.toggleFavorite.mockReturnValue(new Promise<void>((r) => { resolveToggle = r; }));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    let p: Promise<void> = Promise.resolve();
    act(() => { p = result.current.handleToggleFav('opp-1'); });
    await waitFor(() => expect(result.current.favs.has('opp-1')).toBe(true));
    expect(mocks.toggleFavorite).toHaveBeenCalledWith('opp-1', false, expect.anything());

    await act(async () => { resolveToggle?.(); await p; });
    expect(result.current.favs.has('opp-1')).toBe(true);
  });

  it('rolls back the optimistic flip and adds opp-1 to favSaveErrors on a genuine failure; retryFavSave(id) replays the EXACT captured intent and succeeds', async () => {
    mocks.toggleFavorite.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleToggleFav('opp-1'); });
    expect(result.current.favs.has('opp-1')).toBe(false); // rolled back
    expect(result.current.favSaveErrors.has('opp-1')).toBe(true);

    mocks.toggleFavorite.mockResolvedValueOnce(true);
    await act(async () => { result.current.retryFavSave('opp-1'); });
    await waitFor(() => expect(result.current.favSaveErrors.has('opp-1')).toBe(false));
    expect(result.current.favs.has('opp-1')).toBe(true);
    // The retry replayed the ORIGINAL "add" intent (isFaved=false, the
    // pre-attempt state) a second time — never recomputed from whatever
    // favs happened to show at retry time.
    expect(mocks.toggleFavorite).toHaveBeenNthCalledWith(2, 'opp-1', false, expect.anything());
  });

  it('A fails, B succeeds: A\'s error/retry survives B\'s entire success — per-id, never a shared global slot', async () => {
    mocks.toggleFavorite.mockRejectedValueOnce(new Error('boom')); // A (opp-a)
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleToggleFav('opp-a'); });
    expect(result.current.favSaveErrors.has('opp-a')).toBe(true);

    mocks.toggleFavorite.mockResolvedValueOnce(true); // B (opp-b) succeeds cleanly
    await act(async () => { await result.current.handleToggleFav('opp-b'); });
    expect(result.current.favs.has('opp-b')).toBe(true);
    // B's success must not have touched A's still-visible error.
    expect(result.current.favSaveErrors.has('opp-a')).toBe(true);
    expect(result.current.favSaveErrors.has('opp-b')).toBe(false);

    mocks.toggleFavorite.mockResolvedValueOnce(true);
    await act(async () => { result.current.retryFavSave('opp-a'); });
    await waitFor(() => expect(result.current.favSaveErrors.has('opp-a')).toBe(false));
    expect(result.current.favs.has('opp-a')).toBe(true);
    expect(result.current.favs.has('opp-b')).toBe(true); // still there, untouched
  });

  it('A and B favorite failures coexist independently in favSaveErrors', async () => {
    mocks.toggleFavorite.mockRejectedValueOnce(new Error('boom-a'));
    mocks.toggleFavorite.mockRejectedValueOnce(new Error('boom-b'));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleToggleFav('opp-a'); });
    await act(async () => { await result.current.handleToggleFav('opp-b'); });
    expect(result.current.favSaveErrors.has('opp-a')).toBe(true);
    expect(result.current.favSaveErrors.has('opp-b')).toBe(true);
    expect(result.current.favSaveErrors.size).toBe(2);

    // Retrying B alone clears only B.
    mocks.toggleFavorite.mockResolvedValueOnce(true);
    await act(async () => { result.current.retryFavSave('opp-b'); });
    await waitFor(() => expect(result.current.favSaveErrors.has('opp-b')).toBe(false));
    expect(result.current.favSaveErrors.has('opp-a')).toBe(true);
  });
});

describe('useResultsInteractions — handleTrackInteraction', () => {
  it('passes an owner token, upserts via trackInteraction, and un-sets via removeInteraction on a repeat click of the same status', async () => {
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleTrackInteraction('opp-1', 'applied'); });
    expect(mocks.trackInteraction).toHaveBeenCalledWith('opp-1', 'applied', expect.anything());
    expect(result.current.interactions.get('opp-1')).toBe('applied');

    await act(async () => { await result.current.handleTrackInteraction('opp-1', 'applied'); });
    expect(mocks.removeInteraction).toHaveBeenCalledWith('opp-1', expect.anything());
    expect(result.current.interactions.has('opp-1')).toBe(false);
  });

  it('rolls back to the last known-persisted status and adds opp-1 to trackSaveErrors on failure — never leaves a failed write showing as saved; retryTrackSave(id) replays the exact SET', async () => {
    mocks.trackInteraction.mockRejectedValueOnce(new Error('write failed'));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleTrackInteraction('opp-1', 'applied'); });
    expect(result.current.interactions.has('opp-1')).toBe(false); // rolled back
    expect(result.current.trackSaveErrors.has('opp-1')).toBe(true);

    mocks.trackInteraction.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryTrackSave('opp-1'); });
    await waitFor(() => expect(result.current.trackSaveErrors.has('opp-1')).toBe(false));
    expect(result.current.interactions.get('opp-1')).toBe('applied');
    expect(mocks.trackInteraction).toHaveBeenNthCalledWith(2, 'opp-1', 'applied', expect.anything());
    expect(mocks.removeInteraction).not.toHaveBeenCalled();
  });

  it('A\'s SET fails, B\'s SET succeeds: A\'s error/retry survives B\'s success — per-id, never a shared global slot; retrying A replays the exact SET', async () => {
    mocks.trackInteraction.mockRejectedValueOnce(new Error('boom')); // A
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    await act(async () => { await result.current.handleTrackInteraction('opp-a', 'applied'); });
    expect(result.current.trackSaveErrors.has('opp-a')).toBe(true);

    mocks.trackInteraction.mockResolvedValueOnce(undefined); // B succeeds
    await act(async () => { await result.current.handleTrackInteraction('opp-b', 'replied'); });
    expect(result.current.interactions.get('opp-b')).toBe('replied');
    expect(result.current.trackSaveErrors.has('opp-a')).toBe(true); // untouched by B's success
    expect(result.current.trackSaveErrors.has('opp-b')).toBe(false);

    mocks.trackInteraction.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryTrackSave('opp-a'); });
    await waitFor(() => expect(result.current.trackSaveErrors.has('opp-a')).toBe(false));
    expect(result.current.interactions.get('opp-a')).toBe('applied');
    expect(mocks.trackInteraction).toHaveBeenNthCalledWith(3, 'opp-a', 'applied', expect.anything());
  });

  it('a failed REMOVE (untoggling an existing status) retries via removeInteraction again — NEVER trackInteraction', async () => {
    // Establish an existing status first so the next click is a REMOVE.
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    await act(async () => { await result.current.handleTrackInteraction('opp-1', 'applied'); });
    expect(result.current.interactions.get('opp-1')).toBe('applied');

    mocks.removeInteraction.mockRejectedValueOnce(new Error('boom'));
    await act(async () => {
      await result.current.handleTrackInteraction('opp-1', 'applied'); // same type again -> REMOVE
    });
    expect(result.current.interactions.get('opp-1')).toBe('applied'); // rolled back to the pre-remove value
    expect(result.current.trackSaveErrors.has('opp-1')).toBe(true);
    expect(mocks.removeInteraction).toHaveBeenCalledTimes(1);

    mocks.removeInteraction.mockResolvedValueOnce(undefined);
    await act(async () => { result.current.retryTrackSave('opp-1'); });
    await waitFor(() => expect(result.current.trackSaveErrors.has('opp-1')).toBe(false));
    expect(result.current.interactions.has('opp-1')).toBe(false); // the retried REMOVE actually took effect
    expect(mocks.removeInteraction).toHaveBeenCalledTimes(2); // called AGAIN
    expect(mocks.trackInteraction).toHaveBeenCalledTimes(1); // never re-invoked for the retry — only the original SET
  });
});

describe('useResultsInteractions — favorites initial-load failure and recovery', () => {
  it('a getFavorites rejection sets favoritesLoadError, keeps ownerReady false, and blocks every owner write; retryFavoritesLoad recovers and enables controls', async () => {
    mocks.getFavorites.mockRejectedValueOnce(new Error('network down'));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.favoritesLoadError).toBe(true));
    expect(result.current.favoritesLoading).toBe(false);
    expect(result.current.ownerReady).toBe(false);

    // Zero owner writes while unready — a click is a fail-closed no-op.
    await act(async () => { await result.current.handleToggleFav('opp-1'); });
    expect(mocks.toggleFavorite).not.toHaveBeenCalled();
    expect(result.current.favs.has('opp-1')).toBe(false);

    mocks.getFavorites.mockResolvedValueOnce(new Set(['opp-9']));
    await act(async () => { result.current.retryFavoritesLoad(); });
    await waitFor(() => expect(result.current.favoritesLoadError).toBe(false));
    expect(result.current.ownerReady).toBe(true);
    expect(result.current.favs.has('opp-9')).toBe(true);

    // Controls are enabled now — a real write goes through.
    await act(async () => { await result.current.handleToggleFav('opp-1'); });
    expect(mocks.toggleFavorite).toHaveBeenCalledWith('opp-1', false, expect.anything());
  });
});

describe('useResultsInteractions — same-identity load retries race (P1): an OLDER attempt resolving LATE must never mutate loading/error/data/ownerReady once a NEWER attempt has already applied its result', () => {
  it('favorites: R1 issued, then R2 issued and succeeds first (authoritative) — R1 rejecting LATE afterward has ZERO effect (no data overwrite, no favoritesLoadError/ownerReady flip)', async () => {
    mocks.getFavorites.mockRejectedValueOnce(new Error('initial boom'));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.favoritesLoadError).toBe(true));

    // R1: an older retry that will settle LATE (after R2).
    let rejectR1: (() => void) | undefined;
    mocks.getFavorites.mockReturnValueOnce(new Promise<Set<string>>((_res, rej) => {
      rejectR1 = () => rej(new Error('R1 late boom'));
    }));
    act(() => { result.current.retryFavoritesLoad(); }); // R1 issued, still pending

    // R2: a NEWER retry, issued before R1 settles, that resolves and is authoritative.
    mocks.getFavorites.mockResolvedValueOnce(new Set(['r2-fav']));
    await act(async () => { result.current.retryFavoritesLoad(); }); // R2 issued and resolves
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.favs.has('r2-fav')).toBe(true);
    expect(result.current.favoritesLoadError).toBe(false);
    expect(result.current.favoritesLoading).toBe(false);

    // R1 (the OLDER, superseded attempt) finally rejects LATE — must not
    // resurrect favoritesLoadError=true (which, combined with the
    // ownerReady=true R2 already set, would be a contradictory state) or
    // touch loading.
    await act(async () => { rejectR1?.(); });
    expect(result.current.favoritesLoadError).toBe(false);
    expect(result.current.ownerReady).toBe(true);
    expect(result.current.favoritesLoading).toBe(false);
    expect(result.current.favs.has('r2-fav')).toBe(true);
  });

  it('favorites: R1 issued, R2 issued and succeeds first — R1 SUCCEEDING late (with different/stale data) afterward has ZERO effect on favs', async () => {
    mocks.getFavorites.mockRejectedValueOnce(new Error('initial boom'));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.favoritesLoadError).toBe(true));

    let resolveR1: ((v: Set<string>) => void) | undefined;
    mocks.getFavorites.mockReturnValueOnce(new Promise((r) => { resolveR1 = r; }));
    act(() => { result.current.retryFavoritesLoad(); }); // R1

    mocks.getFavorites.mockResolvedValueOnce(new Set(['r2-fav']));
    await act(async () => { result.current.retryFavoritesLoad(); }); // R2 — authoritative
    await waitFor(() => expect(result.current.favs.has('r2-fav')).toBe(true));

    // R1 finally resolves LATE with DIFFERENT (stale) data — must not overwrite R2's.
    await act(async () => { resolveR1?.(new Set(['r1-stale-fav'])); });
    expect(result.current.favs.has('r1-stale-fav')).toBe(false);
    expect(result.current.favs.has('r2-fav')).toBe(true);
  });

  it('interactions: after the authoritative retry (R2) succeeds, a real status write is applied — an OLDER retry (R1) resolving even LATER must not erase that write', async () => {
    mocks.getInteractions.mockRejectedValueOnce(new Error('initial boom'));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.interactionsError).toBe(true));
    await waitFor(() => expect(result.current.ownerReady).toBe(true)); // favorites side hydrated fine

    let resolveR1: ((v: Map<string, string>) => void) | undefined;
    mocks.getInteractions.mockReturnValueOnce(new Promise((r) => { resolveR1 = r; }));
    act(() => { result.current.retryInteractionsLoad(); }); // R1 — stays pending

    mocks.getInteractions.mockResolvedValueOnce(new Map([['opp-1', 'applied']]));
    await act(async () => { result.current.retryInteractionsLoad(); }); // R2 — authoritative
    await waitFor(() => expect(result.current.interactionsError).toBe(false));
    expect(result.current.interactions.get('opp-1')).toBe('applied');

    // A real status write happens now, on top of R2's confirmed data.
    await act(async () => { await result.current.handleTrackInteraction('opp-1', 'interviewing'); });
    expect(result.current.interactions.get('opp-1')).toBe('interviewing');

    // R1 (superseded) FINALLY resolves, late, with stale data that would
    // erase the just-applied status write (and resurrect a phantom id) if
    // it were allowed to land.
    await act(async () => { resolveR1?.(new Map([['opp-1', 'applied'], ['opp-9', 'rejected']])); });
    expect(result.current.interactions.get('opp-1')).toBe('interviewing'); // NOT erased by stale R1
    expect(result.current.interactions.has('opp-9')).toBe(false); // R1's data never applied at all
  });
});

describe('useResultsInteractions — missing-identity coverage: U1 favorites left pending across a switch, rejecting late, must not touch U2', () => {
  it('U1 getFavorites stays pending; switch to U2; U2 hydrates successfully; U1 rejects late — U2 favorites remain, ownerReady=true, favoritesLoading=false, favoritesLoadError=false', async () => {
    let rejectU1: (() => void) | undefined;
    mocks.getFavorites.mockReturnValueOnce(new Promise<Set<string>>((_res, rej) => {
      rejectU1 = () => rej(new Error('U1 late boom'));
    }));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(mocks.getFavorites).toHaveBeenCalledTimes(1));
    expect(result.current.ownerReady).toBe(false); // U1's read is still pending

    mocks.getFavorites.mockResolvedValueOnce(new Set(['u2-fav']));
    mocks.getInteractions.mockResolvedValueOnce(new Map());
    await act(async () => { authChangeCallback?.(authState('u2')); });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.favs.has('u2-fav')).toBe(true);

    await act(async () => { rejectU1?.(); });
    expect(result.current.favs.has('u2-fav')).toBe(true); // untouched
    expect(result.current.ownerReady).toBe(true);
    expect(result.current.favoritesLoading).toBe(false);
    expect(result.current.favoritesLoadError).toBe(false);
  });
});

describe('useResultsInteractions — rapid double-click on the SAME opportunity', () => {
  it('a second click while the first write is still in flight is a fail-closed no-op, not a second overlapping mutation', async () => {
    let resolveToggle: (() => void) | undefined;
    mocks.toggleFavorite.mockReturnValue(new Promise<void>((r) => { resolveToggle = r; }));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    let p1: Promise<void> = Promise.resolve();
    let p2: Promise<void> = Promise.resolve();
    act(() => {
      p1 = result.current.handleToggleFav('opp-1');
      p2 = result.current.handleToggleFav('opp-1'); // same tick, same id — must be dropped
    });
    await waitFor(() => expect(result.current.pendingFavIds.has('opp-1')).toBe(true));
    expect(mocks.toggleFavorite).toHaveBeenCalledTimes(1);

    await act(async () => { resolveToggle?.(); await Promise.all([p1, p2]); });
    expect(mocks.toggleFavorite).toHaveBeenCalledTimes(1);
    expect(result.current.pendingFavIds.has('opp-1')).toBe(false);
  });

  it('same guard for track/remove: a second click on the same opportunity while its write is in flight is a fail-closed no-op', async () => {
    let resolveTrack: (() => void) | undefined;
    mocks.trackInteraction.mockReturnValue(new Promise<void>((r) => { resolveTrack = r; }));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    let p1: Promise<void> = Promise.resolve();
    let p2: Promise<void> = Promise.resolve();
    act(() => {
      p1 = result.current.handleTrackInteraction('opp-1', 'applied');
      p2 = result.current.handleTrackInteraction('opp-1', 'applied'); // same tick, same id — must be dropped
    });
    await waitFor(() => expect(result.current.pendingTrackIds.has('opp-1')).toBe(true));
    expect(mocks.trackInteraction).toHaveBeenCalledTimes(1);

    await act(async () => { resolveTrack?.(); await Promise.all([p1, p2]); });
    expect(mocks.trackInteraction).toHaveBeenCalledTimes(1);
    expect(result.current.pendingTrackIds.has('opp-1')).toBe(false);
  });
});

describe('useResultsInteractions — pending flag is generation-scoped, not just id-scoped', () => {
  it('a stale write completion from an abandoned identity does not clear a newer identity\'s pending flag for the SAME opportunity id', async () => {
    let resolveU1Write: (() => void) | undefined;
    mocks.toggleFavorite.mockImplementationOnce(() => new Promise<void>((r) => { resolveU1Write = r; }));

    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true)); // U1 (default null identity) hydrated

    // U1 starts a write for opp-shared, still pending.
    act(() => { void result.current.handleToggleFav('opp-shared'); });
    await waitFor(() => expect(result.current.pendingFavIds.has('opp-shared')).toBe(true));
    expect(mocks.toggleFavorite).toHaveBeenCalledTimes(1);

    // Live switch to U2 — resets pending state and re-hydrates independently.
    mocks.getFavorites.mockResolvedValueOnce(new Set());
    mocks.getInteractions.mockResolvedValueOnce(new Map());
    await act(async () => { authChangeCallback?.(authState('u2')); });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.pendingFavIds.has('opp-shared')).toBe(false); // the switch's own reset cleared U1's stale pending

    // U2 independently starts its OWN write for the SAME opportunity id.
    let resolveU2Write: (() => void) | undefined;
    mocks.toggleFavorite.mockImplementationOnce(() => new Promise<void>((r) => { resolveU2Write = r; }));
    act(() => { void result.current.handleToggleFav('opp-shared'); });
    await waitFor(() => expect(result.current.pendingFavIds.has('opp-shared')).toBe(true));
    expect(mocks.toggleFavorite).toHaveBeenCalledTimes(2);

    // The abandoned U1 write FINALLY resolves late — must NOT clear U2's pending flag.
    await act(async () => { resolveU1Write?.(); });
    expect(result.current.pendingFavIds.has('opp-shared')).toBe(true); // still pending — U2's own write not yet done

    // U2's own write resolving is what actually clears it.
    await act(async () => { resolveU2Write?.(); });
    await waitFor(() => expect(result.current.pendingFavIds.has('opp-shared')).toBe(false));
  });
});

describe('useResultsInteractions — identity switch clears ALL per-id error maps; a late U1 rejection cannot touch U2', () => {
  it('a real switch clears favSaveErrors/trackSaveErrors; a U1 favorite write left pending across the switch that later rejects LATE creates zero error for U2 and does not clear U2\'s own pending flag for the SAME id', async () => {
    // U1: a failed favorite AND a failed status, both visible.
    mocks.toggleFavorite.mockRejectedValueOnce(new Error('boom'));
    mocks.trackInteraction.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    await act(async () => { await result.current.handleToggleFav('opp-shared'); });
    await act(async () => { await result.current.handleTrackInteraction('opp-shared', 'applied'); });
    expect(result.current.favSaveErrors.has('opp-shared')).toBe(true);
    expect(result.current.trackSaveErrors.has('opp-shared')).toBe(true);

    // U1 starts a THIRD write, for a DIFFERENT id, that stays pending across the switch and rejects LATE.
    let rejectU1Write: (() => void) | undefined;
    mocks.toggleFavorite.mockImplementationOnce(() => new Promise<void>((_res, rej) => {
      rejectU1Write = () => rej(new Error('late boom'));
    }));
    act(() => { void result.current.handleToggleFav('opp-late'); });
    await waitFor(() => expect(result.current.pendingFavIds.has('opp-late')).toBe(true));

    // Live switch to U2 — must clear every per-id error/pending map.
    mocks.getFavorites.mockResolvedValueOnce(new Set());
    mocks.getInteractions.mockResolvedValueOnce(new Map());
    await act(async () => { authChangeCallback?.(authState('u2')); });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.favSaveErrors.size).toBe(0);
    expect(result.current.trackSaveErrors.size).toBe(0);
    expect(result.current.pendingFavIds.has('opp-late')).toBe(false);

    // U2 independently starts its OWN write for the SAME id (opp-late).
    let resolveU2Write: (() => void) | undefined;
    mocks.toggleFavorite.mockImplementationOnce(() => new Promise<void>((r) => { resolveU2Write = r; }));
    act(() => { void result.current.handleToggleFav('opp-late'); });
    await waitFor(() => expect(result.current.pendingFavIds.has('opp-late')).toBe(true));

    // The abandoned U1 write finally rejects, LATE — must not create an
    // error, must not clear U2's pending flag for the same id.
    await act(async () => { rejectU1Write?.(); });
    expect(result.current.favSaveErrors.has('opp-late')).toBe(false); // no error leaked in from U1
    expect(result.current.pendingFavIds.has('opp-late')).toBe(true); // U2's own write still pending

    await act(async () => { resolveU2Write?.(); });
    await waitFor(() => expect(result.current.pendingFavIds.has('opp-late')).toBe(false));
    expect(result.current.favSaveErrors.has('opp-late')).toBe(false); // U2's write succeeded cleanly
  });

  it('same guarantee on the STATUS channel: a U1 track write left pending across the switch that later rejects LATE creates zero error for U2 and does not clear U2\'s own pending flag for the SAME id', async () => {
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));

    let rejectU1Write: (() => void) | undefined;
    mocks.trackInteraction.mockImplementationOnce(() => new Promise<void>((_res, rej) => {
      rejectU1Write = () => rej(new Error('late boom'));
    }));
    act(() => { void result.current.handleTrackInteraction('opp-late', 'applied'); });
    await waitFor(() => expect(result.current.pendingTrackIds.has('opp-late')).toBe(true));

    mocks.getFavorites.mockResolvedValueOnce(new Set());
    mocks.getInteractions.mockResolvedValueOnce(new Map());
    await act(async () => { authChangeCallback?.(authState('u2')); });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.trackSaveErrors.size).toBe(0);
    expect(result.current.pendingTrackIds.has('opp-late')).toBe(false);

    let resolveU2Write: (() => void) | undefined;
    mocks.trackInteraction.mockImplementationOnce(() => new Promise<void>((r) => { resolveU2Write = r; }));
    act(() => { void result.current.handleTrackInteraction('opp-late', 'replied'); });
    await waitFor(() => expect(result.current.pendingTrackIds.has('opp-late')).toBe(true));

    await act(async () => { rejectU1Write?.(); });
    expect(result.current.trackSaveErrors.has('opp-late')).toBe(false);
    expect(result.current.pendingTrackIds.has('opp-late')).toBe(true); // U2's own write still pending

    await act(async () => { resolveU2Write?.(); });
    await waitFor(() => expect(result.current.pendingTrackIds.has('opp-late')).toBe(false));
    expect(result.current.trackSaveErrors.has('opp-late')).toBe(false);
    expect(result.current.interactions.get('opp-late')).toBe('replied'); // U2's write actually landed
  });
});

describe('useResultsInteractions — identityGeneration/ownerScopeKey: driven ONLY by a real uid transition, never by ownerReady', () => {
  it('the initial resolution establishes generation 1 and ownerScopeKey; a same-uid re-observation (TOKEN_REFRESHED) is a no-op; a REAL U1->U2 transition advances both; a switch to signed-out (null) also advances generation but sets ownerScopeKey to null', async () => {
    mocks.getAuthState.mockResolvedValue(authState('u1'));
    const { result } = renderHook(() => useResultsInteractions());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.identityGeneration).toBe(1);
    expect(result.current.ownerScopeKey).toBe('u1');

    // Same-uid re-observation — e.g. TOKEN_REFRESHED reporting u1 again.
    await act(async () => { authChangeCallback?.(authState('u1')); });
    expect(result.current.identityGeneration).toBe(1); // unchanged
    expect(result.current.ownerScopeKey).toBe('u1');

    // A load-failure + retry cycle flips ownerReady false->true->false->true
    // WITHOUT any identity change — identityGeneration must stay put too,
    // proving it is never derived from ownerReady.
    mocks.getFavorites.mockRejectedValueOnce(new Error('boom'));
    await act(async () => { result.current.retryFavoritesLoad(); });
    await waitFor(() => expect(result.current.favoritesLoadError).toBe(true));
    expect(result.current.identityGeneration).toBe(1);
    mocks.getFavorites.mockResolvedValueOnce(new Set());
    await act(async () => { result.current.retryFavoritesLoad(); });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.identityGeneration).toBe(1); // still generation 1

    // A REAL transition to a different uid.
    mocks.getFavorites.mockResolvedValueOnce(new Set());
    mocks.getInteractions.mockResolvedValueOnce(new Map());
    await act(async () => { authChangeCallback?.(authState('u2')); });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.identityGeneration).toBe(2);
    expect(result.current.ownerScopeKey).toBe('u2');

    // A REAL transition to signed-out (null uid).
    mocks.getFavorites.mockResolvedValueOnce(new Set());
    mocks.getInteractions.mockResolvedValueOnce(new Map());
    await act(async () => { authChangeCallback?.(authState(null)); });
    await waitFor(() => expect(result.current.identityGeneration).toBe(3));
    expect(result.current.ownerScopeKey).toBeNull();
  });
});

describe('useResultsInteractions — onIdentityChange callback', () => {
  it('does not fire on the first identity resolution (a normal hydration, not a switch), only on a REAL subsequent transition', async () => {
    const onIdentityChange = vi.fn();
    const { result } = renderHook(() => useResultsInteractions(onIdentityChange));
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(onIdentityChange).not.toHaveBeenCalled();

    await act(async () => { authChangeCallback?.(authState('u1')); });
    expect(onIdentityChange).toHaveBeenCalledTimes(1);

    // A same-uid re-observation (e.g. TOKEN_REFRESHED reporting u1 again) is not a real transition.
    await act(async () => { authChangeCallback?.(authState('u1')); });
    expect(onIdentityChange).toHaveBeenCalledTimes(1);

    await act(async () => { authChangeCallback?.(authState('u2')); });
    expect(onIdentityChange).toHaveBeenCalledTimes(2);
  });
});

describe('useResultsInteractions — initial identity resolution: generation/scope/read counts across a genuine first resolution + a real subsequent transition', () => {
  it('A: getAuthState genuinely resolves null first (generation 1, scope null, gen-1\'s own reads applied); a SUBSEQUENT live uid=u1 event is a real transition — generation 2, scope u1, onIdentityChange exactly once, and ONLY generation-2\'s own reads are shown (gen-1\'s leftover data is gone, not merely that the callback fired)', async () => {
    mocks.getAuthState.mockResolvedValue(authState(null));
    mocks.getFavorites.mockResolvedValueOnce(new Set(['gen1-fav']));
    mocks.getInteractions.mockResolvedValueOnce(new Map([['gen1-opp', 'applied']]));
    const onIdentityChange = vi.fn();
    const { result } = renderHook(() => useResultsInteractions(onIdentityChange));

    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.identityGeneration).toBe(1);
    expect(result.current.ownerScopeKey).toBeNull();
    expect(result.current.favs.has('gen1-fav')).toBe(true);
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1);
    expect(mocks.getInteractions).toHaveBeenCalledTimes(1);
    expect(onIdentityChange).not.toHaveBeenCalled(); // the FIRST resolution — never a "change"

    // A REAL subsequent transition: live uid=u1.
    mocks.getFavorites.mockResolvedValueOnce(new Set(['gen2-fav']));
    mocks.getInteractions.mockResolvedValueOnce(new Map([['gen2-opp', 'interviewing']]));
    await act(async () => { authChangeCallback?.(authState('u1')); });

    expect(result.current.identityGeneration).toBe(2);
    expect(result.current.ownerScopeKey).toBe('u1');
    expect(onIdentityChange).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    // ONLY generation-2's own reads are showing — not just "the callback
    // fired", but the actual data + read-call-count generation.
    expect(result.current.favs.has('gen1-fav')).toBe(false);
    expect(result.current.favs.has('gen2-fav')).toBe(true);
    expect(result.current.interactions.has('gen1-opp')).toBe(false);
    expect(result.current.interactions.get('gen2-opp')).toBe('interviewing');
    expect(mocks.getFavorites).toHaveBeenCalledTimes(2); // exactly one read per generation
    expect(mocks.getInteractions).toHaveBeenCalledTimes(2);
  });

  it('B: getAuthState is DEFERRED (will eventually resolve with a STALE u1) but a live u2 event arrives FIRST — this is the FIRST authoritative resolution (generation 1, scope u2, onIdentityChange NOT called — it is a hydration, not a "switch"); the deferred stale snapshot resolving LATE must be a complete no-op across generation, scope, data, AND read-call counts', async () => {
    let resolveAuthState: ((v: ReturnType<typeof authState>) => void) | undefined;
    mocks.getAuthState.mockReturnValue(new Promise((r) => { resolveAuthState = r; }));
    mocks.getFavorites.mockResolvedValueOnce(new Set(['u2-fav']));
    mocks.getInteractions.mockResolvedValueOnce(new Map([['u2-opp', 'applied']]));
    const onIdentityChange = vi.fn();
    const { result } = renderHook(() => useResultsInteractions(onIdentityChange));

    // Live u2 arrives BEFORE the initial getAuthState() promise ever settles
    // — onAuthChange's subscriber callback is captured synchronously in the
    // SAME mount effect that issued the still-pending getAuthState() call.
    await act(async () => { authChangeCallback?.(authState('u2')); });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.identityGeneration).toBe(1); // the FIRST resolution — not a "switch"
    expect(result.current.ownerScopeKey).toBe('u2');
    expect(onIdentityChange).not.toHaveBeenCalled();
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1);
    expect(mocks.getInteractions).toHaveBeenCalledTimes(1);

    // The deferred initial snapshot FINALLY resolves — late, and with a
    // DIFFERENT (stale) uid. liveEventSeen must make this a pure no-op:
    // no new generation, no scope change, no new reads, no callback.
    await act(async () => { resolveAuthState?.(authState('u1')); });

    expect(result.current.identityGeneration).toBe(1);
    expect(result.current.ownerScopeKey).toBe('u2');
    expect(result.current.favs.has('u2-fav')).toBe(true);
    expect(onIdentityChange).not.toHaveBeenCalled();
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1); // no additional read triggered
    expect(mocks.getInteractions).toHaveBeenCalledTimes(1);
  });
});

describe('useResultsInteractions — a stale U1 read resolving after a live U1->U2 switch never applies', () => {
  it('discards a late getFavorites/getInteractions result from the abandoned identity and only shows U2\'s own data', async () => {
    let resolveU1Favs: ((v: Set<string>) => void) | undefined;
    let resolveU1Inter: ((v: Map<string, string>) => void) | undefined;
    mocks.getFavorites.mockReturnValueOnce(new Promise((r) => { resolveU1Favs = r; }));
    mocks.getInteractions.mockReturnValueOnce(new Promise((r) => { resolveU1Inter = r; }));

    const { result } = renderHook(() => useResultsInteractions());
    // U1's initial getAuthState() resolution (mocked as null/anonymous by
    // default) already kicked off the U1 reads above, still pending.
    await waitFor(() => expect(mocks.getFavorites).toHaveBeenCalledTimes(1));

    // Live switch to U2 — must reset state and issue U2's OWN reads.
    mocks.getFavorites.mockResolvedValueOnce(new Set(['u2-fav']));
    mocks.getInteractions.mockResolvedValueOnce(new Map([['u2-opp', 'replied']]));
    await act(async () => { authChangeCallback?.(authState('u2')); });

    // The abandoned U1 promises finally resolve, LATE, with U1's data.
    await act(async () => {
      resolveU1Favs?.(new Set(['u1-fav']));
      resolveU1Inter?.(new Map([['u1-opp', 'applied']]));
    });

    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.favs.has('u1-fav')).toBe(false);
    expect(result.current.favs.has('u2-fav')).toBe(true);
    expect(result.current.interactions.has('u1-opp')).toBe(false);
    expect(result.current.interactions.get('u2-opp')).toBe('replied');
  });
});
