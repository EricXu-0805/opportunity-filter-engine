/* @vitest-environment jsdom */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import {
  readInitialFiltersFromUrl,
  readInitialSemanticRerank,
  useResultsUrlSync,
} from './use-results-url';

describe('readInitialFiltersFromUrl', () => {
  it('R69-A: defaults activeTab to "high_priority" when ?tab= is absent', () => {
    const result = readInitialFiltersFromUrl(new URLSearchParams(''));
    expect(result.activeTab).toBe('high_priority');
  });

  it('R69-A: respects ?tab=all explicitly (legacy saved searches)', () => {
    // Prior to R69-A, "all" was the implicit default; saved searches stored
    // tab='all' as their no-op value. After R69-A, savedSearchToUrl explicitly
    // emits ?tab=all, and the reader must round-trip it back to 'all'.
    const result = readInitialFiltersFromUrl(new URLSearchParams('tab=all'));
    expect(result.activeTab).toBe('all');
  });

  it('respects every non-default tab', () => {
    for (const tab of ['all', 'good_match', 'reach', 'starred'] as const) {
      const result = readInitialFiltersFromUrl(new URLSearchParams(`tab=${tab}`));
      expect(result.activeTab).toBe(tab);
    }
  });

  it('returns DEFAULT_FILTERS-shaped object when URL is empty', () => {
    const result = readInitialFiltersFromUrl(new URLSearchParams(''));
    expect(result.filters).toEqual({
      paid: '',
      intl: '',
      source: '',
      onCampus: '',
      deadline: '',
      minScore: 0,
      scope: '',
    });
    expect(result.searchQuery).toBe('');
    expect(result.sortBy).toBe('score');
  });

  it('hydrates filters from URL keys (loc/dl/min/scope round-trip)', () => {
    const result = readInitialFiltersFromUrl(
      new URLSearchParams('paid=yes&intl=no&source=uiuc_faculty&loc=yes&dl=14&min=70&scope=open&sort=deadline&q=ml'),
    );
    expect(result.filters).toEqual({
      paid: 'yes',
      intl: 'no',
      source: 'uiuc_faculty',
      onCampus: 'yes',
      deadline: '14',
      minScore: 70,
      scope: 'open',
    });
    expect(result.sortBy).toBe('deadline');
    expect(result.searchQuery).toBe('ml');
  });

  it('sanitizes stale or malformed deep-link values before the strict API boundary', () => {
    const result = readInitialFiltersFromUrl(new URLSearchParams(
      `tab=wrong&paid=maybe&intl=wrong&loc=remote&dl=365&min=101.9`
      + `&scope=global&sort=popular&q=${'q'.repeat(220)}&source=${'s'.repeat(120)}`,
    ));

    expect(result.activeTab).toBe('high_priority');
    expect(result.filters).toEqual({
      paid: '',
      intl: '',
      source: 's'.repeat(100),
      onCampus: '',
      deadline: '',
      minScore: 100,
      scope: '',
    });
    expect(result.sortBy).toBe('score');
    expect(result.searchQuery).toBe('q'.repeat(200));
  });

  it.each(['abc', 'Infinity', '-1'])(
    'normalizes invalid min score %s without producing a 422 request',
    (min) => {
      const result = readInitialFiltersFromUrl(new URLSearchParams(`min=${min}`));
      expect(result.filters.minScore).toBe(0);
    },
  );
});

describe('readInitialSemanticRerank', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('ignores ?ai=1 while AI refine is outside the accepted release', () => {
    localStorage.setItem('ofe_semantic_rerank', '0');
    expect(readInitialSemanticRerank(new URLSearchParams('ai=1'))).toBe(false);
  });

  it('prefers ?ai=0 over localStorage', () => {
    localStorage.setItem('ofe_semantic_rerank', '1');
    expect(readInitialSemanticRerank(new URLSearchParams('ai=0'))).toBe(false);
  });

  it('ignores a stale enabled preference in localStorage', () => {
    localStorage.setItem('ofe_semantic_rerank', '1');
    localStorage.setItem('ofe_semantic_rerank_opt_in_v1', '1');
    expect(readInitialSemanticRerank(new URLSearchParams(''))).toBe(false);
  });

  it('defaults to deterministic matching', () => {
    expect(readInitialSemanticRerank(new URLSearchParams(''))).toBe(false);
  });
});

describe('useResultsUrlSync (R69-A omit-sentinel)', () => {
  const replaceStateSpy = vi.fn();
  let originalReplaceState: typeof window.history.replaceState;

  beforeEach(() => {
    replaceStateSpy.mockReset();
    originalReplaceState = window.history.replaceState;
    window.history.replaceState = replaceStateSpy as unknown as typeof window.history.replaceState;
  });

  afterEach(() => {
    window.history.replaceState = originalReplaceState;
  });

  function lastUrl(): string {
    const calls = replaceStateSpy.mock.calls;
    if (calls.length === 0) return '';
    const last = calls[calls.length - 1];
    return last[2] as string;
  }

  const EMPTY_STATE = {
    activeTab: 'high_priority' as const,
    debouncedQuery: '',
    filters: {
      paid: '' as const,
      intl: '' as const,
      source: '' as const,
      onCampus: '' as const,
      deadline: '' as const,
      minScore: 0,
      scope: '' as const,
    },
    sortBy: 'score' as const,
    // Deterministic matching is the accepted release path.
    semanticRerank: false,
  };

  it('omits ?tab= when activeTab is the new default "high_priority"', () => {
    renderHook(() => useResultsUrlSync(EMPTY_STATE));
    expect(lastUrl()).toBe('/results');
  });

  it('emits ?tab=all when activeTab is "all" (now an explicit, non-default tab)', () => {
    renderHook(() => useResultsUrlSync({ ...EMPTY_STATE, activeTab: 'all' }));
    expect(lastUrl()).toBe('/results?tab=all');
  });

  it('emits ?tab=starred for non-default tabs', () => {
    renderHook(() => useResultsUrlSync({ ...EMPTY_STATE, activeTab: 'starred' }));
    expect(lastUrl()).toBe('/results?tab=starred');
  });

  it('round-trips multiple state pieces in one URL', () => {
    renderHook(() => useResultsUrlSync({
      ...EMPTY_STATE,
      activeTab: 'all',
      debouncedQuery: 'nlp',
      filters: { ...EMPTY_STATE.filters, paid: 'yes', minScore: 60 },
      sortBy: 'deadline',
      semanticRerank: false,
    }));
    const url = lastUrl();
    expect(url).toContain('tab=all');
    expect(url).toContain('q=nlp');
    expect(url).toContain('paid=yes');
    expect(url).toContain('min=60');
    expect(url).toContain('sort=deadline');
    expect(url).not.toContain('ai=');
  });

  it('emits ?scope= when the discovery-scope facet is active, omits when default', () => {
    renderHook(() => useResultsUrlSync({
      ...EMPTY_STATE,
      filters: { ...EMPTY_STATE.filters, scope: 'campus' },
    }));
    expect(lastUrl()).toBe('/results?scope=campus');
  });

  it('never emits an AI-refine parameter while the feature is dormant', () => {
    renderHook(() => useResultsUrlSync({ ...EMPTY_STATE, semanticRerank: true }));
    expect(lastUrl()).toBe('/results');
  });
});
