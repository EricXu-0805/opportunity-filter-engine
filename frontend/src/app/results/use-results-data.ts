'use client';

import { useEffect, useState } from 'react';
import { getMatches } from '@/lib/api';
import { trackOnce } from '@/lib/analytics';
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
// compact, self-contained projection of each result; a hit performs no network
// lookup or re-match, so returning to /results is instant. Because those
// projections can preserve old release behavior, storage-key version bumps are
// mandatory whenever the public record/ranking contract changes. The semantic
// key remains for a future accepted AI-refine path; this release always passes
// false.
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

    const hash = hashProfile(profile);

    /* eslint-disable react-hooks/set-state-in-effect -- the cache read is a
       synchronous localStorage parse; setting data/loading from it in the same
       commit is what makes the return to /results instant (no skeleton, no
       network). The fetch-on-miss branch sets state from async callbacks. */
    const cached = readMatchCache(hash, semanticRerank);
    if (cached) {
      setData(cached);
      setLoading(false);
      trackOnce('matches_generated', { llm: semanticRerank, cached: true });
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const result = await getMatches(profile!, { llm: semanticRerank });
        if (cancelled) return;
        setData(result);
        writeMatchCache(hash, semanticRerank, result);
        trackOnce('matches_generated', { llm: semanticRerank });
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : t('results.loadFailed'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [profile, data, semanticRerank, t]);

  return { data, setData, loading, error, showSlowHint };
}
