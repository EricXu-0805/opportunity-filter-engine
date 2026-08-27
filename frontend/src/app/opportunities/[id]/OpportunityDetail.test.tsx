/* @vitest-environment jsdom */
// Narrow integration test: proves the CALLER (OpportunityDetail) actually
// remounts TrackerPanel across an identityGeneration change, via a real
// key={`${identityGeneration}:${opp.id}`} — not just that the hook exposes
// the right number (see use-opportunity-detail.test.tsx for that). Every
// OTHER child is stubbed so this stays a narrow, fast test of the wiring,
// with the REAL TrackerPanel doing the actual mount/unmount work.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useRef } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

vi.mock('@/components/StorageStatusBanner', () => ({ default: () => null }));
// Rendered as a sentinel rather than null: "the contact reveal is absent" is
// a real assertion only if a mounted one would have been visible. It records
// every mount and renders BOTH of the real component's outcomes — an unlocked
// address (a live mailto) and the signed-out prompt (which raises the auth
// modal and re-fetches the record on success). Deleting the parent's gate must
// make these tests red, not merely change which branch renders.
const contactRevealMounts = vi.hoisted(() => [] as string[]);
vi.mock('./ContactRevealSection', () => ({
  ContactRevealSection: (props: { opp: { id: string } }) => {
    contactRevealMounts.push(props.opp.id);
    return (
      <div data-testid="contact-reveal">
        <a data-testid="contact-reveal-revealed" href="mailto:pi@example.edu">email</a>
        <button data-testid="contact-reveal-sign-in" type="button">sign in to reveal</button>
      </div>
    );
  },
}));
// Visible sentinels, not nulls. Every one of these rendered `null`, so
// "the eligibility section is absent" was true of a mounted one as well —
// the parent could mount all six for a closed listing and nothing here
// would have noticed. Each sentinel is the section's real name, so a gate
// that stops gating shows up as an element that should not be on the page.
vi.mock('./DetailSections', () => ({
  DescriptionSection: () => <div data-testid="section-description" />,
  RecentWorksSection: () => <div data-testid="section-recent-works" />,
  AtAGlanceSection: () => <div data-testid="section-at-a-glance" />,
  EligibilitySection: () => <div data-testid="section-eligibility" />,
  ApplicationSection: () => <div data-testid="section-application" />,
  KeywordsSection: () => <div data-testid="section-keywords" />,
}));
vi.mock('./OpportunityHeader', () => ({
  OpportunityHeader: (props: {
    onOpenEmailModal?: () => void;
    onOpenTailorModal?: () => void;
    onOpenRenovationModal?: () => void;
  }) => (
    <div>
      {/* Withholding the opener is how the control leaves the tree entirely.
          Tailor and Renovate were reported here; Cold Email was not, so
          nothing checked that the parent stops handing it over. */}
      <span data-testid="header-email-handler">{String(Boolean(props.onOpenEmailModal))}</span>
      <span data-testid="header-tailor-handler">{String(Boolean(props.onOpenTailorModal))}</span>
      <span data-testid="header-renovate-handler">{String(Boolean(props.onOpenRenovationModal))}</span>
    </div>
  ),
}));
vi.mock('./SimilarOpportunities', () => ({ SimilarOpportunities: () => null }));
// A sentinel, not null: the student's own status pills must survive every
// posture, and "they are present" is only an assertion if a missing one
// would have been visible.
vi.mock('./InteractionPills', () => ({
  InteractionPills: () => <div data-testid="interaction-pills" />,
}));
// The Cold Email modal was never stubbed here, so nothing checked that a
// dead target stops mounting it — the real one is dynamically imported and
// simply never appeared in these tests.
vi.mock('@/components/ColdEmailModal', () => ({
  default: () => <div data-testid="cold-email-modal" />,
}));
vi.mock('./ChatDrawer', () => ({ ChatDrawer: () => <div data-testid="chat-drawer" /> }));
vi.mock('./ProfessorFollowToggle', () => ({
  ProfessorFollowToggle: () => <div data-testid="professor-follow" />,
}));
vi.mock('@/components/ResumeRenovationModal', () => ({
  default: () => <div data-testid="renovation-modal" />,
}));
vi.mock('@/components/OpportunityChatbot', () => ({
  default: () => <div data-testid="opportunity-chatbot" />,
}));
// A sentinel mock, NOT the real TailorModal: the real component has its OWN
// ownerScopeKey-driven reset effect, which would clear its draft on a prop
// change alone — a test built on the real component would stay green even
// with the parent's key REMOVED, proving nothing about the key itself. This
// sentinel's mountId is generated exactly once per genuine mount (useRef's
// initializer), so it can ONLY change via an actual unmount+remount — the
// one thing a missing key would fail to cause. The real ownerReady/
// ownerScopeKey props are rendered too, so the wiring of those (separately
// from the key) stays covered.
vi.mock('@/components/TailorModal', () => ({
  default: function MockTailorModal(props: { isOpen: boolean; ownerReady: boolean; ownerScopeKey: string | null }) {
    const mountIdRef = useRef(Math.random().toString(36).slice(2));
    if (!props.isOpen) return null;
    return (
      <div data-testid="mock-tailor-modal">
        <span data-testid="mount-id">{mountIdRef.current}</span>
        <span data-testid="owner-ready">{String(props.ownerReady)}</span>
        <span data-testid="owner-scope-key">{String(props.ownerScopeKey)}</span>
      </div>
    );
  },
}));

// A mutable copy of the release switches, defaulting to their real values.
// askAi is false in production, so `flag && actionable && <X/>` is false
// whatever `actionable` says — every "the chatbot is absent" assertion below
// would hold with the posture gate deleted. One describe turns it on so the
// gate is the only thing left deciding.
const releaseFlags = vi.hoisted(() => ({}) as Record<string, unknown>);
vi.mock('@/lib/release-scope', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/release-scope')>();
  Object.assign(releaseFlags, actual.RELEASE_SCOPE);
  return { ...actual, RELEASE_SCOPE: releaseFlags };
});

const mockHookState = vi.hoisted(() => ({ current: null as unknown }));
vi.mock('./use-opportunity-detail', () => ({
  useOpportunityDetail: () => mockHookState.current,
}));

import OpportunityDetail from './OpportunityDetail';
import { STORAGE_KEYS } from '@/lib/storage-keys';

function baseHookResult(overrides: Record<string, unknown> = {}) {
  return {
    identityGeneration: 1,
    ownerScopeKey: 'owner-1',
    isFavorited: false,
    favoriteLoading: false,
    favoriteError: false,
    retryFavoriteHydration: () => {},
    favoriteSaving: false,
    favoriteSaveError: false,
    ownerReady: true,
    interactionDetail: { type: 'applied', notes: 'U1 notes' },
    interaction: 'applied',
    interactionLoading: false,
    interactionError: false,
    retryInteractionHydration: () => {},
    statusSaving: false,
    statusError: false,
    retryTrack: () => {},
    emailModalOpen: false,
    setEmailModalOpen: () => {},
    shareCopied: false,
    chatDrawerOpen: false,
    setChatDrawerOpen: () => {},
    tailorOpen: false,
    setTailorOpen: () => {},
    renovationOpen: false,
    setRenovationOpen: () => {},
    suggestion: null,
    suggestionSaving: false,
    suggestionError: false,
    handleStar: async () => {},
    handleTrack: async () => {},
    saveDetails: async () => ({ status: 'committed' as const }),
    handleUseSuggestion: async () => {},
    handleDismissSuggestion: () => {},
    handleShare: async () => {},
    ...overrides,
  };
}

const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

// Action surfaces mount only for an actionable target, so the default fixture
// carries the truth a live record has.
const opp = {
  id: 'opp-1',
  title: 'Test Opportunity',
  // A confirmed listing, with the wire kind the server sends beside it. An
  // unreviewed source type is no longer actionable, so without this the
  // default fixture would be the 26-row exception and none of the action
  // surfaces below would mount for the reason under test.
  source_type: 'campus_program',
  record_kind: 'listing',
  target_truth: { ...ACTIONABLE_TRUTH },
} as never;

describe('OpportunityDetail — MVP capability surface', () => {
  it('keeps Tailor and Renovate while not mounting Ask AI or Professor Signals', async () => {
    window.localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({
      institution: 'UIUC', major: 'CS', grade: 'Sophomore', is_international: false,
      research_interests: 'ml', skills: [],
    }));
    mockHookState.current = baseHookResult({ tailorOpen: true, renovationOpen: true });

    render(<OpportunityDetail opp={opp} />);

    expect(screen.getByTestId('header-tailor-handler')).toHaveTextContent('true');
    expect(screen.getByTestId('header-renovate-handler')).toHaveTextContent('true');
    expect(await screen.findByTestId('mock-tailor-modal')).toBeInTheDocument();
    expect(await screen.findByTestId('renovation-modal')).toBeInTheDocument();
    expect(screen.queryByTestId('opportunity-chatbot')).not.toBeInTheDocument();
    expect(screen.queryByTestId('chat-drawer')).not.toBeInTheDocument();
    expect(screen.queryByTestId('professor-follow')).not.toBeInTheDocument();
  });
});

describe('OpportunityDetail — TrackerPanel is keyed by identityGeneration', () => {
  it('an identityGeneration bump (a real account switch) force-remounts TrackerPanel — an uncommitted local draft from the OLD identity never leaks into the NEW one, even when both share the same opportunity id', () => {
    mockHookState.current = baseHookResult({
      identityGeneration: 1,
      interactionDetail: { type: 'applied', notes: 'U1 notes' },
    });
    const { rerender } = render(<OpportunityDetail opp={opp} />);

    // detail.notes is truthy, so the panel starts already expanded.
    const textarea = screen.getByPlaceholderText('detail.tracker.notesPlaceholder') as HTMLTextAreaElement;
    expect(textarea.value).toBe('U1 notes');
    fireEvent.change(textarea, { target: { value: 'U1 unsaved draft, never blurred' } });
    expect(textarea.value).toBe('U1 unsaved draft, never blurred');

    // A real account switch — SAME opportunity id, but a NEW
    // identityGeneration and a different (U2's own) interactionDetail.
    mockHookState.current = baseHookResult({
      identityGeneration: 2,
      interactionDetail: { type: 'applied', notes: 'U2 notes' },
    });
    rerender(<OpportunityDetail opp={opp} />);

    const remounted = screen.getByPlaceholderText('detail.tracker.notesPlaceholder') as HTMLTextAreaElement;
    expect(remounted.value).toBe('U2 notes'); // fresh instance — U1's draft never leaked through
  });

  it('a re-render with the SAME identityGeneration does NOT remount TrackerPanel — an uncommitted draft survives an unrelated parent re-render', () => {
    mockHookState.current = baseHookResult({ identityGeneration: 1 });
    const { rerender } = render(<OpportunityDetail opp={opp} />);
    const textarea = screen.getByPlaceholderText('detail.tracker.notesPlaceholder') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'still typing' } });

    // Same identityGeneration — some other, unrelated state changed (e.g. shareCopied).
    mockHookState.current = baseHookResult({ identityGeneration: 1, shareCopied: true });
    rerender(<OpportunityDetail opp={opp} />);

    const stillThere = screen.getByPlaceholderText('detail.tracker.notesPlaceholder') as HTMLTextAreaElement;
    expect(stillThere.value).toBe('still typing'); // NOT remounted — draft preserved
  });
});

describe('OpportunityDetail — TailorModal is keyed by identityGeneration (C1-R2B)', () => {
  it('an identityGeneration bump force-remounts TailorModal — proven via a sentinel mount-id that can ONLY change on a genuine unmount+remount, not merely on a prop change (the real component\'s own ownerScopeKey-driven internal reset would otherwise mask a missing key). tailorOpen is kept true across BOTH renders (the mock fully controls it) to isolate the key\'s OWN protection from hydrate()\'s separate setTailorOpen(false) safety net', async () => {
    window.localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({
      institution: 'UIUC', major: 'CS', grade: 'Sophomore', is_international: false,
      research_interests: 'ml', skills: [],
    }));

    mockHookState.current = baseHookResult({
      identityGeneration: 1,
      ownerScopeKey: 'owner-1',
      tailorOpen: true,
    });
    const { rerender } = render(<OpportunityDetail opp={opp} />);
    // next/dynamic({ssr:false}) resolves the (mocked) module asynchronously
    // even in this test environment — findByTestId waits for it instead of
    // assuming a synchronous first paint.
    const mountId1 = (await screen.findByTestId('mount-id')).textContent;
    expect(screen.getByTestId('owner-ready').textContent).toBe('true');
    expect(screen.getByTestId('owner-scope-key').textContent).toBe('owner-1');

    // A real account switch — identityGeneration bumps, ownerScopeKey
    // changes, tailorOpen STAYS true (the mock doesn't flip it, unlike the
    // real hook's hydrate()) — isolating the key's own contribution.
    mockHookState.current = baseHookResult({
      identityGeneration: 2,
      ownerScopeKey: 'owner-2',
      tailorOpen: true,
    });
    rerender(<OpportunityDetail opp={opp} />);

    const mountId2 = screen.getByTestId('mount-id').textContent;
    expect(mountId2).not.toBe(mountId1); // genuinely torn down and recreated — a fresh instance
    expect(screen.getByTestId('owner-scope-key').textContent).toBe('owner-2'); // real props still flow through
  });

  it('a re-render with the SAME identityGeneration does NOT remount TailorModal — the sentinel\'s mount-id survives an unrelated parent re-render', async () => {
    window.localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({
      institution: 'UIUC', major: 'CS', grade: 'Sophomore', is_international: false,
      research_interests: 'ml', skills: [],
    }));

    mockHookState.current = baseHookResult({ identityGeneration: 1, ownerScopeKey: 'owner-1', tailorOpen: true });
    const { rerender } = render(<OpportunityDetail opp={opp} />);
    const mountId1 = (await screen.findByTestId('mount-id')).textContent;

    mockHookState.current = baseHookResult({
      identityGeneration: 1, ownerScopeKey: 'owner-1', tailorOpen: true, shareCopied: true,
    });
    rerender(<OpportunityDetail opp={opp} />);

    const mountId2 = screen.getByTestId('mount-id').textContent;
    expect(mountId2).toBe(mountId1); // NOT remounted — same instance throughout
  });
});

describe('OpportunityDetail target-truth postures', () => {
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

  function targetWith(truth: unknown) {
    // A confirmed listing in every case, so the only thing varying across the
    // matrix is the truth. Leaving the kind out would make every row here
    // fail for the same second reason and the matrix would prove nothing
    // about the postures it is named for.
    const record: Record<string, unknown> = {
      id: 'opp-1', title: 'Test Opportunity',
      source_type: 'campus_program', record_kind: 'listing',
      // Where it came from is rendered conditionally on this field. Without
      // it the "the source line survives" assertion below would fail for a
      // missing fixture rather than a missing gate.
      source: 'SOURCE_SENTINEL',
    };
    if (truth !== undefined) record.target_truth = truth;
    return record as never;
  }

  beforeEach(() => {
    window.localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({
      institution: 'UIUC', major: 'CS', grade: 'Sophomore', is_international: false,
      research_interests: 'ml', skills: [],
    }));
    contactRevealMounts.length = 0;
    mockHookState.current = baseHookResult({
      tailorOpen: true, emailModalOpen: true, renovationOpen: true, chatDrawerOpen: true,
    });
  });

  it.each(POSTURES)('mounts no action modal for a %s target', (_label, truth) => {
    render(<OpportunityDetail opp={targetWith(truth)} />);
    // Not mounted, not merely closed: a mounted modal ships its effects and
    // sits one state change away from opening.
    expect(screen.queryByTestId('mock-tailor-modal')).toBeNull();
    expect(screen.queryByTestId('renovation-modal')).toBeNull();
    expect(screen.queryByTestId('opportunity-chatbot')).toBeNull();
    expect(screen.queryByTestId('chat-drawer')).toBeNull();
  });

  it.each(POSTURES)('passes no modal openers to the header for a %s target', (_label, truth) => {
    render(<OpportunityDetail opp={targetWith(truth)} />);
    // Undefined openers, not disabled buttons: the header renders each control
    // only when it has one, so an absent opener is what removes the action
    // from the accessibility tree and the tab order.
    expect(screen.getByTestId('header-tailor-handler').textContent).toBe('false');
    expect(screen.getByTestId('header-renovate-handler').textContent).toBe('false');
  });

  it.each(POSTURES)('does not mount the contact reveal for a %s target', (_label, truth) => {
    // Revealing a contact re-fetches the record, can raise the sign-in modal,
    // and ends in a mailto — all direct actions on the target. Both of the
    // component's own states are covered by the sentinel below.
    const { container } = render(<OpportunityDetail opp={targetWith(truth)} />);
    expect(screen.queryByTestId('contact-reveal')).toBeNull();
    expect(screen.queryByTestId('contact-reveal-revealed')).toBeNull();
    expect(screen.queryByTestId('contact-reveal-sign-in')).toBeNull();
    expect(container.querySelector('a[href^="mailto:"]')).toBeNull();
    expect(contactRevealMounts).toHaveLength(0);
  });

  it('keeps the action surfaces for an actionable target', () => {
    render(<OpportunityDetail opp={targetWith({
      listing_state: 'open',
      reference_only: false,
      actionable: true,
      accepting_state: 'accepting',
      reason_code: null,
      verified_at: null,
      expires_at: null,
    })} />);
    expect(screen.getByTestId('mock-tailor-modal')).toBeInTheDocument();
    expect(screen.getByTestId('header-tailor-handler').textContent).toBe('true');
    // Both contact-reveal branches are reachable again, and the component
    // actually mounted — so the absence assertions above mean something.
    expect(contactRevealMounts).toEqual(['opp-1']);
    expect(screen.getByTestId('contact-reveal-revealed')).toBeInTheDocument();
    expect(screen.getByTestId('contact-reveal-sign-in')).toBeInTheDocument();
  });

  // -------------------------------------------------------------------
  // Which body sections exist at all
  // -------------------------------------------------------------------
  // Four blocks of offer terms — what it pays, when it closes, who may
  // apply, what to submit. The sections themselves only ever read
  // `source_type`, so a closed listing rendered its complete application
  // section directly under a banner saying the application was closed.

  const OFFER_SECTIONS = [
    'section-description', 'section-at-a-glance',
    'section-eligibility', 'section-application',
  ];
  // Never gated: the record's own history, its topics, where it came from.
  const ALWAYS = ['section-recent-works', 'section-keywords'];

  it.each(POSTURES)('mounts no offer section for a %s listing', (_label, truth) => {
    render(<OpportunityDetail opp={targetWith(truth)} />);
    for (const id of OFFER_SECTIONS) {
      expect(screen.queryByTestId(id), id).toBeNull();
    }
    for (const id of ALWAYS) {
      expect(screen.getByTestId(id), id).toBeInTheDocument();
    }
  });

  describe('with every gated capability switched on', () => {
    // Isolated to this block, and never written to the production object.
    beforeEach(() => {
      releaseFlags.askAi = true;
      releaseFlags.resumeRenovate = true;
    });
    afterEach(() => {
      releaseFlags.askAi = false;
      releaseFlags.resumeRenovate = false;
    });

    const DYNAMIC = [
      'cold-email-modal', 'mock-tailor-modal',
      'renovation-modal', 'opportunity-chatbot',
    ];

    it.each(POSTURES)('tears down every action surface when a target becomes %s', async (_label, truth) => {
      // A transition, not a fresh render. Four of these arrive through
      // next/dynamic, so querying a freshly-rendered dead target proves
      // nothing: the sentinel would be absent for a tick either way. Mount
      // them for real first, then let the same instance turn dead.
      const { rerender } = render(<OpportunityDetail opp={targetWith(ACTIONABLE_TRUTH)} />);
      for (const id of DYNAMIC) {
        expect(await screen.findByTestId(id), id).toBeInTheDocument();
      }
      expect(screen.getByTestId('chat-drawer')).toBeInTheDocument();

      rerender(<OpportunityDetail opp={targetWith(truth)} />);

      for (const id of [...DYNAMIC, 'chat-drawer']) {
        expect(screen.queryByTestId(id), id).toBeNull();
      }
      // And the openers the header would have rendered controls for.
      expect(screen.getByTestId('header-email-handler')).toHaveTextContent('false');
      expect(screen.getByTestId('header-tailor-handler')).toHaveTextContent('false');
      expect(screen.getByTestId('header-renovate-handler')).toHaveTextContent('false');
    });

    it('mounts all of them for a current listing', async () => {
      render(<OpportunityDetail opp={targetWith(ACTIONABLE_TRUTH)} />);
      expect(screen.getByTestId('header-email-handler')).toHaveTextContent('true');
      expect(screen.getByTestId('header-tailor-handler')).toHaveTextContent('true');
      expect(screen.getByTestId('header-renovate-handler')).toHaveTextContent('true');
      // These four arrive through next/dynamic, so they resolve a tick late.
      for (const id of DYNAMIC) {
        expect(await screen.findByTestId(id), id).toBeInTheDocument();
      }
      expect(screen.getByTestId('chat-drawer')).toBeInTheDocument();
    });
  });

  it.each(POSTURES)('keeps the student\'s own record of a %s target', (_label, truth) => {
    // The tracker is the student's notes about their own process. It outlives
    // the target, and none of it is a claim we are making about the target.
    render(<OpportunityDetail opp={targetWith(truth)} />);
    expect(screen.getByTestId('interaction-pills')).toBeInTheDocument();
    // By placeholder: the textarea's accessible name comes from an sr-only
    // span carrying `detail.sections.description`, which reads as the
    // opportunity's description rather than the student's notes.
    expect(
      screen.getByPlaceholderText('detail.tracker.notesPlaceholder'),
    ).toBeInTheDocument();
    // Where it came from stays readable too.
    expect(screen.getByText('detail.source')).toBeInTheDocument();
  });

  it('mounts all four for a current listing', () => {
    // The control. A parent that mounted nothing would satisfy every case
    // above and ship a detail page with no detail on it.
    render(<OpportunityDetail opp={targetWith(ACTIONABLE_TRUTH)} />);
    for (const id of [...OFFER_SECTIONS, ...ALWAYS]) {
      expect(screen.getByTestId(id), id).toBeInTheDocument();
    }
  });

  it('a live faculty profile gets every profile-shaped section', () => {
    // A directory row is a live thing to act on, and the sections already
    // implement profile-shaped variants — a projected description, the
    // faculty at-a-glance, an outreach block, and an eligibility block that
    // hides year/major/skills and keeps only the fail-closed international
    // answer and an explicit citizenship restriction.
    const faculty: Record<string, unknown> = {
      id: 'opp-1', title: 'Prof. Rivera',
      source_type: 'faculty_research', record_kind: 'faculty_contact',
      target_truth: {
        listing_state: 'unknown', reference_only: false, actionable: true,
        accepting_state: 'unknown', reason_code: null,
        verified_at: null, expires_at: null,
      },
    };
    render(<OpportunityDetail opp={faculty as never} />);

    expect(screen.getByTestId('section-description')).toBeInTheDocument();
    expect(screen.getByTestId('section-at-a-glance')).toBeInTheDocument();
    expect(screen.getByTestId('section-application')).toBeInTheDocument();
    expect(screen.getByTestId('section-eligibility')).toBeInTheDocument();
    for (const id of ALWAYS) {
      expect(screen.getByTestId(id), id).toBeInTheDocument();
    }
  });
});
