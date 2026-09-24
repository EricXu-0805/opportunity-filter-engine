/* @vitest-environment jsdom */
// The page owns writing buffers independently of the result cards. These
// sentinel editors test mount identity, profile/target forwarding and action
// eligibility; the real editors' async/provider guards have their own tests.
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import { useLayoutEffect, useState } from 'react';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import type { Opportunity, ProfileData } from '@/lib/types';

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
const feed = vi.hoisted(() => ({ current: null as unknown, loading: false, error: null as string | null }));
vi.mock('./use-results-data', () => ({
  useResultsData: () => ({
    data: feed.current,
    setData: vi.fn(),
    loading: feed.loading,
    error: feed.error,
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
const profileFeed = vi.hoisted(() => ({ current: undefined as ProfileData | null | undefined }));
vi.mock('./use-results-profile-view', () => ({
  useAcceptedProfileView: () => ({
    accepted: { profile: profileFeed.current === undefined ? TEST_PROFILE : profileFeed.current, view: {} }, accept: vi.fn(), clear: vi.fn(),
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
const ownerFeed = vi.hoisted(() => ({ uid: 'owner-1', generation: 1, ready: true, retire: null as (() => void) | null }));
vi.mock('./use-results-interactions', () => ({
  useResultsInteractions: (retire: () => void) => { ownerFeed.retire = retire; return ({
    favs: new Set(), interactions: new Map(), feedback: new Map(),
    ownerReady: ownerFeed.ready, ownerScopeKey: ownerFeed.uid, identityGeneration: ownerFeed.generation,
    favPending: new Set(), trackPending: new Set(),
    favSaveErrors: new Set(), trackSaveErrors: new Set(),
    toggleFavorite: vi.fn(), trackInteraction: vi.fn(),
    retryFavSave: vi.fn(), retryTrackSave: vi.fn(), submitFeedback: vi.fn(),
  }); },
}));

const modalHistory = vi.hoisted(() => ({ request: null as (() => boolean) | null, close: null as (() => void) | null }));
vi.mock('./use-result-modal-history', () => ({
  useResultModalHistory: (_open: boolean, close: () => void, _owner: unknown, request: () => boolean) => {
    modalHistory.request = request; modalHistory.close = close;
  },
}));

vi.mock('@/components/ColdEmailModal', () => ({
  default: function EmailEditor({ isOpen, opportunityId, profile, targetReady, reminderTarget }: {
    isOpen: boolean; opportunityId: string; profile: ProfileData; targetReady: boolean; reminderTarget?: Opportunity;
  }) {
    const [text, setText] = useState('Original email');
    return isOpen ? <div role="dialog" data-testid="cold-email-modal">
      <span>target:{opportunityId}</span><span data-testid="editor-profile">{profile.research_interests}</span>
      <textarea aria-label="Email text" value={text} onChange={(event) => setText(event.target.value)} />
      <button type="button" disabled={!targetReady} onClick={() => generateColdEmail(opportunityId)}>Generate</button>
      <span data-testid="reminder-target">{reminderTarget?.id ?? 'unavailable'}</span>
    </div> : null;
  },
}));
vi.mock('@/components/ResumeWorkspaceModal', () => ({
  default: function ResumeEditor({ isOpen, opportunity, profile, targetReady, onClose, onCloseRequestChange }: {
    isOpen: boolean; opportunity: Opportunity; profile: ProfileData; targetReady: boolean;
    onClose: () => void; onCloseRequestChange: (request: (() => boolean) | null) => void;
  }) {
    const [text, setText] = useState('Original résumé');
    const [confirmClose, setConfirmClose] = useState(false);
    useLayoutEffect(() => {
      onCloseRequestChange(() => { setConfirmClose(true); return false; });
      return () => onCloseRequestChange(null);
    }, [onCloseRequestChange]);
    return isOpen ? <div role="dialog" data-testid="resume-modal">
      <span>target:{opportunity.id}</span><span data-testid="target-description">{opportunity.description_clean}</span>
      <span data-testid="editor-profile">{profile.research_interests}</span>
      <textarea aria-label="Résumé text" value={text} onChange={(event) => setText(event.target.value)} />
      <input aria-label="Include degree" type="checkbox" defaultChecked />
      <button type="button" disabled={!targetReady}>Adapt résumé</button>
      {confirmClose && <><button onClick={() => setConfirmClose(false)}>Keep editing</button><button onClick={onClose}>Discard</button></>}
    </div> : null;
  },
}));

const captured = vi.hoisted(() => ({
  draft: null as null | ((id: string) => void), resume: null as null | ((id: string) => void),
}));
vi.mock('./MatchList', () => ({
  MatchList: (props: { onDraftEmail: (id: string) => void; onOpenResume: (id: string) => void }) => {
    captured.draft = props.onDraftEmail; captured.resume = props.onOpenResume;
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
  act(() => captured.draft!(id));
  await waitFor(() => {
    expect(screen.getByTestId('cold-email-modal')).toBeInTheDocument();
  });
  return mounted;
}

beforeEach(async () => {
  vi.clearAllMocks();
  captured.draft = null; captured.resume = null;
  feed.current = null; feed.loading = false; feed.error = null;
  profileFeed.current = undefined;
  ownerFeed.uid = 'owner-1'; ownerFeed.generation = 1; ownerFeed.ready = true;
  window.localStorage.clear();
  advanceOwnerEpoch('owner-1'); await syncLocalIdentityOwner('owner-1');
});

describe('Results keeps writing buffers while current target actions fail closed', () => {
  it('opens for a current actionable target and Generate works', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    await openDialogFor('a');
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
    expect(generateColdEmail).toHaveBeenCalledWith('a');
    expect(screen.getByTestId('reminder-target')).toHaveTextContent('a');
  });

  it.each(['closed', 'missing', 'unready'] as const)('refuses both editors at entry when target/owner is %s', async (mode) => {
    feed.current = response([result('a', mode === 'closed' ? CLOSED_TRUTH : ACTIONABLE_TRUTH)]);
    ownerFeed.ready = mode !== 'unready';
    await mountResults();
    const id = mode === 'missing' ? 'never-existed' : 'a';
    act(() => { captured.draft!(id); captured.resume!(id); });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(generateColdEmail).not.toHaveBeenCalled();
  });

  it.each(['missing', 'closed', 'loading', 'error'] as const)('keeps the email edit but disables Generate and reminders while %s', async (mode) => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await openDialogFor('a');
    const input = screen.getByRole('textbox', { name: 'Email text' });
    fireEvent.change(input, { target: { value: 'My unsaved email' } });
    feed.loading = mode === 'loading'; feed.error = mode === 'error' ? 'read failed' : null;
    const next = mode === 'closed' ? response([result('a', CLOSED_TRUTH)])
      : mode === 'missing' ? response([]) : mode === 'loading' ? null : feed.current;
    await refeed(view, ResultsPage, next);
    expect(screen.getByRole('textbox', { name: 'Email text' })).toBe(input);
    expect(input).toHaveValue('My unsaved email');
    expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled();
    expect(screen.getByTestId('reminder-target')).toHaveTextContent('unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
    expect(generateColdEmail).not.toHaveBeenCalled();
  });

  it('restores actions only from a current same-id actionable row, preserving email edits', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await openDialogFor('a');
    fireEvent.change(screen.getByRole('textbox', { name: 'Email text' }), { target: { value: 'Keep my email' } });
    await refeed(view, ResultsPage, null);
    await refeed(view, ResultsPage, response([result('b', ACTIONABLE_TRUTH)]));
    expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled();
    await refeed(view, ResultsPage, response([result('a', CLOSED_TRUTH)]));
    expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled();
    await refeed(view, ResultsPage, response([result('a', ACTIONABLE_TRUTH)]));
    expect(screen.getByRole('button', { name: 'Generate' })).toBeEnabled();
    expect(screen.getByRole('textbox', { name: 'Email text' })).toHaveValue('Keep my email');
    fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
    expect(generateColdEmail).toHaveBeenCalledTimes(1);
  });

  it('keeps the same résumé editor through rematch, missing rows and errors, and passes new profile/target content', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await mountResults();
    act(() => captured.resume!('a'));
    const input = await screen.findByRole('textbox', { name: 'Résumé text' });
    fireEvent.change(input, { target: { value: 'Unsubmitted résumé edit' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include degree' }));
    profileFeed.current = { ...TEST_PROFILE, research_interests: 'New confirmed interests' };
    feed.loading = true;
    await refeed(view, ResultsPage, null);
    expect(screen.queryByTestId('mock-match-list')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Adapt résumé' })).toBeDisabled();
    expect(screen.getByTestId('editor-profile')).toHaveTextContent('New confirmed interests');
    feed.loading = false;
    await refeed(view, ResultsPage, response([]));
    expect(screen.getByRole('textbox', { name: 'Résumé text' })).toBe(input);
    expect(input).toHaveValue('Unsubmitted résumé edit');
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    feed.error = 'read failed';
    await refeed(view, ResultsPage, null);
    expect(input).toBeInTheDocument();
    feed.error = null;
    const refreshed = result('a', ACTIONABLE_TRUTH);
    refreshed.opportunity.description_clean = 'Updated target requirements';
    await refeed(view, ResultsPage, response([refreshed]));
    expect(screen.getByTestId('target-description')).toHaveTextContent('Updated target requirements');
    expect(screen.getByRole('button', { name: 'Adapt résumé' })).toBeEnabled();
    expect(input).toHaveValue('Unsubmitted résumé edit');
    expect(screen.getByRole('checkbox')).not.toBeChecked();
  });

  it('preserves the editor when the same owner profile is temporarily unavailable, without enabling actions', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await openDialogFor('a');
    const input = screen.getByRole('textbox', { name: 'Email text' });
    fireEvent.change(input, { target: { value: 'My retained email' } });
    profileFeed.current = null;
    await refeed(view, ResultsPage, feed.current);
    expect(screen.getByRole('textbox', { name: 'Email text' })).toBe(input);
    expect(input).toHaveValue('My retained email');
    expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled();
  });

  it.each(['email', 'resume'] as const)('retires the private %s buffer on an owner-generation transition even if the uid is unchanged', async (kind) => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await mountResults();
    act(() => (kind === 'email' ? captured.draft : captured.resume)!('a'));
    await screen.findByRole('dialog');
    advanceOwnerEpoch(null); advanceOwnerEpoch('owner-1');
    await syncLocalIdentityOwner('owner-1');
    await refeed(view, ResultsPage, feed.current);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('revokes an open résumé immediately on the identity-change callback', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    await mountResults();
    act(() => captured.resume!('a'));
    await screen.findByRole('dialog');
    act(() => ownerFeed.retire!());
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps the résumé dirty-close guard connected while the list is absent', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH)]);
    const { view, ResultsPage } = await mountResults();
    act(() => captured.resume!('a'));
    const input = await screen.findByRole('textbox', { name: 'Résumé text' });
    fireEvent.change(input, { target: { value: 'Unsaved protected edit' } });
    await refeed(view, ResultsPage, null);
    act(() => { expect(modalHistory.request!()).toBe(false); });
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    expect(input).toHaveValue('Unsaved protected edit');
    act(() => { expect(modalHistory.request!()).toBe(false); });
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('does not silently retarget or replace an already open editor', async () => {
    feed.current = response([result('a', ACTIONABLE_TRUTH), result('b', ACTIONABLE_TRUTH)]);
    await openDialogFor('a');
    fireEvent.change(screen.getByRole('textbox', { name: 'Email text' }), { target: { value: 'My target A email' } });
    act(() => { captured.resume!('b'); captured.draft!('b'); });
    expect(screen.getAllByRole('dialog')).toHaveLength(1);
    expect(screen.getByTestId('cold-email-modal')).toHaveTextContent('target:a');
    expect(screen.getByRole('textbox', { name: 'Email text' })).toHaveValue('My target A email');
  });
});
