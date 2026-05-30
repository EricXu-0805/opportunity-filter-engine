'use client';

import { useMemo } from 'react';
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
}

export interface UseResultsFiltersOutput {
  filtered: MatchResult[];
  paginated: MatchResult[];
  totalPages: number;
}

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
}: UseResultsFiltersInput): UseResultsFiltersOutput {
  const filtered = useMemo(() => {
    if (!data?.results) return [];
    let results: MatchResult[];

    if (activeTab === 'starred') {
      results = data.results.filter((m) => favs.has(m.opportunity.id));
    } else if (activeTab === 'all') {
      results = data.results.filter((m) => m.bucket !== 'low_fit');
    } else {
      results = data.results.filter((m) => m.bucket === activeTab);
    }

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
      results = results.filter((m) =>
        filters.intl === 'yes'
          ? m.opportunity.eligibility.international_friendly === 'yes'
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
      results = results.filter((m) => m.final_score >= filters.minScore);
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
  }, [data, activeTab, debouncedQuery, filters, favs, sortBy, interactions, showDismissed]);

  const totalPages = Math.ceil(filtered.length / pageSize);
  const paginated = useMemo(
    () => filtered.slice((page - 1) * pageSize, page * pageSize),
    [filtered, page, pageSize],
  );

  return { filtered, paginated, totalPages };
}
