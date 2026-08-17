import { describe, expect, it } from 'vitest';
import type { Opportunity } from '@/lib/types';
import { buildOpportunityJsonLd } from './json-ld';

function opportunity(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'listing-1',
    title: 'Research Assistant',
    organization: 'Test University',
    opportunity_type: 'research',
    paid: 'yes',
    location: 'Test City',
    on_campus: true,
    description_clean: 'A confirmed research opening.',
    keywords: [],
    eligibility: {
      international_friendly: 'unknown',
      preferred_year: [],
      majors: [],
      skills_required: [],
      citizenship_required: null,
    },
    application: {
      application_effort: 'unknown',
      requires_resume: 'unknown',
      contact_method: 'website',
    },
    metadata: { is_active: true, confidence_score: 1 },
    ...overrides,
  };
}

describe('opportunity structured data truth boundary', () => {
  it('does not publish a faculty contact profile as a JobPosting', () => {
    expect(buildOpportunityJsonLd(opportunity({ source_type: 'faculty_research' }))).toBeNull();
  });

  it('does not publish a stale record with no reviewed source type as a JobPosting', () => {
    expect(buildOpportunityJsonLd(opportunity({ source_type: undefined }))).toBeNull();
    expect(buildOpportunityJsonLd(opportunity({ source_type: 'unknown' }))).toBeNull();
  });

  it('keeps JobPosting structured data for actual listing records', () => {
    expect(buildOpportunityJsonLd(opportunity({ source_type: 'campus_program' }))).toMatchObject({
      '@type': 'JobPosting',
      title: 'Research Assistant',
    });
  });
});
