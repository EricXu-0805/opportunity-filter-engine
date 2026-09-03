import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import { useCallback, useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, type MatchViewRequestState } from '@/lib/api';
import type { MatchesResponse, ProfileData } from '@/lib/types';
import { useResultsData } from './use-results-data';
import MatchCard from '@/components/MatchCard';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';

const mocks = vi.hoisted(() => ({
  getMatchView: vi.fn(),
  readMatchCache: vi.fn(),
  writeMatchCache: vi.fn(),
  clearMatchCache: vi.fn(),
  trackOnce: vi.fn(),
}));

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return { ...actual, getMatchView: mocks.getMatchView };
});
vi.mock('@/lib/match-cache', async () => {
  const actual = await vi.importActual<typeof import('@/lib/match-cache')>('@/lib/match-cache');
  return {
    MATCH_VIEW_CONTRACT_VERSION: actual.MATCH_VIEW_CONTRACT_VERSION,
    TARGET_TRUTH_CONTRACT: actual.TARGET_TRUTH_CONTRACT,
    // The real acceptance rule: the marker AND the one frozen wire version
    // this backend emits (`match-view-v3-faculty-trust`) — exact, not a
    // family. Stubbing it would let a looser check pass here and fail in
    // prod, and paraphrasing it here is how the comment and the contract
    // drift apart.
    isAcceptedMatchViewContract: actual.isAcceptedMatchViewContract,
    hasValidMatchResultIdentity: actual.hasValidMatchResultIdentity,
    // The one shared validator every surface calls. Stubbing it would let a
    // partial check pass here and fail in production.
    isTrustedMatchViewPage: actual.isTrustedMatchViewPage,
    readMatchCache: mocks.readMatchCache,
    writeMatchCache: mocks.writeMatchCache,
    clearMatchCache: mocks.clearMatchCache,
  };
});
vi.mock('@/lib/analytics', () => ({ trackOnce: mocks.trackOnce }));
// For the DOM block at the bottom of this file, which renders a real
// MatchCard against whatever the hook is holding.
vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string, vars?: Record<string, string | number>) =>
      (vars && 'count' in vars ? `${key}:${vars.count}` : key),
  }),
}));
vi.mock('@/components/TailorModal', () => ({
  default: () => <div data-testid="tailor-modal" />,
}));

const profile: ProfileData = {
  institution: 'UIUC',
  college: 'Grainger',
  major: 'CS',
  grade: 'Sophomore',
  is_international: false,
  research_interests: 'machine learning',
  skills: [{ name: 'Python', level: 'experienced' }],
};

const baseView: MatchViewRequestState = {
  tab: 'all',
  search_query: '',
  paid: '',
  intl: '',
  source: '',
  on_campus: '',
  deadline: '',
  min_score: 0,
  scope: '',
  sort_by: 'score',
  show_dismissed: false,
  favorite_ids: [],
  dismissed_ids: [],
  today: '2026-07-31',
};

function response(
  id: string,
  overrides: Partial<MatchesResponse> = {},
): MatchesResponse {
  return {
    total: 1,
    high_priority: 1,
    good_match: 0,
    reach: 0,
    low_fit: 0,
    results: [{
      opportunity_id: id,
      eligibility_score: 80,
      readiness_score: 80,
      upside_score: 80,
      final_score: 80,
      bucket: 'high_priority',
      reasons_fit: [],
      reasons_gap: [],
      next_steps: [],
      opportunity: {
        id,
        title: id,
        organization: 'Test University',
        opportunity_type: 'research',
        // A confirmed listing. An unreviewed source_type is no longer
        // actionable, so a fixture without one would make every page here a
        // page of dead rows and the loader would refuse it for that reason.
        source_type: 'campus_program',
        record_kind: 'listing',
        // A live response carries a truth on every row; without one the whole
        // page is refused, which is the contract these fixtures exercise.
        target_truth: {
          listing_state: 'open',
          reference_only: false,
          actionable: true,
          accepting_state: 'accepting',
          reason_code: null,
          verified_at: null,
          expires_at: null,
        },
        paid: 'unknown',
        location: '',
        on_campus: true,
        description_clean: '',
        keywords: [],
        eligibility: {
          international_friendly: 'unknown',
          preferred_year: [],
          majors: [],
          skills_required: [],
          citizenship_required: false,
        },
        application: {
          application_effort: 'unknown',
          requires_resume: 'unknown',
          contact_method: 'website',
        },
        metadata: {
          is_active: true,
          confidence_score: 1,
        },
      },
    }],
    returned_count: 1,
    has_more: false,
    next_cursor: null,
    result_set_id: `set-${id}`,
    // The wire the backend actually emits. A fixture on a version nothing
    // serves would make every page here a page this client should refuse.
    contract_version: 'match-view-v3-faculty-trust',
    target_truth_contract: 'target-truth-v2',
    view_start: 0,
    filtered_total: 1,
    view_counts: {
      all: 1,
      high_priority: 1,
      good_match: 0,
      reach: 0,
      starred: 0,
    },
    view_id: `view-${id}`,
    ai_refined: false,
    ...overrides,
  };
}

const t = (key: string) => key;

describe('useResultsData', () => {
  beforeEach(() => {
    mocks.getMatchView.mockReset();
    mocks.readMatchCache.mockReset();
    mocks.writeMatchCache.mockReset();
    // Was missing: several tests below assert on it, and without a reset one
    // test's clear satisfies the next test's assertion.
    mocks.clearMatchCache.mockReset();
    mocks.trackOnce.mockReset();
    mocks.readMatchCache.mockReturnValue(null);
  });

  it('sends nothing until the AI-refine preference is readable', async () => {
    // Firing early costs a full server-side ranking under the wrong answer and
    // a second one the moment the right answer lands — two rankings per page
    // load. Local ownership is established asynchronously, so "not yet" is the
    // normal first-render state, not an edge case.
    mocks.getMatchView.mockResolvedValue(response('a'));
    const { result, rerender } = renderHook(
      ({ settled }) => useResultsData(profile, true, baseView, 1, t, settled),
      { initialProps: { settled: false } },
    );
    await waitFor(() => expect(result.current.loading).toBe(true));
    expect(mocks.getMatchView).not.toHaveBeenCalled();

    rerender({ settled: true });
    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(1));
    expect(mocks.getMatchView.mock.calls[0][2].llm).toBe(true);
  });

  it('re-renders that change nothing but object identity do not re-rank', async () => {
    // Measured on production 2026-08-30: every /results load sent FIVE
    // POST /api/matches/view with a byte-identical body, four of them aborted
    // a moment later. The abort is client-side only — the server had already
    // started ranking the full corpus for each, so one student opening one
    // page cost five rankings of ~1,100 opportunities.
    //
    // The mechanism is the dep array, not the hook's logic: `requestKey` is a
    // content hash and is stable, but `profile` and `view` were ALSO deps, and
    // their identities churn while the page hydrates.
    mocks.getMatchView.mockResolvedValue(response('a'));
    const { rerender } = renderHook(
      ({ p, v }) => useResultsData(p, true, v, 1, t, true),
      { initialProps: { p: profile, v: baseView } },
    );
    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(1));
    const firstSignal = mocks.getMatchView.mock.calls[0][2].signal as AbortSignal;

    for (let i = 0; i < 4; i += 1) {
      // Structurally identical, referentially new — exactly what a parent
      // rebuilding these objects on each render produces.
      rerender({ p: { ...profile, skills: [...profile.skills] }, v: { ...baseView } });
    }
    await act(async () => { await Promise.resolve(); });

    expect(mocks.getMatchView).toHaveBeenCalledTimes(1);
    // Not enough to send once: the request that WAS sent has to survive. A
    // dedupe that skips the resend while the effect's cleanup still aborts the
    // one in flight leaves the page loading forever.
    expect(firstSignal.aborted).toBe(false);
  });

  it('forwards the AI-refine choice into the request, both ways', async () => {
    // The hop that was missing: semanticRerank keyed the cache and nothing
    // else, so /matches/view always answered deterministically no matter what
    // the toggle said. Assert the flag reaches the call, not just the key.
    mocks.getMatchView.mockResolvedValue(response('a'));
    const { rerender } = renderHook(
      ({ llm }) => useResultsData(profile, llm, baseView, 1, t, true),
      { initialProps: { llm: true } },
    );
    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(1));
    expect(mocks.getMatchView.mock.calls[0][2].llm).toBe(true);

    rerender({ llm: false });
    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(2));
    expect(mocks.getMatchView.mock.calls[1][2].llm).toBe(false);
  });

  it('aborts the obsolete request and ignores its late response', async () => {
    const resolvers: Array<(value: MatchesResponse) => void> = [];
    const signals: AbortSignal[] = [];
    mocks.getMatchView.mockImplementation(
      (_profile, _view, options: { signal: AbortSignal }) => {
        signals.push(options.signal);
        return new Promise<MatchesResponse>((resolve) => {
          resolvers.push(resolve);
        });
      },
    );
    const { result, rerender } = renderHook(
      ({ view }) => useResultsData(profile, false, view, 1, t, true),
      { initialProps: { view: baseView } },
    );
    await waitFor(() => expect(signals).toHaveLength(1));

    const changedView = { ...baseView, paid: 'yes' as const };
    rerender({ view: changedView });
    await waitFor(() => expect(signals).toHaveLength(2));
    expect(signals[0].aborted).toBe(true);

    await act(async () => {
      resolvers[1](response('new'));
    });
    await waitFor(() => {
      expect(result.current.data?.results[0]?.opportunity_id).toBe('new');
    });
    await act(async () => {
      resolvers[0](response('stale'));
    });
    expect(result.current.data?.results[0]?.opportunity_id).toBe('new');
  });

  it('uses the previous page cursor instead of a numeric offset', async () => {
    mocks.getMatchView
      .mockResolvedValueOnce(response('first', {
        total: 2,
        filtered_total: 2,
        has_more: true,
        next_cursor: 'cursor-for-page-2',
      }))
      .mockResolvedValueOnce(response('second', { view_start: 50 }));

    const { result, rerender } = renderHook(
      ({ page }) => useResultsData(profile, false, baseView, page, t, true),
      { initialProps: { page: 1 } },
    );
    await waitFor(() => expect(result.current.data).not.toBeNull());
    rerender({ page: 2 });
    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(2));
    expect(mocks.getMatchView.mock.calls[1][2].cursor).toBe('cursor-for-page-2');
  });

  it('never paints a cached page one — only the live response paints, and only it mints a cursor', async () => {
    // The stored page is good for seven days; a listing closes in one. It used
    // to paint immediately and be corrected when the live response landed,
    // which meant every load opened on rows up to a week stale — with a live
    // Apply link, and no server action in front of it to catch the difference.
    const cached = response('cached-first', {
      total: 2,
      filtered_total: 2,
      has_more: true,
      next_cursor: 'stale-cached-cursor',
    });
    mocks.readMatchCache.mockReturnValue(cached);
    let resolveValidation: ((value: MatchesResponse) => void) | undefined;
    mocks.getMatchView
      .mockImplementationOnce(() => new Promise<MatchesResponse>((resolve) => {
        resolveValidation = resolve;
      }))
      .mockResolvedValueOnce(response('live-second', { view_start: 50 }));

    const { result, rerender, unmount } = renderHook(
      ({ page }) => useResultsData(profile, false, baseView, page, t, true),
      { initialProps: { page: 1 } },
    );
    // The request is out, which is exactly the window the cache used to fill.
    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(1));
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
    expect(result.current.refined).toBe(false);
    expect(result.current.paginationReady).toBe(false);
    expect(result.current.error).toBeNull();

    await act(async () => {
      resolveValidation?.(response('live-first', {
        total: 2,
        filtered_total: 2,
        has_more: true,
        next_cursor: 'live-cursor-for-page-2',
      }));
    });
    // Only now is there a list, and it is the live one.
    expect(result.current.data?.results[0]?.opportunity_id).toBe('live-first');
    await waitFor(() => expect(result.current.paginationReady).toBe(true));
    rerender({ page: 2 });
    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(2));
    expect(mocks.getMatchView.mock.calls[1][2].cursor)
      .toBe('live-cursor-for-page-2');
    await waitFor(() => {
      expect(result.current.data?.results[0]?.opportunity_id).toBe('live-second');
    });

    unmount();
  });

  it('rejects a live response whose nested opportunity id drifted from the top-level id, and never caches it', async () => {
    const bad = response('bad');
    (bad.results[0].opportunity as unknown as Record<string, unknown>).id = 'drifted-id';
    mocks.getMatchView.mockResolvedValueOnce(bad);

    const { result } = renderHook(() => useResultsData(profile, false, baseView, 1, t, true));

    await waitFor(() => expect(result.current.error).toBe('Match results need to be refreshed. Please retry.'));
    expect(result.current.data).toBeNull();
    expect(mocks.writeMatchCache).not.toHaveBeenCalled();
  });

  it.each([
    ['missing', undefined],
    ['null', null],
    ['malformed', { listing_state: 'open' }],
    ['closed', {
      listing_state: 'closed', reference_only: false, actionable: false,
      accepting_state: 'not_accepting', reason_code: 'listing_closed',
      verified_at: null, expires_at: null,
    }],
    ['self-contradicting', {
      listing_state: 'closed', reference_only: false, actionable: true,
      accepting_state: 'accepting', reason_code: null,
      verified_at: null, expires_at: null,
    }],
  ])(
    'rejects the whole live page when one row has a %s truth, and clears the cache',
    async (_label, truth) => {
      // Not a filter: showing 1 of 2 rows under a "2 matches" header, with the
      // facet counts still saying 2, is a quieter lie than an error.
      const bad = response('mixed', {
        results: [response('mixed').results[0], response('other').results[0]],
      });
      const poisoned = bad.results[1].opportunity as unknown as Record<string, unknown>;
      if (truth === undefined) delete poisoned.target_truth;
      else poisoned.target_truth = truth;
      mocks.getMatchView.mockResolvedValueOnce(bad);

      const { result } = renderHook(() => useResultsData(profile, false, baseView, 1, t, true));

      await waitFor(() => expect(result.current.error).toBe(
        'Match results need to be refreshed. Please retry.',
      ));
      expect(result.current.data).toBeNull();
      expect(mocks.writeMatchCache).not.toHaveBeenCalled();
      expect(mocks.clearMatchCache).toHaveBeenCalled();
    },
  );

  it('refuses a live page on a wire version nobody has negotiated', async () => {
    // Every row is perfect and the truth marker is present — only the version
    // is one nothing emits. Accepting it in advance would mean rendering a
    // payload whose fields were never agreed, on the strength of a string.
    mocks.getMatchView.mockResolvedValueOnce(
      response('v4-page', { contract_version: 'match-view-v4-target-truth' }),
    );

    const { result } = renderHook(() => useResultsData(profile, false, baseView, 1, t, true));

    // The MATCH_CONTRACT_MISMATCH path, by its user-visible half: a
    // retryable refresh prompt, not a generic failure and not a silent
    // partial page.
    await waitFor(() => expect(result.current.error).toBe(
      'Match results need to be refreshed. Please retry.',
    ));
    expect(result.current.data).toBeNull();
    // Nothing stored, and whatever an earlier response left behind is
    // dropped: the same cause is at least as likely to be sitting in it.
    expect(mocks.writeMatchCache).not.toHaveBeenCalled();
    expect(mocks.clearMatchCache).toHaveBeenCalled();
  });

  /**
   * Mint a real page-2 cursor first.
   *
   * The hook refuses to request page 2 without one, so a test that mounts
   * straight at page 2 never issues the call its mock is waiting for — it
   * times out looking like a failure of the code under test. Page 1 has to
   * succeed and hand back has_more + next_cursor before the dead-cursor path
   * is even reachable.
   */
  function paginatedHarness(onCursorReset: () => void) {
    // `page` lives in React state, not a closure variable: the reset callback
    // has to actually re-render the hook, or the recovery request is never
    // issued and the test would pass with the refetch deleted.
    let setPageExternally: ((n: number) => void) | null = null;
    const hook = renderHook(() => {
      const [page, setPage] = useState(1);
      setPageExternally = setPage;
      const data = useResultsData(
        profile, false, baseView, page, t, true,
        useCallback(() => { setPage(1); onCursorReset(); }, []),
      );
      return { data, page };
    });
    return {
      ...hook,
      goToPage: (n: number) => act(() => { setPageExternally!(n); }),
    };
  }

  it.each(['MATCH_CURSOR_INVALID', 'MATCH_CURSOR_EXPIRED'])(
    'drops a dead cursor on %s and returns to page 1 exactly once',
    async (code) => {
      // The snapshot the cursor points at is gone, so replaying it can never
      // succeed. Recovery is a fresh page-1 request; surfacing an error would
      // leave the reader on a page they cannot leave.
      const onCursorReset = vi.fn();
      mocks.getMatchView
        .mockResolvedValueOnce(response('p1', { has_more: true, next_cursor: 'cursor-2' }))
        .mockRejectedValueOnce(
          new ApiError(code === 'MATCH_CURSOR_EXPIRED' ? 409 : 400, code, 'dead cursor', false),
        )
        .mockResolvedValueOnce(response('fresh-p1'));

      const harness = paginatedHarness(onCursorReset);
      await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(1));

      harness.goToPage(2);
      await waitFor(() => expect(onCursorReset).toHaveBeenCalledTimes(1));
      // The recovery request must actually happen — deleting it is the mutant
      // this waits for.
      await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(3));

      // page 1 (no cursor) → page 2 (the dead cursor, once) → page 1 again
      // (no cursor). The dead cursor is never replayed.
      const cursors = mocks.getMatchView.mock.calls.map(
        (call) => (call[2] as { cursor?: string | null } | undefined)?.cursor ?? null,
      );
      expect(cursors).toEqual([null, 'cursor-2', null]);
      expect(mocks.clearMatchCache).toHaveBeenCalled();
      expect(harness.result.current.page).toBe(1);
      await waitFor(() =>
        expect(harness.result.current.data.data?.result_set_id).toBe('set-fresh-p1'),
      );
      expect(harness.result.current.data.error).toBeNull();
    },
  );

  it.each(['MATCH_CURSOR_INVALID', 'MATCH_CURSOR_EXPIRED'])(
    'does not loop when %s arrives on page 1',
    async (code) => {
      // Page 1 carries no cursor, so this code there means something else is
      // wrong. Resetting again would spin.
      const onCursorReset = vi.fn();
      mocks.getMatchView.mockRejectedValue(new ApiError(409, code, 'dead cursor', false));

      const { result } = renderHook(() => useResultsData(
        profile, false, baseView, 1, t, true, onCursorReset,
      ));

      await waitFor(() => expect(result.current.error).toBe('dead cursor'));
      expect(onCursorReset).not.toHaveBeenCalled();
    },
  );

  it('leaves an ordinary error alone rather than resetting the page', async () => {
    const onCursorReset = vi.fn();
    mocks.getMatchView
      .mockResolvedValueOnce(response('p1', { has_more: true, next_cursor: 'cursor-2' }))
      .mockRejectedValueOnce(new ApiError(503, 'MATCH_BUSY', 'busy', true));

    const harness = paginatedHarness(onCursorReset);
    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(1));
    harness.goToPage(2);

    await waitFor(() => expect(harness.result.current.data.error).toBe('busy'));
    expect(onCursorReset).not.toHaveBeenCalled();
    expect(harness.result.current.page).toBe(2);
  });

  it('rejects a live response with duplicate result ids, and never caches it', async () => {
    const bad = response('dup', {
      results: [
        response('dup').results[0],
        response('dup').results[0],
      ],
    });
    mocks.getMatchView.mockResolvedValueOnce(bad);

    const { result } = renderHook(() => useResultsData(profile, false, baseView, 1, t, true));

    await waitFor(() => expect(result.current.error).toBe('Match results need to be refreshed. Please retry.'));
    expect(result.current.data).toBeNull();
    expect(mocks.writeMatchCache).not.toHaveBeenCalled();
  });

  it('captures the owner token at REQUEST START: a deferred write lands with the ORIGIN identity even after the owner switches mid-flight', async () => {
    advanceOwnerEpoch('results-data-cache-token-u1');
    await syncLocalIdentityOwner('results-data-cache-token-u1');
    const u1Token = captureOwnerToken();

    let resolveFetch: ((value: MatchesResponse) => void) | undefined;
    mocks.getMatchView.mockImplementation(
      () => new Promise<MatchesResponse>((resolve) => { resolveFetch = resolve; }),
    );

    renderHook(() => useResultsData(profile, false, baseView, 1, t, true));
    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(1));

    // The hook's own props (profile/view/page) never change here, so this
    // in-flight request is not aborted by the switch — its effect instance
    // keeps running to completion under the identity that was active when
    // IT started, not whichever identity happens to be current by the time
    // its network round-trip finally resolves.
    advanceOwnerEpoch('results-data-cache-token-u2');
    await syncLocalIdentityOwner('results-data-cache-token-u2');

    await act(async () => {
      resolveFetch?.(response('deferred'));
    });

    await waitFor(() => expect(mocks.writeMatchCache).toHaveBeenCalledTimes(1));
    expect(mocks.writeMatchCache.mock.calls[0]?.[3]).toEqual(u1Token);
  });

  it('paints the rule ranking first and swaps in the refined one when it lands', async () => {
    // A first refined page is about twenty seconds and four of them are the
    // rule ranking the refine has to run before it can call the model. The
    // student reads that ranking while the rest happens.
    let resolveRefine: ((value: MatchesResponse) => void) | undefined;
    mocks.getMatchView.mockImplementation(
      (_profile, _view, options: { llm: boolean }) => (options.llm
        ? new Promise<MatchesResponse>((resolve) => { resolveRefine = resolve; })
        : Promise.resolve(response('rule'))),
    );

    const { result } = renderHook(() => useResultsData(profile, true, baseView, 1, t, true));

    await waitFor(
      () => expect(result.current.data?.result_set_id).toBe('set-rule'),
      { timeout: 4000 },
    );
    expect(result.current.loading).toBe(false);
    expect(result.current.refining).toBe(true);
    expect(result.current.refined).toBe(false);
    // The refined snapshot owns the cursor chain; paging off an interim list
    // would page a result set that is about to be replaced.
    expect(result.current.paginationReady).toBe(false);
    expect(mocks.writeMatchCache).not.toHaveBeenCalled();

    await act(async () => {
      resolveRefine?.(response('ai', { ai_refined: true }));
    });

    await waitFor(() => expect(result.current.data?.result_set_id).toBe('set-ai'));
    expect(result.current.refining).toBe(false);
    expect(result.current.refined).toBe(true);
    expect(result.current.paginationReady).toBe(true);
    expect(mocks.writeMatchCache).toHaveBeenCalledTimes(1);
    expect(mocks.writeMatchCache.mock.calls[0][2].result_set_id).toBe('set-ai');
  });

  it('spends no second ranking when the refine answers straight away', async () => {
    // A warm server snapshot needs no help, and a rule ranking fired behind a
    // request that already returned is pure server cost. This is the shape that
    // once took the E2E job from seven minutes to past its timeout.
    mocks.getMatchView.mockResolvedValue(response('warm', { ai_refined: true }));

    const { result } = renderHook(() => useResultsData(profile, true, baseView, 1, t, true));

    await waitFor(() => expect(result.current.data?.result_set_id).toBe('set-warm'));
    await new Promise((resolve) => { setTimeout(resolve, 900); });
    expect(mocks.getMatchView).toHaveBeenCalledTimes(1);
    expect(result.current.refining).toBe(false);
    expect(result.current.refined).toBe(true);
  });

  it('does not make a warm load wait out the interim timer', async () => {
    // The timer exists for the cold case. Awaiting it unconditionally would
    // add its full interval to every AI-on first page, warm ones included —
    // slower than doing nothing at all, and it holds the request closure alive
    // that long after an unmount.
    mocks.getMatchView.mockResolvedValue(response('warm'));

    const started = Date.now();
    const { result } = renderHook(() => useResultsData(profile, true, baseView, 1, t, true));
    await waitFor(() => expect(result.current.data?.result_set_id).toBe('set-warm'));

    expect(Date.now() - started).toBeLessThan(400);
  });

  it('believes the server over the request when the refine silently degraded', async () => {
    // The request asked for a refine and got 200 with a complete list back.
    // Nothing in the results distinguishes a degraded pass from a real one —
    // the provider being unconfigured, the day budget degrading the call, and
    // an unusable batch all return the rule ranking. Only ai_refined does.
    mocks.getMatchView.mockResolvedValue(response('degraded', { ai_refined: false }));

    const { result } = renderHook(() => useResultsData(profile, true, baseView, 1, t, true));

    await waitFor(() => expect(result.current.data?.result_set_id).toBe('set-degraded'));
    expect(result.current.refined).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('leaves the rule list up and claims nothing when the refine fails', async () => {
    // The interim list is a real, complete answer and stays. What it must not
    // do is inherit the badge for work that failed.
    let rejectRefine: ((reason: Error) => void) | undefined;
    mocks.getMatchView.mockImplementation(
      (_profile, _view, options: { llm: boolean }) => (options.llm
        ? new Promise<MatchesResponse>((_resolve, reject) => { rejectRefine = reject; })
        : Promise.resolve(response('rule'))),
    );

    const { result } = renderHook(() => useResultsData(profile, true, baseView, 1, t, true));

    await waitFor(() => expect(result.current.refining).toBe(true), { timeout: 4000 });
    await act(async () => { rejectRefine?.(new Error('provider down')); });

    await waitFor(() => expect(result.current.refineFailed).toBe(true));
    // NOT `error`: the results page renders its list under
    // `!loading && !error && data`, so setting error here would hide a list
    // that loaded correctly because an enhancement to it did not.
    expect(result.current.error).toBeNull();
    expect(result.current.data?.result_set_id).toBe('set-rule');
    expect(result.current.refining).toBe(false);
    expect(result.current.refined).toBe(false);
    expect(mocks.writeMatchCache).not.toHaveBeenCalled();
  });

  it('still fails the page when there is no list to keep', async () => {
    // No interim painted means nothing loaded, and a student staring at an
    // empty page has to be told why.
    mocks.getMatchView.mockRejectedValue(new Error('provider down'));

    const { result } = renderHook(() => useResultsData(profile, true, baseView, 1, t, true));

    await waitFor(() => expect(result.current.error).toBe('results.loadFailed'));
    expect(result.current.data).toBeNull();
    expect(result.current.refineFailed).toBe(false);
  });

  it('a cached page no longer suppresses the interim rule list — with AI on and a slow refine, the llm:false request still goes out on its own timer', async () => {
    // This test used to assert the opposite, and correctly so: the cache had
    // already put a list on screen, so the extra server-side ranking bought
    // the student nothing. Now the cache paints nothing, so the wait it was
    // filling is a blank page, and the interim is the only honest way to fill
    // it. Skipping it because a stored page exists would leave the student
    // staring at a spinner while a week-old list sat unused and unusable.
    mocks.readMatchCache.mockReturnValue(response('cached'));
    let resolveRefine: ((value: MatchesResponse) => void) | undefined;
    mocks.getMatchView
      .mockImplementationOnce(
        () => new Promise<MatchesResponse>((resolve) => { resolveRefine = resolve; }),
      )
      .mockResolvedValueOnce(response('rule'));

    const { result } = renderHook(() => useResultsData(profile, true, baseView, 1, t, true));

    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(1));
    expect(mocks.getMatchView.mock.calls[0][2].llm).toBe(true);
    // Nothing at all until the interim's own timer elapses. The cached page is
    // not a head start; it is not on screen.
    expect(result.current.data).toBeNull();

    await waitFor(
      () => expect(mocks.getMatchView).toHaveBeenCalledTimes(2),
      { timeout: 4000 },
    );
    expect(mocks.getMatchView.mock.calls[1][2].llm).toBe(false);
    await waitFor(() => expect(result.current.data?.result_set_id).toBe('set-rule'));
    expect(result.current.refining).toBe(true);
    expect(result.current.refined).toBe(false);
    // And it is the interim that is on screen, never the cached page.
    expect(result.current.data?.results[0]?.opportunity_id).toBe('rule');

    await act(async () => { resolveRefine?.(response('ai', { ai_refined: true })); });
    await waitFor(() => expect(result.current.data?.result_set_id).toBe('set-ai'));
    expect(result.current.refined).toBe(true);
  });

  describe('a live failure never falls back to the stored page', () => {
    // Three ways the live request can fail to produce a showable list. None of
    // them may reveal the cache: whatever went wrong, the stored page is the
    // one thing on the machine that is guaranteed not to have been checked.
    it('a thrown request leaves nothing on screen', async () => {
      mocks.readMatchCache.mockReturnValue(response('cached'));
      mocks.getMatchView.mockRejectedValue(new Error('provider down'));

      const { result } = renderHook(() => useResultsData(profile, false, baseView, 1, t, true));

      await waitFor(() => expect(result.current.error).toBe('results.loadFailed'));
      expect(result.current.data).toBeNull();
    });

    it('a response the shared validator refuses leaves nothing on screen', async () => {
      mocks.readMatchCache.mockReturnValue(response('cached'));
      const bad = response('bad');
      delete (bad.results[0].opportunity as unknown as Record<string, unknown>).target_truth;
      mocks.getMatchView.mockResolvedValue(bad);

      const { result } = renderHook(() => useResultsData(profile, false, baseView, 1, t, true));

      await waitFor(() => expect(result.current.error).toBe(
        'Match results need to be refreshed. Please retry.',
      ));
      expect(result.current.data).toBeNull();
      expect(mocks.clearMatchCache).toHaveBeenCalled();
    });

    it('a trusted EMPTY page is shown as empty, not backfilled from the cache', async () => {
      // "No results" is an answer, and an honest one. Filling it from a stored
      // page would be the single most misleading thing this hook could do:
      // the student changed a filter and got someone else's older list back.
      mocks.readMatchCache.mockReturnValue(response('cached'));
      mocks.getMatchView.mockResolvedValue(response('live-empty', {
        results: [], total: 0, high_priority: 0, filtered_total: 0, returned_count: 0,
        view_counts: { all: 0, high_priority: 0, good_match: 0, reach: 0, starred: 0 },
      }));

      const { result } = renderHook(() => useResultsData(profile, false, baseView, 1, t, true));

      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(result.current.error).toBeNull();
      expect(result.current.data?.results).toEqual([]);
      expect(result.current.data?.result_set_id).toBe('set-live-empty');
    });
  });
});

// ---------------------------------------------------------------------------
// The same contract, measured where it matters: the page.
// ---------------------------------------------------------------------------
// `data === null` is the mechanism; "no Apply button on a dead listing" is the
// promise. This block renders a real MatchCard against whatever the hook is
// holding, under the same gate the page uses — results/page.tsx renders the
// list inside `{!loading && !error && data && ...}`. Nothing else about the
// page is simulated, and MatchList between them is a pass-through: every CTA
// and every offer term in question lives in the card.

function poisonedPage(id: string, overrides: Partial<MatchesResponse> = {}) {
  const page = response(id, overrides);
  Object.assign(page.results[0].opportunity, {
    title: 'CACHED Vision Lab RA',
    opportunity_type: 'Poisontype',
    paid: 'yes',
    deadline: '2099-12-31',
    deadline_is_estimate: false,
    compensation_details: 'POISON $32/hr',
    eligibility: {
      international_friendly: 'yes',
      preferred_year: [], majors: [],
      skills_required: [], citizenship_required: false,
    },
    application: {
      application_effort: 'low',
      requires_resume: 'unknown',
      contact_method: 'email',
      application_url: 'https://example.edu/apply',
    },
  });
  return page;
}

const OFFER_ON_SCREEN = [
  'card.applyNow', 'card.draftEmail', 'card.tailorResume',
  'Poisontype', 'badges.paid', 'badges.intlOk', '2099-12-31',
  'POISON $32/hr', 'CACHED Vision Lab RA',
];

function Harness() {
  const { data, loading, error } = useResultsData(profile, false, baseView, 1, t, true);
  if (loading || error || !data) return <div data-testid="no-list" />;
  return (
    <div data-testid="list">
      {data.results.map((m) => (
        <MatchCard
          key={m.opportunity.id}
          match={m}
          profile={profile}
          onDraftEmail={() => {}}
          ownerReady
        />
      ))}
    </div>
  );
}

describe('what a warm cache can put in front of a student', () => {
  // Its own reset: this block sits outside the `useResultsData` describe, so
  // without it every mock implementation AND every call count carries over
  // from the tests above — which is how the first draft of these three tests
  // timed out against a call counter that was already at nine.
  beforeEach(() => {
    mocks.getMatchView.mockReset();
    mocks.readMatchCache.mockReset();
    mocks.writeMatchCache.mockReset();
    mocks.clearMatchCache.mockReset();
    mocks.trackOnce.mockReset();
    mocks.readMatchCache.mockReturnValue(null);
    localStorage.clear();
  });

  it('nothing, while the live request is still out — no rows, no CTAs, no offer terms', async () => {
    mocks.readMatchCache.mockReturnValue(poisonedPage('cached-poison'));
    mocks.getMatchView.mockImplementation(() => new Promise<MatchesResponse>(() => {}));

    render(<Harness />);

    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('no-list')).toBeInTheDocument();
    expect(screen.queryByTestId('list')).toBeNull();
    for (const text of OFFER_ON_SCREEN) {
      expect(screen.queryByText(text)).toBeNull();
    }
    expect(screen.queryByTestId('tailor-modal')).toBeNull();
    expect(document.querySelector('a[href*="/apply"]')).toBeNull();
  });

  it('still nothing, once the live answer says that row is closed', async () => {
    const cached = poisonedPage('cached-poison');
    mocks.readMatchCache.mockReturnValue(cached);
    const closed = poisonedPage('cached-poison');
    closed.results[0].opportunity.target_truth = {
      listing_state: 'closed',
      reference_only: false,
      actionable: false,
      accepting_state: 'not_accepting',
      reason_code: 'listing_closed',
      verified_at: null,
      expires_at: null,
    };
    mocks.getMatchView.mockResolvedValue(closed);

    render(<Harness />);

    // `no-list` is on screen from the first frame, so asserting it alone would
    // pass against a hook that had done nothing yet. Wait for a signal that
    // only the refusal branch produces: rejecting a page clears the stored one
    // (a page with a row the validator refuses says the cache is at least as
    // likely to hold the same rot). Only then is the DOM worth reading.
    await waitFor(() => expect(mocks.clearMatchCache).toHaveBeenCalledTimes(1));
    expect(mocks.getMatchView).toHaveBeenCalledTimes(1);
    expect(mocks.writeMatchCache).not.toHaveBeenCalled();
    expect(screen.getByTestId('no-list')).toBeInTheDocument();
    expect(screen.queryByTestId('list')).toBeNull();
    for (const text of OFFER_ON_SCREEN) {
      expect(screen.queryByText(text)).toBeNull();
    }
  });

  it('and only a trusted, actionable live page produces a row and its Apply link', async () => {
    // The control. A hook that renders nothing under every condition would
    // pass both tests above and ship a blank product.
    mocks.readMatchCache.mockReturnValue(poisonedPage('cached-poison'));
    const live = poisonedPage('live-good');
    live.results[0].opportunity.title = 'LIVE Vision Lab RA';
    mocks.getMatchView.mockResolvedValue(live);

    render(<Harness />);

    await waitFor(() => expect(screen.getByTestId('list')).toBeInTheDocument());
    expect(screen.getByText('LIVE Vision Lab RA')).toBeInTheDocument();
    expect(screen.getByText('card.applyNow')).toBeInTheDocument();
    expect(screen.getByText('Poisontype')).toBeInTheDocument();
    // The cached row's title never appeared at any point.
    expect(screen.queryByText('CACHED Vision Lab RA')).toBeNull();
  });
});
