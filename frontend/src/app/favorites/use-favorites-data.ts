'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { getShortlistOpportunities } from '@/lib/api';
import { getAuthState, getFavorites, onAuthChange, toggleFavorite } from '@/lib/supabase';
import { captureOwnerToken } from '@/lib/identity-owner';
import { removeCustomImport } from '@/lib/custom-imports';
import type { Opp } from './types';

export interface UseFavoritesDataResult {
  serverOpportunities: Opp[];
  loading: boolean;
  error: boolean;
  retry: () => void;
  /** Bumps ONLY on a REAL uid transition (the first resolution counts; a
   *  same-uid re-observation is a no-op) — never derived from ownerReady,
   *  which can flip within one identity. Callers that need to force-
   *  destroy identity-scoped local state (e.g. a Tailor modal's draft) key
   *  on this, not on ownerReady or an opportunity id alone. */
  identityGeneration: number;
  /** True once getFavorites() has primed the shared owner primitive for
   *  the CURRENT generation — private actions (remove, Tailor) must stay
   *  disabled until this is true. */
  ownerReady: boolean;
  /** The exact CURRENT resolved uid, or null while unresolved. Callers
   *  that persist private, per-owner content (a Tailor draft) key their
   *  storage by this, never by ownerReady or an opportunity id alone. */
  ownerScopeKey: string | null;
  /** Favorited ids the shortlist fetch could not resolve — never removed, just reported. */
  unavailableCount: number;
  handleRemove: (opp: Opp) => Promise<void>;
  /** The opp a remove attempt most recently failed for — the caller shows a
   *  visible "couldn't remove, retry?" affordance keyed off this, never a
   *  silent no-op. Cleared on the next handleRemove attempt. */
  removeError: Opp | null;
  retryRemove: () => void;
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
  const [ownerReady, setOwnerReady] = useState(false);
  const [identityGeneration, setIdentityGeneration] = useState(0);
  const [ownerScopeKey, setOwnerScopeKey] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<Opp | null>(null);
  // Data-attempt generation: bumped by EVERY load (a real identity
  // hydration AND a manual retry) — this is what load()/handleRemove use
  // to drop a stale response. identityGenerationRef below is a SEPARATE,
  // narrower counter that only a REAL uid transition may ever advance; a
  // manual retry of the SAME owner must never look like an identity change
  // to a caller keying identity-scoped local UI (e.g. Tailor) off it.
  const generationRef = useRef(0);
  const identityGenerationRef = useRef(0);
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
      // getFavorites() unconditionally primes the shared owner primitive
      // via its own ensureAnonSession() call — only now is it safe for
      // handleRemove to capture a token that isn't the unprimed sentinel.
      setOwnerReady(true);
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

  // Shared by both a real identity hydration and a manual retry — resets
  // the DATA state and issues a fresh load under a new data-attempt
  // generation. Deliberately does NOT touch identityGeneration/
  // ownerScopeKey; only hydrate() (below) does that, for a REAL identity
  // transition specifically.
  const resetAndLoad = useCallback(() => {
    const generation = ++generationRef.current;
    setServerOpportunities([]);
    setUnavailableCount(0);
    setLoading(true);
    setError(false);
    setRemoveError(null);
    // Reset at every load, not just the first: a stale `true` surviving a
    // U1->U2 transition (or a retry) would leave handleRemove gated open
    // (able to capture/write) during the window before this NEW
    // generation's own getFavorites() has actually primed the shared owner
    // primitive — only that call's own success may re-arm it.
    setOwnerReady(false);
    load(generation);
  }, [load]);

  const hydrate = useCallback((identity: string | null) => {
    const idGen = ++identityGenerationRef.current;
    setIdentityGeneration(idGen);
    setOwnerScopeKey(identity);
    resetAndLoad();
  }, [resetAndLoad]);

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
      hydrate(identity);
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

  // A manual retry re-attempts the load under the SAME already-known
  // identity — it never changes who's active (identityGeneration/
  // ownerScopeKey stay exactly as they were), only the data.
  const retry = useCallback(() => { resetAndLoad(); }, [resetAndLoad]);

  const handleRemove = useCallback(async (opp: Opp) => {
    if (opp._customId) {
      // Captured HERE, at the moment the user's remove intent began — not
      // gated on ownerReady below, which is specific to the server-backed
      // toggleFavorite path; a custom import's removal is a pure local
      // write already gated by identity-owner's own token validation.
      const removed = removeCustomImport(opp._customId, captureOwnerToken());
      // A stale/rejected removal must surface the SAME visible retry path
      // as a failed server-backed removal below — never a silent no-op the
      // user has no way to know didn't take effect.
      setRemoveError(removed ? null : opp);
      return;
    }
    if (!ownerReady || loading) return; // never capture the unprimed sentinel token, and nothing renderable to act on while loading
    const generation = generationRef.current;
    const token = captureOwnerToken();
    setRemoveError(null);
    try {
      await toggleFavorite(opp.id, true, token);
    } catch {
      // An identity change mid-flight means this remove belongs to an
      // abandoned account's list — it must never edit the fresher
      // identity's list. Only silent when the generation ALSO changed
      // (a real hydrate() already reset this view); otherwise this is a
      // genuine failure for the list the user is still looking at and
      // must be shown, never a quiet no-op.
      if (generationRef.current !== generation) return;
      setRemoveError(opp);
      return;
    }
    if (generationRef.current !== generation) return;
    setServerOpportunities(prev => prev.filter(o => o.id !== opp.id));
  }, [ownerReady, loading]);

  const retryRemove = useCallback(() => {
    if (removeError) void handleRemove(removeError);
  }, [removeError, handleRemove]);

  return {
    serverOpportunities, loading, error, retry, unavailableCount,
    identityGeneration, ownerReady, ownerScopeKey,
    handleRemove, removeError, retryRemove,
  };
}
