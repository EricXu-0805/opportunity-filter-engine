/*
 * SavedSearchesSection digest-editor tests.
 *
 * Pins the pre-migration degradation (digests=null hides every digest
 * control) and the editor's save contract: opt-in requires a valid email,
 * and onDigestSave receives exactly what the user confirmed.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('@/lib/supabase', () => ({
  supabase: { from: vi.fn() },
  getDeviceId: vi.fn(),
}));

import { SavedSearchesSection } from './SavedSearchesSection';
import type { SavedSearch, SavedSearchDigest } from '@/lib/saved-searches';

const t = (key: string, vars?: Record<string, string | number>) =>
  vars ? `${key}:${JSON.stringify(vars)}` : key;

const SEARCH: SavedSearch = {
  id: 'uuid-1',
  name: 'ML labs',
  query: 'ml',
  filters: {
    paid: '', intl: '', source: '', onCampus: '', deadline: '', minScore: 0,
  },
  sort_by: 'score',
  tab: 'all',
  created_at: '2026-05-24T00:00:00Z',
  updated_at: '2026-05-24T00:00:00Z',
  last_run_at: null,
  last_result_ids: [],
  new_match_ids: [],
};

function renderSection(
  digests: Map<string, SavedSearchDigest> | null,
  onDigestSave = vi.fn().mockResolvedValue(true),
) {
  render(
    <SavedSearchesSection
      savedSearches={[SEARCH]}
      digests={digests}
      onApplyOptimisticClear={vi.fn()}
      onRemove={vi.fn()}
      onDigestSave={onDigestSave}
      t={t}
    />,
  );
  return { onDigestSave };
}

const digestButton = () =>
  screen.queryByRole('button', {
    name: 'favorites.savedSearches.digestButtonAria:{"name":"ML labs"}',
  });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('SavedSearchesSection digest editor', () => {
  it('hides all digest controls when digests is null (pre-migration)', () => {
    renderSection(null);
    expect(digestButton()).toBeNull();
    expect(screen.queryByText('favorites.savedSearches.digestOnBadge')).toBeNull();
  });

  it('shows the weekly-email badge for opted-in searches', () => {
    renderSection(new Map([['uuid-1', { email: 'user@example.com', optIn: true }]]));
    expect(screen.getByText('favorites.savedSearches.digestOnBadge')).toBeInTheDocument();
  });

  it('opens the editor prefilled and saves a new opt-in', async () => {
    const { onDigestSave } = renderSection(
      new Map([['uuid-1', { email: '', optIn: false }]]),
    );
    fireEvent.click(digestButton()!);

    const emailInput = screen.getByLabelText('favorites.savedSearches.digestEmailAria');
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.change(emailInput, { target: { value: 'user@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'favorites.savedSearches.digestSave' }));

    await waitFor(() =>
      expect(onDigestSave).toHaveBeenCalledWith('uuid-1', {
        email: 'user@example.com',
        optIn: true,
      }),
    );
    // editor closes on success
    expect(screen.queryByLabelText('favorites.savedSearches.digestEmailAria')).toBeNull();
  });

  it('blocks save with an invalid email while opted in', () => {
    const { onDigestSave } = renderSection(
      new Map([['uuid-1', { email: '', optIn: false }]]),
    );
    fireEvent.click(digestButton()!);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.change(screen.getByLabelText('favorites.savedSearches.digestEmailAria'), {
      target: { value: 'nope' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'favorites.savedSearches.digestSave' }));

    expect(onDigestSave).not.toHaveBeenCalled();
    expect(screen.getByText('favorites.savedSearches.digestEmailInvalid')).toBeInTheDocument();
  });

  it('surfaces a failure message when the save rejects server-side', async () => {
    renderSection(
      new Map([['uuid-1', { email: 'user@example.com', optIn: true }]]),
      vi.fn().mockResolvedValue(false),
    );
    fireEvent.click(digestButton()!);
    fireEvent.click(screen.getByRole('button', { name: 'favorites.savedSearches.digestSave' }));

    await waitFor(() =>
      expect(screen.getByText('favorites.savedSearches.digestSaveFailed')).toBeInTheDocument(),
    );
  });
});
