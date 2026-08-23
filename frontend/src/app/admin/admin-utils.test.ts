import { describe, expect, it } from 'vitest';
import {
  diff, findPreviousSnapshot, humanAge, listingPct, listingScopedHistory,
} from './admin-utils';
import { QUALITY_SCOPE } from './types';
import type { AdminResponse, HistoryEntry, TFunc } from './types';

const t: TFunc = (key, vars) => {
  if (vars && 'n' in vars) return `${key}:${vars.n}`;
  return key;
};

// Every comparison helper now requires the scope marker on BOTH sides — a
// legacy payload carries `listing_total` as well, it just counted unreviewed
// records inside it. These builders make the marker explicit so a test that
// means "legacy" has to say so.
const baseResponse = (overrides: Partial<AdminResponse['global']> = {}): AdminResponse => ({
  total: 1000,
  quality_scope: QUALITY_SCOPE,
  global: { listing_total: 1000, empty_majors: 10, empty_keywords: 20, ...overrides },
  sources: [],
  worst_fields: [],
  generated_at: '2025-01-01T00:00:00Z',
});

/** A history entry in the current scope. */
const scoped = (entry: Omit<HistoryEntry, 'quality_scope'>): HistoryEntry =>
  ({ ...entry, quality_scope: QUALITY_SCOPE });

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
    const prev: HistoryEntry = scoped({ t: '', total: 1000, listing_total: 1000, empty_majors: 5 });
    expect(diff('empty_majors', baseResponse({ empty_majors: 10 }), prev)).toBe(5);
  });

  it('returns negative delta when current is smaller', () => {
    const prev: HistoryEntry = scoped({ t: '', total: 1000, listing_total: 1000, empty_majors: 30 });
    expect(diff('empty_majors', baseResponse({ empty_majors: 10 }), prev)).toBe(-20);
  });

  it('treats missing current key as zero', () => {
    const prev: HistoryEntry = scoped({ t: '', total: 1000, listing_total: 1000, empty_majors: 7 });
    const resp = baseResponse();
    delete (resp.global as Record<string, number>).empty_majors;
    expect(diff('empty_majors', resp, prev)).toBe(-7);
  });

  it('does not compare a listing metric with a legacy mixed-scope snapshot', () => {
    const current = baseResponse({ listing_total: 2, missing_deadline: 1 });
    const legacy: HistoryEntry = { t: '', total: 20, missing_deadline: 1 };
    expect(diff('missing_deadline', current, legacy)).toBeNull();
  });

  it('compares listing metrics when both snapshots are in the current scope', () => {
    const current = baseResponse({ listing_total: 2, missing_deadline: 1 });
    const previous = scoped({ t: '', total: 20, listing_total: 2, missing_deadline: 0 });
    expect(diff('missing_deadline', current, previous)).toBe(1);
  });

  it('refuses a legacy CURRENT response even against a current-scope history entry', () => {
    // The direction a rollback produces: an old backend answering while the
    // disk still holds new-scope history.
    const current = baseResponse({ listing_total: 2, missing_deadline: 1 });
    delete current.quality_scope;
    const previous = scoped({ t: '', total: 20, listing_total: 2, missing_deadline: 0 });
    expect(diff('missing_deadline', current, previous)).toBeNull();
  });

  it('refuses a scope marker this build does not know', () => {
    // A future scope is not the current one, and a build that cannot say what
    // changed must not pretend the numbers line up.
    const current = { ...baseResponse({ listing_total: 2, missing_deadline: 1 }), quality_scope: 'reviewed-record-kind-v2' };
    const previous = scoped({ t: '', total: 20, listing_total: 2, missing_deadline: 0 });
    expect(diff('missing_deadline', current, previous)).toBeNull();
    expect(diff('missing_deadline', baseResponse({ listing_total: 2, missing_deadline: 1 }), {
      ...previous, quality_scope: 'reviewed-record-kind-v2',
    })).toBeNull();
  });

  it('refuses a correctly-marked snapshot that is missing the denominator', () => {
    // The marker is necessary, not sufficient — a truncated or partial
    // payload can carry it and still have no listing_total to divide by.
    const current = baseResponse({ missing_deadline: 1 });
    delete (current.global as Record<string, number>).listing_total;
    expect(diff('missing_deadline', current, scoped({
      t: '', total: 20, listing_total: 2, missing_deadline: 0,
    }))).toBeNull();
    expect(diff('missing_deadline', baseResponse({ listing_total: 2, missing_deadline: 1 }), scoped({
      t: '', total: 20, missing_deadline: 0,
    }))).toBeNull();
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
    quality_scope: QUALITY_SCOPE,
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

  it('omits the percentage for a legacy response that still carries listing_total', () => {
    // The case the field-presence check could never catch: an old backend
    // ships the denominator, it just counted unreviewed records inside it.
    const data = real();
    delete data.quality_scope;
    expect(listingPct('empty_majors', data)).toBeUndefined();
  });

  it('omits the percentage for a FUTURE marker, not just a missing one', () => {
    // Exact equality, not truthiness. A later scope will also ship a
    // denominator and a marker; this build cannot say what changed between
    // them, so it must not divide one by the other.
    expect(listingPct('empty_majors', {
      ...real(), quality_scope: 'reviewed-record-kind-v2',
    })).toBeUndefined();
  });

  it('drops legacy and malformed history before plotting a listing trend', () => {
    // Legacy: has the denominator but not the marker. Malformed: has the
    // marker but no denominator — plotting it would draw a cliff to zero
    // that never happened in the data.
    const legacy: HistoryEntry = { t: 'old', total: 20, listing_total: 2, missing_deadline: 1 };
    const malformed: HistoryEntry = {
      t: 'broken', total: 20, missing_deadline: 1, quality_scope: QUALITY_SCOPE,
    };
    // Complete in every way except that its marker is a scope this build does
    // not know. Included so relaxing the exact check to "marker is truthy"
    // cannot pass.
    const future: HistoryEntry = {
      t: 'future', total: 20, listing_total: 2, missing_deadline: 1,
      quality_scope: 'reviewed-record-kind-v2',
    };
    const scoped: HistoryEntry = {
      t: 'new', total: 20, listing_total: 2, missing_deadline: 1, quality_scope: QUALITY_SCOPE,
    };
    expect(listingScopedHistory([legacy, malformed, future, scoped])).toEqual([scoped]);
  });
});

describe('findPreviousSnapshot', () => {
  // `data` and `history` are fetched together, and the backend appends at
  // most one history entry per hour — so the current snapshot is sometimes
  // already the last row and sometimes not. An index-based answer means two
  // different things in those two cases.
  const at = (iso: string, extra: Partial<HistoryEntry> = {}): HistoryEntry => scoped({
    t: iso, total: 20, listing_total: 2, missing_deadline: 1, ...extra,
  });
  const current = (generatedAt: string, scopeOverride?: string | null): AdminResponse => {
    const response = { ...baseResponse(), generated_at: generatedAt };
    if (scopeOverride === null) delete response.quality_scope;
    else if (scopeOverride) response.quality_scope = scopeOverride;
    return response;
  };

  const older = at('2026-08-01T00:00:00Z');
  const previous = at('2026-08-02T00:00:00Z');
  const now = '2026-08-03T00:00:00Z';

  it('picks the last entry strictly before the current snapshot', () => {
    expect(findPreviousSnapshot([older, previous], current(now))).toEqual(previous);
  });

  it('skips the current snapshot when the backend already appended it', () => {
    // Same timestamp = the same snapshot. Comparing it with itself reports
    // "no change" on a board whose whole job is to show change.
    const self = at(now);
    expect(findPreviousSnapshot([older, previous, self], current(now))).toEqual(previous);
  });

  it('is not fooled by an entry appended after the current snapshot', () => {
    // A concurrent write, or a history response fetched a beat later.
    const newer = at('2026-08-04T00:00:00Z');
    expect(findPreviousSnapshot([previous, newer], current(now))).toEqual(previous);
  });

  it('skips legacy and malformed rows on the way back', () => {
    const legacy: HistoryEntry = { t: '2026-08-02T12:00:00Z', total: 20, listing_total: 2 };
    const malformed = scoped({ t: '2026-08-02T18:00:00Z', total: 20 });
    expect(findPreviousSnapshot([previous, legacy, malformed], current(now)))
      .toEqual(previous);
  });

  it.each([
    ['a legacy current response', null],
    ['a future scope', 'reviewed-record-kind-v2'],
  ])('returns null for %s, however much history exists', (_, scope) => {
    expect(findPreviousSnapshot([older, previous], current(now, scope))).toBeNull();
  });

  it('returns null when the current snapshot has no parseable time', () => {
    // No "now" to measure from. Falling back to an index would invent a
    // delta out of whichever row happened to sit second from the end.
    expect(findPreviousSnapshot([older, previous], current('not-a-date'))).toBeNull();
  });

  it('returns null when nothing precedes the current snapshot', () => {
    expect(findPreviousSnapshot([at('2026-08-05T00:00:00Z')], current(now))).toBeNull();
    expect(findPreviousSnapshot([], current(now))).toBeNull();
  });
});
