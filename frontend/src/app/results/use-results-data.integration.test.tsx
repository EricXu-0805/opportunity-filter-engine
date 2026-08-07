// Integration companion to use-results-data.test.tsx: that file mocks
// @/lib/match-cache entirely, so it can prove WHAT TOKEN the hook passes
// but not what the REAL primitive does with a stale one once it gets there.
// This file mocks only the network (getMatchView) and analytics — identity-
// owner and match-cache are the real, production modules — so the full
// caller -> primitive chain is exercised exactly as it runs in the browser.
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MatchViewRequestState } from '@/lib/api';
import type { MatchesResponse, ProfileData } from '@/lib/types';
import { useResultsData } from './use-results-data';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { MATCH_VIEW_CONTRACT_VERSION, readMatchCache, writeMatchCache as writeMatchCacheRaw } from '@/lib/match-cache';

const mocks = vi.hoisted(() => ({ getMatchView: vi.fn(), trackOnce: vi.fn() }));
vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return { ...actual, getMatchView: mocks.getMatchView };
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

function response(id: string): MatchesResponse {
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
    contract_version: MATCH_VIEW_CONTRACT_VERSION,
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
  };
}

const t = (key: string) => key;

describe('useResultsData x match-cache integration: a stale write never corrupts a different owner\'s real cache', () => {
  beforeEach(() => {
    localStorage.clear();
    mocks.getMatchView.mockReset();
    mocks.trackOnce.mockReset();
  });

  it('a deferred U1 response, arriving after U2 has already written their own real cache, is silently dropped by the real primitive without touching U2\'s entry', async () => {
    advanceOwnerEpoch('results-integration-u1');
    await syncLocalIdentityOwner('results-integration-u1');

    let resolveFetch: ((value: MatchesResponse) => void) | undefined;
    mocks.getMatchView.mockImplementation(
      () => new Promise<MatchesResponse>((resolve) => { resolveFetch = resolve; }),
    );

    renderHook(() => useResultsData(profile, false, baseView, 1, t));
    await waitFor(() => expect(mocks.getMatchView).toHaveBeenCalledTimes(1));

    advanceOwnerEpoch('results-integration-u2');
    await syncLocalIdentityOwner('results-integration-u2');
    const u2Token = captureOwnerToken();
    const wroteU2 = writeMatchCacheRaw('u2-real-hash', false, response('u2-real'), u2Token);
    expect(wroteU2).toBe(true);

    await act(async () => {
      resolveFetch?.(response('u1-stale'));
    });

    // U1's stale write attempt (real writeMatchCache, real stale-token gate)
    // must neither overwrite the single-slot cache with its own data NOR
    // clear it as a "failed write" side effect — U2's real, already-
    // persisted entry must still read back exactly as U2 left it.
    const u2Cache = readMatchCache('u2-real-hash', false);
    expect(u2Cache).not.toBeNull();
    expect(u2Cache!.results[0]?.opportunity_id).toBe('u2-real');
  });
});
