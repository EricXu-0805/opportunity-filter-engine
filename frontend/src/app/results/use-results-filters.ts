'use client';

import { useMemo } from 'react';
import { matchesScope } from '@/lib/discovery-scope';
import { daysUntil, expandSearchAliases } from '@/lib/match-utils';
import type { MatchesResponse, MatchResult } from '@/lib/types';
import type { InteractionType } from '@/lib/supabase';
import type { Filters, SortKey, Tab } from './types';

export interface UseResultsFiltersInput {
  data: MatchesResponse | null;
  activeTab: Tab;
  debouncedQuery: string;
  filters: Filters;
  favs: Set<string>;
  sortBy: SortKey;
  interactions: Map<string, InteractionType>;
  showDismissed: boolean;
  page: number;
  pageSize: number;
  homeSchool: string;
}

export interface UseResultsFiltersOutput {
  filtered: MatchResult[];
  paginated: MatchResult[];
  totalPages: number;
  /**
   * `page` clamped to [1, totalPages]: hiding dismissed items or un-starring
   * on a late page can shrink the set below the current page, which used to
   * render a blank grid with a "5 / 3" pager. Render THIS, not the raw input.
   */
  effectivePage: number;
  /**
   * Per-tab counts that reflect the ACTIVE field filters (source, scope, paid,
   * search, …) — every badge equals exactly what its tab shows when clicked.
   * Computed from the same `base` set as `filtered` (all non-tab filters
   * applied), so e.g. filtering by a source with no high-priority matches
   * shows `high_priority: 0` instead of the misleading global count above an
   * empty list.
   */
  counts: Record<Tab, number>;
}

const EMPTY_COUNTS: Record<Tab, number> = {
  all: 0,
  high_priority: 0,
  good_match: 0,
  reach: 0,
  starred: 0,
};

export function useResultsFilters({
  data,
  activeTab,
  debouncedQuery,
  filters,
  favs,
  sortBy,
  interactions,
  showDismissed,
  page,
  pageSize,
  homeSchool,
}: UseResultsFiltersInput): UseResultsFiltersOutput {
  // `base` is every result that passes the active *field* filters (paid, intl,
  // source, on-campus, deadline, min-score, scope, search) and the dismissed
  // toggle — but NOT the tab/bucket selection or favorites. Both the per-tab
  // counts and the displayed list derive from it, so the badge for a tab and
  // the list under that tab can never disagree.
  const base = useMemo(() => {
    if (!data?.results) return [];
    let results = data.results;

    if (!showDismissed) {
      results = results.filter((m) => interactions.get(m.opportunity.id) !== 'dismissed');
    }
    if (filters.paid) {
      results = results.filter((m) =>
        filters.paid === 'yes'
          ? m.opportunity.paid === 'yes' || m.opportunity.paid === 'stipend'
          : m.opportunity.paid === 'no' || m.opportunity.paid === 'unknown',
      );
    }
    if (filters.intl) {
      // 'no' is the labeled "Show all (incl. US-only)" option — a deliberate
      // no-op, same set as ''. Optional-chain: a cached row whose projection
      // carried no eligibility object must not throw the whole results page.
      results = results.filter((m) =>
        filters.intl === 'yes'
          ? m.opportunity.eligibility?.international_friendly === 'yes'
          : true,
      );
    }
    if (filters.source) {
      results = results.filter((m) => m.opportunity.source === filters.source);
    }
    if (filters.onCampus) {
      results = results.filter((m) =>
        filters.onCampus === 'yes' ? m.opportunity.on_campus : !m.opportunity.on_campus,
      );
    }
    if (filters.deadline) {
      results = results.filter((m) => {
        const d = daysUntil(m.opportunity.deadline);
        if (filters.deadline === 'passed') return d !== null && d < 0;
        if (d === null || d < 0) return false;
        return d <= Number(filters.deadline);
      });
    }
    if (filters.minScore > 0) {
      // Filter on the DISPLAYED (rounded) score: the card shows
      // Math.round(final_score), so a 79.6 renders as "80%" and must survive
      // minScore=80 — filtering the raw value made labeled-80 cards vanish.
      results = results.filter((m) => Math.round(m.final_score) >= filters.minScore);
    }
    if (filters.scope) {
      results = results.filter((m) => matchesScope(m.opportunity, filters.scope, homeSchool));
    }

    if (debouncedQuery.trim()) {
      const q = debouncedQuery.toLowerCase();
      const expanded = expandSearchAliases(q);
      results = results.filter((m) => {
        const title = m.opportunity.title.toLowerCase();
        const org = m.opportunity.organization?.toLowerCase() ?? '';
        const kws = m.opportunity.keywords ?? [];
        const desc = (m.opportunity.description_clean ?? m.opportunity.description_raw ?? '').toLowerCase();
        const dept = m.opportunity.department?.toLowerCase() ?? '';
        const reasons = m.reasons_fit.join(' ').toLowerCase();
        return expanded.some((term) =>
          title.includes(term) ||
          org.includes(term) ||
          dept.includes(term) ||
          kws.some((k) => k.toLowerCase().includes(term)) ||
          desc.includes(term) ||
          reasons.includes(term)
        );
      });
    }

    return results;
  }, [data, debouncedQuery, filters, interactions, showDismissed, homeSchool]);

  const counts = useMemo<Record<Tab, number>>(() => {
    if (!data?.results) return EMPTY_COUNTS;
    const c: Record<Tab, number> = { all: 0, high_priority: 0, good_match: 0, reach: 0, starred: 0 };
    for (const m of base) {
      if (m.bucket !== 'low_fit') c.all += 1;
      if (m.bucket === 'high_priority') c.high_priority += 1;
      else if (m.bucket === 'good_match') c.good_match += 1;
      else if (m.bucket === 'reach') c.reach += 1;
      if (favs.has(m.opportunity.id)) c.starred += 1;
    }
    return c;
  }, [base, favs, data]);

  const filtered = useMemo(() => {
    let results: MatchResult[];
    if (activeTab === 'starred') {
      results = base.filter((m) => favs.has(m.opportunity.id));
    } else if (activeTab === 'all') {
      results = base.filter((m) => m.bucket !== 'low_fit');
    } else {
      results = base.filter((m) => m.bucket === activeTab);
    }

    if (sortBy === 'deadline') {
      results = [...results].sort((a, b) => {
        const da = a.opportunity.deadline || '9999';
        const db = b.opportunity.deadline || '9999';
        return da.localeCompare(db);
      });
    } else if (sortBy === 'newest') {
      results = [...results].sort((a, b) => {
        const pa = a.opportunity.posted_date || '';
        const pb = b.opportunity.posted_date || '';
        return pb.localeCompare(pa);
      });
    }

    return results;
  }, [base, activeTab, favs, sortBy]);

  const totalPages = Math.ceil(filtered.length / pageSize);
  const effectivePage = Math.min(Math.max(1, page), Math.max(1, totalPages));
  const paginated = useMemo(
    () => filtered.slice((effectivePage - 1) * pageSize, effectivePage * pageSize),
    [filtered, effectivePage, pageSize],
  );

  return { filtered, paginated, totalPages, effectivePage, counts };
}
