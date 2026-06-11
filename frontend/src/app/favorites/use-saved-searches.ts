'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  listSavedSearchDigests,
  listSavedSearches,
  removeSavedSearch,
  setSavedSearchDigest,
  type SavedSearch,
  type SavedSearchDigest,
} from '@/lib/saved-searches';
import type { TFunc } from './types';

export interface UseSavedSearchesResult {
  savedSearches: SavedSearch[];
  /** null while loading or when migration 013 is unapplied — the section
   *  hides all digest UI on null. */
  digests: Map<string, SavedSearchDigest> | null;
  handleRemove: (search: SavedSearch) => Promise<void>;
  handleApplyOptimisticClear: (id: string) => void;
  handleDigestSave: (id: string, digest: SavedSearchDigest) => Promise<boolean>;
}

// Optimistic local clear of new_match_ids when the user clicks an item:
// /results' useSavedSearchAck will ack server-side on landing, but the
// badge on /favorites would otherwise keep showing until the next load
// because savedSearches is held in this component's state.
export function useSavedSearches(t: TFunc): UseSavedSearchesResult {
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [digests, setDigests] = useState<Map<string, SavedSearchDigest> | null>(null);

  useEffect(() => {
    let cancelled = false;
    listSavedSearches()
      .then((data) => {
        if (!cancelled) setSavedSearches(data);
      })
      .catch(() => {});
    listSavedSearchDigests()
      .then((data) => {
        if (!cancelled) setDigests(data);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const handleDigestSave = useCallback(
    async (id: string, digest: SavedSearchDigest): Promise<boolean> => {
      const ok = await setSavedSearchDigest(id, digest);
      if (ok) {
        setDigests((prev) => {
          if (!prev) return prev;
          const next = new Map(prev);
          next.set(id, digest);
          return next;
        });
      }
      return ok;
    },
    [],
  );

  const handleRemove = useCallback(async (search: SavedSearch) => {
    if (!window.confirm(t('favorites.savedSearches.deleteConfirm', { name: search.name }))) return;
    const ok = await removeSavedSearch(search.id);
    if (ok) {
      setSavedSearches((prev) => prev.filter((s) => s.id !== search.id));
    }
  }, [t]);

  const handleApplyOptimisticClear = useCallback((id: string) => {
    setSavedSearches((prev) =>
      prev.map((s) => (s.id === id ? { ...s, new_match_ids: [] } : s)),
    );
  }, []);

  return { savedSearches, digests, handleRemove, handleApplyOptimisticClear, handleDigestSave };
}
