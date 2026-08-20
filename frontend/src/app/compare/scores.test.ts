import { describe, expect, it } from 'vitest';
import type { Opportunity, ProfileData } from '@/lib/types';
import {
  computeDecisionFactors,
  sortByCanonicalScore,
  type CompareRow,
} from './scores';

const PROFILE = {
  major: 'Computer Science',
  grade: 'Junior',
  is_international: false,
  skills: [{ name: 'Python', level: 'experienced' }],
} as ProfileData;

function opportunity(id: string, effort: string): Opportunity {
  return {
    id,
    title: id,
    organization: 'Test U',
    opportunity_type: 'research',
    paid: 'unknown',
    location: '',
    on_campus: null,
    description_clean: '',
    keywords: [],
    application: {
      application_effort: effort,
      requires_resume: 'unknown',
      contact_method: 'unknown',
    },
    eligibility: {
      international_friendly: 'unknown',
      preferred_year: [],
      majors: [],
      skills_required: [],
      citizenship_required: null,
    },
    metadata: { is_active: true, confidence_score: 1 },
  };
}

function row(id: string, finalScore: number | null, inputIndex: number): CompareRow {
  const opp = opportunity(id, id === 'local-high' ? 'low' : 'high');
  return {
    opp,
    inputIndex,
    factors: computeDecisionFactors(PROFILE, opp),
    status: finalScore === null ? 'error' : 'ready',
    match: finalScore === null ? null : {
      final_score: finalScore,
      bucket: finalScore > 70 ? 'high_priority' : 'reach',
      reasons_fit: [`canonical fit ${id}`],
      reasons_gap: [],
      explanation: '',
      method: 'local',
      matcher_version: 'test-matcher-v1',
    },
  };
}

describe('compare score truth source', () => {
  it('computes Ease as a decision-factor estimate where higher means less effort', () => {
    expect(computeDecisionFactors(PROFILE, opportunity('low', 'low')).ease).toBe(100);
    expect(computeDecisionFactors(PROFILE, opportunity('medium', 'medium')).ease).toBe(60);
    expect(computeDecisionFactors(PROFILE, opportunity('high', 'high')).ease).toBe(30);
  });

  it('keeps missing listing evidence unknown and recognizes paid=no as unpaid', () => {
    const unknown = computeDecisionFactors(PROFILE, opportunity('unknown', 'high'));
    expect(unknown.skill_match).toBeNull();
    expect(unknown.eligibility).toBeNull();
    expect(unknown.compensation).toBeNull();
    expect(unknown.deadline_runway).toBeNull();

    const unpaid = computeDecisionFactors(PROFILE, {
      ...opportunity('unpaid', 'medium'),
      paid: 'no',
    });
    expect(unpaid.compensation).toBe(30);
  });

  it('does not fabricate a major-match score when the listing names no majors', () => {
    const noMajors = computeDecisionFactors(PROFILE, opportunity('no-majors', 'medium'));
    expect(noMajors.eligibility).toBeNull();

    const withEvidence = computeDecisionFactors(PROFILE, {
      ...opportunity('with-evidence', 'medium'),
      eligibility: {
        majors: ['Computer Science'],
        preferred_year: ['Junior'],
        international_friendly: 'yes',
        skills_required: [],
        citizenship_required: false,
      },
    });
    expect(withEvidence.eligibility).toBe(100);
  });

  it('treats an explicit unknown year sentinel as missing evidence', () => {
    const factors = computeDecisionFactors(PROFILE, {
      ...opportunity('unknown-year', 'unknown'),
      eligibility: {
        majors: ['Computer Science'],
        preferred_year: ['unknown'],
        international_friendly: 'unknown',
        skills_required: [],
        citizenship_required: null,
      },
    });
    expect(factors.eligibility).toBeNull();
    expect(factors.ease).toBeNull();
  });

  it.each([true, null, undefined])(
    'does not score a deadline as exact runway when precision is %s',
    (deadlineIsEstimate) => {
      const factors = computeDecisionFactors(PROFILE, {
        ...opportunity('estimated', 'medium'),
        deadline: '2030-01-01',
        deadline_is_estimate: deadlineIsEstimate,
      });
      expect(factors.deadline_runway).toBeNull();
    },
  );

  it('scores rolling programs on runway without needing a date', () => {
    const factors = computeDecisionFactors(PROFILE, {
      ...opportunity('rolling', 'medium'),
      is_rolling: true,
    });
    expect(factors.deadline_runway).toBe(85);
  });

  it('does not score legacy opening fields on a faculty contact profile', () => {
    const factors = computeDecisionFactors(PROFILE, {
      ...opportunity('faculty-contact', 'low'),
      source_type: 'faculty_research',
      paid: 'yes',
      is_rolling: true,
      deadline: '2099-12-31',
      eligibility: {
        international_friendly: 'yes',
        preferred_year: ['Junior'],
        majors: ['Computer Science'],
        skills_required: ['Python'],
        citizenship_required: null,
      },
    });
    expect(factors.skill_match).toBeNull();
    expect(factors.eligibility).toBeNull();
    expect(factors.ease).toBeNull();
    expect(factors.compensation).toBeNull();
    expect(factors.deadline_runway).toBeNull();
    expect(factors.intl_friendly).toBeNull();
  });

  it('sorts only by canonical final_score, never by locally estimated factors', () => {
    const rows = [row('local-high', 21, 0), row('local-low', 93, 1)];
    expect(sortByCanonicalScore(rows).map((item) => item.opp.id)).toEqual([
      'local-low',
      'local-high',
    ]);
  });

  it('keeps failed canonical rows after scored rows in stable input order', () => {
    const rows = [row('failed-a', null, 0), row('ready', 50, 1), row('failed-b', null, 2)];
    expect(sortByCanonicalScore(rows).map((item) => item.opp.id)).toEqual([
      'ready',
      'failed-a',
      'failed-b',
    ]);
  });
});
