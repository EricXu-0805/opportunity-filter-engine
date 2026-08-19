/* @vitest-environment jsdom */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import {
  readInitialFiltersFromUrl,
  readSemanticRerankUrlPin,
  resolveSemanticRerank,
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

describe('readSemanticRerankUrlPin', () => {
  it('reads explicit values only after the feature is accepted', () => {
    expect(readSemanticRerankUrlPin(new URLSearchParams('ai=1'), true)).toBe(true);
    expect(readSemanticRerankUrlPin(new URLSearchParams('ai=0'), true)).toBe(false);
    expect(readSemanticRerankUrlPin(new URLSearchParams(''), true)).toBe(null);
    expect(readSemanticRerankUrlPin(new URLSearchParams('ai=yes'), true)).toBe(null);
    expect(readSemanticRerankUrlPin(new URLSearchParams('ai=1'), false)).toBe(null);
  });
});

describe('resolveSemanticRerank', () => {
  it('lets the URL win over the stored preference in both directions', () => {
    // A share link has to reproduce what the sender saw, not what the recipient
    // last chose.
    expect(resolveSemanticRerank(true, true, '0', true)).toBe(true);
    expect(resolveSemanticRerank(false, true, '1', true)).toBe(false);
  });

  it('keeps the deterministic default when the student has never chosen', () => {
    expect(resolveSemanticRerank(null, false, null, true)).toBe(false);
  });

  it('honors a stored choice in both directions', () => {
    expect(resolveSemanticRerank(null, true, '0', true)).toBe(false);
    expect(resolveSemanticRerank(null, true, '1', true)).toBe(true);
  });

  it('stays off while the stored preference is unreadable', () => {
    // `undefined` is "ownership is not confirmed yet", which is not "nothing was
    // stored". Reading it as absent would turn the pass back on for a student
    // who had already opted out — and spend on them — during every first render.
    expect(resolveSemanticRerank(null, undefined, null, true)).toBe(false);
    expect(resolveSemanticRerank(null, undefined, '1', true)).toBe(false);
  });

  it('still lets an explicit URL through before the preference is readable', () => {
    expect(resolveSemanticRerank(true, undefined, null, true)).toBe(true);
  });

  it('fails closed while the release gate is closed', () => {
    expect(resolveSemanticRerank(true, true, '1', false)).toBe(false);
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
    semanticRerank: false,
    semanticSettled: true,
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

  it('removes stale AI-refine state from shareable URLs while closed', () => {
    renderHook(() => useResultsUrlSync({ ...EMPTY_STATE, semanticRerank: true }));
    expect(lastUrl()).toBe('/results');
  });

  it('writes no ?ai= at all until the preference is readable', () => {
    // The unreadable window is not an opt-out. Stamping ?ai=0 during it would
    // survive into the address bar, and the next load would read that back as
    // an explicit URL pin — a transient unknown promoted to a permanent no.
    renderHook(() => useResultsUrlSync({ ...EMPTY_STATE, semanticSettled: false }));
    expect(lastUrl()).toBe('/results');
  });

  it('still writes the other facets while the preference is unreadable', () => {
    renderHook(() => useResultsUrlSync({
      ...EMPTY_STATE,
      activeTab: 'all',
      semanticSettled: false,
    }));
    expect(lastUrl()).toBe('/results?tab=all');
  });
});
