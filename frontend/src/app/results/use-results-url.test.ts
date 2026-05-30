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
    });
    expect(result.searchQuery).toBe('');
    expect(result.sortBy).toBe('score');
  });

  it('hydrates filters from URL keys (loc/dl/min round-trip)', () => {
    const result = readInitialFiltersFromUrl(
      new URLSearchParams('paid=yes&intl=no&source=uiuc_faculty&loc=yes&dl=14&min=70&sort=deadline&q=ml'),
    );
    expect(result.filters).toEqual({
      paid: 'yes',
      intl: 'no',
      source: 'uiuc_faculty',
      onCampus: 'yes',
      deadline: '14',
      minScore: 70,
    });
    expect(result.sortBy).toBe('deadline');
    expect(result.searchQuery).toBe('ml');
  });
});

describe('readInitialSemanticRerank', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('prefers ?ai=1 over localStorage', () => {
    localStorage.setItem('ofe_semantic_rerank', '0');
    expect(readInitialSemanticRerank(new URLSearchParams('ai=1'))).toBe(true);
  });

  it('prefers ?ai=0 over localStorage', () => {
    localStorage.setItem('ofe_semantic_rerank', '1');
    expect(readInitialSemanticRerank(new URLSearchParams('ai=0'))).toBe(false);
  });

  it('falls back to localStorage when no ?ai param', () => {
    localStorage.setItem('ofe_semantic_rerank', '0');
    expect(readInitialSemanticRerank(new URLSearchParams(''))).toBe(false);
  });

  it('defaults to true when neither URL nor localStorage present', () => {
    expect(readInitialSemanticRerank(new URLSearchParams(''))).toBe(true);
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
    },
    sortBy: 'score' as const,
    semanticRerank: true,
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
    expect(url).toContain('ai=0');
  });

  it('emits ai=0 only when semantic is off', () => {
    renderHook(() => useResultsUrlSync({ ...EMPTY_STATE, semanticRerank: false }));
    expect(lastUrl()).toBe('/results?ai=0');
  });

  it('omits ai param when semantic is on (the default)', () => {
    renderHook(() => useResultsUrlSync(EMPTY_STATE));
    expect(lastUrl()).toBe('/results');
  });
});
