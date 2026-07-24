import { describe, expect, it } from 'vitest';
import type { MatchResult, Opportunity } from '@/lib/types';
import { isCanonicalProgramMatch, sortProgramsByCanonicalMatch } from './canonical-matches';

function opportunity(id: string, type = 'fellowship'): Opportunity {
  return {
    id,
    title: id,
    organization: 'Example',
    opportunity_type: type,
    paid: 'unknown',
    location: '',
    on_campus: false,
    description_clean: '',
    keywords: [],
    eligibility: {
      international_friendly: 'unknown',
      preferred_year: [],
      majors: [],
      skills_required: [],
      citizenship_required: false,
    },
    application: {
      contact_method: 'website',
      application_effort: 'unknown',
      requires_resume: 'unknown',
    },
    metadata: { is_active: true, confidence_score: 0.5 },
  };
}

function match(opp: Opportunity, score: number): MatchResult {
  return {
    opportunity_id: opp.id,
    eligibility_score: score,
    readiness_score: score,
    upside_score: score,
    final_score: score,
    bucket: score >= 80 ? 'high_priority' : 'reach',
    reasons_fit: ['Grounded fit'],
    reasons_gap: [],
    next_steps: [],
    opportunity: opp,
  };
}

describe('canonical fellowship matching helpers', () => {
  it('sorts only by canonical score and keeps unscored rows stable at the end', () => {
    const a = opportunity('a');
    const b = opportunity('b', 'summer_program');
    const c = opportunity('c');
    const matches = new Map([
      ['a', match(a, 60)],
      ['b', match(b, 90)],
    ]);

    expect(sortProgramsByCanonicalMatch([a, c, b], matches).map((row) => row.id))
      .toEqual(['b', 'a', 'c']);
  });

  it('rejects malformed, mismatched, or non-program responses', () => {
    const valid = match(opportunity('program'), 88);
    expect(isCanonicalProgramMatch(valid)).toBe(true);
    expect(isCanonicalProgramMatch({ ...valid, final_score: Number.NaN })).toBe(false);
    expect(isCanonicalProgramMatch({ ...valid, opportunity_id: 'other' })).toBe(false);
    expect(isCanonicalProgramMatch({
      ...valid,
      opportunity: opportunity('program', 'research'),
    })).toBe(false);
  });
});
