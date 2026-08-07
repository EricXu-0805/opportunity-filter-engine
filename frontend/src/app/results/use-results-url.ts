'use client';

import { useEffect } from 'react';
import type { ReadonlyURLSearchParams } from 'next/navigation';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { readUserScopedRaw } from '@/lib/identity-owner';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import { DEFAULT_FILTERS, type Filters, type SortKey, type Tab } from './types';

// Pure reader for the URL → initial-state hydration that runs once on mount
// of /results. Keys MUST stay in sync with the writer below AND with
// lib/saved-searches.ts:savedSearchToUrl — that helper builds the URL the
// /favorites "Apply saved search" link points back to.
//
// R69-A: default tab is 'high_priority' (was 'all'). Rationale: the "All" tab
// dilutes the user's high-signal matches with mid/low-fit results — first-time
// visitors saw Math fellowships before their top CS/CV picks. "High Priority"
// (bucket === 'high_priority') is what they actually came for. URL omit
// sentinel moves in lock-step: `?tab=high_priority` is omitted, every other
// tab (including the explicit 'all') round-trips through the URL so deep
// links, saved searches, and bookmarks stay deterministic.
export function readInitialFiltersFromUrl(
  searchParams: URLSearchParams | ReadonlyURLSearchParams,
): {
  activeTab: Tab;
  searchQuery: string;
  filters: Filters;
  sortBy: SortKey;
} {
  const allow = <T extends string>(
    raw: string | null,
    values: readonly T[],
    fallback: T,
  ): T => (raw !== null && values.includes(raw as T) ? raw as T : fallback);
  const rawMinScore = Number(searchParams.get('min') || 0);
  const minScore = Number.isFinite(rawMinScore)
    ? Math.min(100, Math.max(0, Math.trunc(rawMinScore)))
    : 0;

  return {
    activeTab: allow<Tab>(
      searchParams.get('tab'),
      ['all', 'high_priority', 'good_match', 'reach', 'starred'],
      'high_priority',
    ),
    searchQuery: (searchParams.get('q') || '').slice(0, 200),
    filters: {
      paid: allow(searchParams.get('paid'), ['', 'yes', 'no'], ''),
      intl: allow(searchParams.get('intl'), ['', 'yes', 'no'], ''),
      source: (searchParams.get('source') || '').slice(0, 100),
      onCampus: allow(searchParams.get('loc'), ['', 'yes', 'no'], ''),
      deadline: allow(
        searchParams.get('dl'),
        ['', '7', '14', '30', 'passed'],
        '',
      ),
      minScore,
      scope: allow(searchParams.get('scope'), ['', 'campus', 'open'], ''),
    },
    sortBy: allow<SortKey>(
      searchParams.get('sort'),
      ['score', 'deadline', 'newest'],
      'score',
    ),
  };
}

// AI-refine state fails closed before consulting URL or localStorage. Once the
// feature passes acceptance, the dormant branch below preserves explicit URL
// then saved-preference resolution; until then deterministic is unconditional.
// Kept separate from readInitialFiltersFromUrl because it consults
// localStorage too — the filters reader is pure URL.
export function readInitialSemanticRerank(
  searchParams: URLSearchParams | ReadonlyURLSearchParams,
): boolean {
  if (!RELEASE_SCOPE.matchAiRefine) return false;
  const p = searchParams.get('ai');
  if (p === '1') return true;
  if (p === '0') return false;
  const stored = readUserScopedRaw(STORAGE_KEYS.SEMANTIC_RERANK);
  if (stored === '0') return false;
  if (stored === '1') return true;
  return false;
}

// URL writer. Uses history.replaceState (not router.replace) to avoid
// triggering a Next.js navigation on every filter tick — the URL bar
// stays in sync but no remount fires. Excludes ?highlight= and
// ?savedSearchId= intentionally: those are mount-once params consumed by
// useHighlightSet / useSavedSearchAck and self-clear on the first edit
// (cross-file contract documented in lib/saved-searches.ts:189).
export function useResultsUrlSync(state: {
  activeTab: Tab;
  debouncedQuery: string;
  filters: Filters;
  sortBy: SortKey;
  semanticRerank: boolean;
}): void {
  const { activeTab, debouncedQuery, filters, sortBy, semanticRerank } = state;
  useEffect(() => {
    const params = new URLSearchParams();
    // R69-A: omit-sentinel is 'high_priority' (the new default). Every other
    // tab — including 'all' — must round-trip through the URL so /favorites
    // "Apply saved search" deep links land on the tab the user saved.
    if (activeTab !== 'high_priority') params.set('tab', activeTab);
    if (debouncedQuery) params.set('q', debouncedQuery);
    if (filters.paid) params.set('paid', filters.paid);
    if (filters.intl) params.set('intl', filters.intl);
    if (filters.source) params.set('source', filters.source);
    if (filters.onCampus) params.set('loc', filters.onCampus);
    if (filters.deadline) params.set('dl', filters.deadline);
    if (filters.minScore > 0) params.set('min', String(filters.minScore));
    if (filters.scope) params.set('scope', filters.scope);
    if (sortBy !== 'score') params.set('sort', sortBy);
    // Only an accepted AI-refine release may serialize its state into a
    // shareable URL. Dormant-feature query params are removed.
    if (RELEASE_SCOPE.matchAiRefine) {
      params.set('ai', semanticRerank ? '1' : '0');
    }
    const qs = params.toString();
    const newUrl = qs ? `/results?${qs}` : '/results';
    window.history.replaceState(null, '', newUrl);
  }, [activeTab, debouncedQuery, filters, sortBy, semanticRerank]);
}

export { DEFAULT_FILTERS };
