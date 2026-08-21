import { describe, expect, it } from 'vitest';
import type { Opportunity } from '@/lib/types';
import { buildOpportunityJsonLd } from './json-ld';

function opportunity(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'listing-1',
    title: 'Research Assistant',
    organization: 'Test University',
    opportunity_type: 'research',
    // Structured data is only published for a target the server still calls
    // actionable, so the default fixture carries a live truth.
    target_truth: {
      listing_state: 'open',
      reference_only: false,
      actionable: true,
      accepting_state: 'accepting',
      reason_code: null,
      verified_at: null,
      expires_at: null,
    },
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

});

describe('no opportunity is published as a JobPosting today', () => {
  // `record_kind === 'listing'` says "this is an opportunity record". It does
  // NOT say "this is employment". The corpus has no source-backed employment
  // classification, no structured numeric compensation, and no verified
  // organization/address/country — so the load-bearing employment,
  // compensation, location and organization claims were inferred or guessed:
  // employmentType from `opportunity_type`, currency/unit from nothing at
  // all, and `addressCountry: 'US'` hardcoded. A JobPosting outlives the page
  // in a search index, which is the one place an unsupported employment claim
  // does the most damage.
  //
  // So: nothing is emitted, for anything, until those prerequisites exist.

  const ACTIONABLE: [string, Record<string, unknown>][] = [
    ['a confirmed campus listing', { source_type: 'campus_program' }],
    ['an internship listing', { source_type: 'internship', opportunity_type: 'internship' }],
    ['a research listing', { source_type: 'campus_lab', opportunity_type: 'research' }],
    ['a summer program', { source_type: 'summer_program', opportunity_type: 'summer_program' }],
    ['a fellowship', { source_type: 'external', opportunity_type: 'fellowship' }],
    // The shape that makes the defect concrete rather than theoretical:
    // a real corpus row (`rss-our-7b7684c6`) that is a research SYMPOSIUM.
    // It is a reviewed, actionable listing, so today it ships as a
    // JobPosting with employmentType INTERN. The record carries no
    // employment or job evidence at all, so nothing supports publishing it
    // as a JobPosting.
    ['a networking event', {
      source_type: 'rss',
      opportunity_type: 'event',
      title: 'Networking & Communication Opportunity - Chicago Area Undergraduate Research Symposium (CAURS)',
      organization: 'University of Illinois at Urbana-Champaign',
      location: 'Champaign, IL',
      paid: 'unknown',
      compensation_details: '',
    }],
  ];

  it.each(ACTIONABLE)('emits nothing for %s', (_label, overrides) => {
    expect(buildOpportunityJsonLd(opportunity(overrides as never))).toBeNull();
  });

  const COMPENSATION: [string, Record<string, unknown>][] = [
    // `paid` is a three-state flag, not an amount. Every one of these used to
    // produce currency USD and unitText HOUR, neither of which the record says.
    //
    // The first two are the REAL high-frequency shape, not a synthetic edge:
    // `compensation_details` is an EMPTY STRING on 2,116 of the 2,662 paid
    // records this function actually saw. `??` is nullish-only, so the empty
    // string was not replaced — it was published verbatim as the numeric
    // `value` of a QuantitativeValue, at USD and HOUR.
    ['paid=yes with an empty compensation string', {
      source_type: 'campus_program', paid: 'yes', compensation_details: '',
    }],
    ['a stipend with an empty compensation string', {
      source_type: 'campus_program', paid: 'stipend', compensation_details: '',
    }],
    ['paid=yes with no figure', { source_type: 'campus_program', paid: 'yes' }],
    ['a stipend with no figure', { source_type: 'campus_program', paid: 'stipend' }],
    ['free-text compensation', {
      source_type: 'campus_program', paid: 'yes',
      compensation_details: '$18/hr during term, negotiable',
    }],
    ['a stipend described in prose', {
      source_type: 'campus_program', paid: 'stipend',
      compensation_details: 'Summer stipend of approximately $4,000 total',
    }],
    ['paid but no compensation_details at all', {
      source_type: 'campus_program', paid: 'yes', compensation_details: undefined,
    }],
  ];

  it.each(COMPENSATION)('emits nothing for %s', (_label, overrides) => {
    // A prose string in schema.org's numeric `value` slot is not a smaller
    // claim than a wrong number — it is an unparseable one presented as data.
    expect(buildOpportunityJsonLd(opportunity(overrides as never))).toBeNull();
  });

  const IDENTITY: [string, Record<string, unknown>][] = [
    // `addressCountry: 'US'` was asserted for every one of these.
    //
    // The empty-string organization is the shape the live corpus actually has
    // (279 records); it passed straight through as `name: ''`. The nullish
    // case below is the one that would hit the `?? 'Host institution'`
    // fallback, and no current record is nullish — it is covered as a
    // synthetic/future risk, not as something observed today.
    ['a listing with an empty organization string', {
      source_type: 'campus_program', organization: '',
    }],
    ['a listing with no organization', {
      source_type: 'campus_program', organization: undefined,
    }],
    ['a listing with no location', { source_type: 'campus_program', location: undefined }],
    ['a listing with neither', {
      source_type: 'campus_program', organization: undefined, location: undefined,
    }],
    ['a non-US listing', {
      source_type: 'external', organization: 'ETH Zürich', location: 'Zürich, Switzerland',
    }],
  ];

  it.each(IDENTITY)('emits nothing for %s', (_label, overrides) => {
    expect(buildOpportunityJsonLd(opportunity(overrides as never))).toBeNull();
  });

  it('emits nothing even for a verified, non-estimated deadline', () => {
    // The strongest case the old code had for publishing anything: a date the
    // source actually stated. A trustworthy validThrough on an untrustworthy
    // JobPosting is still an untrustworthy JobPosting.
    expect(buildOpportunityJsonLd(opportunity({
      source_type: 'summer_program',
      deadline: '2026-08-20',
      deadline_is_estimate: false,
    } as never))).toBeNull();
  });

  it('emits no structured data of any other type either', () => {
    // Not a downgrade to Event/Program/EducationalOccupationalProgram. Those
    // carry their own unverified assertions (dates, locations, providers) and
    // swapping one invented type for another is not a fail-closed boundary.
    const jsonLd = buildOpportunityJsonLd(opportunity({ source_type: 'campus_program' }));
    expect(jsonLd).toBeNull();
    expect(JSON.stringify(jsonLd)).not.toContain('@type');
    expect(JSON.stringify(jsonLd)).not.toContain('schema.org');
  });
});

describe('structured data is withheld for non-actionable targets', () => {
  const cases: [string, unknown][] = [
    ['closed', {
      listing_state: 'closed', reference_only: true, actionable: false,
      accepting_state: 'not_accepting', reason_code: 'listing_closed',
      verified_at: null, expires_at: null,
    }],
    ['reference-only', {
      listing_state: 'unknown', reference_only: true, actionable: false,
      accepting_state: 'unknown', reason_code: 'reference_only',
      verified_at: null, expires_at: null,
    }],
    ['inactive', {
      listing_state: 'unknown', reference_only: false, actionable: false,
      accepting_state: 'unknown', reason_code: 'inactive',
      verified_at: null, expires_at: null,
    }],
    ['faculty-not-accepting', {
      listing_state: 'unknown', reference_only: false, actionable: false,
      accepting_state: 'not_accepting', reason_code: 'faculty_not_accepting',
      verified_at: null, expires_at: null,
    }],
    ['malformed', { listing_state: 'open' }],
    ['self-contradicting', {
      listing_state: 'closed', reference_only: false, actionable: true,
      accepting_state: 'accepting', reason_code: null,
      verified_at: null, expires_at: null,
    }],
    ['null', null],
  ];

  it.each(cases)('emits no JobPosting for a %s target', (_label, truth) => {
    // A JobPosting tells a search engine this is a job someone can apply for,
    // and it outlives the page in the index — the worst place for a stale
    // opening claim.
    // Every case names its kind explicitly. The base fixture carries NO
    // source_type, so leaving it out makes each row `unknown` — and an
    // unknown kind is refused before the truth is consulted at all. The block
    // would then stay green with the posture gate deleted outright, which is
    // the only thing it exists to test. `faculty_not_accepting` is the one
    // reason a listing cannot carry; the rest are canonical on a listing.
    expect(buildOpportunityJsonLd(
      opportunity({
        target_truth: truth,
        source_type: (truth as { reason_code?: string } | null)?.reason_code === 'faculty_not_accepting'
          ? 'faculty_research'
          : 'campus_program',
      } as never),
    )).toBeNull();
  });

  it('emits no JobPosting when the field is absent entirely', () => {
    // A reviewed listing first, so the missing truth is the only thing left
    // to refuse it. Starting from the bare fixture leaves the record kind
    // `unknown`, which is refused before the truth is even looked at — the
    // assertion would then hold with the truth gate removed entirely.
    const opp = opportunity({ source_type: 'campus_program' });
    delete (opp as unknown as Record<string, unknown>).target_truth;
    expect(buildOpportunityJsonLd(opp)).toBeNull();
  });
});
