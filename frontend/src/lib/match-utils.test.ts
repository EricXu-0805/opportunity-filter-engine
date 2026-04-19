import { describe, it, expect } from 'vitest';
import {
  daysUntil,
  getDeadlineUrgency,
  expandSearchAliases,
  matchesToCSV,
  hashProfile,
} from './match-utils';
import type { MatchResult } from './types';

const NOW = new Date('2026-04-16T10:00:00Z');

describe('daysUntil', () => {
  it('returns null for missing deadline', () => {
    expect(daysUntil(undefined, NOW)).toBeNull();
    expect(daysUntil('', NOW)).toBeNull();
  });

  it('returns null for malformed date', () => {
    expect(daysUntil('not-a-date', NOW)).toBeNull();
  });

  it('returns positive days for future', () => {
    expect(daysUntil('2026-04-23', NOW)).toBe(7);
    expect(daysUntil('2026-05-16', NOW)).toBe(30);
  });

  it('returns negative days for past', () => {
    expect(daysUntil('2026-04-10', NOW)).toBe(-6);
  });

  it('handles today/boundary consistently', () => {
    const days = daysUntil('2026-04-16', NOW);
    expect(days).toBeGreaterThanOrEqual(-1);
    expect(days).toBeLessThanOrEqual(1);
  });
});

describe('getDeadlineUrgency', () => {
  it('classifies urgency buckets', () => {
    expect(getDeadlineUrgency(undefined, NOW)).toBeNull();
    expect(getDeadlineUrgency('2026-04-10', NOW)).toBe('passed');
    expect(getDeadlineUrgency('2026-04-20', NOW)).toBe('urgent');
    expect(getDeadlineUrgency('2026-05-01', NOW)).toBe('soon');
    expect(getDeadlineUrgency('2026-06-15', NOW)).toBe('later');
  });

  it('handles boundary days', () => {
    expect(getDeadlineUrgency('2026-04-23', NOW)).toBe('urgent');
    expect(getDeadlineUrgency('2026-04-24', NOW)).toBe('soon');
    expect(getDeadlineUrgency('2026-05-16', NOW)).toBe('soon');
    expect(getDeadlineUrgency('2026-05-17', NOW)).toBe('later');
  });
});

describe('expandSearchAliases', () => {
  it('expands known single-term abbreviation', () => {
    expect(expandSearchAliases('ml')).toContain('machine learning');
    expect(expandSearchAliases('ml')).toContain('ml');
  });

  it('is case insensitive on input', () => {
    expect(expandSearchAliases('ML')).toContain('machine learning');
    expect(expandSearchAliases('Nlp')).toContain('natural language processing');
  });

  it('expands abbreviation appearing inside longer query', () => {
    const terms = expandSearchAliases('ml research lab');
    expect(terms.some(t => t.includes('machine learning'))).toBe(true);
  });

  it('returns only the input when no alias matches', () => {
    expect(expandSearchAliases('robotics')).toEqual(['robotics']);
  });

  it('handles multiple alias expansions (e.g. hci)', () => {
    const terms = expandSearchAliases('hci');
    expect(terms).toContain('human computer interaction');
    expect(terms).toContain('human-computer interaction');
  });
});

function makeMatch(overrides: Partial<MatchResult['opportunity']> = {}, extras: Partial<MatchResult> = {}): MatchResult {
  return {
    opportunity_id: 'test-1',
    eligibility_score: 80, readiness_score: 70, upside_score: 60,
    final_score: 74.5,
    bucket: 'good_match',
    reasons_fit: [], reasons_gap: [], next_steps: [],
    ...extras,
    opportunity: {
      id: 'test-1',
      title: 'ML Research Assistant',
      organization: 'UIUC',
      opportunity_type: 'research',
      paid: 'yes',
      location: 'Urbana',
      source: 'uiuc_sro',
      on_campus: true,
      description_clean: '',
      keywords: [],
      deadline: '2026-05-15',
      url: 'https://example.com/apply',
      eligibility: {
        international_friendly: 'yes',
        preferred_year: [],
        majors: [],
        skills_required: [],
        citizenship_required: false,
      },
      application: { application_effort: 'low', requires_resume: 'yes', contact_method: 'email' },
      metadata: { is_active: true, confidence_score: 0.9 },
      ...overrides,
    },
  };
}

describe('matchesToCSV', () => {
  it('emits a header row', () => {
    const csv = matchesToCSV([makeMatch()]);
    const [header] = csv.split('\n');
    expect(header).toContain('"Title"');
    expect(header).toContain('"Score"');
    expect(header).toContain('"Bucket"');
  });

  it('emits one data row per match', () => {
    const csv = matchesToCSV([makeMatch(), makeMatch({ id: 'test-2', title: 'Other' })]);
    expect(csv.split('\n').length).toBe(3);
  });

  it('escapes double quotes in field values', () => {
    const csv = matchesToCSV([makeMatch({ title: 'Lab "AI for Good"' })]);
    expect(csv).toContain('"Lab ""AI for Good"""');
  });

  it('prefers application_url over opportunity.url', () => {
    const csv = matchesToCSV([
      makeMatch({
        url: 'https://old-url.com',
        application: {
          application_effort: 'low',
          requires_resume: 'yes',
          contact_method: 'email',
          application_url: 'https://apply-here.com',
        },
      }),
    ]);
    expect(csv).toContain('"https://apply-here.com"');
    expect(csv).not.toContain('old-url');
  });

  it('handles missing organization', () => {
    const csv = matchesToCSV([makeMatch({ organization: undefined })]);
    expect(csv).toContain('""');
  });

  it('formats score to 1 decimal', () => {
    const csv = matchesToCSV([makeMatch({}, { final_score: 87.345 })]);
    expect(csv).toContain('"87.3"');
  });
});

describe('hashProfile', () => {
  const base = {
    major: 'CS', college: 'Grainger', grade: 'sophomore',
    is_international: true, skills: [{ name: 'Python', level: 'experienced' }],
    research_interests: 'ML',
  };

  it('produces deterministic output', () => {
    expect(hashProfile(base)).toBe(hashProfile(base));
  });

  it('differs when a field changes', () => {
    expect(hashProfile(base)).not.toBe(hashProfile({ ...base, major: 'ECE' }));
    expect(hashProfile(base)).not.toBe(hashProfile({ ...base, research_interests: 'Robotics' }));
  });

  it('is order-independent for skills', () => {
    const h1 = hashProfile({ ...base, skills: [
      { name: 'Python', level: 'experienced' },
      { name: 'Java', level: 'beginner' },
    ]});
    const h2 = hashProfile({ ...base, skills: [
      { name: 'Java', level: 'beginner' },
      { name: 'Python', level: 'experienced' },
    ]});
    expect(h1).toBe(h2);
  });

  it('distinguishes skill level changes', () => {
    const h1 = hashProfile({ ...base, skills: [{ name: 'Python', level: 'beginner' }] });
    const h2 = hashProfile({ ...base, skills: [{ name: 'Python', level: 'expert' }] });
    expect(h1).not.toBe(h2);
  });
});
