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
  clearMatchCache,
  isTrustedMatchViewPage,
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
  /** The refine failed but a rule-ranked list is on screen. Deliberately not
   *  `error`: the page hides the list whenever `error` is set, and hiding a
   *  list that loaded because an enhancement to it did not is worse than what
   *  the student had before the enhancement existed. */
  refineFailed: boolean;
}

interface CursorState {
  requestKey: string;
  byPage: Map<number, string | null>;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function isCompleteView(result: MatchesResponse): boolean {
  // One shared validator — see isTrustedMatchViewPage. The view-specific
  // fields below are the only thing this surface adds.
  return isTrustedMatchViewPage(result)
    && typeof result.filtered_total === 'number'
    && !!result.view_counts
    && typeof result.view_start === 'number';
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
  /**
   * Called once when a dead cursor is dropped, so the page owner can return to
   * page 1. Optional: a caller that never paginates has nothing to reset.
   */
  onCursorReset?: () => void,
): UseResultsDataResult {
  const [data, setData] = useState<MatchesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showSlowHint, setShowSlowHint] = useState(false);
  const [paginationReady, setPaginationReady] = useState(false);
  const [refining, setRefining] = useState(false);
  const [refined, setRefined] = useState(false);
  const [refineFailed, setRefineFailed] = useState(false);
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
    setRefineFailed(false);
    // Nothing reaches the page until THIS request cycle produces it. The
    // stored page is good for seven days; a listing closes in one. Painting it
    // first put a live Apply link, a pay badge, a deadline countdown and the
    // Draft/Tailor actions on rows the server may already be refusing — and
    // Apply is a raw external link with no server action in front of it to
    // catch the difference, so the student learns about it from the dead form.
    //
    // The cache is still WRITTEN below, and still read elsewhere: Header asks
    // whether one exists to decide where "Find Matches" goes, and Compare
    // reads its matcher_version to keep two generations off one screen. What
    // is gone is only the paint — this hook no longer reads it.
    if (page === 1) setData(null);
    /* eslint-enable react-hooks/set-state-in-effect */
    // A refine that fails AFTER the interim rule list painted keeps that list
    // rather than replacing it with an error: the interim came from this same
    // request cycle, so unlike the cache it cannot be a stale generation.
    let interimPainted = false;

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
        // Skipped past page one, where the refined snapshot owns the cursor
        // chain. Deliberately NOT skipped for a cache hit any more: the cache
        // no longer paints, so a stored page is no longer something the
        // student is waiting in front of — it is nothing on screen, and the
        // interim is the only thing that can fill that wait honestly.
        if (semanticRerank && page === 1) {
          // Race, don't sleep. Awaiting the timer outright would delay every
          // warm load by the full interval as well — the timer exists for the
          // cold case only — and would leave a live timer plus this whole
          // closure alive for that long after an unmount, which is enough
          // memory pressure to take a test worker down.
          let timer: ReturnType<typeof setTimeout> | undefined;
          await Promise.race([
            request.then(() => undefined, () => undefined),
            new Promise<void>((resolve) => {
              timer = setTimeout(resolve, INTERIM_PAINT_AFTER_MS);
            }),
          ]);
          clearTimeout(timer);
          if (!active) return;
          if (!requestSettled) {
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
                interimPainted = true;
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
          // Drop any stored page too: whatever made this response unshowable
          // (an old contract, a row without truth) is at least as likely to be
          // sitting in the cache written by an earlier response.
          clearMatchCache(cacheToken);
          throw new ApiError(
            502,
            'MATCH_CONTRACT_MISMATCH',
            'Match results need to be refreshed. Please retry.',
            true,
          );
        }
        setData(result);
        // What the server says happened, not what this request asked for. The
        // two differ whenever the provider was unconfigured, the day budget
        // degraded the call, or a batch came back unusable — and each of those
        // still returns a complete rule ranking, so nothing else in the
        // response distinguishes them.
        setRefined(result.ai_refined === true);
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
        // A dead cursor is recoverable exactly once, and only from a later
        // page: the snapshot it points at is gone, so the fix is to drop it
        // and start over rather than surface an error the user cannot act on.
        // Guarded against looping — a page-1 request carries no cursor, so the
        // same code arriving there means something else is wrong and the
        // error is shown.
        if (
          caught instanceof ApiError
          && (caught.code === 'MATCH_CURSOR_INVALID' || caught.code === 'MATCH_CURSOR_EXPIRED')
          && page > 1
        ) {
          cursorsRef.current.byPage.clear();
          clearMatchCache(cacheToken);
          onCursorReset?.();
          return;
        }
        if (interimPainted) {
          setRefineFailed(true);
        } else {
          setError(
            caught instanceof ApiError
              ? caught.message
              : t('results.loadFailed'),
          );
        }
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
    // onCursorReset is in the deps because the effect calls it: leaving it out
    // captures whichever instance existed at mount, which is the classic stale
    // closure. Callers pass a stable (useCallback) reference, so listing it
    // does not cause a refetch.
  }, [profile, semanticRerank, view, page, requestKey, t, onCursorReset]);

  return {
    data, setData, loading, error, showSlowHint, paginationReady, refining, refined, refineFailed,
  };
}
