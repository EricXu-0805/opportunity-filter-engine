/* @vitest-environment jsdom */
// The Cold Email dialog is the one target control on /results that does not
// live inside a result's keyed subtree. Every other one — Tailor, Renovate,
// gap analysis — is rendered by MatchCard, so when the row disappears React
// unmounts the control with it. This dialog only copies an id at click time
// and then survives on its own, which means a refresh that closes the target
// leaves a working Generate button pointed at it.
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const { getMatchView, generateColdEmail } = vi.hoisted(() => ({
  getMatchView: vi.fn(),
  generateColdEmail: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  getMatchView,
  generateColdEmail,
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

// `data` is driven directly. The real loader refuses a whole page containing a
// closed row — correctly — so a non-actionable row can never arrive through
// it, and the interesting states here would be unreachable. What is being
// tested is the page's own guard on the state it holds: an id captured at
// click time, still held after the results underneath it changed.
const feed = vi.hoisted(() => ({ current: null as unknown }));
vi.mock('./use-results-data', () => ({
  useResultsData: () => ({
    data: feed.current,
    setData: vi.fn(),
    loading: false,
    error: null,
    showSlowHint: false,
    paginationReady: true,
    refining: false,
    refined: false,
    refineFailed: false,
  }),
}));

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

// The dialog itself is stubbed to something unmistakable and interactive, so
// "the dialog is gone" is a DOM fact rather than an inference about props.
vi.mock('@/components/ColdEmailModal', () => ({
  default: ({ isOpen, opportunityId }: { isOpen: boolean; opportunityId: string }) => (
    isOpen
      ? (
        <div role="dialog" data-testid="cold-email-modal">
          <span>target:{opportunityId}</span>
          <button type="button" onClick={() => generateColdEmail(opportunityId)}>Generate</button>
        </div>
        )
      : null
  ),
}));

// Captures the page's own openEmailModal so the dialog can be opened the way
// a card would open it, without depending on MatchList's markup.
const captured = vi.hoisted(() => ({ draft: null as null | ((id: string) => void) }));
vi.mock('./MatchList', () => ({
  MatchList: (props: { onDraftEmail: (id: string) => void }) => {
    captured.draft = props.onDraftEmail;
    return <div data-testid="mock-match-list" />;
  },
}));
vi.mock('./ResultsHeader', () => ({ ResultsHeader: () => null }));

const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

const CLOSED_TRUTH = {
  listing_state: 'closed',
  reference_only: false,
  actionable: false,
  accepting_state: 'not_accepting',
  reason_code: 'listing_closed',
  verified_at: null,
  expires_at: null,
} as const;

function result(id: string, truth: unknown) {
  return {
    opportunity_id: id,
    eligibility_score: 80, readiness_score: 80, upside_score: 80, final_score: 80,
    bucket: 'high_priority', reasons_fit: [], reasons_gap: [], next_steps: [],
    opportunity: {
      id, title: id, organization: 'Test University',
      opportunity_type: 'research', source_type: 'campus_program',
      target_truth: truth, paid: 'unknown', location: '',
      description_clean: '', keywords: [],
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

function response(results: unknown[]) {
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
  };
}

/** Mount once. Every later step reuses THIS instance — see `refeed`. */
async function mountResults() {
  const { default: ResultsPage } = await import('./page');
  const view = render(<ResultsPage />);
  await waitFor(() => expect(captured.draft).not.toBeNull());
  return { view, ResultsPage };
}

/**
 * Swap the results underneath the SAME mounted page.
 *
 * Deliberately not a remount with a new key: unmounting destroys the dialog
 * whatever the guard does, so a test written that way passes with the guard
 * deleted. The refresh being modelled here does not remount anything — the
 * hook returns a new `data` and the page re-renders around it.
 */
async function refeed(
  view: Awaited<ReturnType<typeof mountResults>>['view'],
  ResultsPage: React.ComponentType,
  next: unknown,
) {
  feed.current = next;
  view.rerender(<ResultsPage />);
  await waitFor(() => expect(captured.draft).not.toBeNull());
}

async function openDialogFor(id: string) {
  const mounted = await mountResults();
  captured.draft!(id);
  await waitFor(() => {
    expect(screen.getByTestId('cold-email-modal')).toBeInTheDocument();
  });
  return mounted;
}

beforeEach(() => {
  vi.clearAllMocks();
  captured.draft = null;
  feed.current = null;
  window.localStorage.clear();
});

describe('the cold email dialog cannot outlive its target', () => {
  it('opens for a live target, with a Generate button that works', async () => {
    // The positive control every "not called" assertion below depends on. If
    // Generate were unreachable even here, those assertions would be vacuous.
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    await openDialogFor('a');

    expect(screen.getByTestId('cold-email-modal')).toHaveTextContent('target:a');
    screen.getByRole('button', { name: 'Generate' }).click();
    expect(generateColdEmail).toHaveBeenCalledWith('a');
  });

  it('refuses to open for a target that is not actionable', async () => {
    feed.current = response([result('a', CLOSED_TRUTH)]);
    await mountResults();

    captured.draft!('a');

    expect(screen.queryByTestId('cold-email-modal')).not.toBeInTheDocument();
    expect(generateColdEmail).not.toHaveBeenCalled();
  });

  it('refuses to open for an id that is not in the results at all', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    await mountResults();

    captured.draft!('never-existed');

    expect(screen.queryByTestId('cold-email-modal')).not.toBeInTheDocument();
  });

  it('withdraws itself when the refreshed results no longer contain the target', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await openDialogFor('a');
    expect(screen.getByRole('button', { name: 'Generate' })).toBeInTheDocument();

    // A trusted, genuinely empty result set — same page instance throughout.
    await refeed(view, ResultsPage, response([]));

    await waitFor(() => {
      expect(screen.queryByTestId('cold-email-modal')).not.toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'Generate' })).not.toBeInTheDocument();
    expect(generateColdEmail).not.toHaveBeenCalled();
  });

  it('withdraws itself when the target comes back non-actionable', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await openDialogFor('a');
    expect(screen.getByRole('button', { name: 'Generate' })).toBeInTheDocument();

    await refeed(view, ResultsPage, response([result('a', CLOSED_TRUTH)]));

    await waitFor(() => {
      expect(screen.queryByTestId('cold-email-modal')).not.toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'Generate' })).not.toBeInTheDocument();
    expect(generateColdEmail).not.toHaveBeenCalled();
  });

  it('withdraws the dialog while a refetch has no results to check against', async () => {
    // This asserted the opposite, on the reasoning that absence is not
    // evidence and a draft should not be lost for nothing. Two things
    // changed. The cache no longer paints, so `data === null` is the ordinary
    // state between a filter change and its answer rather than a rare blip —
    // and standing on the check made when the dialog opened means a working
    // Generate button behind a posture nobody has re-read, against a backend
    // that during a split deploy may not understand the current truth
    // contract at all.
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await openDialogFor('a');

    await refeed(view, ResultsPage, null);

    await waitFor(() => {
      expect(screen.queryByTestId('cold-email-modal')).not.toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'Generate' })).not.toBeInTheDocument();
    expect(generateColdEmail).not.toHaveBeenCalled();
  });

  it('a target that comes back closed does not bring the dialog back', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await openDialogFor('a');

    await refeed(view, ResultsPage, null);
    await waitFor(() => expect(screen.queryByTestId('cold-email-modal')).not.toBeInTheDocument());

    await refeed(view, ResultsPage, response([result('a', CLOSED_TRUTH)]));

    expect(screen.queryByTestId('cold-email-modal')).not.toBeInTheDocument();
  });

  it('a target that comes back live does not resurface on its own either', async () => {
    // Withdrawal is not a pause. The student closed nothing and typed
    // nothing since; a dialog reappearing under their cursor because a
    // request finished is its own surprise, and re-opening is one click.
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await openDialogFor('a');

    await refeed(view, ResultsPage, null);
    await waitFor(() => expect(screen.queryByTestId('cold-email-modal')).not.toBeInTheDocument());

    await refeed(view, ResultsPage, response([result('a', ACTIONABLE_TRUTH)]));

    expect(screen.queryByTestId('cold-email-modal')).not.toBeInTheDocument();
  });

  it('can be explicitly reopened against the new live results snapshot', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await openDialogFor('a');

    await refeed(view, ResultsPage, null);
    await waitFor(() => expect(screen.queryByTestId('cold-email-modal')).not.toBeInTheDocument());

    await refeed(view, ResultsPage, response([result('a', ACTIONABLE_TRUTH)]));
    expect(screen.queryByTestId('cold-email-modal')).not.toBeInTheDocument();

    captured.draft!('a');
    await waitFor(() => expect(screen.getByTestId('cold-email-modal')).toBeInTheDocument());
    screen.getByRole('button', { name: 'Generate' }).click();
    expect(generateColdEmail).toHaveBeenCalledWith('a');
  });
});
