'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError,
  getMatchView,
  type MatchViewRequestState,
} from '@/lib/api';
import { trackOnce } from '@/lib/analytics';
import { captureOwnerToken } from '@/lib/identity-owner';
import { hashProfile } from '@/lib/match-utils';
import {
  MATCH_VIEW_CONTRACT_VERSION,
  hasValidMatchResultIdentity,
  readMatchCache,
  writeMatchCache,
} from '@/lib/match-cache';
import type { MatchesResponse, ProfileData } from '@/lib/types';
import type { TFunc } from './types';

const MATCH_VIEW_PAGE_SIZE = 50;

interface UseResultsDataResult {
  data: MatchesResponse | null;
  setData: React.Dispatch<React.SetStateAction<MatchesResponse | null>>;
  loading: boolean;
  error: string | null;
  showSlowHint: boolean;
  paginationReady: boolean;
}

interface CursorState {
  requestKey: string;
  byPage: Map<number, string | null>;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

/** One exact server-side results page.
 *
 * The cursor map is page-local and generation-bound. Changing any profile or
 * view predicate creates a fresh request key, drops every old cursor and starts
 * at page one. AbortController stops obsolete browser requests instead of only
 * suppressing their React state updates.
 */
export function useResultsData(
  profile: ProfileData | null,
  semanticRerank: boolean,
  view: MatchViewRequestState,
  page: number,
  t: TFunc,
): UseResultsDataResult {
  const [data, setData] = useState<MatchesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showSlowHint, setShowSlowHint] = useState(false);
  const [paginationReady, setPaginationReady] = useState(false);
  const requestKey = useMemo(
    () => profile
      ? `${hashProfile(profile)}:${semanticRerank ? '1' : '0'}:${JSON.stringify(view)}`
      : '',
    [profile, semanticRerank, view],
  );
  const cursorsRef = useRef<CursorState>({
    requestKey: '',
    byPage: new Map([[1, null]]),
  });

  useEffect(() => {
    if (!loading) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset the slow hint as soon as the active request finishes
      setShowSlowHint(false);
      return;
    }
    const timer = setTimeout(() => setShowSlowHint(true), 8000);
    return () => clearTimeout(timer);
  }, [loading]);

  useEffect(() => {
    if (!profile || !requestKey) return;
    if (cursorsRef.current.requestKey !== requestKey) {
      cursorsRef.current = {
        requestKey,
        byPage: new Map([[1, null]]),
      };
    }
    const cursor = cursorsRef.current.byPage.get(page);
    if (page > 1 && !cursor) {
      // Every reachable page must have been minted by the preceding response.
      // Showing the previous page under a new page number would be a silent
      // duplicate, so fail closed if parent state ever gets ahead of the
      // cursor chain.
      setData(null);
      setLoading(false);
      setError(t('results.loadFailed'));
      setPaginationReady(false);
      return;
    }

    const controller = new AbortController();
    let active = true;
    const cacheKey = requestKey;
    // Captured at the moment this request STARTS, not re-captured just
    // before the write below — a stale caller (identity moved on during
    // the network round-trip) must not write this response into a
    // different account's cache slot.
    const cacheToken = captureOwnerToken();

    /* eslint-disable react-hooks/set-state-in-effect -- page/profile/view changes intentionally enter a new request state */
    setLoading(true);
    setError(null);
    setPaginationReady(false);
    if (page === 1) {
      const cached = readMatchCache(cacheKey, semanticRerank);
      if (cached?.contract_version === MATCH_VIEW_CONTRACT_VERSION) {
        setData(cached);
        // Cached metadata paints immediately, but the network request below is
        // still mandatory generation validation. Its cursor is deliberately
        // NOT trusted: local cache lives seven days while the server snapshot
        // lives minutes, so pagination stays locked until the live response.
        setLoading(false);
        trackOnce('matches_generated', {
          llm: semanticRerank,
          cached: true,
          validated: false,
        });
      } else {
        setData(null);
      }
    }
    /* eslint-enable react-hooks/set-state-in-effect */

    (async () => {
      try {
        const result = await getMatchView(profile, view, {
          cursor: cursor ?? null,
          pageSize: MATCH_VIEW_PAGE_SIZE,
          signal: controller.signal,
        });
        if (!active) return;
        if (
          result.contract_version !== MATCH_VIEW_CONTRACT_VERSION
          || typeof result.filtered_total !== 'number'
          || !result.view_counts
          || typeof result.view_start !== 'number'
          || !hasValidMatchResultIdentity(result.results)
        ) {
          throw new ApiError(
            502,
            'MATCH_CONTRACT_MISMATCH',
            'Match results need to be refreshed. Please retry.',
            true,
          );
        }
        setData(result);
        if (result.has_more && result.next_cursor) {
          cursorsRef.current.byPage.set(page + 1, result.next_cursor);
        } else {
          cursorsRef.current.byPage.delete(page + 1);
        }
        if (page === 1) {
          writeMatchCache(cacheKey, semanticRerank, result, cacheToken);
        }
        setPaginationReady(true);
        trackOnce('matches_generated', {
          llm: semanticRerank,
          page,
          validated: true,
        });
      } catch (caught) {
        if (!active || isAbort(caught)) return;
        setError(
          caught instanceof ApiError
            ? caught.message
            : t('results.loadFailed'),
        );
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
      controller.abort();
    };
  }, [profile, semanticRerank, view, page, requestKey, t]);

  return { data, setData, loading, error, showSlowHint, paginationReady };
}
