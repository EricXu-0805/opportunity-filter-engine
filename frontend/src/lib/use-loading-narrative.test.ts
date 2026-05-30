import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useLoadingNarrative } from './use-loading-narrative';

function makeT(): (key: string, vars?: Record<string, string | number>) => string {
  return (key, vars) => {
    if (vars && 'count' in vars) return `${key}:${vars.count}`;
    return key;
  };
}

describe('useLoadingNarrative', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns the done state when not loading', () => {
    const { result } = renderHook(() =>
      useLoadingNarrative({ loading: false, semanticRerank: false, opportunityCount: 100, t: makeT() }),
    );
    expect(result.current.percent).toBe(100);
    expect(result.current.message).toBe('');
    expect(result.current.phaseIndex).toBe(-1);
  });

  it('starts at phase 0 (readingProfile) when loading begins', () => {
    const { result } = renderHook(() =>
      useLoadingNarrative({ loading: true, semanticRerank: false, opportunityCount: 0, t: makeT() }),
    );
    expect(result.current.key).toBe('readingProfile');
    expect(result.current.phaseIndex).toBe(0);
    expect(result.current.percent).toBe(15);
  });

  it('advances through 4 phases in plain mode over ~4 seconds', () => {
    const { result } = renderHook(() =>
      useLoadingNarrative({ loading: true, semanticRerank: false, opportunityCount: 1900, t: makeT() }),
    );

    expect(result.current.key).toBe('readingProfile');
    expect(result.current.percent).toBe(15);

    act(() => { vi.advanceTimersByTime(900); });
    expect(result.current.key).toBe('scanning');
    expect(result.current.message).toBe('results.loadingPhases.scanning:1900');
    expect(result.current.percent).toBe(50);

    act(() => { vi.advanceTimersByTime(1300); });
    expect(result.current.key).toBe('scoring');
    expect(result.current.percent).toBe(80);

    act(() => { vi.advanceTimersByTime(1600); });
    expect(result.current.key).toBe('polishing');
    expect(result.current.percent).toBe(95);
  });

  it('advances through 5 phases in AI mode (includes reranking step)', () => {
    const { result } = renderHook(() =>
      useLoadingNarrative({ loading: true, semanticRerank: true, opportunityCount: 1900, t: makeT() }),
    );

    expect(result.current.key).toBe('readingProfile');
    expect(result.current.percent).toBe(12);

    act(() => { vi.advanceTimersByTime(900); });
    expect(result.current.key).toBe('scanning');

    act(() => { vi.advanceTimersByTime(1300); });
    expect(result.current.key).toBe('scoring');

    act(() => { vi.advanceTimersByTime(1400); });
    expect(result.current.key).toBe('reranking');
    expect(result.current.percent).toBe(85);

    act(() => { vi.advanceTimersByTime(1600); });
    expect(result.current.key).toBe('polishing');
    expect(result.current.percent).toBe(95);
  });

  it('holds at the last phase if the response is slow to arrive', () => {
    const { result } = renderHook(() =>
      useLoadingNarrative({ loading: true, semanticRerank: false, opportunityCount: 0, t: makeT() }),
    );

    act(() => { vi.advanceTimersByTime(10_000); });
    expect(result.current.key).toBe('polishing');
    expect(result.current.percent).toBe(95);
  });

  it('jumps to 100% / empty message when loading flips to false', () => {
    const { result, rerender } = renderHook(
      ({ loading }) => useLoadingNarrative({ loading, semanticRerank: false, opportunityCount: 0, t: makeT() }),
      { initialProps: { loading: true } },
    );

    act(() => { vi.advanceTimersByTime(1200); });
    expect(result.current.key).toBe('scanning');

    rerender({ loading: false });
    expect(result.current.percent).toBe(100);
    expect(result.current.message).toBe('');
    expect(result.current.phaseIndex).toBe(-1);
  });

  it('resets to phase 0 when loading flips back true', () => {
    const { result, rerender } = renderHook(
      ({ loading }: { loading: boolean }) =>
        useLoadingNarrative({ loading, semanticRerank: false, opportunityCount: 0, t: makeT() }),
      { initialProps: { loading: true } },
    );

    act(() => { vi.advanceTimersByTime(5000); });
    expect(result.current.key).toBe('polishing');

    rerender({ loading: false });
    rerender({ loading: true });

    expect(result.current.key).toBe('readingProfile');
    expect(result.current.percent).toBe(15);
  });

  it('uses the count placeholder for the scanning phase only when count > 0', () => {
    const { result } = renderHook(() =>
      useLoadingNarrative({ loading: true, semanticRerank: false, opportunityCount: 0, t: makeT() }),
    );

    act(() => { vi.advanceTimersByTime(900); });
    expect(result.current.key).toBe('scanning');
    expect(result.current.message).toBe('results.loadingPhases.scanning');
  });

  it('respects prefers-reduced-motion by holding at phase 0', () => {
    const original = window.matchMedia;
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: (q: string) => ({
        matches: q === '(prefers-reduced-motion: reduce)',
        media: q,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as unknown as MediaQueryList,
    });

    const { result } = renderHook(() =>
      useLoadingNarrative({ loading: true, semanticRerank: true, opportunityCount: 0, t: makeT() }),
    );

    expect(result.current.key).toBe('readingProfile');

    act(() => { vi.advanceTimersByTime(10_000); });
    expect(result.current.key).toBe('readingProfile');
    expect(result.current.phaseIndex).toBe(0);

    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: original,
    });
  });

  it('cleans up timers on unmount (no orphan state updates)', () => {
    const { result, unmount } = renderHook(() =>
      useLoadingNarrative({ loading: true, semanticRerank: false, opportunityCount: 0, t: makeT() }),
    );

    expect(result.current.key).toBe('readingProfile');
    unmount();
    expect(() => { vi.advanceTimersByTime(10_000); }).not.toThrow();
  });
});
