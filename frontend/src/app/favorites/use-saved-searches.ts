'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  listSavedSearches,
  removeSavedSearch,
  type SavedSearch,
} from '@/lib/saved-searches';
import type { TFunc } from './types';

export interface UseSavedSearchesResult {
  savedSearches: SavedSearch[];
  handleRemove: (search: SavedSearch) => Promise<void>;
  handleApplyOptimisticClear: (id: string) => void;
}

// Optimistic local clear of new_match_ids when the user clicks an item:
// /results' useSavedSearchAck will ack server-side on landing, but the
// badge on /favorites would otherwise keep showing until the next load
// because savedSearches is held in this component's state.
export function useSavedSearches(t: TFunc): UseSavedSearchesResult {
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);

  useEffect(() => {
    let cancelled = false;
    listSavedSearches()
      .then((data) => {
        if (!cancelled) setSavedSearches(data);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

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

  return { savedSearches, handleRemove, handleApplyOptimisticClear };
}
