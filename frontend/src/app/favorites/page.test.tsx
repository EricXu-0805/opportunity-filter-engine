/*
 * /favorites page zero-state discipline (W14): a failed server load renders
 * a dedicated error state with a retry — DISTINCT from the "you haven't
 * starred anything" empty state the old `catch {}` faked on failure. Retry
 * refetches and recovers, and the saved-searches section failure surfaces
 * as an inline note instead of silently vanishing.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockGetFavorites = vi.fn();
const mockGetOpportunitiesByIds = vi.fn();
const mockListSavedSearches = vi.fn();
const mockListSavedSearchDigests = vi.fn();

vi.mock('@/lib/supabase', () => ({
  getFavorites: () => mockGetFavorites(),
  toggleFavorite: vi.fn(() => Promise.resolve(false)),
  getInteractionsFull: vi.fn(() => Promise.resolve(new Map())),
  onAuthChange: () => () => {},
}));

vi.mock('@/lib/api', () => ({
  getOpportunitiesByIds: (...args: unknown[]) => mockGetOpportunitiesByIds(...args),
  sendFavoritesEmail: vi.fn(),
}));

vi.mock('@/lib/saved-searches', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  listSavedSearches: () => mockListSavedSearches(),
  listSavedSearchDigests: () => mockListSavedSearchDigests(),
  removeSavedSearch: vi.fn(() => Promise.resolve(true)),
  setSavedSearchDigest: vi.fn(() => Promise.resolve(true)),
}));

vi.mock('@/lib/custom-imports', () => ({
  useCustomImports: () => [],
  removeCustomImport: vi.fn(),
}));

vi.mock('@/components/StorageStatusBanner', () => ({
  default: () => <div data-testid="storage-status-banner" />,
}));

vi.mock('@/components/SaveFavoritesAnchor', () => ({
  default: () => null,
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

import FavoritesPage from './page';

beforeEach(() => {
  mockGetFavorites.mockResolvedValue(new Set());
  mockGetOpportunitiesByIds.mockResolvedValue([]);
  mockListSavedSearches.mockResolvedValue([]);
  mockListSavedSearchDigests.mockResolvedValue(new Map());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('FavoritesPage — truthful zero states', () => {
  it('renders the genuine empty state when the user has no favorites', async () => {
    render(<FavoritesPage />);

    expect(await screen.findByText('favorites.emptyHint')).toBeInTheDocument();
    expect(screen.queryByTestId('favorites-load-error')).toBeNull();
  });

  it('renders the error state (not the empty state) when the load fails', async () => {
    mockGetFavorites.mockRejectedValue(new Error('offline'));

    render(<FavoritesPage />);

    expect(await screen.findByTestId('favorites-load-error')).toBeInTheDocument();
    expect(screen.getByText('favorites.loadError')).toBeInTheDocument();
    expect(screen.queryByText('favorites.emptyHint')).toBeNull();
  });

  it('retry refetches and renders the favorites on success', async () => {
    mockGetFavorites
      .mockRejectedValueOnce(new Error('blip'))
      .mockResolvedValueOnce(new Set(['opp-1']));
    mockGetOpportunitiesByIds.mockResolvedValue([
      { id: 'opp-1', title: 'Saved Lab', description: '', opportunity_type: 'research' },
    ]);

    render(<FavoritesPage />);

    fireEvent.click(await screen.findByText('common.retry'));

    await waitFor(() => {
      expect(screen.getByText('Saved Lab')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('favorites-load-error')).toBeNull();
    expect(mockGetFavorites).toHaveBeenCalledTimes(2);
  });

  it('shows an inline error note when saved searches fail to load (section must not vanish)', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['opp-1']));
    mockGetOpportunitiesByIds.mockResolvedValue([
      { id: 'opp-1', title: 'Saved Lab', description: '', opportunity_type: 'research' },
    ]);
    mockListSavedSearches.mockRejectedValue(new Error('saved-searches down'));

    render(<FavoritesPage />);

    expect(await screen.findByTestId('saved-searches-load-error')).toBeInTheDocument();
    expect(screen.getByText('favorites.savedSearches.loadError')).toBeInTheDocument();
    // The failure note replaces the "save one from results" empty hint.
    expect(screen.queryByText('favorites.savedSearches.emptyHint')).toBeNull();
  });
});
