import { describe, it, expect } from 'vitest';
import {
  FEATURED_FETCH_POOL,
  FEATURED_PREVIEW_LIMIT,
  compareUrgency,
  isPastDeadline,
  rankFeaturedFellowships,
} from './featured-fellowships-rank';
import type { Opportunity } from '@/lib/types';

const NOW = new Date('2026-06-01T12:00:00Z');
const PAST = '2026-05-31';
const TODAY = '2026-06-01';
const SOON = '2026-06-10';
const LATER = '2026-08-15';
const FAR = '2027-01-20';

function opp(id: string, deadline?: string): Opportunity {
  return {
    id,
    title: id,
    organization: 'org',
    opportunity_type: 'summer_program',
    paid: 'no',
    location: 'Urbana',
    on_campus: true,
    deadline,
    description_clean: '',
    keywords: [],
    eligibility: {
      international_friendly: 'no',
      preferred_year: [],
      majors: [],
      skills_required: [],
      citizenship_required: false,
    },
    application: { application_effort: 'medium', requires_resume: 'no', contact_method: 'email' },
    metadata: { is_active: true, confidence_score: 0.9 },
  };
}

describe('isPastDeadline', () => {
  it('returns false when deadline is undefined (rolling)', () => {
    expect(isPastDeadline(undefined, NOW)).toBe(false);
  });

  it('returns false when deadline is malformed (best-effort, do not hide)', () => {
    expect(isPastDeadline('not-a-date', NOW)).toBe(false);
  });

  it('returns false when deadline is exactly today (same calendar day is still open)', () => {
    expect(isPastDeadline(TODAY, NOW)).toBe(false);
  });

  it('returns true when deadline is the day before today', () => {
    expect(isPastDeadline(PAST, NOW)).toBe(true);
  });

  it('returns false when deadline is in the future', () => {
    expect(isPastDeadline(FAR, NOW)).toBe(false);
  });
});

describe('compareUrgency', () => {
  it('places dated opportunities before undated', () => {
    expect(compareUrgency(opp('a', SOON), opp('b'))).toBeLessThan(0);
    expect(compareUrgency(opp('a'), opp('b', SOON))).toBeGreaterThan(0);
  });

  it('treats two undated opportunities as equal (stable insertion order)', () => {
    expect(compareUrgency(opp('a'), opp('b'))).toBe(0);
  });

  it('orders two dated opportunities soonest first', () => {
    expect(compareUrgency(opp('a', SOON), opp('b', LATER))).toBeLessThan(0);
    expect(compareUrgency(opp('a', FAR), opp('b', SOON))).toBeGreaterThan(0);
  });

  it('treats malformed-deadline opportunities as less urgent than valid ones', () => {
    expect(compareUrgency(opp('a', 'garbage'), opp('b', SOON))).toBeGreaterThan(0);
    expect(compareUrgency(opp('a', SOON), opp('b', 'garbage'))).toBeLessThan(0);
  });
});

describe('rankFeaturedFellowships', () => {
  it('returns an empty list when the input is empty', () => {
    expect(rankFeaturedFellowships([], NOW)).toEqual([]);
  });

  it('filters out opportunities whose deadline is in the past', () => {
    const ranked = rankFeaturedFellowships(
      [opp('past', PAST), opp('soon', SOON), opp('rolling')],
      NOW,
    );
    expect(ranked.map((o) => o.id)).toEqual(['soon', 'rolling']);
  });

  it('keeps the same-day deadline (boundary: today is still open)', () => {
    const ranked = rankFeaturedFellowships(
      [opp('today', TODAY), opp('past', PAST)],
      NOW,
    );
    expect(ranked.map((o) => o.id)).toEqual(['today']);
  });

  it('sorts the surviving opportunities by urgency (soonest first), undated last', () => {
    const ranked = rankFeaturedFellowships(
      [opp('rolling'), opp('far', FAR), opp('soon', SOON), opp('later', LATER)],
      NOW,
    );
    expect(ranked.map((o) => o.id)).toEqual(['soon', 'later', 'far']);
  });

  it('caps the result at the preview limit (default 3)', () => {
    const ranked = rankFeaturedFellowships(
      [
        opp('a', '2026-07-01'),
        opp('b', '2026-07-02'),
        opp('c', '2026-07-03'),
        opp('d', '2026-07-04'),
        opp('e', '2026-07-05'),
      ],
      NOW,
    );
    expect(ranked.map((o) => o.id)).toEqual(['a', 'b', 'c']);
    expect(ranked).toHaveLength(FEATURED_PREVIEW_LIMIT);
  });

  it('respects a caller-supplied limit override', () => {
    const ranked = rankFeaturedFellowships(
      [opp('a', '2026-07-01'), opp('b', '2026-07-02'), opp('c', '2026-07-03')],
      NOW,
      1,
    );
    expect(ranked.map((o) => o.id)).toEqual(['a']);
  });

  it('does not mutate the input array', () => {
    const input = [opp('far', FAR), opp('soon', SOON)];
    const snapshot = input.map((o) => o.id);
    rankFeaturedFellowships(input, NOW);
    expect(input.map((o) => o.id)).toEqual(snapshot);
  });

  it('exports a fetch-pool constant >= preview limit so the filter has room to work', () => {
    expect(FEATURED_FETCH_POOL).toBeGreaterThanOrEqual(FEATURED_PREVIEW_LIMIT);
  });
});
