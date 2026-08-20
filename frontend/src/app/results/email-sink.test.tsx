/* @vitest-environment jsdom */
// The "email this list" path fetches its own page — a second, independent
// getMatchView that does NOT go through useResultsData. So it has to repeat
// the same validation, or a page the results view would refuse can still be
// mailed. During the Vercel-first deploy window those rows reach an OLD
// backend through the legacy bridge fields, which renders whatever it is
// handed, so a silent pass here becomes a false claim in someone's inbox.
//
// What this file proves is that the loader REJECTS. It deliberately does not
// assert "sendMatchesEmail was not called" — nothing here calls it, so that
// assertion would pass with the guard deleted. The send-level assertion lives
// in ResultsHeader.test.tsx, where the real onSend chain runs against a mocked
// sendMatchesEmail.
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';

const mockGetMatchView = vi.fn();

vi.mock('@/lib/api', () => ({
  getMatchView: (...args: unknown[]) => mockGetMatchView(...args),
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

vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key }) }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: () => {}, replace: () => {} }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ open: () => {} }) }));
vi.mock('@/lib/supabase', () => ({
  getAuthState: vi.fn().mockResolvedValue({
    user: null, isAnonymous: true, email: null, session: null,
  }),
  getStorageStatus: vi.fn().mockReturnValue({ status: 'synced', error: null }),
  onStorageStatusChange: () => () => {},
}));
vi.mock('@/lib/saved-searches', () => ({
  listSavedSearchDigests: vi.fn().mockResolvedValue(null),
  saveSearch: vi.fn(),
  setSavedSearchDigest: vi.fn(),
}));
vi.mock('@/lib/match-feedback', () => ({
  getMatchFeedback: vi.fn().mockResolvedValue(new Map()),
  setMatchFeedback: vi.fn(),
}));
vi.mock('./use-highlight-set', () => ({ useHighlightSet: () => new Set() }));
vi.mock('./use-saved-search-ack', () => ({ useSavedSearchAck: () => {} }));

const TEST_PROFILE = {
  institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  is_international: false, research_interests: 'machine learning', skills: [],
};
vi.mock('./use-results-profile-view', () => ({
  useAcceptedProfileView: () => ({
    accepted: { profile: TEST_PROFILE, view: {} }, accept: vi.fn(), clear: vi.fn(),
  }),
  useCrossSchoolToggle: () => ({ crossSchool: false, setCrossSchool: vi.fn(), clear: vi.fn() }),
}));
vi.mock('./use-results-keyboard-nav', () => ({
  useResultsKeyboardNav: () => ({ focusedIdx: -1, setFocusedIdx: vi.fn() }),
}));
vi.mock('@/lib/use-local-storage-json', () => ({
  useHasLocalStorageKey: () => true,
  useLocalStorageJSON: (_key: string, transform?: (raw: unknown) => unknown) =>
    transform ? transform(null) : null,
  writeLocalStorageJSON: vi.fn().mockReturnValue(true),
}));
vi.mock('./use-results-interactions', () => ({
  useResultsInteractions: () => ({
    favs: new Set(), interactions: new Map(), feedback: new Map(),
    ownerReady: true, ownerScopeKey: 'owner-1', identityGeneration: 1,
    favPending: new Set(), trackPending: new Set(),
    favSaveErrors: new Set(), trackSaveErrors: new Set(),
    toggleFavorite: vi.fn(), trackInteraction: vi.fn(),
    retryFavSave: vi.fn(), retryTrackSave: vi.fn(), submitFeedback: vi.fn(),
  }),
}));
vi.mock('./MatchList', () => ({ MatchList: () => <div data-testid="mock-match-list" /> }));

// Captures the loader the page hands its header, so the guard can be driven
// directly without depending on the header's markup.
const captured = vi.hoisted(
  () => ({ load: null as null | (() => Promise<unknown[]>) }),
);
vi.mock('./ResultsHeader', () => ({
  ResultsHeader: (props: { loadEmailMatches: () => Promise<unknown[]> }) => {
    captured.load = props.loadEmailMatches;
    return null;
  },
}));

const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

/** A live result row. `truth` must be passed explicitly — see withoutTruth. */
function result(id: string, truth: unknown) {
  return {
    opportunity_id: id,
    eligibility_score: 80, readiness_score: 80, upside_score: 80, final_score: 80,
    bucket: 'high_priority', reasons_fit: [], reasons_gap: [], next_steps: [],
    opportunity: {
      id,
      title: id,
      organization: 'Test University',
      opportunity_type: 'research',
      source_type: 'campus_program',
      target_truth: truth,
      paid: 'unknown',
      location: '',
      description_clean: '',
      keywords: [],
      eligibility: {
        international_friendly: 'unknown', preferred_year: [],
        majors: [], skills_required: [], citizenship_required: null,
      },
      application: {
        application_effort: 'unknown', requires_resume: 'unknown', contact_method: 'website',
      },
      metadata: { is_active: true, confidence_score: 1 },
    },
  };
}

/** Genuinely absent, not undefined-with-a-default. */
function withoutTruth(id: string) {
  const row = result(id, ACTIONABLE_TRUTH);
  delete (row.opportunity as Record<string, unknown>).target_truth;
  return row;
}

function response(results: unknown[], overrides: Record<string, unknown> = {}) {
  return {
    total: results.length, high_priority: results.length, good_match: 0, reach: 0, low_fit: 0,
    results,
    returned_count: results.length, has_more: false, next_cursor: null,
    contract_version: 'match-view-v3-faculty-trust',
    target_truth_contract: 'target-truth-v2',
    view_start: 0, filtered_total: results.length,
    view_counts: {
      all: results.length, high_priority: results.length,
      good_match: 0, reach: 0, starred: 0,
    },
    view_id: 'view-1', result_set_id: 'set-1',
    ...overrides,
  };
}

async function loader() {
  const { default: ResultsPage } = await import('./page');
  render(<ResultsPage />);
  await waitFor(() => expect(captured.load).not.toBeNull());
  return captured.load!;
}

beforeEach(() => {
  vi.clearAllMocks();
  captured.load = null;
  window.localStorage.clear();
});

describe('the email loader refuses a page it cannot vouch for', () => {
  const BAD_PAGES: [string, () => unknown][] = [
    ['a closed target', () => response([
      result('ok-1', ACTIONABLE_TRUTH),
      result('closed-1', {
        ...ACTIONABLE_TRUTH,
        listing_state: 'closed', actionable: false,
        accepting_state: 'not_accepting', reason_code: 'listing_closed',
        reference_only: true,
      }),
    ])],
    ['an absent truth', () => response([result('ok-1', ACTIONABLE_TRUTH), withoutTruth('gone')])],
    ['a null truth', () => response([result('null-1', null)])],
    ['a malformed truth', () => response([result('bad-1', { listing_state: 'open' })])],
    ['a self-contradicting truth', () => response([
      result('contra-1', { ...ACTIONABLE_TRUTH, listing_state: 'closed' }),
    ])],
    ['a duplicate id', () => response([
      result('dup-1', ACTIONABLE_TRUTH), result('dup-1', ACTIONABLE_TRUTH),
    ])],
    ['a response with no target-truth marker', () => response(
      [result('ok-1', ACTIONABLE_TRUTH)],
      { target_truth_contract: undefined },
    )],
    ['an unknown wire version', () => response(
      [result('ok-1', ACTIONABLE_TRUTH)],
      { contract_version: 'match-view-v9-future' },
    )],
    // The one that used to be pre-accepted. Nothing emits it, so a page
    // arriving under it was written by something whose fields were never
    // agreed — and a digest is sent under our name, to an inbox, unreviewed.
    ['a wire version nobody has negotiated', () => response(
      [result('ok-1', ACTIONABLE_TRUTH)],
      { contract_version: 'match-view-v4-target-truth' },
    )],
  ];

  it('accepts the wire version the backend actually emits', async () => {
    // The positive control for the rejections below: without it they could
    // all pass because the loader refuses everything.
    mockGetMatchView.mockResolvedValue(response(
      [result('ok-1', ACTIONABLE_TRUTH)],
      { contract_version: 'match-view-v3-faculty-trust' },
    ));
    const load = await loader();
    await expect(load()).resolves.toHaveLength(1);
  });

  it.each(BAD_PAGES)('rejects rather than returning %s', async (_label, build) => {
    mockGetMatchView.mockResolvedValue(build());
    const load = await loader();
    await expect(load()).rejects.toThrow();
  });

  it('rejects a row whose nested id drifted from its top-level id', async () => {
    const drifted = result('outer-1', ACTIONABLE_TRUTH);
    (drifted.opportunity as Record<string, unknown>).id = 'inner-other';
    mockGetMatchView.mockResolvedValue(response([drifted]));
    const load = await loader();
    await expect(load()).rejects.toThrow();
  });

  it('returns every row, unfiltered and in order, when the page checks out', async () => {
    const rows = [
      result('first', ACTIONABLE_TRUTH),
      result('second', ACTIONABLE_TRUTH),
      result('third', ACTIONABLE_TRUTH),
    ];
    mockGetMatchView.mockResolvedValue(response(rows));
    const load = await loader();

    const returned = await load();
    // Same objects, same order: the guard is all-or-nothing, never a filter.
    expect(returned).toEqual(rows);
  });
});
