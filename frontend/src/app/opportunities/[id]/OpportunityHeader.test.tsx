import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { Opportunity, ProfileData } from '@/lib/types';

vi.mock('@/components/ResponsivenessBadge', () => ({
  default: () => <span>unaccepted-professor-signal</span>,
}));

import { OpportunityHeader } from './OpportunityHeader';

// Every action on this header gates on the server-stamped truth, so the
// default fixture carries the shape a live record has.
export const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

const OPP = {
  id: 'opp-1',
  title: 'Research Opportunity',
  organization: 'Example Lab',
  opportunity_type: 'Research',
  // A confirmed listing: reviewed source type plus the wire kind the server
  // sends with it. Tests that need an unreviewed or faculty record override
  // these explicitly.
  source_type: 'campus_program',
  record_kind: 'listing',
  target_truth: { ...ACTIONABLE_TRUTH },
  metadata: { is_active: true, confidence_score: 0.9 },
} as unknown as Opportunity;

// A live faculty profile as the backend actually emits one: a directory page
// states no listing and no acceptance, so both are `unknown` — never the
// (open, accepting) pair a confirmed listing carries. Overriding only
// `source_type` on the listing fixture leaves an impossible record whose wire
// kind and truth both belong to something else.
const FACULTY_TRUTH = {
  listing_state: 'unknown',
  reference_only: false,
  actionable: true,
  accepting_state: 'unknown',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

function facultyOpp(overrides: Record<string, unknown> = {}): Opportunity {
  return {
    ...OPP,
    source_type: 'faculty_research',
    record_kind: 'faculty_contact',
    target_truth: { ...FACULTY_TRUTH },
    ...overrides,
  } as unknown as Opportunity;
}

const PROFILE = {
  institution: 'Example University',
  major: 'Computer Science',
  grade: 'Junior',
  research_interests: 'machine learning',
  skills: [{ name: 'Python', level: 'experienced' }],
} as ProfileData;

const noop = () => {};
const t = (key: string) => key;

function renderHeader(overrides: Partial<React.ComponentProps<typeof OpportunityHeader>> = {}) {
  return render(
    <OpportunityHeader
      opp={OPP}
      profile={PROFILE}
      isFavorited={false}
      favoriteDisabled={false}
      favoriteBusy={false}
      shareCopied={false}
      onStar={noop}
      onOpenEmailModal={noop}
      onOpenTailorModal={noop}
      tailorDisabled={false}
      onOpenRenovationModal={undefined}
      onShare={noop}
      t={t}
      {...overrides}
    />,
  );
}

describe('OpportunityHeader MVP release surface', () => {
  it('badges a remote posting using the values the pipeline writes', () => {
    // The badge tested `remote_option === 'yes'`. The corpus vocabulary is
    // {unknown, no, remote, hybrid, null} — 'yes' does not occur once — so it
    // was unreachable for 100% of traffic while 67 genuinely remote or hybrid
    // records showed nothing.
    renderHeader({ opp: { ...OPP, remote_option: 'remote' } as unknown as typeof OPP });
    expect(screen.getByText('badges.remoteOk')).toBeInTheDocument();
  });

  it('distinguishes hybrid from fully remote', () => {
    renderHeader({ opp: { ...OPP, remote_option: 'hybrid' } as unknown as typeof OPP });
    expect(screen.getByText('badges.hybrid')).toBeInTheDocument();
    expect(screen.queryByText('badges.remoteOk')).toBeNull();
  });

  it('badges nothing when the posting says on-site or says nothing', () => {
    for (const value of ['no', 'unknown']) {
      const { unmount } = renderHeader({
        opp: { ...OPP, remote_option: value } as unknown as typeof OPP,
      });
      expect(screen.queryByText('badges.remoteOk')).toBeNull();
      expect(screen.queryByText('badges.hybrid')).toBeNull();
      unmount();
    }
  });

  it('hedges the pay badge when the pay value was read off the page', () => {
    // "in many cases, funding or a stipend" set paid: yes on 220 records via a
    // substring scan. A green "Paid" is a student planning a summer around it.
    renderHeader({
      opp: { ...OPP, paid: 'yes', paid_attribution: 'inferred' } as unknown as typeof OPP,
    });
    expect(screen.getByText('badges.fundingMentioned')).toBeInTheDocument();
    expect(screen.queryByText('badges.paid')).toBeNull();
  });

  it('keeps the plain pay badge when the posting stated it', () => {
    renderHeader({ opp: { ...OPP, paid: 'yes' } as unknown as typeof OPP });
    expect(screen.getByText('badges.paid')).toBeInTheDocument();
    expect(screen.queryByText('badges.fundingMentioned')).toBeNull();
  });

  it('keeps Tailor while hiding Professor Signals', () => {
    renderHeader();

    expect(screen.getByText('card.tailorResume')).toBeInTheDocument();
    expect(screen.queryByText('unaccepted-professor-signal')).not.toBeInTheDocument();
  });

  it('labels a faculty directory record as a contact, not a confirmed opening', () => {
    renderHeader({
      opp: facultyOpp({
        url: 'https://faculty.example.edu/real-profile',
        paid: 'yes',
        on_campus: true,
        remote_option: 'yes',
        deadline: '2020-01-01',
        deadline_is_estimate: false,
        eligibility: {
          international_friendly: 'yes',
          citizenship_required: false,
          preferred_year: [],
          majors: [],
          skills_required: [],
        },
        application: {
          application_effort: 'unknown',
          requires_resume: 'unknown',
          contact_method: 'email',
          application_url: 'https://fake.example.edu/apply',
        },
      }),
    });
    expect(screen.getByText('card.facultyContactUnconfirmed')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'detail.viewFacultyProfile' })).toHaveAttribute(
      'href',
      'https://faculty.example.edu/real-profile',
    );
    expect(screen.queryByRole('link', { name: 'detail.apply' })).not.toBeInTheDocument();
    expect(screen.queryByText('badges.paid')).not.toBeInTheDocument();
    expect(screen.queryByText('badges.onCampus')).not.toBeInTheDocument();
    expect(screen.queryByText('badges.remoteOk')).not.toBeInTheDocument();
    expect(screen.queryByText('badges.internationalFriendly')).not.toBeInTheDocument();
    expect(screen.queryByText('badges.pastDeadline')).not.toBeInTheDocument();
    expect(screen.queryByText('2020-01-01')).not.toBeInTheDocument();
  });

  it('renders an undergraduate stop state and hides Draft Email', () => {
    renderHeader({
      opp: facultyOpp({
        faculty_availability_status: 'not_accepting_undergraduates',
        // The truth the backend stamps alongside that status. An actionable
        // truth here would be a combination the current wire never produces,
        // and the badge would then be tested against an impossible record.
        target_truth: {
          listing_state: 'unknown',
          reference_only: false,
          actionable: false,
          accepting_state: 'not_accepting',
          reason_code: 'faculty_not_accepting',
          verified_at: null,
          expires_at: null,
        },
        url: 'https://faculty.example.edu/profile',
      }),
    });

    expect(screen.getByText('card.facultyNotAcceptingUndergraduates')).toBeInTheDocument();
    expect(screen.queryByText('card.facultyContactUnconfirmed')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'detail.draftEmail' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'detail.viewFacultyProfile' })).toBeInTheDocument();
  });

  it.each([
    ['open but not accepting-stated', { listing_state: 'open', accepting_state: 'unknown' }],
    ['unstamped yet claiming to accept', { listing_state: 'unknown', accepting_state: 'accepting' }],
  ])('suspends every CTA for a live truth that is %s', (_label, fields) => {
    // Both claim `actionable`. Neither is a shape the backend emits, so the
    // page cannot vouch for the record — and Apply, Draft Email and Tailor
    // all unlock off exactly that vouching.
    renderHeader({
      opp: {
        ...OPP,
        target_truth: { ...ACTIONABLE_TRUTH, ...fields },
        application: { application_url: 'https://example.edu/apply-here' },
        url: 'https://example.edu/source',
      } as Opportunity,
    });

    expect(screen.getByText('detail.unverifiedBanner')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'detail.apply' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'detail.draftEmail' })).not.toBeInTheDocument();
    expect(screen.queryByText('card.tailorResume')).not.toBeInTheDocument();
    expect(screen.queryByText('apply-here')).not.toBeInTheDocument();
  });

  it('gives the faculty stop its own banner, not the closed-listing one', () => {
    // The server-stamped truth, not just the legacy status field. Without
    // `target_truth` the posture is `unknown` and the vague banner renders,
    // which would let a wrong branch pass unnoticed.
    renderHeader({
      opp: facultyOpp({
        faculty_availability_status: 'not_accepting_undergraduates',
        // The canonical refusal shape for this reason, overriding the live
        // faculty truth the helper supplies.
        target_truth: {
          listing_state: 'unknown',
          reference_only: false,
          actionable: false,
          accepting_state: 'not_accepting',
          reason_code: 'faculty_not_accepting',
          verified_at: null,
          expires_at: null,
        },
        application: { application_url: 'https://example.edu/apply-here' },
        url: 'https://faculty.example.edu/profile',
      }),
    });

    expect(screen.getByText('detail.notAcceptingBanner')).toBeInTheDocument();
    // None of the other three explanations. A closed listing, a reference
    // record and a deactivated row are different facts about different things.
    expect(screen.queryByText('detail.closedBanner')).not.toBeInTheDocument();
    expect(screen.queryByText('detail.referenceBanner')).not.toBeInTheDocument();
    expect(screen.queryByText('detail.inactiveBanner')).not.toBeInTheDocument();
    expect(screen.queryByText('detail.unverifiedBanner')).not.toBeInTheDocument();

    // Every outbound action is gone, not merely disabled: a disabled control
    // still sits in the accessibility tree and still says the action exists.
    expect(screen.queryByRole('link', { name: 'detail.apply' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'detail.draftEmail' })).not.toBeInTheDocument();
    expect(screen.queryByText('card.tailorResume')).not.toBeInTheDocument();
    expect(screen.queryByText('card.renovateResume')).not.toBeInTheDocument();
    expect(screen.queryByText('apply-here')).not.toBeInTheDocument();
    // Reading the source stays available — that is what "kept for reference"
    // means.
    expect(screen.getByRole('link', { name: 'detail.viewFacultyProfile' })).toBeInTheDocument();
  });

  it('renders research inactivity as a warning without disabling an inquiry', () => {
    renderHeader({
      opp: facultyOpp({ faculty_availability_status: 'research_inactive' }),
    });
    expect(screen.getByText('card.facultyResearchInactive')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'detail.draftEmail' })).toBeInTheDocument();
  });

  it('shows Renovate only when the parent supplies its handler', () => {
    // This leaf does not read the release flag. OpportunityDetail owns the
    // public gate; this preserves dormant implementation coverage without
    // making the MVP surface reachable.
    renderHeader();
    expect(screen.queryByText('card.renovateResume')).not.toBeInTheDocument();

    renderHeader({ onOpenRenovationModal: noop });
    expect(screen.getByText('card.renovateResume')).toBeInTheDocument();
  });
});

/** A local calendar date `days` ahead, so daysUntil's local parse is exact. */
function localDateIn(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return [
    d.getFullYear(),
    `${d.getMonth() + 1}`.padStart(2, '0'),
    `${d.getDate()}`.padStart(2, '0'),
  ].join('-');
}

// Everything a listing carries, all of it poisonous. The record IS a listing —
// a reviewed source type, the wire kind to match — so nothing here is in doubt
// except whether the offer is still on.
const OFFER_POISON = {
  opportunity_type: 'POISON_TYPE',
  paid: 'yes',
  on_campus: true,
  // The value the pipeline writes. This said 'yes', which the corpus
  // vocabulary {unknown, no, remote, hybrid, null} does not contain — so the
  // control below asserted a badge that production could never render, and
  // the dead badge went unnoticed.
  remote_option: 'remote',
  location: 'POISON Urbana, IL',
  // Tomorrow, computed at run time. A date in 2099 produces no urgency band
  // at all, so every "no countdown" assertion below would hold with the
  // deadline gate deleted — the single-point mutant would survive.
  deadline: localDateIn(1),
  deadline_is_estimate: false,
  eligibility: {
    international_friendly: 'yes',
    citizenship_required: false,
    preferred_year: [], majors: [], skills_required: [],
  },
  application: {
    application_effort: 'low',
    requires_resume: 'yes',
    contact_method: 'email',
    application_url: 'https://example.edu/apply-here',
  },
  url: 'https://example.edu/source',
};

// `POISON TYPE`, not `POISON_TYPE`: formatType turns the underscore into a
// space before rendering, so asserting the raw field value would be an
// assertion that can never match — vacuous in both directions.
const OFFER_BADGES = [
  'POISON TYPE', 'badges.paid', 'badges.onCampus', 'badges.remoteOk',
  'badges.internationalFriendly', 'POISON Urbana, IL',
];

// Every non-actionable shape, each with the ONE banner it is allowed to show.
// Four of these used to be three: `record_kind_unverified` fell off the end of
// the ternary chain onto `detail.closedBanner`, telling a student an
// application window had shut on a record nobody had reviewed.
const DEAD_STATES: Array<[string, Record<string, unknown>, unknown, string]> = [
  ['closed listing', { source_type: 'campus_program', record_kind: 'listing' }, {
    listing_state: 'closed', reference_only: false, actionable: false,
    accepting_state: 'not_accepting', reason_code: 'listing_closed',
    verified_at: null, expires_at: null,
  }, 'detail.closedBanner'],
  ['reference record', { source_type: 'campus_program', record_kind: 'listing' }, {
    listing_state: 'unknown', reference_only: true, actionable: false,
    accepting_state: 'unknown', reason_code: 'reference_only',
    verified_at: null, expires_at: null,
  }, 'detail.referenceBanner'],
  ['deactivated record', { source_type: 'campus_program', record_kind: 'listing' }, {
    listing_state: 'unknown', reference_only: false, actionable: false,
    accepting_state: 'unknown', reason_code: 'inactive',
    verified_at: null, expires_at: null,
  }, 'detail.inactiveBanner'],
  // The availability status travels with the truth, because that status is
  // where the reason comes from. Without it the record would be refused for a
  // reason nothing on it states.
  ['faculty who said no', {
    source_type: 'faculty_research',
    record_kind: 'faculty_contact',
    faculty_availability_status: 'not_accepting_undergraduates',
  }, {
    listing_state: 'unknown', reference_only: false, actionable: false,
    accepting_state: 'not_accepting', reason_code: 'faculty_not_accepting',
    verified_at: null, expires_at: null,
  }, 'detail.notAcceptingBanner'],
  // Only an unreviewed kind may claim this reason — see readTruth. A source
  // type outside the listing allowlist WITH the matching wire kind, so the
  // derived/wire agreement check actually runs; deleting both fields would
  // skip it entirely.
  ['unreviewed kind', {
    source_type: 'departmental_newsletter', record_kind: 'unknown',
  }, {
    listing_state: 'unknown', reference_only: false, actionable: false,
    accepting_state: 'unknown', reason_code: 'record_kind_unverified',
    verified_at: null, expires_at: null,
  }, 'detail.kindUnverifiedBanner'],
  // Not a reason at all: a truth this build cannot parse.
  ['unreadable truth', { source_type: 'campus_program', record_kind: 'listing' },
    { listing_state: 'open' }, 'detail.unverifiedBanner'],
];

const ALL_BANNERS = DEAD_STATES.map(([, , , key]) => key);

describe('OpportunityHeader — a target we cannot vouch for states no terms', () => {
  function renderDead(kind: Record<string, unknown>, truth: unknown) {
    return renderHeader({
      opp: { ...OPP, ...OFFER_POISON, ...kind, target_truth: truth } as unknown as Opportunity,
    });
  }

  it.each(DEAD_STATES)('shows no offer term for a %s', (_label, kind, truth) => {
    renderDead(kind, truth);
    for (const text of OFFER_BADGES) {
      expect(screen.queryByText(text)).toBeNull();
    }
    // No deadline phrasing of any kind: not the date, not "past deadline",
    // and — since the fixture's deadline is tomorrow — not the urgency band
    // that a live listing genuinely renders for it.
    expect(screen.queryByText(OFFER_POISON.deadline)).toBeNull();
    expect(screen.queryByText('badges.pastDeadline')).toBeNull();
    expect(screen.queryByText(/^deadline\./)).toBeNull();
    // A refused target is never also announced as an unconfirmed contact:
    // for a listing there is no such badge, and for the faculty stop the red
    // one above already says it in the source's own words.
    expect(screen.queryByText('card.facultyContactUnconfirmed')).toBeNull();
  });

  it.each(DEAD_STATES)('gives a %s its own banner and no other', (_label, kind, truth, key) => {
    renderDead(kind, truth);
    expect(screen.getByText(key)).toBeInTheDocument();
    for (const other of ALL_BANNERS.filter((b) => b !== key)) {
      expect(screen.queryByText(other)).toBeNull();
    }
  });

  it.each(DEAD_STATES)('keeps identity, source and the star for a %s', (_label, kind, truth) => {
    renderDead(kind, truth);
    expect(screen.getByText('Research Opportunity')).toBeInTheDocument();
    expect(screen.getByText('Example Lab')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'detail.favoriteAdd' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'detail.share' })).toBeInTheDocument();
    // Readable at the source, and never under an Apply label.
    expect(screen.queryByRole('link', { name: 'detail.apply' })).toBeNull();
    const source = screen.getByRole('link', {
      name: kind.source_type === 'faculty_research'
        ? 'detail.viewFacultyProfile'
        : 'detail.viewSource',
    });
    expect(source).toHaveAttribute('href', 'https://example.edu/source');
  });

  it('keeps every one of those terms while the listing IS current', () => {
    // The control. Hiding all of it unconditionally passes every case above.
    renderHeader({
      opp: { ...OPP, ...OFFER_POISON, target_truth: { ...ACTIONABLE_TRUTH } } as unknown as Opportunity,
    });
    for (const text of OFFER_BADGES) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    // The countdown the dead cases must not have. Tomorrow is one day out, so
    // this is the singular phrasing rather than the {days} one.
    expect(screen.getByText('deadline.urgentSingle')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'detail.apply' })).toBeInTheDocument();
    for (const banner of ALL_BANNERS) {
      expect(screen.queryByText(banner)).toBeNull();
    }
  });

  it('a live faculty profile keeps its affiliation and contact framing but states no terms', () => {
    // The other control, and the one that separates "hide everything for a
    // non-listing" from "hide the terms of an offer". A directory row is a
    // live thing to act on; it just has no offer.
    renderHeader({
      opp: facultyOpp({ ...OFFER_POISON, location: 'Urbana, IL' }),
    });
    expect(screen.getByText('card.facultyContactUnconfirmed')).toBeInTheDocument();
    expect(
      screen.getByText('detail.fields.facultyAffiliationLocation'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'detail.draftEmail' })).toBeInTheDocument();
    for (const text of ['POISON TYPE', 'badges.paid', 'badges.onCampus',
      'badges.remoteOk', 'badges.internationalFriendly', OFFER_POISON.deadline]) {
      expect(screen.queryByText(text)).toBeNull();
    }
    expect(screen.queryByText(/^deadline\./)).toBeNull();
    for (const banner of ALL_BANNERS) {
      expect(screen.queryByText(banner)).toBeNull();
    }
  });
});

describe('OpportunityHeader favorite control — disabled vs busy', () => {
  it('is enabled and not busy in the normal (idle) state', () => {
    renderHeader({ favoriteDisabled: false, favoriteBusy: false });
    const star = screen.getByRole('button', { name: 'detail.favoriteAdd' });
    expect(star).not.toBeDisabled();
    expect(star).toHaveAttribute('aria-busy', 'false');
  });

  it('is disabled and busy while hydration/save is actually in flight', () => {
    renderHeader({ favoriteDisabled: true, favoriteBusy: true });
    const star = screen.getByRole('button', { name: 'detail.favoriteAdd' });
    expect(star).toBeDisabled();
    expect(star).toHaveAttribute('aria-busy', 'true');
  });

  it('is disabled but NOT busy after a hydration failure — an error is not "busy", and Retry (elsewhere) is the only recovery path', () => {
    renderHeader({ favoriteDisabled: true, favoriteBusy: false });
    const star = screen.getByRole('button', { name: 'detail.favoriteAdd' });
    expect(star).toBeDisabled();
    expect(star).toHaveAttribute('aria-busy', 'false');
  });
});
