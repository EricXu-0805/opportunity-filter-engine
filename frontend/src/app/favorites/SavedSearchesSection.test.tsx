/*
 * SavedSearchesSection digest-editor tests.
 *
 * Pins the pre-migration degradation (digests=null hides every digest
 * control) and the editor's save contract: opt-in requires a valid email,
 * and onDigestSave receives exactly what the user confirmed.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';

vi.mock('@/lib/supabase', () => ({
  supabase: { from: vi.fn() },
  getDeviceId: vi.fn(),
}));

import { SavedSearchesSection } from './SavedSearchesSection';
import { useSavedSearches } from './use-saved-searches';
import { getDeviceId, supabase } from '@/lib/supabase';
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

// M50: a read failure says so and can be retried. Before this, the list read
// turned any error into [] — the section showed "save one from results" over
// searches that still existed, its load-error note was unreachable, and there
// was no way to ask again short of reloading the page.
describe('saved searches that could not be read', () => {
  function sectionWithError(onRetry = vi.fn()) {
    render(
      <SavedSearchesSection
        savedSearches={[]}
        digests={null}
        loadError
        onRetry={onRetry}
        onApplyOptimisticClear={vi.fn()}
        onRemove={vi.fn()}
        onDigestSave={vi.fn()}
        t={t}
      />,
    );
    return { onRetry };
  }

  it('shows the error, never the empty hint, and offers a retry', () => {
    const { onRetry } = sectionWithError();
    expect(screen.getByTestId('saved-searches-load-error')).toBeInTheDocument();
    expect(screen.queryByText('favorites.savedSearches.emptyHint')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  // The supabase-js builder shape listSavedSearches and the digest read use.
  function reads(...results: Array<{ data: unknown; error: { message: string } | null }>) {
    const queue = [...results];
    vi.mocked(supabase.from).mockImplementation(() => {
      const result = queue.shift() ?? { data: [], error: null };
      const builder = {
        select: () => builder,
        eq: () => builder,
        order: () => Promise.resolve(result),
        then: (resolve: (value: typeof result) => unknown) => Promise.resolve(result).then(resolve),
      };
      return builder as unknown as ReturnType<typeof supabase.from>;
    });
  }

  it('retries the read and replaces the error with the searches it finds', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.mocked(getDeviceId).mockResolvedValue('device-1');
    const row = {
      id: 'uuid-1', name: 'ML labs', query: 'ml', filters_json: SEARCH.filters,
      sort_by: 'score', tab: 'all', created_at: SEARCH.created_at,
      updated_at: SEARCH.updated_at, last_run_at: null, last_result_ids: [], new_match_ids: [],
    };
    // list (fails), digests (pre-migration), then the retried list.
    reads(
      { data: null, error: { message: 'network down' } },
      { data: null, error: { message: 'column "digest_email" does not exist' } },
      { data: [row], error: null },
    );

    const { result } = renderHook(() => useSavedSearches(t));
    await waitFor(() => expect(result.current.loadError).toBe(true));
    expect(result.current.savedSearches).toEqual([]);

    await act(async () => { await result.current.retryLoad(); });
    expect(result.current.loadError).toBe(false);
    expect(result.current.savedSearches.map((search) => search.name)).toEqual(['ML labs']);
    warn.mockRestore();
  });

  it('only the newest read lands: an older retry failing late does not undo a newer success', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.mocked(getDeviceId).mockResolvedValue('device-1');
    type Result = { data: unknown; error: { message: string } | null };
    const pending: Array<(result: Result) => void> = [];
    vi.mocked(supabase.from).mockImplementation(() => {
      let settle!: (result: Result) => void;
      const result = new Promise<Result>((resolve) => { settle = resolve; });
      pending.push(settle);
      const builder = {
        select: () => builder,
        eq: () => builder,
        order: () => result,
        then: (resolve: (value: Result) => unknown) => result.then(resolve),
      };
      return builder as unknown as ReturnType<typeof supabase.from>;
    });
    const { result } = renderHook(() => useSavedSearches(t));
    await waitFor(() => expect(pending).toHaveLength(2)); // list + digests
    await act(async () => { pending[0]({ data: null, error: { message: 'down' } }); });
    await act(async () => { pending[1]({ data: null, error: { message: 'x does not exist' } }); });
    await waitFor(() => expect(result.current.loadError).toBe(true));

    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => { first = result.current.retryLoad(); });
    await waitFor(() => expect(pending).toHaveLength(3));
    act(() => { second = result.current.retryLoad(); });
    await waitFor(() => expect(pending).toHaveLength(4));
    const row = {
      id: 'uuid-1', name: 'ML labs', query: 'ml', filters_json: SEARCH.filters,
      sort_by: 'score', tab: 'all', created_at: SEARCH.created_at,
      updated_at: SEARCH.updated_at, last_run_at: null, last_result_ids: [], new_match_ids: [],
    };
    await act(async () => { pending[3]({ data: [row], error: null }); await second; });
    await act(async () => { pending[2]({ data: null, error: { message: 'late' } }); await first; });
    expect(result.current.loadError).toBe(false);
    expect(result.current.savedSearches.map((search) => search.name)).toEqual(['ML labs']);
    warn.mockRestore();
  });

  it('a retry that fails again keeps the error up rather than an empty list', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.mocked(getDeviceId).mockResolvedValue('device-1');
    reads(
      { data: null, error: { message: 'network down' } },
      { data: null, error: { message: 'column "digest_email" does not exist' } },
      { data: null, error: { message: 'still down' } },
    );
    const { result } = renderHook(() => useSavedSearches(t));
    await waitFor(() => expect(result.current.loadError).toBe(true));
    await act(async () => { await result.current.retryLoad(); });
    expect(result.current.loadError).toBe(true);
    warn.mockRestore();
  });
});
