import { describe, expect, it } from 'vitest';
import { diff, humanAge, listingPct, listingScopedHistory } from './admin-utils';
import type { AdminResponse, HistoryEntry, TFunc } from './types';

const t: TFunc = (key, vars) => {
  if (vars && 'n' in vars) return `${key}:${vars.n}`;
  return key;
};

const baseResponse = (overrides: Partial<AdminResponse['global']> = {}): AdminResponse => ({
  total: 1000,
  global: { listing_total: 1000, empty_majors: 10, empty_keywords: 20, ...overrides },
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
    const prev: HistoryEntry = { t: '', total: 1000, listing_total: 1000, empty_majors: 5 };
    expect(diff('empty_majors', baseResponse({ empty_majors: 10 }), prev)).toBe(5);
  });

  it('returns negative delta when current is smaller', () => {
    const prev: HistoryEntry = { t: '', total: 1000, listing_total: 1000, empty_majors: 30 };
    expect(diff('empty_majors', baseResponse({ empty_majors: 10 }), prev)).toBe(-20);
  });

  it('treats missing current key as zero', () => {
    const prev: HistoryEntry = { t: '', total: 1000, listing_total: 1000, empty_majors: 7 };
    const resp = baseResponse();
    delete (resp.global as Record<string, number>).empty_majors;
    expect(diff('empty_majors', resp, prev)).toBe(-7);
  });

  it('does not compare a listing metric with a legacy mixed-scope snapshot', () => {
    const current = baseResponse({ listing_total: 2, missing_deadline: 1 });
    const legacy: HistoryEntry = { t: '', total: 20, missing_deadline: 1 };
    expect(diff('missing_deadline', current, legacy)).toBeNull();
  });

  it('compares listing metrics when both snapshots carry listing_total', () => {
    const current = baseResponse({ listing_total: 2, missing_deadline: 1 });
    const previous: HistoryEntry = {
      t: '', total: 20, listing_total: 2, missing_deadline: 0,
    };
    expect(diff('missing_deadline', current, previous)).toBe(1);
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


describe('listingPct', () => {
  // The served corpus is 127,885 faculty contact profiles vs 7,427 listings.
  // The backend excludes faculty rows from these counters and ships the right
  // denominator as global.listing_total; dividing by `total` instead reports
  // every defect rate ~18x lower than it is, on the dashboard used to judge
  // whether the data is fit to ship.
  const real = (): AdminResponse => ({
    total: 135312,
    global: { listing_total: 7427, empty_majors: 1000 },
    sources: [],
    worst_fields: [],
    generated_at: '2026-08-19T00:00:00Z',
  });

  it('divides a listing-only counter by the listing denominator', () => {
    expect(listingPct('empty_majors', real())).toBeCloseTo(13.46, 1);
  });

  it('omits the percentage when the backend ships no listing_total', () => {
    const data = real();
    delete data.global.listing_total;
    expect(listingPct('empty_majors', data)).toBeUndefined();
  });

  it('omits the percentage when the listing denominator is zero', () => {
    const data = real();
    data.global.listing_total = 0;
    data.total = 0;
    expect(listingPct('empty_majors', data)).toBeUndefined();
  });

  it('returns 0 for a counter the backend did not send', () => {
    expect(listingPct('missing_deadline', real())).toBe(0);
  });

  it('uses the requested 20 total / 2 listing / 1 missing denominator', () => {
    const data = real();
    data.total = 20;
    data.global.listing_total = 2;
    data.global.missing_deadline = 1;
    expect(listingPct('missing_deadline', data)).toBe(50);
  });

  it('drops legacy mixed-scope history before plotting a listing trend', () => {
    const legacy: HistoryEntry = { t: 'old', total: 20, missing_deadline: 1 };
    const scoped: HistoryEntry = {
      t: 'new', total: 20, listing_total: 2, missing_deadline: 1,
    };
    expect(listingScopedHistory([legacy, scoped])).toEqual([scoped]);
  });
});
