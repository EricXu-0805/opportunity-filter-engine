/* @vitest-environment jsdom */
import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import type { MatchResult, MatchesResponse, Opportunity } from '@/lib/types';
import { DEFAULT_FILTERS, type Filters, type Tab } from './types';
import { useResultsFilters } from './use-results-filters';

function mr(id: string, source: string, bucket: MatchResult['bucket']): MatchResult {
  return {
    opportunity_id: id,
    eligibility_score: 0,
    readiness_score: 0,
    upside_score: 0,
    final_score: 80,
    bucket,
    reasons_fit: [],
    reasons_gap: [],
    next_steps: [],
    opportunity: {
      id,
      source,
      title: id,
      organization: '',
      keywords: [],
      paid: 'unknown',
      on_campus: false,
      deadline: null,
      description_clean: '',
      description_raw: '',
      eligibility: { international_friendly: 'unknown' },
    } as unknown as Opportunity,
  };
}

const RESULTS: MatchResult[] = [
  mr('fac-1', 'ucb_eecs_faculty', 'high_priority'),
  mr('fac-2', 'ucb_eecs_faculty', 'high_priority'),
  mr('prog-1', 'ucb_research_programs', 'good_match'),
  mr('prog-2', 'ucb_research_programs', 'reach'),
  mr('prog-3', 'ucb_research_programs', 'reach'),
  mr('low-1', 'ucb_eecs_faculty', 'low_fit'),
];

const DATA: MatchesResponse = {
  total: RESULTS.length,
  high_priority: 2,
  good_match: 1,
  reach: 2,
  low_fit: 1,
  results: RESULTS,
};

function run(overrides: { activeTab?: Tab; filters?: Partial<Filters> }) {
  return renderHook(() =>
    useResultsFilters({
      data: DATA,
      activeTab: overrides.activeTab ?? 'high_priority',
      debouncedQuery: '',
      filters: { ...DEFAULT_FILTERS, ...overrides.filters },
      favs: new Set<string>(),
      sortBy: 'score',
      interactions: new Map(),
      showDismissed: true,
      page: 1,
      pageSize: 50,
      homeSchool: 'ucb',
    }),
  ).result.current;
}

describe('useResultsFilters — filter-aware tab counts', () => {
  it('counts the whole ranked set (minus low_fit) when no field filter is active', () => {
    const { counts } = run({});
    expect(counts).toEqual({ all: 5, high_priority: 2, good_match: 1, reach: 2, starred: 0 });
  });

  it('a source filter that has no high-priority matches yields high_priority: 0 (the bug)', () => {
    // ucb_research_programs only has good_match/reach records here — so the
    // high-priority badge must read 0, not the global 2 above an empty list.
    const { counts } = run({ filters: { source: 'ucb_research_programs' } });
    expect(counts.high_priority).toBe(0);
    expect(counts.good_match).toBe(1);
    expect(counts.reach).toBe(2);
    expect(counts.all).toBe(3);
  });

  it('every tab badge equals exactly what that tab shows under the active filter', () => {
    for (const tab of ['all', 'high_priority', 'good_match', 'reach'] as const) {
      const { counts, filtered } = run({ activeTab: tab, filters: { source: 'ucb_research_programs' } });
      expect(counts[tab], tab).toBe(filtered.length);
    }
  });

  it('high_priority tab + source with no high-priority records → empty list AND zero badge', () => {
    const { counts, filtered } = run({
      activeTab: 'high_priority',
      filters: { source: 'ucb_research_programs' },
    });
    expect(filtered).toHaveLength(0);
    expect(counts.high_priority).toBe(0);
  });
});

describe('useResultsFilters — tri-state campus evidence', () => {
  it('unknown location is neither on-campus nor off-campus', () => {
    const triState = {
      ...DATA,
      results: [
        { ...mr('campus-yes', 'test', 'good_match'), opportunity: { ...mr('campus-yes', 'test', 'good_match').opportunity, on_campus: true } },
        { ...mr('campus-no', 'test', 'good_match'), opportunity: { ...mr('campus-no', 'test', 'good_match').opportunity, on_campus: false } },
        { ...mr('campus-unknown', 'test', 'good_match'), opportunity: { ...mr('campus-unknown', 'test', 'good_match').opportunity, on_campus: null } },
      ],
    } as MatchesResponse;

    const filteredIds = (onCampus: 'yes' | 'no') => renderHook(() =>
      useResultsFilters({
        data: triState,
        activeTab: 'all',
        debouncedQuery: '',
        filters: { ...DEFAULT_FILTERS, onCampus },
        favs: new Set<string>(),
        sortBy: 'score',
        interactions: new Map(),
        showDismissed: true,
        page: 1,
        pageSize: 50,
        homeSchool: 'test',
      }),
    ).result.current.filtered.map((match) => match.opportunity.id);

    expect(filteredIds('yes')).toEqual(['campus-yes']);
    expect(filteredIds('no')).toEqual(['campus-no']);
  });
});

describe('useResultsFilters — the deadline facet on a rolling corpus', () => {
  // Every record in RESULTS has deadline: null. Faculty contacts remain
  // undated, but must not be promoted into the rolling-open set.
  it('a dated option finds nothing when no match carries a deadline', () => {
    expect(run({ activeTab: 'all', filters: { deadline: '30' } }).filtered).toHaveLength(0);
  });

  it('rolling selects on is_rolling, independent of the deadline field', () => {
    const rolling = { ...DATA, results: DATA.results.map((r, i) => ({
      ...r,
      opportunity: {
        ...r.opportunity,
        is_rolling: i % 2 === 0,
        source_type: r.opportunity.source?.includes('faculty')
          ? 'faculty_research'
          : 'campus_program',
      },
    })) };
    const out = renderHook(() =>
      useResultsFilters({
        data: rolling as MatchesResponse,
        activeTab: 'all',
        debouncedQuery: '',
        filters: { ...DEFAULT_FILTERS, deadline: 'rolling' },
        favs: new Set<string>(),
        sortBy: 'score',
        interactions: new Map(),
        showDismissed: true,
        page: 1,
        pageSize: 50,
        homeSchool: 'ucb',
      }),
    ).result.current;
    // Even indices are stamped rolling, but index 0 is only a faculty contact.
    expect(out.filtered.map((m) => m.opportunity.id)).toEqual(['prog-1', 'prog-3']);
  });
});

describe('useResultsFilters — canonical consistency guards', () => {
  it('fails poisoned faculty opening fields closed in every positive facet', () => {
    const faculty = mr('faculty-poison', 'faculty_source', 'good_match');
    faculty.opportunity = {
      ...faculty.opportunity,
      source_type: 'faculty_research',
      paid: 'yes',
      on_campus: true,
      deadline: '2026-01-01',
      posted_date: '2099-01-01',
      eligibility: {
        ...faculty.opportunity.eligibility,
        international_friendly: 'yes',
        citizenship_required: false,
      },
    };
    const listing = mr('real-listing', 'listing_source', 'good_match');
    listing.opportunity = {
      ...listing.opportunity,
      source_type: 'campus_program',
      paid: 'yes',
      on_campus: true,
      deadline: '2027-01-01',
      posted_date: '2027-01-01',
      eligibility: {
        ...listing.opportunity.eligibility,
        international_friendly: 'yes',
      },
    };
    const data = { ...DATA, total: 2, results: [faculty, listing] } as MatchesResponse;
    const filteredIds = (filters: Partial<Filters>) => renderHook(() =>
      useResultsFilters({
        data,
        activeTab: 'all',
        debouncedQuery: '',
        filters: { ...DEFAULT_FILTERS, ...filters },
        favs: new Set<string>(),
        sortBy: 'score',
        interactions: new Map(),
        showDismissed: true,
        page: 1,
        pageSize: 50,
        homeSchool: 'test',
      }),
    ).result.current.filtered.map((match) => match.opportunity.id);

    expect(filteredIds({ paid: 'yes' })).toEqual(['real-listing']);
    expect(filteredIds({ intl: 'yes' })).toEqual(['real-listing']);
    expect(filteredIds({ onCampus: 'yes' })).toEqual(['real-listing']);
    // The existing "unpaid / not disclosed" option includes honest unknowns.
    expect(filteredIds({ paid: 'no' })).toEqual(['faculty-poison']);

    const sortedIds = (sortBy: 'deadline' | 'newest') => renderHook(() =>
      useResultsFilters({
        data,
        activeTab: 'all',
        debouncedQuery: '',
        filters: { ...DEFAULT_FILTERS },
        favs: new Set<string>(),
        sortBy,
        interactions: new Map(),
        showDismissed: true,
        page: 1,
        pageSize: 50,
        homeSchool: 'test',
      }),
    ).result.current.filtered.map((match) => match.opportunity.id);
    expect(sortedIds('deadline')).toEqual(['real-listing', 'faculty-poison']);
    expect(sortedIds('newest')).toEqual(['real-listing', 'faculty-poison']);
  });

  it('minScore filters on the DISPLAYED (rounded) score', () => {
    // A 79.6 renders as "80%" on the card, so it must survive minScore=80 —
    // filtering the raw value made labeled-80 cards vanish.
    const edge = mr('edge-1', 'ucb_eecs_faculty', 'high_priority');
    edge.final_score = 79.6;
    const data: MatchesResponse = { ...DATA, results: [...RESULTS, edge] };
    const { filtered } = renderHook(() =>
      useResultsFilters({
        data,
        activeTab: 'all',
        debouncedQuery: '',
        filters: { ...DEFAULT_FILTERS, minScore: 80 },
        favs: new Set<string>(),
        sortBy: 'score',
        interactions: new Map(),
        showDismissed: true,
        page: 1,
        pageSize: 50,
        homeSchool: 'ucb',
      }),
    ).result.current;
    expect(filtered.map((m) => m.opportunity_id)).toContain('edge-1');
  });

  it('a cached row without an eligibility object does not crash the intl filter', () => {
    const bare = mr('bare-1', 'ucb_eecs_faculty', 'good_match');
    delete (bare.opportunity as unknown as Record<string, unknown>).eligibility;
    const data: MatchesResponse = { ...DATA, results: [...RESULTS, bare] };
    const { filtered } = renderHook(() =>
      useResultsFilters({
        data,
        activeTab: 'all',
        debouncedQuery: '',
        filters: { ...DEFAULT_FILTERS, intl: 'yes' },
        favs: new Set<string>(),
        sortBy: 'score',
        interactions: new Map(),
        showDismissed: true,
        page: 1,
        pageSize: 50,
        homeSchool: 'ucb',
      }),
    ).result.current;
    // The row is simply not intl-confirmed — excluded, never a thrown render.
    expect(filtered.map((m) => m.opportunity_id)).not.toContain('bare-1');
  });

  it('effectivePage clamps into [1, totalPages] when the set shrinks under the cursor', () => {
    const { effectivePage, paginated, totalPages } = renderHook(() =>
      useResultsFilters({
        data: DATA,
        activeTab: 'all',
        debouncedQuery: '',
        filters: { ...DEFAULT_FILTERS },
        favs: new Set<string>(),
        sortBy: 'score',
        interactions: new Map(),
        showDismissed: true,
        page: 9, // stale cursor far past the end
        pageSize: 2,
        homeSchool: 'ucb',
      }),
    ).result.current;
    expect(totalPages).toBe(3);
    expect(effectivePage).toBe(3);
    expect(paginated.length).toBeGreaterThan(0); // never a blank grid
  });
  it('"Deadline soonest" puts what you can still apply to first', () => {
    // 831 of the 836 listings carrying a deadline have already passed, so the
    // plain ascending sort answered "soonest" with February 2025 — the thing
    // the student missed by the widest margin — at the top of the page.
    const day = (n: number) => {
      const d = new Date();
      d.setDate(d.getDate() + n);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    };
    const withDeadline = (id: string, deadline?: string) => {
      const m = mr(id, 'nsf_reu', 'good_match');
      m.opportunity.source_type = 'program';
      m.opportunity.deadline = deadline;
      return m;
    };
    const results = [
      withDeadline('long-expired', '2025-02-15'),
      withDeadline('soon', day(10)),
      withDeadline('recently-expired', day(-3)),
      withDeadline('later', day(90)),
      withDeadline('rolling'),
    ];
    const data = { ...DATA, total: results.length, results } as MatchesResponse;
    const ids = renderHook(() =>
      useResultsFilters({
        data,
        activeTab: 'all',
        debouncedQuery: '',
        filters: { ...DEFAULT_FILTERS },
        favs: new Set<string>(),
        sortBy: 'deadline',
        interactions: new Map(),
        showDismissed: true,
        page: 1,
        pageSize: 50,
        homeSchool: 'test',
      }),
    ).result.current.filtered.map((match) => match.opportunity.id);

    expect(ids).toEqual([
      'soon', 'later',           // still open, soonest first
      'rolling',                 // no date
      'recently-expired',        // gone, least-stale first
      'long-expired',
    ]);
  });

});
