/*
 * Dashboard tests: the page must show the student's OWN metrics (saved,
 * tracker funnel, favorite deadlines with precision labels, reminders) and
 * honest empty/error states — never whole-database vanity stats.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';

const mockGetFavorites = vi.fn();
const mockGetInteractionsFull = vi.fn();
const mockGetOpportunitiesByIds = vi.fn();

vi.mock('@/lib/supabase', () => ({
  getFavorites: () => mockGetFavorites(),
  getInteractionsFull: () => mockGetInteractionsFull(),
}));

vi.mock('@/lib/api', () => ({
  getOpportunitiesByIds: (...args: unknown[]) => mockGetOpportunitiesByIds(...args),
}));

vi.mock('@/components/PushToggle', () => ({
  default: () => <div data-testid="push-toggle" />,
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

beforeEach(() => {
  mockGetFavorites.mockResolvedValue(new Set());
  mockGetInteractionsFull.mockResolvedValue(new Map());
  mockGetOpportunitiesByIds.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('DashboardPage — personal metrics', () => {
  it('shows the saved count and tracker funnel, with no whole-database stats', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['fav-1', 'fav-2']));
    mockGetInteractionsFull.mockResolvedValue(new Map([
      ['opp-a', { type: 'applied' }],
      ['opp-b', { type: 'applied' }],
      ['opp-c', { type: 'replied' }],
      ['opp-d', { type: 'interviewing' }],
    ]));
    mockGetOpportunitiesByIds.mockResolvedValue([]);

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
    mockGetOpportunitiesByIds.mockResolvedValue([
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
    ]);

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

  it('never lets a non-favorite record leak into the saved-deadline list', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['fav-1']));
    mockGetOpportunitiesByIds.mockResolvedValue([
      { id: 'fav-1', title: 'My Favorite', deadline: isoDateIn(4), deadline_is_estimate: false },
      { id: 'intruder', title: 'Global Record', deadline: isoDateIn(2), deadline_is_estimate: false },
    ]);

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
    mockGetOpportunitiesByIds.mockResolvedValue([
      { id: 'opp-a', title: 'Tracked Lab', organization: 'Org', opportunity_type: 'research' },
    ]);

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
    mockGetOpportunitiesByIds.mockResolvedValue([
      { id: 'fav-1', title: 'Rolling Lab' },
    ]);

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('dashboard.deadlines.emptyTitle')).toBeInTheDocument();
    });
    expect(screen.queryByText('dashboard.deadlines.noSavesTitle')).toBeNull();
  });

  it('surfaces load failures as errors instead of pretending the lists are empty', async () => {
    mockGetFavorites.mockRejectedValue(new Error('offline'));
    mockGetInteractionsFull.mockRejectedValue(new Error('offline'));

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('dashboard.deadlines.errorTitle')).toBeInTheDocument();
    });
    expect(screen.getByText('dashboard.saved.errorTitle')).toBeInTheDocument();
    expect(screen.getAllByText('dashboard.trackerSection.errorTitle').length).toBeGreaterThan(0);
    expect(screen.queryByText('dashboard.deadlines.noSavesTitle')).toBeNull();
  });

  it('keeps the student-recorded statuses and reminder dates when the title lookup fails', async () => {
    mockGetFavorites.mockResolvedValue(new Set());
    mockGetInteractionsFull.mockResolvedValue(new Map([
      ['opp-a', { type: 'applied', remind_at: isoDateIn(1) }],
    ]));
    mockGetOpportunitiesByIds.mockRejectedValue(new Error('batch endpoint down'));

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
