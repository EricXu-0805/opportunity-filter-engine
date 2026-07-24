import { describe, expect, it } from 'vitest';
import type { Opportunity } from '@/lib/types';
import {
  applyFellowshipFilters,
  DEFAULT_FELLOWSHIP_FILTERS,
  fellowshipMatchesDeadline,
  fellowshipMatchesIntl,
  fellowshipMatchesPaid,
  fellowshipMatchesType,
} from './types';

function makeOpp(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'test-1',
    title: 'Sample REU',
    organization: 'Example University',
    opportunity_type: 'summer_program',
    paid: 'yes',
    location: 'off_campus',
    on_campus: false,
    description_clean: 'Summer program for undergraduates.',
    keywords: [],
    eligibility: {
      international_friendly: 'yes',
      preferred_year: ['sophomore', 'junior'],
      majors: ['CS'],
      skills_required: [],
      citizenship_required: false,
    },
    application: {
      contact_method: 'website',
      requires_resume: 'yes',
      application_effort: 'medium',
    },
    metadata: { is_active: true, confidence_score: 0.9 },
    ...overrides,
  };
}

describe('fellowshipMatchesType', () => {
  it('matches only the selected real opportunity_type value', () => {
    expect(fellowshipMatchesType(makeOpp(), '')).toBe(true);
    expect(fellowshipMatchesType(makeOpp(), 'summer_program')).toBe(true);
    expect(fellowshipMatchesType(makeOpp(), 'fellowship')).toBe(false);
  });
});

describe('fellowshipMatchesIntl', () => {
  it('uses the international_friendly field exactly', () => {
    const yes = makeOpp();
    const no = makeOpp({
      eligibility: { ...makeOpp().eligibility, international_friendly: 'no' },
    });
    const unknown = makeOpp({
      eligibility: { ...makeOpp().eligibility, international_friendly: 'unknown' },
    });

    expect(fellowshipMatchesIntl(yes, 'yes')).toBe(true);
    expect(fellowshipMatchesIntl(no, 'no')).toBe(true);
    expect(fellowshipMatchesIntl(unknown, 'yes')).toBe(false);
    expect(fellowshipMatchesIntl(unknown, 'no')).toBe(false);
  });
});

describe('fellowshipMatchesPaid', () => {
  it('treats yes and stipend as funded, no as unpaid, and excludes unknown', () => {
    expect(fellowshipMatchesPaid(makeOpp({ paid: 'yes' }), 'paid')).toBe(true);
    expect(fellowshipMatchesPaid(makeOpp({ paid: 'stipend' }), 'paid')).toBe(true);
    expect(fellowshipMatchesPaid(makeOpp({ paid: 'no' }), 'unpaid')).toBe(true);
    expect(fellowshipMatchesPaid(makeOpp({ paid: 'unknown' }), 'paid')).toBe(false);
    expect(fellowshipMatchesPaid(makeOpp({ paid: 'unknown' }), 'unpaid')).toBe(false);
  });
});

describe('fellowshipMatchesDeadline', () => {
  const now = new Date('2026-07-18T12:00:00Z');

  it('matches a known future date for upcoming and rejects past or invalid dates', () => {
    expect(fellowshipMatchesDeadline(makeOpp({
      deadline: '2026-07-18',
      deadline_is_estimate: false,
    }), 'upcoming', now)).toBe(true);
    expect(fellowshipMatchesDeadline(makeOpp({
      deadline: '2026-08-01',
      deadline_is_estimate: false,
    }), 'upcoming', now)).toBe(true);
    expect(fellowshipMatchesDeadline(makeOpp({
      deadline: '2026-07-17',
      deadline_is_estimate: false,
    }), 'upcoming', now)).toBe(false);
    expect(fellowshipMatchesDeadline(makeOpp({
      deadline: 'TBD',
      deadline_is_estimate: false,
    }), 'upcoming', now)).toBe(false);
    expect(fellowshipMatchesDeadline(makeOpp({}), 'upcoming', now)).toBe(false);
  });

  it.each([true, undefined])(
    'does not treat deadline precision %s as a known upcoming date',
    (deadlineIsEstimate) => {
      expect(fellowshipMatchesDeadline(makeOpp({
        deadline: '2026-08-01',
        deadline_is_estimate: deadlineIsEstimate,
      }), 'upcoming', now)).toBe(false);
    },
  );

  it('uses is_rolling directly instead of guessing from title or deadline text', () => {
    expect(fellowshipMatchesDeadline(makeOpp({ is_rolling: true }), 'rolling', now)).toBe(true);
    expect(fellowshipMatchesDeadline(makeOpp({ is_rolling: false, deadline: 'Rolling' }), 'rolling', now)).toBe(false);
    expect(fellowshipMatchesDeadline(makeOpp({ title: 'Rolling Fellowship' }), 'rolling', now)).toBe(false);
    expect(fellowshipMatchesDeadline(makeOpp({ deadline: undefined }), 'rolling', now)).toBe(false);
  });
});

describe('applyFellowshipFilters', () => {
  it('returns all opportunities with default filters', () => {
    const list = [makeOpp({ id: 'a' }), makeOpp({ id: 'b' })];
    expect(applyFellowshipFilters(list, DEFAULT_FELLOWSHIP_FILTERS)).toEqual(list);
  });

  it('combines type, international, paid, and deadline with AND logic', () => {
    const matching = makeOpp({
      id: 'matching',
      opportunity_type: 'fellowship',
      paid: 'stipend',
      is_rolling: true,
    });
    const wrongType = makeOpp({ id: 'wrong-type', opportunity_type: 'summer_program', is_rolling: true });
    const unknownIntl = makeOpp({
      id: 'unknown-intl',
      opportunity_type: 'fellowship',
      paid: 'stipend',
      is_rolling: true,
      eligibility: { ...makeOpp().eligibility, international_friendly: 'unknown' },
    });

    expect(applyFellowshipFilters([matching, wrongType, unknownIntl], {
      type: 'fellowship',
      international: 'yes',
      paid: 'paid',
      deadline: 'rolling',
    })).toEqual([matching]);
  });
});
