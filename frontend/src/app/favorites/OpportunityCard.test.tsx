import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { OpportunityCard } from './OpportunityCard';
import type { Opp, TFunc } from './types';

const t = ((key: string) => key) as TFunc;
const noop = () => {};

describe('OpportunityCard faculty trust boundary', () => {
  it('labels a non-professor faculty contact neutrally when expanded', () => {
    render(
      <OpportunityCard
        opp={{
          id: 'faculty-lecturer',
          title: 'Senior Lecturer profile',
          source_type: 'faculty_research',
          pi_name: 'Ada Lovelace',
        }}
        selectionMode={false}
        isSelected={false}
        selectedSize={0}
        isExpanded
        hasProfile={false}
        onToggleExpand={noop}
        onToggleSelect={noop}
        onRemove={noop}
        onOpenEmailModal={noop}
        tailorDisabled={false}
        t={t}
      />,
    );
    expect(screen.getByText('card.facultyMember')).toBeInTheDocument();
    expect(screen.queryByText('PI:')).toBeNull();
  });

  it('does not publish poisoned opening requirements when expanded', () => {
    const faculty: Opp = {
      id: 'faculty-ada',
      title: 'Ada profile',
      source_type: 'faculty_research',
      eligibility: {
        international_friendly: 'yes',
        skills_required: ['FAKE_REQUIRED_SKILL'],
      },
    };

    render(
      <OpportunityCard
        opp={faculty}
        selectionMode={false}
        isSelected={false}
        selectedSize={0}
        isExpanded
        hasProfile={false}
        onToggleExpand={noop}
        onToggleSelect={noop}
        onRemove={noop}
        onOpenEmailModal={noop}
        tailorDisabled={false}
        t={t}
      />,
    );

    expect(screen.queryByText('FAKE_REQUIRED_SKILL')).toBeNull();
    expect(screen.queryByText('favorites.requiredSkills')).toBeNull();
  });

  it('shows the undergraduate stop precisely and removes Draft Email', () => {
    const openEmail = vi.fn();
    const faculty: Opp = {
      id: 'faculty-unavailable',
      title: 'Unavailable faculty profile',
      source_type: 'faculty_research',
      faculty_availability_status: 'not_accepting_undergraduates',
      url: 'https://faculty.example/profile',
    };

    render(
      <OpportunityCard
        opp={faculty}
        selectionMode={false}
        isSelected={false}
        selectedSize={0}
        isExpanded={false}
        hasProfile
        onToggleExpand={noop}
        onToggleSelect={noop}
        onRemove={noop}
        onOpenEmailModal={openEmail}
        tailorDisabled={false}
        t={t}
      />,
    );

    expect(screen.getByText('card.facultyNotAcceptingUndergraduates')).toBeInTheDocument();
    expect(screen.queryByText('card.facultyContactUnconfirmed')).toBeNull();
    expect(screen.queryByText('card.draftEmail')).toBeNull();
    expect(openEmail).not.toHaveBeenCalled();
    expect(screen.getByText('card.viewFacultyPage')).toBeInTheDocument();
  });

  it('shows research inactivity but keeps a careful Draft Email path', () => {
    const openEmail = vi.fn();
    render(
      <OpportunityCard
        opp={{
          id: 'faculty-inactive',
          title: 'Faculty profile',
          source_type: 'faculty_research',
          faculty_availability_status: 'research_inactive',
          // Research-inactive is a precise, separate signal: the record itself
          // is still actionable, which is exactly what keeps the careful
          // Draft Email path available here.
          target_truth: {
            listing_state: 'unknown',
            reference_only: false,
            actionable: true,
            accepting_state: 'unknown',
            reason_code: null,
            verified_at: null,
            expires_at: null,
          },
        }}
        selectionMode={false}
        isSelected={false}
        selectedSize={0}
        isExpanded={false}
        hasProfile
        onToggleExpand={noop}
        onToggleSelect={noop}
        onRemove={noop}
        onOpenEmailModal={openEmail}
        tailorDisabled={false}
        t={t}
      />,
    );
    expect(screen.getByText('card.facultyResearchInactive')).toBeInTheDocument();
    expect(screen.getByText('card.draftEmail')).toBeInTheDocument();
  });
});

describe('favorites card target-truth postures', () => {
  const HISTORICAL = {
    listing_state: 'closed',
    reference_only: true,
    actionable: false,
    accepting_state: 'not_accepting',
    reason_code: 'listing_closed',
    verified_at: null,
    expires_at: null,
  } as const;

  const POSTURES: [string, unknown][] = [
    ['historical', HISTORICAL],
    ['unknown (missing)', undefined],
    ['unknown (null)', null],
    ['unknown (malformed)', { listing_state: 'open' }],
    ['unknown (self-contradicting)', { ...HISTORICAL, actionable: true }],
  ];

  function renderSaved(truth: unknown, handlers: {
    openEmail?: () => void; openTailor?: () => void; toggleSelect?: () => void;
    selectionMode?: boolean;
  } = {}) {
    const opp: Record<string, unknown> = {
      id: 'saved-1',
      title: 'A listing saved last term',
      source_type: 'campus_program',
      url: 'https://example.edu/source',
    };
    if (truth !== undefined) opp.target_truth = truth;
    return render(
      <OpportunityCard
        opp={opp as never}
        selectionMode={handlers.selectionMode ?? false}
        isSelected={false}
        selectedSize={0}
        isExpanded
        hasProfile
        onToggleExpand={noop}
        onToggleSelect={handlers.toggleSelect ?? noop}
        onRemove={noop}
        onOpenEmailModal={handlers.openEmail ?? noop}
        onOpenTailorModal={handlers.openTailor ?? noop}
        tailorDisabled={false}
        t={t}
      />,
    );
  }

  it.each(POSTURES)('offers no action controls on a %s saved target', (_label, truth) => {
    renderSaved(truth);
    // The card stays — that is what a shortlist is for — but nothing on it
    // acts on the target.
    expect(screen.queryByText('card.draftEmail')).toBeNull();
    expect(screen.queryByText('card.tailorResume')).toBeNull();
  });

  it.each(POSTURES)('keeps the source link readable on a %s saved target', (_label, truth) => {
    const { container } = renderSaved(truth);
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('https://example.edu/source');
  });

  it.each(POSTURES)('cannot be added to a comparison as a %s target', (_label, truth) => {
    // The overlay is a <button>, not an <input type="checkbox">. The query
    // that used to stand here returned null every time, so the click never
    // happened and the expectation never ran — the test passed on an empty
    // body. Grabbing the real control makes both halves real.
    const toggleSelect = vi.fn();
    renderSaved(truth, { toggleSelect, selectionMode: true });

    const overlay = screen.getByRole('button', { name: 'favorites.toggleSelectAria' });
    expect(overlay).toBeDisabled();
    fireEvent.click(overlay);
    expect(toggleSelect).not.toHaveBeenCalled();
  });

  it('CAN be added to a comparison as an actionable target', () => {
    // The control the matrix above needs: a card that refuses every target
    // would satisfy all five rows and break the compare feature outright.
    const toggleSelect = vi.fn();
    renderSaved({
      listing_state: 'open', reference_only: false, actionable: true,
      accepting_state: 'accepting', reason_code: null,
      verified_at: null, expires_at: null,
    }, { toggleSelect, selectionMode: true });

    const overlay = screen.getByRole('button', { name: 'favorites.toggleSelectAria' });
    expect(overlay).not.toBeDisabled();
    fireEvent.click(overlay);
    expect(toggleSelect).toHaveBeenCalledTimes(1);
  });

  it.each(POSTURES)('reads a source_url-only %s saved record', (_label, truth) => {
    // A historical row may carry only the page the collector read. Reading
    // `url` alone would keep the card and lose its only permitted link.
    const opp: Record<string, unknown> = {
      id: 'saved-src-only',
      title: 'Saved with only a source_url',
      source_type: 'campus_program',
      source_url: 'https://example.edu/scraped',
    };
    if (truth !== undefined) opp.target_truth = truth;
    const { container } = render(
      <OpportunityCard
        opp={opp as never}
        selectionMode={false}
        isSelected={false}
        selectedSize={0}
        isExpanded
        hasProfile
        onToggleExpand={noop}
        onToggleSelect={noop}
        onRemove={noop}
        onOpenEmailModal={noop}
        tailorDisabled={false}
        t={t}
      />,
    );
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('https://example.edu/scraped');
  });

  it('prefers source_url over url when a saved record carries both', () => {
    const opp = {
      id: 'saved-both',
      title: 'Saved with both links',
      source_type: 'campus_program',
      url: 'https://example.edu/display',
      source_url: 'https://example.edu/scraped',
    };
    const { container } = render(
      <OpportunityCard
        opp={opp as never}
        selectionMode={false}
        isSelected={false}
        selectedSize={0}
        isExpanded
        hasProfile
        onToggleExpand={noop}
        onToggleSelect={noop}
        onRemove={noop}
        onOpenEmailModal={noop}
        tailorDisabled={false}
        t={t}
      />,
    );
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('https://example.edu/scraped');
    expect(hrefs).not.toContain('https://example.edu/display');
  });

  it('never lets a custom import into a comparison', () => {
    const toggleSelect = vi.fn();
    render(
      <OpportunityCard
        opp={{ id: 'custom-1', title: 'Typed in by hand', _customId: 'c1' } as never}
        selectionMode
        isSelected={false}
        selectedSize={0}
        isExpanded={false}
        hasProfile
        onToggleExpand={noop}
        onToggleSelect={toggleSelect}
        onRemove={noop}
        onOpenEmailModal={noop}
        tailorDisabled={false}
        t={t}
      />,
    );
    // Same fix as above: the overlay is a button, and the old checkbox query
    // meant this test asserted nothing at all.
    const overlay = screen.getByRole('button', { name: 'favorites.toggleSelectAria' });
    expect(overlay).toBeDisabled();
    fireEvent.click(overlay);
    expect(toggleSelect).not.toHaveBeenCalled();
  });

  it('keeps every control for an actionable saved target', () => {
    renderSaved({
      listing_state: 'open',
      reference_only: false,
      actionable: true,
      accepting_state: 'accepting',
      reason_code: null,
      verified_at: null,
      expires_at: null,
    });
    expect(screen.getByText('card.draftEmail')).toBeInTheDocument();
    expect(screen.getByText('card.tailorResume')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// A shortlist is read weeks after it was built
// ---------------------------------------------------------------------------

const LIVE_TRUTH = {
  listing_state: 'open', reference_only: false, actionable: true,
  accepting_state: 'accepting', reason_code: null,
  verified_at: null, expires_at: null,
} as const;

const OFFER_POISON = {
  opportunity_type: 'POISON_TYPE',
  paid: 'yes',
  location: 'POISON Urbana, IL',
  deadline: '2099-12-31',
  deadline_is_estimate: false,
  description_clean: 'POISON stipend paid monthly, apply by Friday',
  eligibility: {
    international_friendly: 'yes',
    skills_required: ['POISON_REQUIRED_SKILL'],
  },
  keywords: ['machine learning'],
  pi_name: 'Ada Lovelace',
  lab_or_program: 'Vision Lab',
  department: 'ECE',
  source: 'campus_scrape',
  url: 'https://example.edu/source',
};

const OFFER_TEXT = [
  'POISON_TYPE', 'badges.paid', 'badges.intlOk',
  'POISON Urbana, IL', '2099-12-31',
  'POISON stipend paid monthly, apply by Friday',
  'POISON_REQUIRED_SKILL', 'favorites.requiredSkills',
];

// Each non-actionable shape with the ONE label it may carry. `compare.status.*`
// is the shared vocabulary MatchCard also borrows.
const LISTING_KIND = { source_type: 'campus_program', record_kind: 'listing' };

const SAVED_DEAD: Array<[string, Record<string, unknown>, unknown, string]> = [
  ['closed', LISTING_KIND, {
    listing_state: 'closed', reference_only: false, actionable: false,
    accepting_state: 'not_accepting', reason_code: 'listing_closed',
    verified_at: null, expires_at: null,
  }, 'compare.status.closed'],
  ['reference-only', LISTING_KIND, {
    listing_state: 'unknown', reference_only: true, actionable: false,
    accepting_state: 'unknown', reason_code: 'reference_only',
    verified_at: null, expires_at: null,
  }, 'compare.status.reference'],
  ['inactive', LISTING_KIND, {
    listing_state: 'unknown', reference_only: false, actionable: false,
    accepting_state: 'unknown', reason_code: 'inactive',
    verified_at: null, expires_at: null,
  }, 'compare.status.inactive'],
  // The availability status travels with the truth — it is where the reason
  // comes from — and the card's own red badge states it, so the shared
  // status label stands down for this one.
  ['faculty who said no', {
    source_type: 'faculty_research',
    record_kind: 'faculty_contact',
    faculty_availability_status: 'not_accepting_undergraduates',
  }, {
    listing_state: 'unknown', reference_only: false, actionable: false,
    accepting_state: 'not_accepting', reason_code: 'faculty_not_accepting',
    verified_at: null, expires_at: null,
  }, 'card.facultyNotAcceptingUndergraduates'],
  // A source type outside the listing allowlist, with the matching wire kind
  // so the derived/wire agreement check actually runs.
  ['unreviewed kind', {
    source_type: 'departmental_newsletter', record_kind: 'unknown',
  }, {
    listing_state: 'unknown', reference_only: false, actionable: false,
    accepting_state: 'unknown', reason_code: 'record_kind_unverified',
    verified_at: null, expires_at: null,
  }, 'compare.status.kindUnverified'],
  ['unreadable truth', LISTING_KIND,
    { listing_state: 'open' }, 'compare.status.unverified'],
];

const ALL_STATUS = [
  ...SAVED_DEAD.map(([, , , key]) => key), 'compare.status.notAccepting',
];

function renderCard(extra: Record<string, unknown>) {
  return render(
    <OpportunityCard
      opp={{ id: 'saved-1', title: 'A listing saved last term', ...extra } as never}
      selectionMode={false}
      isSelected={false}
      selectedSize={0}
      isExpanded
      hasProfile
      onToggleExpand={noop}
      onToggleSelect={noop}
      onRemove={noop}
      onOpenEmailModal={noop}
      onOpenTailorModal={noop}
      tailorDisabled={false}
      t={t}
    />,
  );
}

describe('OpportunityCard — a saved target we can no longer vouch for', () => {
  it.each(SAVED_DEAD)('shows no offer term for a %s target', (_label, kind, truth) => {
    renderCard({ ...OFFER_POISON, ...kind, target_truth: truth });
    for (const text of OFFER_TEXT) {
      expect(screen.queryByText(text), text).toBeNull();
    }
  });

  it.each(SAVED_DEAD)('gives a %s target its own status label and no other', (_label, kind, truth, key) => {
    renderCard({ ...OFFER_POISON, ...kind, target_truth: truth });
    expect(screen.getByText(key)).toBeInTheDocument();
    for (const other of ALL_STATUS.filter((s) => s !== key)) {
      expect(screen.queryByText(other), other).toBeNull();
    }
  });

  it.each(SAVED_DEAD)('keeps what the student saved on a %s target', (_label, kind, truth) => {
    renderCard({ ...OFFER_POISON, ...kind, target_truth: truth });
    expect(screen.getByText('A listing saved last term')).toBeInTheDocument();
    // Who and where the research is — identity, not terms.
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText('Vision Lab')).toBeInTheDocument();
    expect(screen.getByText('ECE')).toBeInTheDocument();
    expect(screen.getByText('machine learning')).toBeInTheDocument();
    // Where it came from, and the student's own control over their list.
    expect(screen.getByText('campus_scrape')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'favorites.removeAria' })).toBeInTheDocument();
    // The link goes to a source page and says so — not "View Details",
    // which promises the current details of an opening. A faculty page is a
    // faculty page whatever the posture.
    const isFacultyRow = kind.source_type === 'faculty_research';
    const link = screen.getByRole('link', {
      name: isFacultyRow ? 'card.viewFacultyPage' : 'favorites.viewSourceRecord',
    });
    expect(link).toHaveAttribute('href', 'https://example.edu/source');
    expect(screen.queryByText('card.viewDetails')).toBeNull();
  });

  it('keeps every one of those terms while the listing IS current', () => {
    renderCard({ ...OFFER_POISON, source_type: 'campus_program', target_truth: { ...LIVE_TRUTH } });
    for (const text of OFFER_TEXT) {
      expect(screen.getByText(text), text).toBeInTheDocument();
    }
    expect(screen.getByRole('link', { name: 'card.viewDetails' })).toBeInTheDocument();
    for (const status of ALL_STATUS) {
      expect(screen.queryByText(status), status).toBeNull();
    }
  });

  it('a live faculty profile keeps its affiliation and profile text but states no terms', () => {
    renderCard({
      ...OFFER_POISON,
      source_type: 'faculty_research',
      record_kind: 'faculty_contact',
      location: 'Urbana, IL',
      // A profile's own text, not the listing pitch. Handing the offer
      // poison to the faculty control would make "the description survives"
      // and "the offer terms are gone" contradict each other.
      description_clean: 'Faculty research profile: computer vision and medical imaging.',
      target_truth: {
        listing_state: 'unknown', reference_only: false, actionable: true,
        accepting_state: 'unknown', reason_code: null,
        verified_at: null, expires_at: null,
      },
    });
    expect(screen.getByText('card.facultyContactUnconfirmed')).toBeInTheDocument();
    expect(screen.getByText('favorites.facultyAffiliationLocation')).toBeInTheDocument();
    // Profile text survives; every term of an offer does not.
    expect(
      screen.getByText('Faculty research profile: computer vision and medical imaging.'),
    ).toBeInTheDocument();
    for (const text of ['POISON_TYPE', 'badges.paid', 'badges.intlOk',
      '2099-12-31', 'POISON_REQUIRED_SKILL',
      'POISON stipend paid monthly, apply by Friday']) {
      expect(screen.queryByText(text), text).toBeNull();
    }
    for (const status of ALL_STATUS) {
      expect(screen.queryByText(status), status).toBeNull();
    }
  });

  it('a custom entry keeps exactly what its owner typed, and is never given a server status', () => {
    // Nobody ever collected this record, so we have no finding to report
    // about it. A "status unconfirmed" badge here would be us presenting our
    // own silence as a fact about the user's own note.
    renderCard({ ...OFFER_POISON, _customId: 'c1' });
    expect(screen.getByText('favorites.customBadge')).toBeInTheDocument();
    for (const text of OFFER_TEXT) {
      expect(screen.getByText(text), text).toBeInTheDocument();
    }
    // Including the eligibility the student typed. This used to read "not
    // disclosed": the entry has no reviewed source type, so the collector
    // rule failed it closed — an answer about a scrape, applied to a note
    // its owner had just written.
    expect(screen.getByText('badges.intlOk')).toBeInTheDocument();
    for (const status of ALL_STATUS) {
      expect(screen.queryByText(status), status).toBeNull();
    }
    expect(screen.getByRole('link', { name: 'favorites.openSource' })).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'favorites.removeCustomAria' }),
    ).toBeInTheDocument();
  });
});
