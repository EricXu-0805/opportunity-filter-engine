import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { formatRelativeAge, translateKey } from './home-utils';
import type { TFunc } from './types';

const NOW = new Date('2026-01-15T12:00:00Z').getTime();

beforeAll(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

afterAll(() => {
  vi.useRealTimers();
});

describe('formatRelativeAge', () => {
  it('returns "just now" for sub-minute ages', () => {
    expect(formatRelativeAge(new Date(NOW - 5000).toISOString())).toBe('just now');
  });

  it('returns "Nm ago" for minute ages', () => {
    expect(formatRelativeAge(new Date(NOW - 5 * 60 * 1000).toISOString())).toBe('5m ago');
  });

  it('returns "Nh ago" for hour ages', () => {
    expect(formatRelativeAge(new Date(NOW - 3 * 3600 * 1000).toISOString())).toBe('3h ago');
  });

  it('returns "Nd ago" for day ages', () => {
    expect(formatRelativeAge(new Date(NOW - 2 * 86400 * 1000).toISOString())).toBe('2d ago');
  });

  it('returns empty string on invalid input', () => {
    expect(formatRelativeAge('not-a-date')).toBe('');
  });

  it('floors negative durations to "just now"', () => {
    expect(formatRelativeAge(new Date(NOW + 5000).toISOString())).toBe('just now');
  });
});

describe('translateKey', () => {
  const t: TFunc = (key) => {
    if (key === 'majors.CS') return 'Computer Science';
    return key;
  };

  it('returns the translation when one exists', () => {
    expect(translateKey(t, 'majors', 'CS')).toBe('Computer Science');
  });

  it('falls back to the raw name when no translation exists', () => {
    expect(translateKey(t, 'colleges', 'Unknown School')).toBe('Unknown School');
  });

  it('combines namespace and name with a dot', () => {
    const captured: string[] = [];
    const spy: TFunc = (key) => {
      captured.push(key);
      return key;
    };
    translateKey(spy, 'grades', 'Sophomore');
    expect(captured[0]).toBe('grades.Sophomore');
  });
});
