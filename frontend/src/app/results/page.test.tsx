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
import { render, screen, waitFor } from '@testing-library/react';

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

vi.mock('./use-results-profile-view', () => ({
  useAcceptedProfileView: () => ({
    accepted: { profile: TEST_PROFILE, view: {} },
    accept: vi.fn(),
    clear: vi.fn(),
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
