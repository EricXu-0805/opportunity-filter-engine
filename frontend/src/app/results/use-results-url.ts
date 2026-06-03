'use client';

import { useEffect } from 'react';
import type { ReadonlyURLSearchParams } from 'next/navigation';
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
  return {
    activeTab: (searchParams.get('tab') as Tab) || 'high_priority',
    searchQuery: searchParams.get('q') || '',
    filters: {
      paid: (searchParams.get('paid') || '') as Filters['paid'],
      intl: (searchParams.get('intl') || '') as Filters['intl'],
      source: (searchParams.get('source') || '') as Filters['source'],
      onCampus: (searchParams.get('loc') || '') as Filters['onCampus'],
      deadline: (searchParams.get('dl') || '') as Filters['deadline'],
      minScore: Number(searchParams.get('min') || 0),
    },
    sortBy: (searchParams.get('sort') as SortKey) || 'score',
  };
}

// AI/semantic-rerank toggle resolution order:
//   1. ?ai=1 / ?ai=0 in URL (explicit, wins for shareable URLs)
//   2. localStorage 'ofe_semantic_rerank' = '1' / '0' (user preference)
//   3. Default to false (semantic off). The blend in semantic_rerank mixes a
//      0-0.6 cosine similarity (scaled x100) at weight 0.5, which compresses
//      a 91 rule score to ~76 and can float generic-keyword matches above
//      topically specific ones. The rule ranking is accurate, so it is the
//      default; the toggle stays for opt-in experimentation.
// Kept separate from readInitialFiltersFromUrl because it consults
// localStorage too — the filters reader is pure URL.
export function readInitialSemanticRerank(
  searchParams: URLSearchParams | ReadonlyURLSearchParams,
): boolean {
  const p = searchParams.get('ai');
  if (p === '1') return true;
  if (p === '0') return false;
  if (typeof window === 'undefined') return false;
  const stored = localStorage.getItem('ofe_semantic_rerank');
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
    if (sortBy !== 'score') params.set('sort', sortBy);
    if (!semanticRerank) params.set('ai', '0');
    const qs = params.toString();
    const newUrl = qs ? `/results?${qs}` : '/results';
    window.history.replaceState(null, '', newUrl);
  }, [activeTab, debouncedQuery, filters, sortBy, semanticRerank]);
}

export { DEFAULT_FILTERS };
