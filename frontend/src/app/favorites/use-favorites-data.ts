'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { getShortlistOpportunities } from '@/lib/api';
import { getAuthState, getFavorites, onAuthChange, toggleFavorite } from '@/lib/supabase';
import { removeCustomImport } from '@/lib/custom-imports';
import type { Opp } from './types';

export interface UseFavoritesDataResult {
  serverOpportunities: Opp[];
  loading: boolean;
  error: boolean;
  retry: () => void;
  /** Favorited ids the shortlist fetch could not resolve — never removed, just reported. */
  unavailableCount: number;
  handleRemove: (opp: Opp) => Promise<void>;
}

/**
 * Hydrates the /favorites server list: pulls fav IDs from supabase, then
 * resolves them to full opportunity payloads via the fail-closed shortlist
 * accounting helper. Resets and re-hydrates on a real signed-in identity
 * change (never on a same-uid event) — driven from the auth callback itself,
 * not a same-tick effect body — and generation-guards every async write so
 * a stale response from an abandoned identity can never paint over a
 * fresher one.
 *
 * `onIdentityChange`, if given, fires on that same real-transition-only
 * signal (never on the initial resolution, never on a same-uid event) — the
 * caller's page-local UI (expanded cards, open modals, compare selection)
 * lives outside this hook and has no other way to know an account switch
 * just happened.
 */
export function useFavoritesData(onIdentityChange?: () => void): UseFavoritesDataResult {
  const [serverOpportunities, setServerOpportunities] = useState<Opp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [unavailableCount, setUnavailableCount] = useState(0);
  const generationRef = useRef(0);
  // Read via ref (not an effect dependency) so the caller's callback can be
  // fresh every render without re-subscribing auth — only its latest value
  // at call time matters.
  const onIdentityChangeRef = useRef(onIdentityChange);
  useEffect(() => {
    onIdentityChangeRef.current = onIdentityChange;
  });

  const load = useCallback((generation: number) => {
    getFavorites().then((favSet) => {
      if (generationRef.current !== generation) return;
      const ids = Array.from(favSet);
      if (ids.length === 0) {
        // A true empty state — only reachable after this successful, zero-id load.
        setServerOpportunities([]);
        setUnavailableCount(0);
        setLoading(false);
        return;
      }
      getShortlistOpportunities(ids).then((result) => {
        if (generationRef.current !== generation) return;
        setServerOpportunities(result.opportunities as unknown as Opp[]);
        setUnavailableCount(result.unavailableIds.length);
        setLoading(false);
      }).catch(() => {
        if (generationRef.current !== generation) return;
        setLoading(false);
        setError(true);
      });
    }).catch(() => {
      if (generationRef.current !== generation) return;
      setLoading(false);
      setError(true);
    });
  }, []);

  const hydrate = useCallback(() => {
    const generation = ++generationRef.current;
    setServerOpportunities([]);
    setUnavailableCount(0);
    setLoading(true);
    setError(false);
    load(generation);
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    // A live onAuthChange event is always authoritative over this initial
    // snapshot, and onAuthChange also fires for non-identity events
    // (INITIAL_SESSION, TOKEN_REFRESHED) — only a genuine identity change
    // re-hydrates. undefined is a real sentinel: the resolved identity is
    // always `string | null`.
    let liveEventSeen = false;
    let lastIdentity: string | null | undefined;
    function applyIdentity(identity: string | null) {
      if (identity === lastIdentity) return;
      const isFirstResolution = lastIdentity === undefined;
      lastIdentity = identity;
      hydrate();
      // The initial resolution isn't a "change" from the caller's point of
      // view — there was no previous identity's page-local UI to clear.
      if (!isFirstResolution) onIdentityChangeRef.current?.();
    }
    getAuthState().then((state) => {
      if (cancelled || liveEventSeen) return;
      applyIdentity(state.user?.id ?? null);
    }).catch(() => {
      if (cancelled || liveEventSeen) return;
      applyIdentity(null);
    });
    const unsubscribe = onAuthChange((state) => {
      // A queued callback can still fire once after cleanup requests
      // unsubscribe but before it takes effect — check cancelled first.
      if (cancelled) return;
      liveEventSeen = true;
      applyIdentity(state.user?.id ?? null);
    });
    return () => {
      cancelled = true;
      unsubscribe();
      // eslint-disable-next-line react-hooks/exhaustive-deps
      generationRef.current++;
    };
  }, [hydrate]);

  const retry = useCallback(() => { hydrate(); }, [hydrate]);

  const handleRemove = useCallback(async (opp: Opp) => {
    if (opp._customId) {
      removeCustomImport(opp._customId);
      return;
    }
    const generation = generationRef.current;
    try {
      await toggleFavorite(opp.id, true);
    } catch {
      // OpportunityCard calls onRemove without awaiting/catching it — this
      // must never reject and become an unhandled promise rejection. Fail
      // safe: leave the list exactly as-is rather than guess whether the
      // remove actually took effect.
      return;
    }
    // An identity change mid-flight means this remove belongs to an
    // abandoned account's list — it must never edit the fresher identity's
    // list, even if both happen to favorite the same opportunity id.
    if (generationRef.current !== generation) return;
    setServerOpportunities(prev => prev.filter(o => o.id !== opp.id));
  }, []);

  return { serverOpportunities, loading, error, retry, unavailableCount, handleRemove };
}
