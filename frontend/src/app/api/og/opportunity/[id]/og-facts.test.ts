import { describe, expect, it } from 'vitest';
import type { Opportunity } from '@/lib/types';
import { buildOpportunityOgFacts } from './og-facts';

export const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

/** The exact refusal shapes src/evidence.target_truth emits, per reason. */
const REFUSAL = {
  listing_closed: {
    listing_state: 'closed', reference_only: false, actionable: false,
    accepting_state: 'not_accepting', reason_code: 'listing_closed',
    verified_at: null, expires_at: null,
  },
  reference_only: {
    listing_state: 'unknown', reference_only: true, actionable: false,
    accepting_state: 'unknown', reason_code: 'reference_only',
    verified_at: null, expires_at: null,
  },
  inactive: {
    listing_state: 'unknown', reference_only: false, actionable: false,
    accepting_state: 'unknown', reason_code: 'inactive',
    verified_at: null, expires_at: null,
  },
  faculty_not_accepting: {
    listing_state: 'unknown', reference_only: false, actionable: false,
    accepting_state: 'not_accepting', reason_code: 'faculty_not_accepting',
    verified_at: null, expires_at: null,
  },
} as const;

function opportunity(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: 'faculty-ada',
    title: 'Ada Lovelace',
    organization: 'Test University',
    opportunity_type: 'research',
    // A reviewed source type. The untyped case below deletes it deliberately;
    // leaving it off by default would make every fixture here the unreviewed
    // shape and the positive assertions would measure the degraded card.
    source_type: 'faculty_research',
    // Every served record carries a truth. Without one the default fixture
    // would be `unknown` and every positive assertion below would be testing
    // the degraded path while claiming to test the live one.
    target_truth: { ...ACTIONABLE_TRUTH },
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
      // `deadline_is_estimate: false` is explicit and load-bearing: only a
      // recorded judgement makes a date confirmed. Leaving it unset means
      // nobody judged it, and an unjudged date gets no countdown.
      opportunity({ source_type: 'campus_program', deadline_is_estimate: false }),
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
    // `source_type` deleted, not merely undefined: the record has to actually
    // lack the field the way the 26 real rows do.
    const record = opportunity() as unknown as Record<string, unknown>;
    delete record.source_type;
    // And it carries the truth the backend now stamps on that shape.
    record.target_truth = {
      ...ACTIONABLE_TRUTH,
      actionable: false,
      listing_state: 'unknown',
      accepting_state: 'unknown',
      reference_only: false,
      reason_code: 'record_kind_unverified',
    };

    const facts = buildOpportunityOgFacts(
      record as never,
      Date.parse('2026-08-17T00:00:00Z'),
    );

    expect(facts).toMatchObject({
      // Names what is unverified — the type — rather than implying an opening
      // ended, which nothing here ever claimed.
      typeLabel: 'Record type unverified',
      showPaid: false,
      showOnCampus: false,
      showInternational: false,
      daysUntilDeadline: null,
      deadlineLabel: null,
      footer: 'Not presented as an open listing — check the source',
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
      opportunity({
        source_type: 'summer_program',
        deadline: '2026-08-20',
        deadline_is_estimate: false,
      } as never),
      Date.parse('2026-08-18T00:00:00Z'),
    );
    expect(facts.daysUntilDeadline).toBe(2);
    expect(facts.deadlineLabel).toBe('Deadline: 2026-08-20');
  });

  describe('the deadline has three states, not two', () => {
    // The bug this pins: `!isEstimate` treated null/undefined — nobody judged
    // this date — as "confirmed", so the majority of dates in the corpus got
    // a countdown on a shareable image.
    const cases = [
      [false, 2, 'Deadline: 2026-08-20'],
      [true, null, 'Estimated deadline: 2026-08-20'],
      [null, null, 'Listed deadline: 2026-08-20 — verify with source'],
      [undefined, null, 'Listed deadline: 2026-08-20 — verify with source'],
    ] as const;

    it.each(cases)(
      'deadline_is_estimate %s → countdown %s',
      (estimate, days, label) => {
        const facts = buildOpportunityOgFacts(
          opportunity({
            source_type: 'summer_program',
            deadline: '2026-08-20',
            deadline_is_estimate: estimate,
          } as never),
          Date.parse('2026-08-18T00:00:00Z'),
        );
        expect(facts.daysUntilDeadline).toBe(days);
        expect(facts.deadlineLabel).toBe(label);
      },
    );
  });

  describe('a target the truth does not vouch for shares no opening facts', () => {
    // Every field below is populated and every one of them is an offer term.
    // The record is shaped exactly like a live paid on-campus listing; only
    // its truth says otherwise, which is the whole point.
    const REASONS = [
      ['listing_closed', 'Closed listing',
        'This listing has closed — check the source for current openings'],
      ['reference_only', 'Reference record', 'Kept for reference — not an open listing'],
      ['faculty_not_accepting', 'Not accepting undergraduates',
        'Source profile states they are not accepting undergraduates'],
      ['inactive', 'Inactive record', 'No longer active — check the original source'],
    ] as const;

    it.each(REASONS)('%s shares nothing and says why', (reason, typeLabel, footer) => {
      const facts = buildOpportunityOgFacts(
        opportunity({
          // Canonical per reason here too. `faculty_not_accepting` is a
          // person's own written refusal, and only a `faculty_research` row
          // has a person; on a listing the payload is unreadable and the
          // footer under test would never be the one produced.
          source_type: reason === 'faculty_not_accepting'
            ? 'faculty_research'
            : 'campus_program',
          deadline: '2026-08-20',
          deadline_is_estimate: false,
          // Canonical per reason, not a blanket shape: the parser now checks
          // each refusal against the fields the backend actually emits with
          // it, so `accepting_state` differs by reason and a one-size fixture
          // is itself self-contradicting.
          target_truth: {
            ...ACTIONABLE_TRUTH,
            actionable: false,
            reason_code: reason,
            listing_state: reason === 'listing_closed' ? 'closed' : 'unknown',
            reference_only: reason === 'reference_only',
            accepting_state:
              reason === 'listing_closed' || reason === 'faculty_not_accepting'
                ? 'not_accepting'
                : 'unknown',
          },
        } as never),
        Date.parse('2026-08-18T00:00:00Z'),
      );

      expect(facts.typeLabel).toBe(typeLabel);
      expect(facts.footer).toBe(footer);
      expect(facts.showPaid).toBe(false);
      expect(facts.showOnCampus).toBe(false);
      expect(facts.showInternational).toBe(false);
      expect(facts.daysUntilDeadline).toBeNull();
      expect(facts.deadlineLabel).toBeNull();
      // Never blurred into one another: four sources said four things.
      expect(facts.typeLabel).not.toBe('research');
    });

    const UNREADABLE = [
      ['absent', undefined],
      ['null', null],
      ['malformed', { listing_state: 'open' }],
      ['self-contradicting', { ...ACTIONABLE_TRUTH, listing_state: 'closed' }],
    ] as const;

    it.each(UNREADABLE)('a %s truth is unverified, not open', (_label, truth) => {
      const record = opportunity({
        source_type: 'campus_program',
        deadline: '2026-08-20',
        deadline_is_estimate: false,
      } as never);
      const mutable = record as unknown as Record<string, unknown>;
      if (truth === undefined) delete mutable.target_truth;
      else mutable.target_truth = truth;

      const facts = buildOpportunityOgFacts(record, Date.parse('2026-08-18T00:00:00Z'));

      expect(facts.typeLabel).toBe('Status unverified');
      expect(facts.footer).toBe('Check the original source for current details');
      expect(facts.showPaid).toBe(false);
      expect(facts.showOnCampus).toBe(false);
      expect(facts.showInternational).toBe(false);
      expect(facts.daysUntilDeadline).toBeNull();
      expect(facts.deadlineLabel).toBeNull();
    });
  });
});

describe('location is an offer term on a listing and an identity fact on a person', () => {
  // The card copied `location` unconditionally. Two different lies came out of
  // that one line: a closed or inactive LISTING kept showing the job's old
  // location as though the post were still there, and a faculty row that was
  // not actionable kept its location while SILENTLY LOSING the
  // "Faculty affiliation" prefix — so a person's institution rendered in the
  // exact slot where every other card puts a job site.
  const LISTING = {
    id: 'listing-1', source_type: 'campus_program', location: 'Urbana, IL',
  } as unknown as Partial<Opportunity>;

  it('an actionable listing keeps its location, with no prefix', () => {
    const facts = buildOpportunityOgFacts(opportunity(LISTING));
    expect(facts.location).toBe('Urbana, IL');
    expect(facts.locationPrefix).toBe('');
  });

  it.each([
    ['closed', REFUSAL.listing_closed],
    ['reference-only', REFUSAL.reference_only],
    ['inactive', REFUSAL.inactive],
    ['unreadable', { listing_state: 'open' }],
  ])('a %s listing publishes no location at all', (_label, truth) => {
    const facts = buildOpportunityOgFacts(
      opportunity({ ...LISTING, target_truth: truth } as never),
    );
    expect(facts.location).toBe('');
    expect(facts.locationPrefix).toBe('');
  });

  it('an unreviewed record kind publishes no location', () => {
    const record = opportunity({ ...LISTING, location: 'Urbana, IL' } as never);
    delete (record as unknown as Record<string, unknown>).source_type;
    expect(buildOpportunityOgFacts(record).location).toBe('');
  });

  it.each([
    ['actionable', undefined],
    ['not accepting undergraduates', REFUSAL.faculty_not_accepting],
    ['inactive', REFUSAL.inactive],
    ['carrying a malformed truth', { listing_state: 'open' }],
  ])('a %s faculty record keeps its affiliation, labelled', (_label, truth) => {
    // A person's institution does not stop being true because they are not
    // taking students. What must never happen is it appearing unlabelled.
    const record = opportunity({
      source_type: 'faculty_research', location: 'Test City',
      ...(truth === undefined ? {} : { target_truth: truth }),
    } as never);
    const facts = buildOpportunityOgFacts(record);
    expect(facts.location).toBe('Test City');
    expect(facts.locationPrefix).toBe('Faculty affiliation');
  });
});
