import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MatchViewRequestState } from '@/lib/api';
import type { MatchesResponse, ProfileData } from '@/lib/types';
import { useResultsData } from './use-results-data';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';

const mocks = vi.hoisted(() => ({
  getMatchView: vi.fn(),
  readMatchCache: vi.fn(),
  writeMatchCache: vi.fn(),
  trackOnce: vi.fn(),
}));

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return { ...actual, getMatchView: mocks.getMatchView };
});
vi.mock('@/lib/match-cache', async () => {
  const actual = await vi.importActual<typeof import('@/lib/match-cache')>('@/lib/match-cache');
  return {
    MATCH_VIEW_CONTRACT_VERSION: 'match-view-v3-faculty-trust',
    hasValidMatchResultIdentity: actual.hasValidMatchResultIdentity,
    readMatchCache: mocks.readMatchCache,
    writeMatchCache: mocks.writeMatchCache,
  };
});
vi.mock('@/lib/analytics', () => ({ trackOnce: mocks.trackOnce }));

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
    contract_version: 'match-view-v3-faculty-trust',
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

  it('paints cached page one but waits for a live cursor before pagination', async () => {
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
    await waitFor(() => {
      expect(result.current.data?.results[0]?.opportunity_id).toBe('cached-first');
    });
    expect(result.current.paginationReady).toBe(false);
    expect(mocks.getMatchView).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveValidation?.(response('live-first', {
        total: 2,
        filtered_total: 2,
        has_more: true,
        next_cursor: 'live-cursor-for-page-2',
      }));
    });
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

  it('skips the interim request when the cache already painted', async () => {
    // Nothing to wait in front of, so the extra server-side ranking would buy
    // the student nothing.
    mocks.readMatchCache.mockReturnValue(response('cached'));
    let resolveRefine: ((value: MatchesResponse) => void) | undefined;
    mocks.getMatchView.mockImplementation(
      () => new Promise<MatchesResponse>((resolve) => { resolveRefine = resolve; }),
    );

    const { result } = renderHook(() => useResultsData(profile, true, baseView, 1, t, true));

    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => { setTimeout(resolve, 900); });
    expect(mocks.getMatchView).toHaveBeenCalledTimes(1);
    expect(mocks.getMatchView.mock.calls[0][2].llm).toBe(true);
    expect(result.current.refining).toBe(false);

    await act(async () => { resolveRefine?.(response('ai')); });
    await waitFor(() => expect(result.current.data?.result_set_id).toBe('set-ai'));
  });
});
