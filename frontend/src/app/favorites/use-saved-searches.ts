'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  confirmedAccountEmail,
  listSavedSearchDigests,
  listSavedSearches,
  removeSavedSearch,
  setSavedSearchDigest,
  type SavedSearch,
  type SavedSearchDigest,
} from '@/lib/saved-searches';
import { getAuthState } from '@/lib/supabase';
import type { TFunc } from './types';

export interface UseSavedSearchesResult {
  savedSearches: SavedSearch[];
  /** null while loading (the account read included) or when migration 013
   *  is unapplied — the section hides all digest UI on null. */
  digests: Map<string, SavedSearchDigest> | null;
  /** W14: true when the saved-searches list failed to load — the section
   *  renders an inline error note instead of silently vanishing. */
  loadError: boolean;
  /** Ask for the list again after a failed read. */
  retryLoad: () => Promise<void>;
  handleRemove: (search: SavedSearch) => Promise<void>;
  handleApplyOptimisticClear: (id: string) => void;
  handleDigestSave: (id: string, digest: SavedSearchDigest) => Promise<boolean>;
  /** The signed-in account's confirmed email, the only address a digest goes
   *  to. Null for a guest or an account without a confirmed email. */
  accountEmail: string | null;
}

// Optimistic local clear of new_match_ids when the user clicks an item:
// /results' useSavedSearchAck will ack server-side on landing, but the
// badge on /favorites would otherwise keep showing until the next load
// because savedSearches is held in this component's state.
export function useSavedSearches(t: TFunc): UseSavedSearchesResult {
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [digests, setDigests] = useState<Map<string, SavedSearchDigest> | null>(null);
  const [loadError, setLoadError] = useState(false);
  // undefined until the auth read lands: digest UI waits for it, so a row is
  // never shown as "not sent" only because the account is not known yet.
  const [accountEmail, setAccountEmail] = useState<string | null | undefined>(undefined);
  // Only the newest read may land: a retry clicked while the first read is
  // still out must not be overwritten by that read's late failure.
  const readRef = useRef(0);
  // True until a digest read returns settings: a retry reads them again.
  const digestsMissingRef = useRef(true);

  const loadList = useCallback(async (isCurrent: () => boolean): Promise<boolean> => {
    try {
      const data = await listSavedSearches();
      if (isCurrent()) {
        setSavedSearches(data);
        setLoadError(false);
      }
      return true;
    } catch {
      // W14 truthful zero states: the user's saved searches exist but
      // could not be fetched — flag it instead of rendering nothing.
      if (isCurrent()) setLoadError(true);
      return false;
    }
  }, []);

  const loadDigests = useCallback(async (isCurrent: () => boolean) => {
    let data: Map<string, SavedSearchDigest> | null = null;
    try {
      data = await listSavedSearchDigests();
    } catch {
      // digests stay null → all digest UI hides (the documented degraded
      // mode for an unapplied migration 013 or a failed load). The list
      // itself still renders, so this is not a false-empty.
    }
    if (!isCurrent()) return;
    digestsMissingRef.current = data === null;
    setDigests(data);
  }, []);

  const retryLoad = useCallback(async () => {
    const read = ++readRef.current;
    const isCurrent = () => read === readRef.current;
    const listed = await loadList(isCurrent);
    // The digest read fails with the list. A retry that brings the list back
    // reads the email settings again too, or every digest control on it stays
    // hidden. Not awaited: the list is what the retry answers for.
    if (listed && isCurrent() && digestsMissingRef.current) void loadDigests(isCurrent);
  }, [loadList, loadDigests]);

  useEffect(() => {
    let cancelled = false;
    const read = ++readRef.current;
    const isCurrent = () => !cancelled && read === readRef.current;
    void loadList(isCurrent);
    void loadDigests(isCurrent);
    getAuthState()
      .then((auth) => {
        if (!cancelled) setAccountEmail(confirmedAccountEmail(auth));
      })
      .catch(() => {
        // No known confirmed address: the digest cannot be turned on.
        if (!cancelled) setAccountEmail(null);
      });
    return () => { cancelled = true; };
  }, [loadList, loadDigests]);

  const handleDigestSave = useCallback(
    async (id: string, digest: SavedSearchDigest): Promise<boolean> => {
      const ok = await setSavedSearchDigest(id, digest);
      if (ok) {
        setDigests((prev) => {
          if (!prev) return prev;
          const next = new Map(prev);
          const stored = prev.get(id);
          // The send history stays; opting in clears the unsubscribe stamp,
          // as setSavedSearchDigest does on the row.
          next.set(id, {
            ...digest,
            lastSentAt: stored?.lastSentAt ?? null,
            unsubscribedAt: digest.optIn ? null : stored?.unsubscribedAt ?? null,
          });
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

  return {
    savedSearches,
    digests: accountEmail === undefined ? null : digests,
    loadError,
    retryLoad,
    handleRemove,
    handleApplyOptimisticClear,
    handleDigestSave,
    accountEmail: accountEmail ?? null,
  };
}
