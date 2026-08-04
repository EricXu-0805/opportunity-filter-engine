'use client';

import { useCallback, useEffect, useState } from 'react';
import { getOpportunitiesByIds } from '@/lib/api';
import { getFavorites, toggleFavorite } from '@/lib/supabase';
import { removeCustomImport } from '@/lib/custom-imports';
import { useAuthUid } from '@/lib/use-auth-uid';
import type { Opp } from './types';

export interface UseFavoritesDataResult {
  serverOpportunities: Opp[];
  loading: boolean;
  /** W14: true when the server list failed to load — the page renders a
   *  distinct error UI (message + retry), never a false empty state. */
  loadError: boolean;
  retry: () => void;
  handleRemove: (opp: Opp) => Promise<void>;
}

// Hydrates the /favorites server list once at mount: pulls fav IDs from
// supabase, then resolves them to full opportunity payloads via
// getOpportunitiesByIds. The cancelled flag guards against unmount
// during the two-step fetch — same mount-cancellation pattern that
// landed in R21 across the other loads.
//
// W14: a failed load sets `loadError` instead of silently rendering the
// empty state, and the load re-runs on a cross-tab identity switch
// (authEpoch) so Account A's favorites never linger for Account B.
export function useFavoritesData(): UseFavoritesDataResult {
  const [serverOpportunities, setServerOpportunities] = useState<Opp[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const { epoch: authEpoch } = useAuthUid();

  useEffect(() => {
    let cancelled = false;
    /* eslint-disable react-hooks/set-state-in-effect --
       Reset before fetching: a no-op on mount, the isolation clear on an
       identity switch, and the error-state clear on retry. */
    setServerOpportunities([]);
    setLoading(true);
    setLoadError(false);
    /* eslint-enable react-hooks/set-state-in-effect */
    async function load() {
      try {
        const favSet = await getFavorites();
        if (cancelled) return;
        const ids = Array.from(favSet);
        if (ids.length === 0) {
          setLoading(false);
          return;
        }
        const opps = await getOpportunitiesByIds(ids);
        if (cancelled) return;
        setServerOpportunities(opps as unknown as Opp[]);
      } catch {
        // Truthful zero states: a failed load is an ERROR, not an empty list.
        if (!cancelled) setLoadError(true);
      }
      finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [authEpoch, attempt]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);

  const handleRemove = useCallback(async (opp: Opp) => {
    if (opp._customId) {
      removeCustomImport(opp._customId);
      return;
    }
    await toggleFavorite(opp.id, true);
    setServerOpportunities(prev => prev.filter(o => o.id !== opp.id));
  }, []);

  return { serverOpportunities, loading, loadError, retry, handleRemove };
}
