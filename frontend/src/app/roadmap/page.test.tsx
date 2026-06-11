/*
 * Roadmap page error-state tests. Before this fix the catch swallowed
 * API failures and the page fell into the misleading "all set" /
 * empty-CTA branches; these tests pin the distinct error card + retry.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockGetFavorites = vi.fn();
const mockGetRoadmap = vi.fn();

vi.mock('@/lib/supabase', () => ({
  getFavorites: () => mockGetFavorites(),
}));

vi.mock('@/lib/api', () => ({
  getRoadmap: (...args: unknown[]) => mockGetRoadmap(...args),
}));

// Stable reference, like the real hook (useSyncExternalStore caches the
// parse) — a fresh object per render would re-fire the load effect forever.
const PROFILE = { college: 'Grainger', major: 'ECE', grade: 'Freshman' };
vi.mock('@/lib/use-local-storage-json', () => ({
  useLocalStorageJSON: () => PROFILE,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

import RoadmapPage from './page';

const ROADMAP = {
  skills: [
    { skill: 'PyTorch', needed_by: 2, priority: 'high', estimated_time: '4 weeks', courses: ['ECE 449'] },
  ],
  total_labs: 3,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('RoadmapPage — error state', () => {
  it('shows the error card (not the all-set state) when getRoadmap fails', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['opp-1']));
    mockGetRoadmap.mockRejectedValue(new Error('500'));

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('roadmap.errorTitle')).toBeInTheDocument();
    });
    expect(screen.queryByText('roadmap.allSetTitle')).toBeNull();
    expect(screen.queryByText('roadmap.needFavoritesTitle')).toBeNull();
  });

  it('shows the error card when getFavorites itself fails', async () => {
    mockGetFavorites.mockRejectedValue(new Error('network'));

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('roadmap.errorTitle')).toBeInTheDocument();
    });
    expect(mockGetRoadmap).not.toHaveBeenCalled();
  });

  it('retry button re-runs the load and renders the roadmap on success', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['opp-1']));
    mockGetRoadmap
      .mockRejectedValueOnce(new Error('500'))
      .mockResolvedValueOnce(ROADMAP);

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('roadmap.errorTitle')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'roadmap.errorRetry' }));

    await waitFor(() => {
      expect(screen.getByText('PyTorch')).toBeInTheDocument();
    });
    expect(screen.queryByText('roadmap.errorTitle')).toBeNull();
    expect(mockGetRoadmap).toHaveBeenCalledTimes(2);
  });
});
