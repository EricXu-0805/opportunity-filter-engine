import { describe, expect, it } from 'vitest';
import type { Opportunity } from '@/lib/types';
import { buildOpportunityOgFacts } from './og-facts';

function opportunity(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'faculty-ada',
    title: 'Ada Lovelace',
    organization: 'Test University',
    opportunity_type: 'research',
    paid: 'yes',
    location: 'Test City',
    on_campus: true,
    description_clean: 'Faculty profile.',
    keywords: [],
    deadline: '2026-08-20',
    eligibility: {
      international_friendly: 'yes',
      preferred_year: [],
      majors: [],
      skills_required: [],
      citizenship_required: null,
    },
    application: {
      application_effort: 'unknown',
      requires_resume: 'unknown',
      contact_method: 'email',
    },
    metadata: { is_active: true, confidence_score: 1 },
    ...overrides,
  };
}

describe('opportunity OG truth boundary', () => {
  it('renders a faculty row as a contact profile without opening claims', () => {
    const facts = buildOpportunityOgFacts(
      opportunity({ source_type: 'faculty_research' }),
      Date.parse('2026-08-17T00:00:00Z'),
    );

    expect(facts).toMatchObject({
      typeLabel: 'Faculty contact',
      locationPrefix: 'Faculty affiliation',
      showPaid: false,
      showOnCampus: false,
      showInternational: false,
      daysUntilDeadline: null,
      deadlineLabel: null,
      footer: 'Explore research and faculty contacts',
    });
  });

  it('preserves listing facts for a real program record', () => {
    const facts = buildOpportunityOgFacts(
      opportunity({ source_type: 'campus_program' }),
      Date.parse('2026-08-17T00:00:00Z'),
    );

    expect(facts).toMatchObject({
      typeLabel: 'research',
      locationPrefix: '',
      showPaid: true,
      showOnCampus: true,
      showInternational: true,
      daysUntilDeadline: 3,
      deadlineLabel: 'Deadline: 2026-08-20',
      footer: 'Find research & internships that fit you',
    });
  });

  it('fails an untyped stale record closed instead of sharing opening claims', () => {
    const facts = buildOpportunityOgFacts(
      opportunity({ source_type: undefined }),
      Date.parse('2026-08-17T00:00:00Z'),
    );

    expect(facts).toMatchObject({
      typeLabel: 'Record type unconfirmed',
      showPaid: false,
      showOnCampus: false,
      showInternational: false,
      daysUntilDeadline: null,
      deadlineLabel: null,
      footer: 'Check the original source for current details',
    });
  });
});

describe('estimated deadlines are never stated as hard on a share card', () => {
  // 749 corpus records carry deadline_is_estimate (all NSF REU rows, whose
  // date src/collectors/nsf_reu.py derives from the award start month). Every
  // other surface suppresses it — DeadlineBadge greys it to "· Estimated",
  // DetailSections prints "Estimated", getDeadlineUrgency refuses 'urgent' —
  // and this card is minted from the same detail page.
  const estimated = { source_type: 'summer_program', deadline: '2026-08-20', deadline_is_estimate: true };

  it('does not emit a countdown the route renders as a Due-in chip', () => {
    const facts = buildOpportunityOgFacts(
      opportunity(estimated as never),
      Date.parse('2026-08-18T00:00:00Z'),
    );
    expect(facts.daysUntilDeadline).toBeNull();
  });

  it('labels the date as an estimate rather than a deadline', () => {
    const facts = buildOpportunityOgFacts(
      opportunity(estimated as never),
      Date.parse('2026-08-18T00:00:00Z'),
    );
    expect(facts.deadlineLabel).toBe('Estimated deadline: 2026-08-20');
  });

  it('still states a confirmed deadline as fact', () => {
    const facts = buildOpportunityOgFacts(
      opportunity({ source_type: 'summer_program', deadline: '2026-08-20' } as never),
      Date.parse('2026-08-18T00:00:00Z'),
    );
    expect(facts.daysUntilDeadline).toBe(2);
    expect(facts.deadlineLabel).toBe('Deadline: 2026-08-20');
  });
});
