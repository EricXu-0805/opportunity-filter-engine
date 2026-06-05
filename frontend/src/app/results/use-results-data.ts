'use client';

import { useEffect, useState } from 'react';
import { getMatches } from '@/lib/api';
import { hashProfile } from '@/lib/match-utils';
import { readMatchCache, writeMatchCache } from '@/lib/match-cache';
import type { MatchesResponse, ProfileData } from '@/lib/types';
import type { TFunc } from './types';

interface UseResultsDataResult {
  data: MatchesResponse | null;
  setData: React.Dispatch<React.SetStateAction<MatchesResponse | null>>;
  loading: boolean;
  error: string | null;
  showSlowHint: boolean;
}

// Hydrate-from-durable-cache, fetch on miss. The cache (see lib/match-cache)
// is keyed by { hash(profile), semanticRerank } and lives in localStorage as a
// compact copy (no opportunity bodies); a hit re-hydrates the opportunity
// payloads by id — a fast lookup, NOT a re-match — so returning to /results from
// anywhere (nav, another tab, a later session) is instant. Flipping the AI
// toggle changes semanticRerank → cache miss → re-rank. Caller resets data via
// setData(null) when toggling.
export function useResultsData(
  profile: ProfileData | null,
  semanticRerank: boolean,
  t: TFunc,
): UseResultsDataResult {
  const [data, setData] = useState<MatchesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showSlowHint, setShowSlowHint] = useState(false);

  useEffect(() => {
    if (!loading) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset the "slow loading…" hint the instant loading finishes; the setTimeout that would have shown it is also cancelled in cleanup
      setShowSlowHint(false);
      return;
    }
    const timer = setTimeout(() => setShowSlowHint(true), 8000);
    return () => clearTimeout(timer);
  }, [loading]);

  useEffect(() => {
    if (!profile || data) return;

    let cancelled = false;
    const hash = hashProfile(profile);

    async function hydrateOrFetch() {
      const cached = await readMatchCache(hash, semanticRerank);
      if (cancelled) return;
      if (cached) {
        setData(cached);
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const result = await getMatches(profile!, { semantic: semanticRerank });
        if (cancelled) return;
        setData(result);
        writeMatchCache(hash, semanticRerank, result);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : t('results.loadFailed'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    hydrateOrFetch();
    return () => { cancelled = true; };
  }, [profile, data, semanticRerank, t]);

  return { data, setData, loading, error, showSlowHint };
}
