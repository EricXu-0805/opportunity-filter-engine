/*
 * /tracker page zero-state discipline (W14): a failed load renders a
 * dedicated error state with a retry — DISTINCT from the genuine
 * "nothing tracked yet" empty board the old code faked on failure.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockGetInteractionsFull = vi.fn();
const mockGetOpportunitiesByIds = vi.fn();

vi.mock('@/lib/supabase', () => ({
  getInteractionsFull: () => mockGetInteractionsFull(),
  trackInteraction: vi.fn(() => Promise.resolve()),
  removeInteraction: vi.fn(() => Promise.resolve()),
  updateInteractionDetails: vi.fn(() => Promise.resolve(true)),
  onAuthChange: () => () => {},
}));

vi.mock('@/lib/api', () => ({
  getOpportunitiesByIds: (...args: unknown[]) => mockGetOpportunitiesByIds(...args),
}));

vi.mock('@/components/StorageStatusBanner', () => ({
  default: () => <div data-testid="storage-status-banner" />,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    locale: 'en',
    t: (key: string, vars?: Record<string, string | number>) =>
      vars ? `${key} ${JSON.stringify(vars)}` : key,
  }),
}));

import TrackerPage from './page';

beforeEach(() => {
  mockGetInteractionsFull.mockResolvedValue(new Map());
  mockGetOpportunitiesByIds.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('TrackerPage — truthful zero states', () => {
  it('renders the genuine empty board when the user tracked nothing', async () => {
    render(<TrackerPage />);

    expect(await screen.findByText('tracker.emptyTitle')).toBeInTheDocument();
    expect(screen.queryByTestId('tracker-load-error')).toBeNull();
  });

  it('renders the error state (not the empty board) when the load fails', async () => {
    mockGetInteractionsFull.mockRejectedValue(
      new Error('interactions-load-failed: outage'),
    );

    render(<TrackerPage />);

    expect(await screen.findByTestId('tracker-load-error')).toBeInTheDocument();
    expect(screen.getByText('tracker.loadError')).toBeInTheDocument();
    expect(screen.queryByText('tracker.emptyTitle')).toBeNull();
    expect(screen.queryByText('tracker.columnEmpty')).toBeNull();
  });

  it('retry refetches and renders the board on success', async () => {
    mockGetInteractionsFull
      .mockRejectedValueOnce(new Error('interactions-load-failed: blip'))
      .mockResolvedValueOnce(new Map([['o1', { type: 'applied' }]]));
    mockGetOpportunitiesByIds.mockResolvedValue([{ id: 'o1', title: 'Tracked Lab' }]);

    render(<TrackerPage />);

    fireEvent.click(await screen.findByText('common.retry'));

    await waitFor(() => {
      expect(screen.getByText('Tracked Lab')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('tracker-load-error')).toBeNull();
    expect(mockGetInteractionsFull).toHaveBeenCalledTimes(2);
  });
});
