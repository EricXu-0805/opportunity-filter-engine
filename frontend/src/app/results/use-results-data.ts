'use client';

import { useEffect, useState } from 'react';
import { getMatches } from '@/lib/api';
import { hashProfile } from '@/lib/match-utils';
import type { MatchesResponse, ProfileData } from '@/lib/types';
import type { TFunc } from './types';

interface UseResultsDataResult {
  data: MatchesResponse | null;
  setData: React.Dispatch<React.SetStateAction<MatchesResponse | null>>;
  loading: boolean;
  error: string | null;
  showSlowHint: boolean;
}

// Combined cache-hydrate + fetch-on-miss. Splitting these into two
// effects races within the same commit: both run with the pre-commit
// `data` snapshot (still null), so the fetch effect can't see that
// the cache effect just queued setData. Sequential checks inside one
// effect keep cache hits from triggering a redundant API roundtrip,
// which matters most when users navigate back to /results via a
// deep-link (the test that caught this regression).
//
// Cache key is { hash(profile), semanticRerank } — flipping the AI
// toggle invalidates the cache so we re-rank with the new strategy.
// Caller resets data via setData(null) when toggling.
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

    /* eslint-disable react-hooks/set-state-in-effect -- see file-level comment above for the cache+fetch race rationale */

    try {
      const cachedRaw = sessionStorage.getItem('ofe_match_results');
      if (cachedRaw) {
        const cached = JSON.parse(cachedRaw) as {
          hash: string;
          semantic?: boolean;
          data: MatchesResponse;
        };
        if (
          cached.hash === hashProfile(profile)
          && (cached.semantic ?? false) === semanticRerank
        ) {
          setData(cached.data);
          setLoading(false);
          return;
        }
        sessionStorage.removeItem('ofe_match_results');
      }
    } catch {
      sessionStorage.removeItem('ofe_match_results');
    }

    let cancelled = false;

    async function fetchMatches() {
      setLoading(true);
      setError(null);
      try {
        const result = await getMatches(profile!, { semantic: semanticRerank });
        if (!cancelled) {
          setData(result);
          try {
            sessionStorage.setItem(
              'ofe_match_results',
              JSON.stringify({
                hash: hashProfile(profile!),
                semantic: semanticRerank,
                data: result,
              }),
            );
          } catch { /* quota */ }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : t('results.loadFailed'));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchMatches();
    return () => { cancelled = true; };
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [profile, data, semanticRerank, t]);

  return { data, setData, loading, error, showSlowHint };
}
