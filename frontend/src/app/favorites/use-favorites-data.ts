'use client';

import { useCallback, useEffect, useState } from 'react';
import { getOpportunitiesByIds } from '@/lib/api';
import { getFavorites, toggleFavorite } from '@/lib/supabase';
import { removeCustomImport } from '@/lib/custom-imports';
import type { Opp } from './types';

export interface UseFavoritesDataResult {
  serverOpportunities: Opp[];
  loading: boolean;
  handleRemove: (opp: Opp) => Promise<void>;
}

// Hydrates the /favorites server list once at mount: pulls fav IDs from
// supabase, then resolves them to full opportunity payloads via
// getOpportunitiesByIds. The cancelled flag guards against unmount
// during the two-step fetch — same mount-cancellation pattern that
// landed in R21 across the other loads.
export function useFavoritesData(): UseFavoritesDataResult {
  const [serverOpportunities, setServerOpportunities] = useState<Opp[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
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
      } catch {}
      finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const handleRemove = useCallback(async (opp: Opp) => {
    if (opp._customId) {
      removeCustomImport(opp._customId);
      return;
    }
    await toggleFavorite(opp.id, true);
    setServerOpportunities(prev => prev.filter(o => o.id !== opp.id));
  }, []);

  return { serverOpportunities, loading, handleRemove };
}
