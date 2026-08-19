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
/** How long the refine gets to answer before a rule-ranked list is fetched to
 *  fill the wait. Long enough that a warm server snapshot never triggers the
 *  extra ranking, short enough to be invisible next to a cold twenty seconds. */
const INTERIM_PAINT_AFTER_MS = 600;

interface UseResultsDataResult {
  data: MatchesResponse | null;
  setData: React.Dispatch<React.SetStateAction<MatchesResponse | null>>;
  loading: boolean;
  error: string | null;
  showSlowHint: boolean;
  paginationReady: boolean;
  /** A rule-ranked list is on screen and the paid refine is still running. */
  refining: boolean;
  /** The list on screen came back from a refine that succeeded. Not the same
   *  question as "the student asked for one": the interim rule list and a
   *  failed refine both leave this false, and the AI badge is a claim about
   *  the list, not about the toggle. */
  refined: boolean;
}

interface CursorState {
  requestKey: string;
  byPage: Map<number, string | null>;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function isCompleteView(result: MatchesResponse): boolean {
  return result.contract_version === MATCH_VIEW_CONTRACT_VERSION
    && typeof result.filtered_total === 'number'
    && !!result.view_counts
    && typeof result.view_start === 'number'
    && hasValidMatchResultIdentity(result.results);
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
  /** False while the AI-refine preference is still unreadable. See requestKey. */
  preferenceSettled: boolean,
): UseResultsDataResult {
  const [data, setData] = useState<MatchesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showSlowHint, setShowSlowHint] = useState(false);
  const [paginationReady, setPaginationReady] = useState(false);
  const [refining, setRefining] = useState(false);
  const [refined, setRefined] = useState(false);
  // Empty until the AI-refine preference is readable, which suppresses the
  // fetch below. `semanticRerank` is part of this key, and local ownership is
  // established asynchronously, so firing before it settles sends one request
  // under the wrong answer and a second one the moment the right answer
  // arrives — two full rankings per page load, server-side, for one page.
  const requestKey = useMemo(
    () => profile && preferenceSettled
      ? `${hashProfile(profile)}:${semanticRerank ? '1' : '0'}:${JSON.stringify(view)}`
      : '',
    [profile, preferenceSettled, semanticRerank, view],
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
    setRefining(false);
    setRefined(false);
    let painted = false;
    if (page === 1) {
      const cached = readMatchCache(cacheKey, semanticRerank);
      if (cached?.contract_version === MATCH_VIEW_CONTRACT_VERSION) {
        setData(cached);
        // Cached metadata paints immediately, but the network request below is
        // still mandatory generation validation. Its cursor is deliberately
        // NOT trusted: local cache lives seven days while the server snapshot
        // lives minutes, so pagination stays locked until the live response.
        setLoading(false);
        painted = true;
        // Only a refined result is ever written under a refined cache key, so
        // a hit here is a refined list, not merely a requested one.
        setRefined(semanticRerank);
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
      const request = getMatchView(profile, view, {
        cursor: cursor ?? null,
        pageSize: MATCH_VIEW_PAGE_SIZE,
        llm: semanticRerank,
        signal: controller.signal,
      });
      let requestSettled = false;
      const markSettled = () => { requestSettled = true; };
      request.then(markSettled, markSettled);

      try {
        // A first-ever refined page costs about twenty seconds, and roughly
        // four of them are the rule ranking the refine has to run before it can
        // call the model at all. Ask for that ranking on its own as well: it is
        // a real, complete answer, and it puts a list on screen in a quarter of
        // the time. The refined list replaces it when it arrives.
        //
        // Only when the refine is actually slow, though. A warm server snapshot
        // answers in a fraction of INTERIM_PAINT_AFTER_MS, and firing a second
        // full ranking behind a request that already returned would spend real
        // server time to save nothing — the failure mode that once took the E2E
        // job from seven minutes to past its timeout. So the refine goes out
        // first and the interim only follows if it is still outstanding.
        //
        // Skipped when the cache already painted (nothing to wait in front of)
        // and past page one (the refined snapshot owns the cursor chain).
        if (semanticRerank && page === 1 && !painted) {
          await new Promise((resolve) => setTimeout(resolve, INTERIM_PAINT_AFTER_MS));
          if (active && !requestSettled) {
            try {
              const ruleOnly = await getMatchView(profile, view, {
                cursor: null,
                pageSize: MATCH_VIEW_PAGE_SIZE,
                llm: false,
                signal: controller.signal,
              });
              // Re-check: the refine can land while the interim is in flight,
              // and the refined list must never be overwritten by the rule one.
              if (active && !requestSettled && isCompleteView(ruleOnly)) {
                setData(ruleOnly);
                setLoading(false);
                setRefining(true);
                painted = true;
              }
            } catch {
              // An optimization the student never asked for. Say nothing and
              // let the real request below report whatever is actually wrong.
            }
          }
        }

        const result = await request;
        if (!active) return;
        if (!isCompleteView(result)) {
          throw new ApiError(
            502,
            'MATCH_CONTRACT_MISMATCH',
            'Match results need to be refreshed. Please retry.',
            true,
          );
        }
        setData(result);
        setRefined(semanticRerank);
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
        if (active) {
          setLoading(false);
          setRefining(false);
        }
      }
    })();

    return () => {
      active = false;
      controller.abort();
    };
  }, [profile, semanticRerank, view, page, requestKey, t]);

  return { data, setData, loading, error, showSlowHint, paginationReady, refining, refined };
}
