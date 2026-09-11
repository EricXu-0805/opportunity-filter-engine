/*
 * Tail4: results/page.tsx -> MatchList caller-wiring. Everything MatchList
 * itself does with ownerReady/identityGeneration/ownerScopeKey (threading
 * to MatchCard, keying the Tailor subtree, gating the CTA) is already
 * proven with REAL MatchList+MatchCard in MatchList.test.tsx. What no test
 * currently covers is the ONE hop upstream of that: does page.tsx actually
 * read useResultsInteractions()'s return and forward the SAME three values
 * into <MatchList>'s props — the "page.tsx computes it right, MatchList
 * never receives it" class of regression (e.g. a merge dropping a prop, or
 * wiring the wrong local variable into the right prop name, which tsc
 * cannot catch since it only checks the prop's TYPE, not its origin).
 *
 * MatchList itself is therefore a SENTINEL here (mirrors how
 * OpportunityDetail.test.tsx mocks TailorModal directly, and
 * favorites/page.test.tsx mocks OpportunityCard+TailorModal, to isolate
 * the ONE hop each page owns) — real MatchList/MatchCard are exercised in
 * their own test file, not re-tested here.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

const routerRef = { replace: vi.fn(), refresh: vi.fn(), push: vi.fn() };
vi.mock('next/navigation', () => ({
  useRouter: () => routerRef,
  useSearchParams: () => new URLSearchParams(''),
}));

vi.mock('@/lib/auth-modal-context', () => ({
  useAuthModal: () => ({ openModal: vi.fn(), closeModal: vi.fn() }),
}));

vi.mock('@/lib/supabase', () => ({
  getAuthState: vi.fn().mockResolvedValue({ user: null, isAnonymous: true, email: null, session: null }),
  getStorageStatus: vi.fn().mockReturnValue({ status: 'synced', error: null }),
  onStorageStatusChange: () => () => {},
}));

const TEST_OPPORTUNITY = vi.hoisted(() => ({
  id: 'opp-wiring-1',
  title: 'Wiring Test Lab',
  organization: 'Test University',
  opportunity_type: 'research',
  // A confirmed listing, with the wire kind the server sends beside it. An
  // unreviewed source_type is no longer actionable, so the page would refuse
  // this row and the wiring assertions would never see a rendered card.
  source_type: 'campus_program',
  record_kind: 'listing',
  // Live rows carry a truth; a page missing one is refused whole.
  target_truth: {
    listing_state: 'open',
    reference_only: false,
    actionable: true,
    accepting_state: 'accepting',
    reason_code: null,
    verified_at: null,
    expires_at: null,
  },
  paid: 'unknown',
  location: '',
  on_campus: true,
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
    application_effort: 'unknown',
    requires_resume: 'unknown',
    contact_method: 'website',
  },
  metadata: { is_active: true, confidence_score: 1 },
}));

// Overridden per-test by the deadline-facet block below; the default response
// carries no deadline_facets, which is also the shape an older backend sends.
const mockGetMatchView = vi.fn();
vi.mock('@/lib/api', () => ({
  getMatchView: (...args: unknown[]) => mockGetMatchView(...args),
  // The real class: loadEmailMatches throws one when a page fails validation,
  // and a stub would let a broken throw path pass unnoticed.
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      public code: string,
      message: string,
      public retryable: boolean,
    ) {
      super(message);
    }
  },
}));

const MATCH_VIEW_RESPONSE = {
    total: 1, high_priority: 1, good_match: 0, reach: 0, low_fit: 0,
    results: [{
      opportunity_id: TEST_OPPORTUNITY.id,
      eligibility_score: 80, readiness_score: 80, upside_score: 80, final_score: 80,
      bucket: 'high_priority', reasons_fit: [], reasons_gap: [], next_steps: [],
      opportunity: TEST_OPPORTUNITY,
    }],
    returned_count: 1, has_more: false, next_cursor: null,
    // The wire the backend emits; a version nothing serves would make the
    // page refuse this fixture before any of the wiring below is reached.
    contract_version: 'match-view-v3-faculty-trust',
    target_truth_contract: 'target-truth-v2',
    view_start: 0, filtered_total: 1,
    view_counts: { all: 1, high_priority: 1, good_match: 0, reach: 0, starred: 0 },
    view_id: 'view-wiring-1',
    result_set_id: 'set-wiring-1',
};

vi.mock('@/lib/saved-searches', () => ({
  listSavedSearchDigests: vi.fn().mockResolvedValue(null),
  saveSearch: vi.fn(),
  setSavedSearchDigest: vi.fn(),
}));

vi.mock('@/lib/match-feedback', () => ({
  getMatchFeedback: vi.fn().mockResolvedValue(new Map()),
  setMatchFeedback: vi.fn(),
}));

vi.mock('./use-highlight-set', () => ({
  useHighlightSet: () => new Set(),
}));

vi.mock('./use-saved-search-ack', () => ({
  useSavedSearchAck: () => {},
}));

const TEST_PROFILE = {
  institution: 'UIUC',
  college: 'Grainger',
  major: 'CS',
  grade: 'Sophomore',
  is_international: false,
  research_interests: 'machine learning',
  skills: [],
};

// Mutable so a test can walk the real sequence of an identity switch: the
// transition clears the accepted profile (no request can start while it is
// null), then the next account's profile is accepted and the data hook
// re-requests. Reset in beforeEach.
const acceptedProfile = vi.hoisted(() => ({ current: null as unknown, cleared: false }));
vi.mock('./use-results-profile-view', () => ({
  useAcceptedProfileView: () => ({
    accepted: acceptedProfile.cleared
      ? { profile: null, view: null }
      : { profile: acceptedProfile.current ?? TEST_PROFILE, view: {} },
    accept: vi.fn(),
    clear: () => { acceptedProfile.cleared = true; },
  }),
  useCrossSchoolToggle: () => ({ crossSchool: false, setCrossSchool: vi.fn(), clear: vi.fn() }),
}));

vi.mock('./use-results-keyboard-nav', () => ({
  useResultsKeyboardNav: () => ({ focusedIdx: -1, setFocusedIdx: vi.fn() }),
}));

vi.mock('@/lib/use-local-storage-json', () => ({
  useHasLocalStorageKey: () => true,
  // page.tsx calls this twice with different shapes: bare (rawStoredProfile,
  // fine as null) and with a transformer (presets, needs its EMPTY-array
  // shape — parsePresetsArray's own contract — not a bare null ResultsSearch
  // can't call .length on).
  useLocalStorageJSON: (_key: string, transform?: (raw: unknown) => unknown) =>
    transform ? transform(null) : null,
  writeLocalStorageJSON: vi.fn().mockReturnValue(true),
}));

// The one hook whose return this test controls directly — mirrors
// OpportunityDetail.test.tsx mocking use-opportunity-detail and
// favorites/page.test.tsx mocking use-favorites-data for the identical
// reason: isolate the SINGLE hop this file owns.
const mockUseResultsInteractions = vi.fn();
vi.mock('./use-results-interactions', () => ({
  useResultsInteractions: (...args: unknown[]) => mockUseResultsInteractions(...args),
}));

let lastMatchListProps: Record<string, unknown> | null = null;
vi.mock('./MatchList', () => ({
  MatchList: (props: Record<string, unknown>) => {
    lastMatchListProps = props;
    return <div data-testid="mock-match-list" />;
  },
}));

import ResultsPage from './page';
import { getMatchFeedback, setMatchFeedback } from '@/lib/match-feedback';
import { getAuthState } from '@/lib/supabase';
import { OwnerMismatchError } from '@/lib/identity-owner';

function baseInteractions(overrides: Record<string, unknown> = {}) {
  return {
    favs: new Set<string>(),
    interactions: new Map(),
    ownerReady: true,
    identityGeneration: 0,
    ownerScopeKey: 'results-page-test-uid',
    favoritesLoadError: false,
    retryFavoritesLoad: vi.fn(),
    interactionsLoading: false,
    interactionsError: false,
    favSaveErrors: new Map(),
    trackSaveErrors: new Map(),
    pendingFavIds: new Set<string>(),
    pendingTrackIds: new Set<string>(),
    handleToggleFav: vi.fn(),
    handleTrackInteraction: vi.fn(),
    retryFavSave: vi.fn(),
    retryTrackSave: vi.fn(),
    retryInteractionsLoad: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  lastMatchListProps = null;
  acceptedProfile.current = null;
  acceptedProfile.cleared = false;
  // Calls from an earlier test must not satisfy this test's waitFor: a
  // "was called" that is already true lets a deferred mock go unconsumed and
  // the assertion that follows pass for nothing.
  vi.mocked(getMatchFeedback).mockReset().mockResolvedValue(new Map());
  vi.mocked(setMatchFeedback).mockReset().mockResolvedValue(true);
  mockUseResultsInteractions.mockReset();
  mockUseResultsInteractions.mockReturnValue(baseInteractions());
  mockGetMatchView.mockReset();
  mockGetMatchView.mockResolvedValue(MATCH_VIEW_RESPONSE);
});

describe('ResultsPage -> MatchList: ownerReady/identityGeneration/ownerScopeKey caller-wiring (Tail4)', () => {
  it('forwards the EXACT values useResultsInteractions returns into MatchList props, not some other/stale local', async () => {
    mockUseResultsInteractions.mockReturnValue(baseInteractions({
      ownerReady: true,
      identityGeneration: 3,
      ownerScopeKey: 'wiring-test-uid-a',
    }));

    render(<ResultsPage />);
    await waitFor(() => expect(screen.getByTestId('mock-match-list')).toBeInTheDocument());

    expect(lastMatchListProps?.ownerReady).toBe(true);
    expect(lastMatchListProps?.identityGeneration).toBe(3);
    expect(lastMatchListProps?.ownerScopeKey).toBe('wiring-test-uid-a');
  });

  it('a live identityGeneration bump (simulating a real identity switch) reaches MatchList as a NEW prop value on re-render, not a stale one held from mount', async () => {
    mockUseResultsInteractions.mockReturnValue(baseInteractions({
      identityGeneration: 1,
      ownerScopeKey: 'wiring-test-uid-b1',
    }));
    const { rerender } = render(<ResultsPage />);
    await waitFor(() => expect(screen.getByTestId('mock-match-list')).toBeInTheDocument());
    expect(lastMatchListProps?.identityGeneration).toBe(1);

    mockUseResultsInteractions.mockReturnValue(baseInteractions({
      identityGeneration: 2,
      ownerScopeKey: 'wiring-test-uid-b2',
    }));
    rerender(<ResultsPage />);

    await waitFor(() => expect(lastMatchListProps?.identityGeneration).toBe(2));
    expect(lastMatchListProps?.ownerScopeKey).toBe('wiring-test-uid-b2');
  });

  it('ownerReady=false (blocked, mid-transition) reaches MatchList as false — the page must not default it to true when a real value exists', async () => {
    mockUseResultsInteractions.mockReturnValue(baseInteractions({ ownerReady: false }));

    render(<ResultsPage />);
    await waitFor(() => expect(screen.getByTestId('mock-match-list')).toBeInTheDocument());

    expect(lastMatchListProps?.ownerReady).toBe(false);
  });
});

describe('ResultsPage — the match-accuracy thumbs belong to one account', () => {
  const ctx = { bucket: 'reach', finalScore: 42 };
  type FeedbackProps = { feedback: Map<string, string>; onFeedback: (id: string, v: 'up' | 'down' | null, c: typeof ctx) => void };
  const props = () => lastMatchListProps as unknown as FeedbackProps;

  it('an identity switch clears U1\'s verdicts in the transition itself and re-asks the server for U2\'s', async () => {
    // Before: the Map, the fetched-id memory and the mutation counters all
    // outlived the account. U2 saw U1's thumbs, and hydration skipped U2's
    // cards as "already asked about".
    vi.mocked(setMatchFeedback).mockResolvedValue(true);
    const { rerender } = render(<ResultsPage />);
    await waitFor(() => expect(getMatchFeedback).toHaveBeenCalled());
    expect(getMatchFeedback).toHaveBeenCalledWith(['opp-wiring-1']);
    act(() => props().onFeedback('opp-wiring-1', 'up', ctx));
    await waitFor(() => expect(props().feedback.get('opp-wiring-1')).toBe('up'));
    const hydrations = vi.mocked(getMatchFeedback).mock.calls.length;

    // The hook reports a real switch by calling the page's transition
    // handler synchronously, then re-rendering with a bumped generation. The
    // list comes back once U2's profile is accepted and the data hook
    // re-requests (that the list leaves in the transition is pinned below).
    const onIdentityChange = mockUseResultsInteractions.mock.calls.at(-1)?.[0] as () => void;
    act(() => onIdentityChange());

    acceptedProfile.current = { ...TEST_PROFILE, major: 'U2 major' };
    acceptedProfile.cleared = false;
    mockUseResultsInteractions.mockReturnValue(baseInteractions({ identityGeneration: 1, ownerScopeKey: 'u2' }));
    rerender(<ResultsPage />);
    await waitFor(() => expect(screen.getByTestId('mock-match-list')).toBeInTheDocument());
    expect(props().feedback.size).toBe(0);
    await waitFor(() => expect(vi.mocked(getMatchFeedback).mock.calls.length).toBe(hydrations + 1));
    expect(vi.mocked(getMatchFeedback).mock.calls.at(-1)?.[0]).toEqual(['opp-wiring-1']);
  });

  it('U1\'s hydration response arriving after the switch does not paint into U2\'s cleared map', async () => {
    // The effect's `cancelled` flag flips in its cleanup, one task after the
    // auth callback that cleared the map. A response in that gap used to land.
    let resolveHydration: (d: Map<string, 'up' | 'down'>) => void = () => {};
    vi.mocked(getMatchFeedback).mockImplementationOnce(() => new Promise((r) => { resolveHydration = r; }));
    const { rerender } = render(<ResultsPage />);
    await waitFor(() => expect(getMatchFeedback).toHaveBeenCalled());

    const onIdentityChange = mockUseResultsInteractions.mock.calls.at(-1)?.[0] as () => void;
    act(() => onIdentityChange());
    // U1's late response lands in the gap: after the transition cleared the
    // map, before U2's profile is accepted and U2's own request replaces the
    // list (which is when the effect's cleanup would finally have run).
    resolveHydration(new Map([['opp-wiring-1', 'up']]));
    await new Promise((r) => setTimeout(r, 20));

    acceptedProfile.current = { ...TEST_PROFILE, major: 'U2 major' };
    acceptedProfile.cleared = false;
    mockUseResultsInteractions.mockReturnValue(baseInteractions({ identityGeneration: 1, ownerScopeKey: 'u2' }));
    rerender(<ResultsPage />);
    await waitFor(() => expect(screen.getByTestId('mock-match-list')).toBeInTheDocument());

    expect(props().feedback.has('opp-wiring-1')).toBe(false);
  });

  it('a verdict refused for the SAME account is taken back instead of standing as a saved thumb', async () => {
    vi.mocked(setMatchFeedback).mockRejectedValue(new OwnerMismatchError());
    render(<ResultsPage />);
    await waitFor(() => expect(screen.getByTestId('mock-match-list')).toBeInTheDocument());
    act(() => props().onFeedback('opp-wiring-1', 'down', ctx));
    await waitFor(() => expect(props().feedback.has('opp-wiring-1')).toBe(false));
    expect(setMatchFeedback).toHaveBeenCalledWith('opp-wiring-1', 'down', ctx, expect.anything());
  });

  it('a refusal that arrives after a newer click on the same card leaves the newer verdict alone', async () => {
    let rejectFirst: (e: unknown) => void = () => {};
    vi.mocked(setMatchFeedback)
      .mockImplementationOnce(() => new Promise((_r, rej) => { rejectFirst = rej; }))
      .mockResolvedValue(true);
    render(<ResultsPage />);
    await waitFor(() => expect(screen.getByTestId('mock-match-list')).toBeInTheDocument());
    act(() => props().onFeedback('opp-wiring-1', 'down', ctx));
    act(() => props().onFeedback('opp-wiring-1', 'up', ctx));
    await waitFor(() => expect(props().feedback.get('opp-wiring-1')).toBe('up'));
    rejectFirst(new OwnerMismatchError());
    await new Promise((r) => setTimeout(r, 20));
    expect(props().feedback.get('opp-wiring-1')).toBe('up');
  });
});

describe('ResultsPage — what an identity switch must take off the screen in the transition itself', () => {
  const onIdentityChange = () => mockUseResultsInteractions.mock.calls.at(-1)?.[0] as () => void;

  it('the ranked list: U1\'s rows do not stay up as U2\'s fresh-looking list while U2\'s profile is re-accepted', async () => {
    // Before: only the email modal, profile view, cross-school failure and
    // page number were cleared. The data hook nulls `data` when a NEW request
    // starts, and none starts while the profile is null — so the old list,
    // with its scores and per-profile explanations, stayed rendered.
    render(<ResultsPage />);
    await waitFor(() => expect(screen.getByTestId('mock-match-list')).toBeInTheDocument());

    act(() => onIdentityChange()());

    expect(screen.queryByTestId('mock-match-list')).toBeNull();
  });

  it('the Save-search dialog: a name and digest e-mail U1 was typing cannot be submitted onto U2\'s new row', async () => {
    vi.mocked(getAuthState).mockResolvedValue({ user: { id: 'u1' }, isAnonymous: false, email: 'u1@x.edu', session: {} } as never);
    try {
      render(<ResultsPage />);
      // The save control appears once there is something to save.
      fireEvent.change(await screen.findByPlaceholderText('results.search.placeholder'), { target: { value: 'imaging' } });
      fireEvent.click(await screen.findByTitle('results.saveSearchTitle'));
      expect(await screen.findByRole('dialog')).toBeInTheDocument();

      act(() => onIdentityChange()());

      expect(screen.queryByRole('dialog')).toBeNull();
    } finally {
      vi.mocked(getAuthState).mockResolvedValue({ user: null, isAnonymous: true, email: null, session: null } as never);
    }
  });
});

/*
 * The deadline facet is the one control on this rail that could only ever
 * return an empty page. Measured on the published corpus 2026-08-14: 789 of
 * 132,524 records carry a deadline and 786 of those are already past, so
 * "within 7 / 14 / 30 days" matched exactly zero records each. The chips now
 * render from server-side counts, and this covers the hop page.tsx owns —
 * response field in, option list out.
 */
describe('ResultsPage -> FilterRail: deadline chips render on evidence', () => {
  async function deadlineValues() {
    render(<ResultsPage />);
    await waitFor(() => expect(screen.getByTestId('mock-match-list')).toBeInTheDocument());
    const selects = screen.getAllByRole('combobox');
    const rail = selects.find((element) =>
      Array.from(element.querySelectorAll('option')).some(
        (option) => option.getAttribute('value') === 'rolling',
      ),
    );
    expect(rail).toBeDefined();
    return Array.from(rail!.querySelectorAll('option')).map((o) => o.getAttribute('value'));
  }

  it('offers only the two values the corpus can answer when nothing has a live date', async () => {
    mockGetMatchView.mockResolvedValue({
      ...MATCH_VIEW_RESPONSE,
      deadline_facets: { '7': 0, '14': 0, '30': 0, passed: 0 },
    });
    expect(await deadlineValues()).toEqual(['', 'rolling']);
  });

  it('offers exactly the windows the server counted rows for', async () => {
    mockGetMatchView.mockResolvedValue({
      ...MATCH_VIEW_RESPONSE,
      deadline_facets: { '7': 0, '14': 0, '30': 2, passed: 786 },
    });
    expect(await deadlineValues()).toEqual(['', 'rolling', '30', 'passed']);
  });

  it('hides the chips when the backend sends no counts at all', async () => {
    // An older deployment, or a cache entry minted before the field existed.
    // No evidence is not evidence of rows.
    expect(await deadlineValues()).toEqual(['', 'rolling']);
  });
});
