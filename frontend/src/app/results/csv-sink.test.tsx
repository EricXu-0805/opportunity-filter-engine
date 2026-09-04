/* @vitest-environment jsdom */
// Export is the furthest a row ever travels from this session. A spreadsheet
// is opened weeks later, forwarded, pasted into an application tracker — with
// none of the page's context and no way to re-check anything. So the bar is
// higher here than on screen: a row we cannot fully vouch for must not be
// written at all.
//
// This drives the REAL sink. `matchesToCSV` has its own unit tests, but a
// correct row formatter proves nothing if the page hands it rows it should
// have refused — so what is captured here is `downloadCSV`, and the assertion
// on every bad page is that it was never called.
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';

const mockGetMatchView = vi.fn();
const mockDownloadCSV = vi.fn();

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

vi.mock('@/lib/csv-export', () => ({
  downloadCSV: (...args: unknown[]) => mockDownloadCSV(...args),
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

// The page's own list fetch is stubbed out entirely. Left real it calls the
// same mocked getMatchView on mount, so it would consume the queued
// mockResolvedValueOnce responses meant for the export — and the multi-page
// cases would silently assert nothing. Export must be the only consumer.
vi.mock('./use-results-data', () => ({
  useResultsData: () => ({
    data: {
      total: 0, high_priority: 0, good_match: 0, reach: 0, low_fit: 0,
      results: [], returned_count: 0, has_more: false, next_cursor: null,
      contract_version: 'match-view-v3-faculty-trust',
      target_truth_contract: 'target-truth-v2',
      view_start: 0, filtered_total: 0,
      view_counts: { all: 0, high_priority: 0, good_match: 0, reach: 0, starred: 0 },
      view_id: 'view-1', result_set_id: 'set-1',
    },
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
vi.mock('./MatchList', () => ({ MatchList: () => <div data-testid="mock-match-list" /> }));

// The page's own export handler, captured off the header so the sink can be
// driven without depending on the header's markup.
const captured = vi.hoisted(() => ({ exportNow: null as null | (() => Promise<void>) }));
vi.mock('./ResultsHeader', () => ({
  ResultsHeader: (props: { onExport: () => Promise<void> }) => {
    captured.exportNow = props.onExport;
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
      // The kind the truth's reason belongs on. `faculty_not_accepting`
      // quotes a named person and the backend emits it only for a
      // `faculty_research` row — on a listing the page would be refused for
      // being unreadable, which is a different rule than the one the faculty
      // case below means to exercise.
      source_type: (truth as { reason_code?: string } | null)?.reason_code === 'faculty_not_accepting'
        ? 'faculty_research'
        : 'campus_program',
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

async function exporter() {
  const { default: ResultsPage } = await import('./page');
  render(<ResultsPage />);
  await waitFor(() => expect(captured.exportNow).not.toBeNull());
  return captured.exportNow!;
}

function csvBody(): string {
  return String(mockDownloadCSV.mock.calls[0][1]);
}

/** Title cell of each DATA row, header excluded.
 *
 *  Substring search over the whole file cannot show ordering: "Title",
 *  "Organization" and every other header word are in the text too, so a
 *  one-character id would match the header and "prove" any order at all.
 */
function csvTitles(): string[] {
  return csvBody()
    .split('\n')
    .slice(1)
    .filter((line) => line.length > 0)
    .map((line) => /^"((?:[^"]|"")*)"/.exec(line)?.[1] ?? '');
}

/** Cursors the export sent, in order — `null` on the first request. */
function cursorSequence(): (string | null)[] {
  return mockGetMatchView.mock.calls.map(
    (call) => (call[2] as { cursor?: string | null } | undefined)?.cursor ?? null,
  );
}

beforeEach(() => {
  // mockReset, not clearAllMocks: clearing wipes call history but keeps the
  // previous test's resolved value, so a test that forgot to set one would
  // inherit it and pass for the wrong reason.
  mockGetMatchView.mockReset();
  mockDownloadCSV.mockReset();
  captured.exportNow = null;
  window.localStorage.clear();
  // handleExport reports failure through alert(); jsdom leaves it unimplemented.
  vi.spyOn(window, 'alert').mockImplementation(() => {});
});

describe('the CSV sink writes only pages it can vouch for', () => {
  it('downloads a trusted page, in the order the server returned it', async () => {
    const rows = [
      result('row-alpha', ACTIONABLE_TRUTH),
      result('row-bravo', ACTIONABLE_TRUTH),
      result('row-charlie', ACTIONABLE_TRUTH),
    ];
    mockGetMatchView.mockResolvedValue(response(rows));

    await (await exporter())();

    expect(mockDownloadCSV).toHaveBeenCalledTimes(1);
    // Order is part of the deliverable: a spreadsheet reader takes row order
    // as ranking, and the server is the only thing that ranked anything.
    expect(csvTitles()).toEqual(['row-alpha', 'row-bravo', 'row-charlie']);
    expect(window.alert).not.toHaveBeenCalled();
  });

  it('says so when the active view excludes every favorite, instead of doing nothing', async () => {
    // 93.9% of the corpus is faculty contacts and no faculty record can
    // satisfy any deadline chip, so one starred professor plus the one chip
    // that renders is an empty intersection. The header still reads "Export 1
    // starred CSV", and the click used to fire a real round trip and return in
    // silence — repeatably, with no file and no explanation.
    mockGetMatchView.mockResolvedValue(response([]));

    await (await exporter())();

    expect(mockDownloadCSV).not.toHaveBeenCalled();
    expect(window.alert).toHaveBeenCalledWith(
      expect.stringContaining('exportNothingInView'),
    );
  });

  it('downloads once, after both pages, when a two-page fetch checks out', async () => {
    // The positive control for every multi-page assertion below. If the export
    // is the only caller of getMatchView, this is exactly two requests with
    // exactly these cursors — and one file, written after the last one.
    mockGetMatchView
      .mockResolvedValueOnce(response(
        [result('page-one-row', ACTIONABLE_TRUTH)],
        { has_more: true, next_cursor: 'cursor-2', filtered_total: 2 },
      ))
      .mockResolvedValueOnce(response(
        [result('page-two-row', ACTIONABLE_TRUTH)],
        { filtered_total: 2 },
      ));

    await (await exporter())();

    expect(cursorSequence()).toEqual([null, 'cursor-2']);
    expect(mockDownloadCSV).toHaveBeenCalledTimes(1);
    // Page one's row first: the accumulator preserves fetch order across the
    // page boundary, so the file reads in the ranking the server produced.
    expect(csvTitles()).toEqual(['page-one-row', 'page-two-row']);
    expect(window.alert).not.toHaveBeenCalled();
  });

  it('writes the page the backend actually speaks', async () => {
    // The positive control for the version pair below: the marker AND the one
    // wire version this backend emits. Without it the rejection test could
    // pass because the export is broken outright.
    mockGetMatchView.mockResolvedValue(response(
      [result('ok-1', ACTIONABLE_TRUTH)],
      { contract_version: 'match-view-v3-faculty-trust' },
    ));

    await (await exporter())();

    expect(mockDownloadCSV).toHaveBeenCalledTimes(1);
    expect(window.alert).not.toHaveBeenCalled();
  });

  it('refuses a wire version nobody has agreed to, marker notwithstanding', async () => {
    // The marker says the backend makes a truth promise; it does not say what
    // shape the rows arrive in. A version string this client has never seen
    // came from a payload whose fields were never reviewed — and the export
    // is where a row travels furthest from anyone who could check it.
    mockGetMatchView.mockResolvedValue(response(
      [result('ok-1', ACTIONABLE_TRUTH)],
      { contract_version: 'match-view-v4-target-truth' },
    ));

    await (await exporter())();

    expect(mockDownloadCSV).not.toHaveBeenCalled();
    expect(window.alert).toHaveBeenCalled();
  });

  it('treats a marked empty page as a legitimate nothing, not a failure', async () => {
    // No rows to write and no error to report. It still has to say something:
    // the button is labelled "Export N starred CSV" from an unfiltered count,
    // so silence reads as a broken control. What it must NOT say is that the
    // load failed.
    mockGetMatchView.mockResolvedValue(response([]));

    await (await exporter())();

    expect(mockDownloadCSV).not.toHaveBeenCalled();
    expect(window.alert).toHaveBeenCalledTimes(1);
    expect(window.alert).not.toHaveBeenCalledWith(expect.stringContaining('loadFailed'));
  });

  const BAD_PAGES: [string, () => unknown][] = [
    ['no target-truth marker', () => response(
      [result('ok-1', ACTIONABLE_TRUTH)], { target_truth_contract: undefined },
    )],
    ['a marker naming a contract we do not implement', () => response(
      [result('ok-1', ACTIONABLE_TRUTH)], { target_truth_contract: 'target-truth-v9' },
    )],
    ['an unknown wire version', () => response(
      [result('ok-1', ACTIONABLE_TRUTH)], { contract_version: 'match-view-v9-future' },
    )],
    ['an absent truth', () => response([
      result('ok-1', ACTIONABLE_TRUTH), withoutTruth('gone'),
    ])],
    ['a null truth', () => response([result('null-1', null)])],
    ['a malformed truth', () => response([result('bad-1', { listing_state: 'open' })])],
    ['a self-contradicting truth', () => response([
      result('contra-1', { ...ACTIONABLE_TRUTH, listing_state: 'closed' }),
    ])],
    ['a historical row', () => response([
      result('ok-1', ACTIONABLE_TRUTH),
      result('closed-1', {
        ...ACTIONABLE_TRUTH,
        listing_state: 'closed', actionable: false, reference_only: true,
        accepting_state: 'not_accepting', reason_code: 'listing_closed',
      }),
    ])],
    // `result` gives this row source_type `faculty_research`, so it is the
    // canonical faculty refusal being refused — not a kind mismatch that
    // would be rejected before the reason was ever read.
    ['a faculty who said not to ask', () => response([
      result('stop-1', {
        ...ACTIONABLE_TRUTH,
        listing_state: 'unknown', actionable: false,
        accepting_state: 'not_accepting', reason_code: 'faculty_not_accepting',
      }),
    ])],
    ['a duplicate id within one page', () => response([
      result('dup-1', ACTIONABLE_TRUTH), result('dup-1', ACTIONABLE_TRUTH),
    ])],
  ];

  it.each(BAD_PAGES)('writes nothing when the page has %s', async (_label, build) => {
    mockGetMatchView.mockResolvedValue(build());

    await (await exporter())();

    expect(mockDownloadCSV).not.toHaveBeenCalled();
    expect(window.alert).toHaveBeenCalled();
  });

  it('writes nothing when a row\'s nested id drifted from its top-level id', async () => {
    // The export keys columns off one and renders values from the other, so a
    // drift ships one target's deadline under another target's name.
    const drifted = result('outer-1', ACTIONABLE_TRUTH);
    (drifted.opportunity as Record<string, unknown>).id = 'inner-other';
    mockGetMatchView.mockResolvedValue(response([drifted]));

    await (await exporter())();

    expect(mockDownloadCSV).not.toHaveBeenCalled();
  });

  it('writes nothing when an id repeats across two pages', async () => {
    // Per-page validation cannot see this one: each page is internally fine.
    // A duplicate across the boundary means the result set moved under us,
    // and half an old ranking merged with half a new one is not a list.
    mockGetMatchView
      .mockResolvedValueOnce(response(
        [result('a', ACTIONABLE_TRUTH)],
        { has_more: true, next_cursor: 'cursor-2', filtered_total: 2 },
      ))
      .mockResolvedValueOnce(response(
        [result('a', ACTIONABLE_TRUTH)],
        { filtered_total: 2 },
      ));

    await (await exporter())();

    // Both pages were actually requested — otherwise "no download" would be
    // explained by the export stopping early, not by the duplicate.
    expect(cursorSequence()).toEqual([null, 'cursor-2']);
    expect(mockDownloadCSV).not.toHaveBeenCalled();
    expect(window.alert).toHaveBeenCalled();
  });

  it('writes nothing when the second page is untrusted', async () => {
    // The first page is clean and would have downloaded on its own. Checking
    // only the first page is the tempting shortcut and the exact bug: rows
    // accumulate across pages, so page two's closed row lands in the file.
    mockGetMatchView
      .mockResolvedValueOnce(response(
        [result('a', ACTIONABLE_TRUTH)],
        { has_more: true, next_cursor: 'cursor-2', filtered_total: 2 },
      ))
      .mockResolvedValueOnce(response(
        [result('b', { ...ACTIONABLE_TRUTH, actionable: false, reason_code: 'inactive' })],
        { filtered_total: 2 },
      ));

    await (await exporter())();

    expect(cursorSequence()).toEqual([null, 'cursor-2']);
    expect(mockDownloadCSV).not.toHaveBeenCalled();
    expect(window.alert).toHaveBeenCalled();
  });
});
