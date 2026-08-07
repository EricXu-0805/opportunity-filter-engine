import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getFavorites: vi.fn(),
  toggleFavorite: vi.fn(),
  getAuthState: vi.fn(),
  onAuthChange: vi.fn(),
  getShortlistOpportunities: vi.fn(),
  removeCustomImport: vi.fn(),
}));

vi.mock('@/lib/supabase', () => ({
  getFavorites: mocks.getFavorites,
  toggleFavorite: mocks.toggleFavorite,
  getAuthState: mocks.getAuthState,
  onAuthChange: mocks.onAuthChange,
}));

vi.mock('@/lib/api', () => ({
  getShortlistOpportunities: mocks.getShortlistOpportunities,
}));

vi.mock('@/lib/custom-imports', () => ({
  removeCustomImport: mocks.removeCustomImport,
}));

import { useFavoritesData } from './use-favorites-data';
import type { Opp } from './types';

type AuthCb = (state: { session: unknown; user: { id: string } | null; isAnonymous: boolean; email: string | null }) => void;
let authChangeCallback: AuthCb | null = null;

function opp(id: string): Opp {
  return { id, title: `Title ${id}` };
}

beforeEach(() => {
  mocks.getFavorites.mockReset();
  mocks.toggleFavorite.mockReset();
  mocks.getAuthState.mockReset();
  mocks.onAuthChange.mockReset();
  mocks.getShortlistOpportunities.mockReset();
  mocks.removeCustomImport.mockReset();

  mocks.getFavorites.mockResolvedValue(new Set());
  mocks.getAuthState.mockResolvedValue({ session: null, user: null, isAnonymous: false, email: null });
  mocks.onAuthChange.mockImplementation((cb: AuthCb) => {
    authChangeCallback = cb;
    return () => { authChangeCallback = null; };
  });
  mocks.toggleFavorite.mockResolvedValue(false);
});

describe('useFavoritesData — loading / true-empty / error+retry', () => {
  it('starts loading, then settles to a true empty state after a successful zero-id load', async () => {
    mocks.getFavorites.mockResolvedValue(new Set());
    const { result } = renderHook(() => useFavoritesData());
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe(false);
    expect(result.current.serverOpportunities).toEqual([]);
    expect(result.current.unavailableCount).toBe(0);
    expect(mocks.getShortlistOpportunities).not.toHaveBeenCalled(); // no ids, nothing to batch-fetch
  });

  it('a getFavorites failure surfaces as error+retry, never a false empty shortlist', async () => {
    mocks.getFavorites
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(new Set());

    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.loading).toBe(false);
    expect(result.current.serverOpportunities).toEqual([]);

    act(() => { result.current.retry(); });
    expect(result.current.loading).toBe(true);
    // error flips false synchronously inside hydrate() — wait on loading
    // instead, which only clears once the retry's fetch actually resolves.
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe(false);
  });

  it('a getShortlistOpportunities failure (fail-closed ApiError) surfaces as error+retry', async () => {
    mocks.getFavorites.mockResolvedValue(new Set(['opp-1']));
    mocks.getShortlistOpportunities
      .mockRejectedValueOnce(new Error('SHORTLIST_UNKNOWN_ID'))
      .mockResolvedValueOnce({ opportunities: [opp('opp-1')], unavailableIds: [] });

    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.serverOpportunities).toEqual([]);

    act(() => { result.current.retry(); });
    await waitFor(() => expect(result.current.serverOpportunities).toEqual([opp('opp-1')]));
    expect(result.current.error).toBe(false);
  });
});

describe('useFavoritesData — identityGeneration is driven ONLY by a real uid transition, never by retry/ownerReady cycling', () => {
  it('a manual retry (same owner) re-loads the data but does NOT bump identityGeneration or change ownerScopeKey', async () => {
    mocks.getAuthState.mockResolvedValueOnce({
      session: {}, user: { id: 'u1' }, isAnonymous: false, email: 'u1@x.com',
    });
    mocks.getFavorites
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(new Set());

    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.error).toBe(true));
    const genBeforeRetry = result.current.identityGeneration;
    expect(genBeforeRetry).toBeGreaterThan(0);
    expect(result.current.ownerScopeKey).toBe('u1');

    act(() => { result.current.retry(); });
    expect(result.current.loading).toBe(true); // a real, fresh load attempt is in flight
    expect(result.current.identityGeneration).toBe(genBeforeRetry); // unchanged BEFORE the retry settles
    expect(result.current.ownerScopeKey).toBe('u1');

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.identityGeneration).toBe(genBeforeRetry); // still unchanged AFTER it settles
    expect(result.current.ownerScopeKey).toBe('u1');
  });

  it('ownerReady cycling false->true->false->true across a retry never touches identityGeneration', async () => {
    mocks.getFavorites.mockResolvedValueOnce(new Set());
    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    const gen = result.current.identityGeneration;

    mocks.getFavorites.mockRejectedValueOnce(new Error('boom'));
    act(() => { result.current.retry(); });
    expect(result.current.ownerReady).toBe(false); // reset for the new attempt
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.identityGeneration).toBe(gen);

    mocks.getFavorites.mockResolvedValueOnce(new Set());
    act(() => { result.current.retry(); });
    await waitFor(() => expect(result.current.ownerReady).toBe(true));
    expect(result.current.identityGeneration).toBe(gen); // still the SAME generation throughout
  });
});

describe('useFavoritesData — partial accounting', () => {
  it('a partial response preserves the found rows and reports the unavailable count, without dropping the missing ids anywhere', async () => {
    mocks.getFavorites.mockResolvedValue(new Set(['a', 'missing-1', 'missing-2']));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [opp('a')],
      unavailableIds: ['missing-1', 'missing-2'],
    });

    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.serverOpportunities).toEqual([opp('a')]);
    expect(result.current.unavailableCount).toBe(2);
    expect(result.current.error).toBe(false);
    expect(mocks.toggleFavorite).not.toHaveBeenCalled(); // missing ids are reported, never auto-unfavorited
  });

  it('all ids unavailable: reports the count with an empty (but not "true empty") list', async () => {
    mocks.getFavorites.mockResolvedValue(new Set(['gone-1', 'gone-2']));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [],
      unavailableIds: ['gone-1', 'gone-2'],
    });

    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.serverOpportunities).toEqual([]);
    expect(result.current.unavailableCount).toBe(2);
    expect(result.current.error).toBe(false);
  });
});

describe('useFavoritesData — handleRemove generation guard', () => {
  it('never touches customImports remotely: routes _customId removals to removeCustomImport only', async () => {
    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { await result.current.handleRemove({ id: 'x', title: 'X', _customId: 'x' }); });
    expect(mocks.removeCustomImport).toHaveBeenCalledWith('x', expect.objectContaining({ uid: null }));
    expect(mocks.toggleFavorite).not.toHaveBeenCalled();
  });

  it('a server remove filters the removed id out of state once toggleFavorite resolves', async () => {
    mocks.getFavorites.mockResolvedValue(new Set(['a', 'b']));
    mocks.getShortlistOpportunities.mockResolvedValue({
      opportunities: [opp('a'), opp('b')],
      unavailableIds: [],
    });
    let resolveToggle: ((v: boolean) => void) | undefined;
    mocks.toggleFavorite.mockImplementationOnce(() => new Promise((resolve) => { resolveToggle = resolve; }));

    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.serverOpportunities).toEqual([opp('a'), opp('b')]));

    let removePromise!: Promise<void>;
    act(() => { removePromise = result.current.handleRemove(opp('a')); });
    await act(async () => {
      resolveToggle?.(false);
      await removePromise;
    });
    expect(result.current.serverOpportunities).toEqual([opp('b')]);
  });

  it("a U1 remove that completes after switching to U2 does not filter U2's same-id card out of state", async () => {
    // U1's list contains 'shared-id'; the remove is left pending.
    mocks.getFavorites.mockResolvedValueOnce(new Set(['shared-id']));
    mocks.getShortlistOpportunities.mockResolvedValueOnce({
      opportunities: [opp('shared-id')],
      unavailableIds: [],
    });
    let resolveU1Toggle: ((v: boolean) => void) | undefined;
    mocks.toggleFavorite.mockImplementationOnce(
      () => new Promise((resolve) => { resolveU1Toggle = resolve; }),
    );

    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.serverOpportunities).toEqual([opp('shared-id')]));

    let removePromise!: Promise<void>;
    act(() => { removePromise = result.current.handleRemove(opp('shared-id')); }); // U1: remove pending

    // U2 also happens to favorite the SAME opportunity id.
    mocks.getFavorites.mockResolvedValueOnce(new Set(['shared-id']));
    mocks.getShortlistOpportunities.mockResolvedValueOnce({
      opportunities: [opp('shared-id')],
      unavailableIds: [],
    });
    act(() => {
      authChangeCallback?.({ session: {}, user: { id: 'u2' }, isAnonymous: false, email: 'u2@x.com' });
    });
    await waitFor(() => expect(result.current.serverOpportunities).toEqual([opp('shared-id')]));

    // U1's stale remove now completes — it must be a no-op against U2's list.
    await act(async () => {
      resolveU1Toggle?.(false);
      await removePromise;
    });
    expect(result.current.serverOpportunities).toEqual([opp('shared-id')]);
  });

  it('a toggleFavorite rejection is consumed inside the hook: never throws, and the list stays exactly as-is', async () => {
    mocks.getFavorites.mockResolvedValue(new Set(['a']));
    mocks.getShortlistOpportunities.mockResolvedValue({ opportunities: [opp('a')], unavailableIds: [] });
    mocks.toggleFavorite.mockRejectedValueOnce(new Error('network error'));

    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.serverOpportunities).toEqual([opp('a')]));

    // OpportunityCard calls onRemove without awaiting/catching it (a
    // fire-and-forget `onClick={() => onRemove(opp)}`) — if this rejected,
    // it would surface as an unhandled promise rejection in the browser.
    await expect(result.current.handleRemove(opp('a'))).resolves.toBeUndefined();
    expect(result.current.serverOpportunities).toEqual([opp('a')]); // untouched — removal never confirmed
  });
});

describe('useFavoritesData — auth race conditions', () => {
  it('a slow initial getAuthState(U1) resolving AFTER a live U2 event must not roll back or double-load', async () => {
    let resolveInitialAuth: ((s: unknown) => void) | undefined;
    mocks.getAuthState.mockImplementationOnce(
      () => new Promise((resolve) => { resolveInitialAuth = resolve; }),
    );
    mocks.getFavorites.mockResolvedValue(new Set());

    const { result } = renderHook(() => useFavoritesData());

    // A live sign-in event (U2) arrives before the slow initial snapshot resolves.
    act(() => {
      authChangeCallback?.({ session: {}, user: { id: 'u2' }, isAnonymous: false, email: 'u2@x.com' });
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1);

    // The stale snapshot now resolves with a DIFFERENT (U1) identity.
    await act(async () => {
      resolveInitialAuth?.({ session: {}, user: { id: 'u1' }, isAnonymous: false, email: 'u1@x.com' });
    });

    // Must not have rolled back or started a second hydration pass.
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1);
    expect(result.current.loading).toBe(false);
  });

  it("U1's shortlist fetch resolving LATE (after U2 already painted) must not overwrite U2's list", async () => {
    let resolveU1Shortlist: ((r: { opportunities: Opp[]; unavailableIds: string[] }) => void) | undefined;
    mocks.getFavorites.mockResolvedValueOnce(new Set(['x'])); // U1
    mocks.getShortlistOpportunities.mockImplementationOnce(
      () => new Promise((resolve) => { resolveU1Shortlist = resolve; }),
    );

    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(mocks.getShortlistOpportunities).toHaveBeenCalledTimes(1));
    expect(result.current.loading).toBe(true); // U1's fetch still pending

    // Switch to U2, whose own fetch resolves quickly and paints first.
    mocks.getFavorites.mockResolvedValueOnce(new Set(['y']));
    mocks.getShortlistOpportunities.mockResolvedValueOnce({ opportunities: [opp('y')], unavailableIds: [] });
    act(() => {
      authChangeCallback?.({ session: {}, user: { id: 'u2' }, isAnonymous: false, email: 'u2@x.com' });
    });
    await waitFor(() => expect(result.current.serverOpportunities).toEqual([opp('y')]));

    // U1's stale shortlist fetch now resolves — must be a no-op against U2's painted list.
    await act(async () => {
      resolveU1Shortlist?.({ opportunities: [opp('x')], unavailableIds: [] });
    });
    expect(result.current.serverOpportunities).toEqual([opp('y')]);
    expect(result.current.loading).toBe(false);
  });

  it('a queued auth callback that fires after unmount does not re-hydrate', async () => {
    mocks.getFavorites.mockResolvedValue(new Set());
    const { result, unmount } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1);

    // Capture the callback BEFORE unmount — the mock's own unsubscribe()
    // sets the shared `authChangeCallback` variable to null, so reading it
    // AFTER unmount would just be calling `null?.(...)` and trivially pass
    // regardless of whether the hook's own `cancelled` guard works. Calling
    // the captured function reference directly is what actually exercises it.
    const queued = authChangeCallback;
    unmount();

    // Simulate a Supabase event that was already queued before unsubscribe
    // took effect.
    queued?.({ session: {}, user: { id: 'late-user' }, isAnonymous: false, email: 'late@x.com' });

    expect(mocks.getFavorites).toHaveBeenCalledTimes(1); // no post-unmount hydration
  });
});

describe('useFavoritesData — onIdentityChange callback', () => {
  it('fires only on a genuine identity transition, never on the initial resolution or a same-uid event', async () => {
    const onIdentityChange = vi.fn();
    mocks.getAuthState.mockResolvedValueOnce({
      session: {}, user: { id: 'u1' }, isAnonymous: false, email: 'u1@x.com',
    });

    const { result } = renderHook(() => useFavoritesData(onIdentityChange));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(onIdentityChange).not.toHaveBeenCalled(); // initial resolution is not a "change"

    act(() => {
      authChangeCallback?.({ session: {}, user: { id: 'u1' }, isAnonymous: false, email: 'u1@x.com' }); // same uid
    });
    expect(onIdentityChange).not.toHaveBeenCalled();

    act(() => {
      authChangeCallback?.({ session: {}, user: { id: 'u2' }, isAnonymous: false, email: 'u2@x.com' }); // real change
    });
    expect(onIdentityChange).toHaveBeenCalledTimes(1);
  });

  it('reads a fresh onIdentityChange callback each render without re-subscribing auth', async () => {
    const first = vi.fn();
    const second = vi.fn();
    const { result, rerender } = renderHook(
      ({ cb }) => useFavoritesData(cb),
      { initialProps: { cb: first } },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mocks.onAuthChange).toHaveBeenCalledTimes(1);

    rerender({ cb: second });
    expect(mocks.onAuthChange).toHaveBeenCalledTimes(1); // no re-subscription just from a new callback identity

    act(() => {
      authChangeCallback?.({ session: {}, user: { id: 'u2' }, isAnonymous: false, email: 'u2@x.com' });
    });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1); // the latest callback is the one invoked
  });
});

describe('useFavoritesData — auth identity resets', () => {
  it('re-hydrates on a genuine identity change and ignores a same-uid duplicate event', async () => {
    mocks.getFavorites
      .mockResolvedValueOnce(new Set(['a']))
      .mockResolvedValueOnce(new Set());
    mocks.getShortlistOpportunities.mockResolvedValueOnce({ opportunities: [opp('a')], unavailableIds: [] });

    const { result } = renderHook(() => useFavoritesData());
    await waitFor(() => expect(result.current.serverOpportunities).toEqual([opp('a')]));

    // Same identity (default null) repeated — must be a no-op.
    act(() => {
      authChangeCallback?.({ session: null, user: null, isAnonymous: false, email: null });
    });
    expect(mocks.getFavorites).toHaveBeenCalledTimes(1);
    expect(result.current.serverOpportunities).toEqual([opp('a')]);

    // A genuine identity change re-hydrates.
    act(() => {
      authChangeCallback?.({ session: {}, user: { id: 'user-1' }, isAnonymous: false, email: 'a@b.com' });
    });
    expect(result.current.loading).toBe(true);
    expect(result.current.serverOpportunities).toEqual([]); // reset synchronously — no stale flash
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.serverOpportunities).toEqual([]);
  });
});
