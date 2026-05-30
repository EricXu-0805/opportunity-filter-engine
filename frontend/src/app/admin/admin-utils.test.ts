import { describe, expect, it } from 'vitest';
import { diff, humanAge } from './admin-utils';
import type { AdminResponse, HistoryEntry, TFunc } from './types';

const t: TFunc = (key, vars) => {
  if (vars && 'n' in vars) return `${key}:${vars.n}`;
  return key;
};

const baseResponse = (overrides: Partial<AdminResponse['global']> = {}): AdminResponse => ({
  total: 1000,
  global: { empty_majors: 10, empty_keywords: 20, ...overrides },
  sources: [],
  worst_fields: [],
  generated_at: '2025-01-01T00:00:00Z',
});

describe('diff', () => {
  it('returns null when previous is null', () => {
    expect(diff('empty_majors', baseResponse(), null)).toBeNull();
  });

  it('returns null when previous value is missing', () => {
    const prev: HistoryEntry = { t: '', total: 0 };
    expect(diff('empty_majors', baseResponse(), prev)).toBeNull();
  });

  it('returns null when previous value is not a number', () => {
    const prev = { t: '', total: 0, empty_majors: 'oops' } as unknown as HistoryEntry;
    expect(diff('empty_majors', baseResponse(), prev)).toBeNull();
  });

  it('returns positive delta when current is larger', () => {
    const prev: HistoryEntry = { t: '', total: 0, empty_majors: 5 };
    expect(diff('empty_majors', baseResponse({ empty_majors: 10 }), prev)).toBe(5);
  });

  it('returns negative delta when current is smaller', () => {
    const prev: HistoryEntry = { t: '', total: 0, empty_majors: 30 };
    expect(diff('empty_majors', baseResponse({ empty_majors: 10 }), prev)).toBe(-20);
  });

  it('treats missing current key as zero', () => {
    const prev: HistoryEntry = { t: '', total: 0, empty_majors: 7 };
    const resp = baseResponse();
    delete (resp.global as Record<string, number>).empty_majors;
    expect(diff('empty_majors', resp, prev)).toBe(-7);
  });
});

describe('humanAge', () => {
  it('renders "just now" for sub-minute durations', () => {
    expect(humanAge(0.0001, t)).toBe('admin.freshness.justNow');
  });

  it('renders minutes between 1 minute and 1 hour', () => {
    expect(humanAge(0.5, t)).toBe('admin.freshness.minutesAgo:30');
  });

  it('renders hours between 1 and 48 hours', () => {
    expect(humanAge(5, t)).toBe('admin.freshness.hoursAgo:5');
    expect(humanAge(47.4, t)).toBe('admin.freshness.hoursAgo:47');
  });

  it('renders days at and beyond 48 hours', () => {
    expect(humanAge(48, t)).toBe('admin.freshness.daysAgo:2');
    expect(humanAge(120, t)).toBe('admin.freshness.daysAgo:5');
  });

  it('rounds bucket boundaries correctly', () => {
    expect(humanAge(0.999, t)).toBe('admin.freshness.minutesAgo:60');
    expect(humanAge(1, t)).toBe('admin.freshness.hoursAgo:1');
  });
});
