import { describe, it, expect } from 'vitest';
import {
  applyFellowshipFilters,
  DEFAULT_FELLOWSHIP_FILTERS,
  fellowshipMatchesCollege,
  fellowshipMatchesIntl,
  fellowshipMatchesYear,
} from './types';
import type { Opportunity } from '@/lib/types';

function makeOpp(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'test-1',
    title: 'Sample REU',
    organization: 'UIUC',
    opportunity_type: 'summer_program',
    paid: 'yes',
    location: 'on_campus',
    on_campus: true,
    description_clean: 'Summer program for undergrads.',
    keywords: [],
    eligibility: {
      international_friendly: 'yes',
      preferred_year: ['sophomore', 'junior'],
      majors: ['CS'],
      skills_required: [],
      citizenship_required: false,
    },
    application: {
      contact_method: 'email',
      requires_resume: 'yes',
      application_effort: 'low',
    },
    metadata: { is_active: true, confidence_score: 0.9 },
    ...overrides,
  };
}

describe('fellowshipMatchesYear', () => {
  it('returns true for any opp when year filter is empty', () => {
    expect(fellowshipMatchesYear(makeOpp(), '')).toBe(true);
  });

  it('returns true when opp lists the year as preferred', () => {
    const opp = makeOpp();
    expect(fellowshipMatchesYear(opp, 'sophomore')).toBe(true);
    expect(fellowshipMatchesYear(opp, 'junior')).toBe(true);
  });

  it('returns false when opp does not list the year', () => {
    const opp = makeOpp();
    expect(fellowshipMatchesYear(opp, 'freshman')).toBe(false);
  });

  it('returns true when opp has no preferred_year (assumed any)', () => {
    const opp = makeOpp({
      eligibility: { ...makeOpp().eligibility, preferred_year: [] },
    });
    expect(fellowshipMatchesYear(opp, 'freshman')).toBe(true);
  });
});

describe('fellowshipMatchesIntl', () => {
  it('returns true for any opp when intl filter is empty', () => {
    expect(fellowshipMatchesIntl(makeOpp(), '')).toBe(true);
  });

  it('returns true when filter=yes AND opp is intl-friendly', () => {
    expect(fellowshipMatchesIntl(makeOpp(), 'yes')).toBe(true);
  });

  it('returns false when filter=yes AND opp is intl-unfriendly', () => {
    const opp = makeOpp({
      eligibility: { ...makeOpp().eligibility, international_friendly: 'no' },
    });
    expect(fellowshipMatchesIntl(opp, 'yes')).toBe(false);
  });

  it('treats unknown/missing intl flag as yes-permissive when filter=no', () => {
    const opp = makeOpp({
      eligibility: { ...makeOpp().eligibility, international_friendly: 'unknown' },
    });
    expect(fellowshipMatchesIntl(opp, 'no')).toBe(true);
  });
});

describe('fellowshipMatchesCollege', () => {
  it('returns true for any college selection', () => {
    expect(fellowshipMatchesCollege(makeOpp(), 'any')).toBe(true);
  });

  it('matches Grainger via title keyword', () => {
    const opp = makeOpp({ title: 'Grainger Engineering SURF Program' });
    expect(fellowshipMatchesCollege(opp, 'grainger')).toBe(true);
  });

  it('matches Siebel CS via department keyword', () => {
    const opp = makeOpp({ department: 'Computer Science' });
    expect(fellowshipMatchesCollege(opp, 'siebel')).toBe(true);
  });

  it('matches Beckman via organization keyword', () => {
    const opp = makeOpp({ organization: 'Beckman Institute for Advanced Science and Technology' });
    expect(fellowshipMatchesCollege(opp, 'beckman')).toBe(true);
  });

  it('matches LAS via eligibility.majors', () => {
    const opp = makeOpp({
      eligibility: { ...makeOpp().eligibility, majors: ['Psychology', 'Biology'] },
    });
    expect(fellowshipMatchesCollege(opp, 'las')).toBe(true);
  });

  it('returns false when no field hints at the college', () => {
    const opp = makeOpp({
      title: 'Generic Summer Program',
      organization: 'Some Lab',
      department: '',
      lab_or_program: '',
    });
    expect(fellowshipMatchesCollege(opp, 'beckman')).toBe(false);
  });
});

describe('applyFellowshipFilters', () => {
  it('returns all opps with default filters', () => {
    const list = [makeOpp({ id: 'a' }), makeOpp({ id: 'b' })];
    expect(applyFellowshipFilters(list, DEFAULT_FELLOWSHIP_FILTERS)).toHaveLength(2);
  });

  it('combines year + college filters with AND logic', () => {
    const grainger = makeOpp({
      id: 'grainger',
      title: 'Grainger SURF',
      eligibility: { ...makeOpp().eligibility, preferred_year: ['sophomore'] },
    });
    const beckman = makeOpp({
      id: 'beckman',
      title: 'Beckman Summer Program',
      organization: 'Beckman Institute',
      eligibility: { ...makeOpp().eligibility, preferred_year: ['junior'] },
    });
    const all = [grainger, beckman];
    const filtered = applyFellowshipFilters(all, {
      year: 'sophomore', international: '', college: 'grainger',
    });
    expect(filtered).toHaveLength(1);
    expect(filtered[0].id).toBe('grainger');
  });
});
