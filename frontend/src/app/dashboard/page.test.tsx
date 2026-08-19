/*
 * Dashboard tests: the page must show the student's OWN metrics (saved,
 * tracker funnel, favorite deadlines with precision labels, reminders) and
 * honest empty/error states — never whole-database vanity stats.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockGetFavorites = vi.fn();
const mockGetInteractionsFull = vi.fn();
const mockGetShortlistOpportunities = vi.fn();
const mockGetStats = vi.fn();

vi.mock('@/lib/supabase', () => ({
  getFavorites: () => mockGetFavorites(),
  getInteractionsFull: () => mockGetInteractionsFull(),
  // useAuthUid subscribes through this wrapper; never emitting keeps the
  // identity epoch at 0 so the page loads exactly once per test.
  onAuthChange: () => () => {},
}));

vi.mock('@/lib/api', () => ({
  getShortlistOpportunities: (...args: unknown[]) => mockGetShortlistOpportunities(...args),
  getStats: (...args: unknown[]) => mockGetStats(...args),
}));

vi.mock('@/components/PushToggle', () => ({
  default: () => <div data-testid="push-toggle" />,
}));

// W14: the dashboard mounts the storage banner like /favorites and /tracker.
// It has its own test file — stub it and only assert that it is mounted.
vi.mock('@/components/StorageStatusBanner', () => ({
  default: () => <div data-testid="storage-status-banner" />,
}));

// Owns its own data loads and has a dedicated test file — stub it here so
// page tests stay focused on the page's four original sections.
vi.mock('./ProfessorUpdatesSection', () => ({
  ProfessorUpdatesSection: () => <div data-testid="professor-updates-section" />,
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    locale: 'en',
    t: (key: string, vars?: Record<string, string | number>) =>
      vars ? `${key} ${JSON.stringify(vars)}` : key,
  }),
}));

import DashboardPage from './page';

function isoDateIn(days: number): string {
  const date = new Date();
  date.setHours(12, 0, 0, 0);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

/** An ISO timestamp `hours` in the past — for the freshness thresholds. */
function isoHoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
}

/** The batch fetch's fail-closed shape: what resolved, and what did not. */
function shortlist(
  opportunities: Record<string, unknown>[],
  unavailableIds: string[] = [],
) {
  return { opportunities, unavailableIds };
}

/** Never resolves — leaves the page pinned in its loading state. */
function pending<T>(): Promise<T> {
  return new Promise<T>(() => {});
}

/** The four tracker-fed funnel tiles (saved-summary is fed separately). */
const FUNNEL_CARDS = [
  'applied-summary',
  'replied-summary',
  'interviewing-summary',
  'rejected-summary',
] as const;

beforeEach(() => {
  mockGetFavorites.mockResolvedValue(new Set());
  mockGetInteractionsFull.mockResolvedValue(new Map());
  mockGetShortlistOpportunities.mockResolvedValue(shortlist([]));
  mockGetStats.mockResolvedValue({ last_updated_at: isoHoursAgo(2) });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('DashboardPage — personal metrics', () => {
  it('does not mount hidden Professor Updates or the Roadmap CTA', async () => {
    render(<DashboardPage />);

    await waitFor(() => expect(screen.getByTestId('saved-summary')).toHaveTextContent('0'));
    expect(screen.queryByTestId('professor-updates-section')).not.toBeInTheDocument();
    expect(screen.queryByText('dashboard.roadmapCta.title')).not.toBeInTheDocument();
  });

  it('shows the saved count and tracker funnel, with no whole-database stats', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['fav-1', 'fav-2']));
    mockGetInteractionsFull.mockResolvedValue(new Map([
      ['opp-a', { type: 'applied' }],
      ['opp-b', { type: 'applied' }],
      ['opp-c', { type: 'replied' }],
      ['opp-d', { type: 'interviewing' }],
    ]));
    mockGetShortlistOpportunities.mockResolvedValue(shortlist([]));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByTestId('saved-summary')).toHaveTextContent('2');
    });
    expect(screen.getByText('dashboard.summary.title')).toBeInTheDocument();
    // Whole-database vanity metrics are gone.
    expect(screen.queryByText('dashboard.stats.total')).toBeNull();
    expect(screen.queryByText('dashboard.stats.active')).toBeNull();
    expect(screen.queryByText('dashboard.distribution.title')).toBeNull();
    expect(screen.queryByText(/Total Opps/i)).toBeNull();
  });

  it('lists upcoming favorite deadlines with estimate/verify labels, soonest first', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['exact', 'estimated', 'unknown-precision']));
    mockGetInteractionsFull.mockResolvedValue(new Map());
    mockGetShortlistOpportunities.mockResolvedValue(shortlist([
      {
        id: 'estimated',
        title: 'Estimated Deadline Lab',
        organization: 'Org B',
        deadline: isoDateIn(5),
        deadline_is_estimate: true,
      },
      {
        id: 'exact',
        title: 'Exact Deadline Lab',
        organization: 'Org A',
        deadline: isoDateIn(3),
        deadline_is_estimate: false,
      },
      {
        id: 'unknown-precision',
        title: 'Unknown Precision Lab',
        organization: 'Org C',
        deadline: isoDateIn(9),
      },
    ]));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('Exact Deadline Lab')).toBeInTheDocument();
    });
    // Confirmed date → countdown; estimated → estimate label; absent flag → verify.
    expect(screen.getByText('dashboard.deadlines.inDays {"days":3}')).toBeInTheDocument();
    expect(screen.getByText('dashboard.deadlines.estimated')).toBeInTheDocument();
    expect(screen.getByText('dashboard.deadlines.verifyDate')).toBeInTheDocument();

    const titles = screen.getAllByText(/Deadline Lab|Precision Lab/).map((el) => el.textContent);
    expect(titles).toEqual([
      'Exact Deadline Lab',
      'Estimated Deadline Lab',
      'Unknown Precision Lab',
    ]);
  });

  it('does not treat a poisoned faculty-profile date as a saved deadline', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['faculty-1', 'listing-1']));
    mockGetInteractionsFull.mockResolvedValue(new Map());
    mockGetShortlistOpportunities.mockResolvedValue(shortlist([
      {
        id: 'faculty-1',
        title: 'Faculty Contact Profile',
        source_type: 'faculty_research',
        deadline: isoDateIn(1),
        deadline_is_estimate: false,
      },
      {
        id: 'listing-1',
        title: 'Real Listing',
        source_type: 'campus_program',
        deadline: isoDateIn(4),
        deadline_is_estimate: false,
      },
    ]));

    render(<DashboardPage />);

    await waitFor(() => expect(screen.getByText('Real Listing')).toBeInTheDocument());
    expect(screen.queryByText('Faculty Contact Profile')).toBeNull();
  });

  it('never lets a non-favorite record leak into the saved-deadline list', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['fav-1']));
    mockGetShortlistOpportunities.mockResolvedValue(shortlist([
      { id: 'fav-1', title: 'My Favorite', deadline: isoDateIn(4), deadline_is_estimate: false },
      { id: 'intruder', title: 'Global Record', deadline: isoDateIn(2), deadline_is_estimate: false },
    ]));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('My Favorite')).toBeInTheDocument();
    });
    expect(screen.queryByText('Global Record')).toBeNull();
  });

  it('renders tracked applications with statuses and reminders from the student tracker', async () => {
    mockGetFavorites.mockResolvedValue(new Set());
    mockGetInteractionsFull.mockResolvedValue(new Map([
      ['opp-a', { type: 'applied', notes: 'emailed PI', remind_at: isoDateIn(2) }],
    ]));
    mockGetShortlistOpportunities.mockResolvedValue(shortlist([
      { id: 'opp-a', title: 'Tracked Lab', organization: 'Org', opportunity_type: 'research' },
    ]));

    render(<DashboardPage />);

    // The tracked opportunity appears in both the reminders list and the
    // tracker list; the status label also captions a funnel stat card.
    await waitFor(() => {
      expect(screen.getAllByText('Tracked Lab').length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText('tracker.status.applied').length).toBeGreaterThan(1);
    expect(screen.getByText('dashboard.reminders.inDays {"days":2}')).toBeInTheDocument();
    expect(screen.getByTestId('push-toggle')).toBeInTheDocument();
  });
});

describe('DashboardPage — honest empty and error states', () => {
  it('shows honest empty states when the student has no activity yet', async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('dashboard.deadlines.noSavesTitle')).toBeInTheDocument();
    });
    expect(screen.getByText('dashboard.trackerSection.emptyTitle')).toBeInTheDocument();
    expect(screen.getByText('dashboard.reminders.emptyTitle')).toBeInTheDocument();
    expect(screen.getByTestId('saved-summary')).toHaveTextContent('0');
  });

  it('distinguishes "saved but no deadlines" from "nothing saved"', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['fav-1']));
    mockGetShortlistOpportunities.mockResolvedValue(shortlist([
      { id: 'fav-1', title: 'Rolling Lab' },
    ]));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('dashboard.deadlines.emptyTitle')).toBeInTheDocument();
    });
    expect(screen.queryByText('dashboard.deadlines.noSavesTitle')).toBeNull();
  });

  it('surfaces load failures as errors instead of pretending the lists are empty', async () => {
    // W14: these rejections now drive the REAL lib contract —
    // getInteractionsFull/getFavorites throw on session/query failure
    // instead of collapsing into empty collections.
    mockGetFavorites.mockRejectedValue(new Error('offline'));
    mockGetInteractionsFull.mockRejectedValue(new Error('interactions-load-failed: offline'));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('dashboard.deadlines.errorTitle')).toBeInTheDocument();
    });
    expect(screen.getByText('dashboard.saved.errorTitle')).toBeInTheDocument();
    expect(screen.getAllByText('dashboard.trackerSection.errorTitle').length).toBeGreaterThan(0);
    expect(screen.getByText('dashboard.reminders.errorTitle')).toBeInTheDocument();
    expect(screen.queryByText('dashboard.deadlines.noSavesTitle')).toBeNull();
    // W16: every metric fed by a failed load says so explicitly — not a
    // confident 0, and no longer the same em-dash a still-loading or a
    // genuinely-unknown tile would render.
    for (const id of FUNNEL_CARDS) {
      const card = screen.getByTestId(id);
      expect(card).toHaveAttribute('data-state', 'error');
      expect(card).toHaveTextContent('dashboard.summary.unavailable');
      expect(card.textContent).not.toContain('—');
      expect(card.textContent).not.toContain('0');
    }
    expect(screen.getByTestId('saved-summary')).toHaveAttribute('data-state', 'error');
    expect(screen.queryAllByText('—')).toHaveLength(0);
    // The sync-status banner is mounted so a local-only outage is visible.
    expect(screen.getByTestId('storage-status-banner')).toBeInTheDocument();
  });

  it('keeps funnel stat cards out of a fabricated zero when only the tracker load fails', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['fav-1']));
    mockGetShortlistOpportunities.mockResolvedValue(shortlist([]));
    mockGetInteractionsFull.mockRejectedValue(new Error('interactions-load-failed: outage'));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getAllByText('dashboard.trackerSection.errorTitle').length).toBeGreaterThan(0);
    });
    // Saved is real (1); the four funnel cards fed by getInteractionsFull
    // must show the error affordance, never fabricated zeros.
    const savedCard = screen.getByTestId('saved-summary');
    expect(savedCard).toHaveAttribute('data-state', 'ready');
    expect(savedCard).toHaveTextContent('1');
    for (const id of FUNNEL_CARDS) {
      const card = screen.getByTestId(id);
      expect(card).toHaveAttribute('data-state', 'error');
      expect(card.textContent).not.toContain('0');
    }
    expect(screen.getByText('dashboard.reminders.errorTitle')).toBeInTheDocument();
  });

  it('keeps the student-recorded statuses and reminder dates when the title lookup fails', async () => {
    mockGetFavorites.mockResolvedValue(new Set());
    mockGetInteractionsFull.mockResolvedValue(new Map([
      ['opp-a', { type: 'applied', remind_at: isoDateIn(1) }],
    ]));
    mockGetShortlistOpportunities.mockRejectedValue(new Error('batch endpoint down'));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('dashboard.reminders.detailsUnavailable')).toBeInTheDocument();
    });
    // Status funnel and reminder countdown come from the tracker itself
    // (label appears on the stat card and the tracked-row chip).
    expect(screen.getAllByText('tracker.status.applied').length).toBeGreaterThan(1);
    expect(screen.getByText('dashboard.reminders.tomorrow')).toBeInTheDocument();
  });
});

/*
 * W16 — the stat tiles used to collapse loading, error, and unknown into one
 * em-dash, so "we're still fetching" was indistinguishable from "the request
 * failed". Each state must now render distinctly, and a REAL zero must keep
 * rendering as 0 (the point of W14, and the easiest thing to regress).
 */
describe('DashboardPage — stat tile state vocabulary', () => {
  it('renders a skeleton while loading — never an em-dash and never a zero', async () => {
    mockGetFavorites.mockReturnValue(pending<Set<string>>());
    mockGetInteractionsFull.mockReturnValue(pending<Map<string, unknown>>());

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByTestId('saved-summary')).toHaveAttribute('data-state', 'loading');
    });
    expect(screen.getByTestId('saved-summary-skeleton')).toBeInTheDocument();
    for (const id of ['saved-summary', ...FUNNEL_CARDS]) {
      const card = screen.getByTestId(id);
      expect(card).toHaveAttribute('data-state', 'loading');
      expect(card.textContent).not.toContain('—');
      expect(card.textContent).not.toContain('0');
    }
  });

  it('renders a real zero as 0, not as an absence', async () => {
    mockGetFavorites.mockResolvedValue(new Set());
    mockGetInteractionsFull.mockResolvedValue(new Map([['opp-a', { type: 'applied' }]]));
    mockGetShortlistOpportunities.mockResolvedValue(shortlist([{ id: 'opp-a', title: 'Lab' }]));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByTestId('saved-summary')).toHaveAttribute('data-state', 'ready');
    });
    // Zero saves and zero rejections are FACTS here — both render as 0.
    expect(screen.getByTestId('saved-summary')).toHaveTextContent('0');
    expect(screen.getByTestId('rejected-summary')).toHaveTextContent('0');
    expect(screen.getByTestId('applied-summary')).toHaveTextContent('1');
    expect(screen.queryAllByText('—')).toHaveLength(0);
  });

  it('offers a retry from the error state that re-runs the loads', async () => {
    mockGetFavorites.mockRejectedValueOnce(new Error('offline'));
    mockGetInteractionsFull.mockRejectedValueOnce(new Error('interactions-load-failed'));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByTestId('saved-summary')).toHaveAttribute('data-state', 'error');
    });
    mockGetFavorites.mockResolvedValue(new Set(['fav-1']));
    mockGetInteractionsFull.mockResolvedValue(new Map());
    mockGetShortlistOpportunities.mockResolvedValue(shortlist([]));

    fireEvent.click(screen.getAllByText('common.retry')[0]);

    await waitFor(() => {
      expect(screen.getByTestId('saved-summary')).toHaveTextContent('1');
    });
  });
});

/*
 * W16 — favorited/tracked ids the corpus cannot resolve used to be filtered
 * out with no count and no note, so a missing record was indistinguishable
 * from one the student never saved. /favorites (unavailableCount) and
 * /tracker (unavailableItems) already report them; the dashboard now does too.
 */
describe('DashboardPage — unresolvable saved and tracked ids', () => {
  it('reports saved deadlines that could not be loaded instead of dropping them', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['fav-1', 'gone-1', 'gone-2']));
    mockGetShortlistOpportunities.mockResolvedValue(shortlist(
      [{ id: 'fav-1', title: 'Live Lab', deadline: isoDateIn(3), deadline_is_estimate: false }],
      ['gone-1', 'gone-2'],
    ));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('Live Lab')).toBeInTheDocument();
    });
    expect(screen.getByText('dashboard.unavailable.saved {"count":2}')).toBeInTheDocument();
    // The saved count is the student's real total — unchanged by a failed
    // corpus lookup.
    expect(screen.getByTestId('saved-summary')).toHaveTextContent('3');
  });

  it('never claims "no deadlines" when every saved id was unresolvable', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['gone-1']));
    mockGetShortlistOpportunities.mockResolvedValue(shortlist([], ['gone-1']));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('dashboard.unavailable.saved {"count":1}')).toBeInTheDocument();
    });
    expect(screen.queryByText('dashboard.deadlines.emptyTitle')).toBeNull();
    expect(screen.queryByText('dashboard.deadlines.noSavesTitle')).toBeNull();
  });

  it('reports tracked rows whose opportunity could not be loaded', async () => {
    mockGetFavorites.mockResolvedValue(new Set());
    mockGetInteractionsFull.mockResolvedValue(new Map([
      ['opp-a', { type: 'applied' }],
      ['gone-1', { type: 'replied', remind_at: isoDateIn(1) }],
    ]));
    mockGetShortlistOpportunities.mockResolvedValue(shortlist(
      [{ id: 'opp-a', title: 'Tracked Lab' }],
      ['gone-1'],
    ));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('Tracked Lab')).toBeInTheDocument();
    });
    // Once for the tracker list, once for the reminder row that points at
    // the same unresolvable record.
    expect(screen.getAllByText('dashboard.unavailable.tracked {"count":1}').length).toBeGreaterThan(0);
    // The student's own statuses are untouched by the failed lookup.
    expect(screen.getByTestId('applied-summary')).toHaveTextContent('1');
    expect(screen.getByTestId('replied-summary')).toHaveTextContent('1');
  });

  it('shows no unavailable note when everything resolved', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['fav-1']));
    mockGetShortlistOpportunities.mockResolvedValue(shortlist([
      { id: 'fav-1', title: 'Live Lab', deadline: isoDateIn(3), deadline_is_estimate: false },
    ]));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('Live Lab')).toBeInTheDocument();
    });
    expect(screen.queryAllByTestId('dashboard-unavailable-note')).toHaveLength(0);
  });
});

/*
 * W16 — the corpus freshness line. `last_updated_at` was null in production
 * until the backend read the committed collector snapshot, so the one rule
 * that matters here: null/failed must render as UNKNOWN, never as fresh.
 * Thresholds mirror admin/FreshnessBanner.tsx (warn >= 72h, stale >= 96h).
 */
describe('DashboardPage — corpus freshness line', () => {
  async function freshnessState(): Promise<string | null> {
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('corpus-freshness')).not.toHaveAttribute('data-state', 'loading');
    });
    return screen.getByTestId('corpus-freshness').getAttribute('data-state');
  }

  it('renders fresh below the 72h warn boundary', async () => {
    mockGetStats.mockResolvedValue({ last_updated_at: isoHoursAgo(71) });
    expect(await freshnessState()).toBe('fresh');
    expect(screen.getByText(/dashboard\.freshness\.updated/)).toBeInTheDocument();
  });

  it('renders warn at 72h and stale at 96h — the admin banner boundaries', async () => {
    mockGetStats.mockResolvedValue({ last_updated_at: isoHoursAgo(72.5) });
    expect(await freshnessState()).toBe('warn');
    expect(screen.getByText('dashboard.freshness.warnNote')).toBeInTheDocument();
    cleanup();

    mockGetStats.mockResolvedValue({ last_updated_at: isoHoursAgo(96.5) });
    expect(await freshnessState()).toBe('stale');
    expect(screen.getByText('dashboard.freshness.staleNote')).toBeInTheDocument();
  });

  it('renders an explicit unknown when the backend has no timestamp', async () => {
    mockGetStats.mockResolvedValue({ last_updated_at: null });
    expect(await freshnessState()).toBe('unknown');
    expect(screen.getByText('dashboard.freshness.unknown')).toBeInTheDocument();
    // Never a freshness claim we do not have.
    expect(screen.queryByText(/dashboard\.freshness\.updated/)).toBeNull();
  });

  it('renders unknown (not fresh) when the stats request fails', async () => {
    mockGetStats.mockRejectedValue(new Error('stats down'));
    expect(await freshnessState()).toBe('unknown');
    expect(screen.getByText('dashboard.freshness.unknown')).toBeInTheDocument();
  });

  it('shows a checking state while the stats request is in flight', async () => {
    mockGetStats.mockReturnValue(pending<{ last_updated_at: string | null }>());
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('corpus-freshness')).toHaveAttribute('data-state', 'loading');
    });
    expect(screen.getByText('dashboard.freshness.checking')).toBeInTheDocument();
  });
});
