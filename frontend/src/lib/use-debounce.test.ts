import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useDebounce } from './use-debounce';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useDebounce', () => {
  it('returns the initial value synchronously', () => {
    const { result } = renderHook(() => useDebounce('hello', 250));
    expect(result.current).toBe('hello');
  });

  it('does not update until the delay has elapsed', () => {
    const { result, rerender } = renderHook(({ v }) => useDebounce(v, 250), {
      initialProps: { v: 'a' },
    });
    expect(result.current).toBe('a');

    rerender({ v: 'b' });
    expect(result.current).toBe('a');

    act(() => {
      vi.advanceTimersByTime(249);
    });
    expect(result.current).toBe('a');

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe('b');
  });

  it('resets the timer if the value changes again before the delay', () => {
    const { result, rerender } = renderHook(({ v }) => useDebounce(v, 100), {
      initialProps: { v: 'first' },
    });

    rerender({ v: 'second' });
    act(() => {
      vi.advanceTimersByTime(80);
    });
    expect(result.current).toBe('first');

    rerender({ v: 'third' });
    act(() => {
      vi.advanceTimersByTime(80);
    });
    expect(result.current).toBe('first');

    act(() => {
      vi.advanceTimersByTime(20);
    });
    expect(result.current).toBe('third');
  });

  it('supports a delay of 0 (flushes on the next tick)', () => {
    const { result, rerender } = renderHook(({ v }) => useDebounce(v, 0), {
      initialProps: { v: 1 },
    });

    rerender({ v: 2 });
    expect(result.current).toBe(1);

    act(() => {
      vi.advanceTimersByTime(0);
    });
    expect(result.current).toBe(2);
  });

  it('works with non-string types (numbers, objects)', () => {
    const obj1 = { a: 1 };
    const obj2 = { a: 2 };
    const { result, rerender } = renderHook(({ v }: { v: { a: number } }) => useDebounce(v, 50), {
      initialProps: { v: obj1 },
    });

    rerender({ v: obj2 });
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(result.current).toBe(obj2);
  });

  it('cancels the pending timer on unmount', () => {
    const { rerender, unmount } = renderHook(({ v }) => useDebounce(v, 200), {
      initialProps: { v: 'x' },
    });
    rerender({ v: 'y' });
    unmount();
    expect(() => {
      vi.advanceTimersByTime(200);
    }).not.toThrow();
  });
});
