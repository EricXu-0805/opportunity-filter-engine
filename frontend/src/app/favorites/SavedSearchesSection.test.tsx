/*
 * SavedSearchesSection digest-editor tests.
 *
 * Pins the pre-migration degradation (digests=null hides every digest
 * control) and the digest's one-address contract: the cron sends only to the
 * signed-in account's confirmed email, so that is the only address the editor
 * offers, the "weekly email" badge shows only on rows the cron will send, and
 * an opted-in row stored for any other address says it is not being sent.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';

vi.mock('@/lib/supabase', () => ({
  supabase: { from: vi.fn() },
  getDeviceId: vi.fn(),
  getAuthState: vi.fn().mockResolvedValue({
    session: null, user: null, isAnonymous: false, email: null,
  }),
}));

import { SavedSearchesSection } from './SavedSearchesSection';
import { useSavedSearches } from './use-saved-searches';
import { getAuthState, getDeviceId, supabase } from '@/lib/supabase';
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
  accountEmail: string | null = null,
) {
  const element = (email: string | null) => (
    <SavedSearchesSection
      savedSearches={[SEARCH]}
      digests={digests}
      onApplyOptimisticClear={vi.fn()}
      onRemove={vi.fn()}
      onDigestSave={onDigestSave}
      accountEmail={email}
      t={t}
    />
  );
  const { rerender } = render(element(accountEmail));
  return { onDigestSave, setAccountEmail: (email: string | null) => rerender(element(email)) };
}

const digestButton = () =>
  screen.queryByRole('button', {
    name: 'favorites.savedSearches.digestButtonAria:{"name":"ML labs"}',
  });
const emailField = () => screen.queryByLabelText('favorites.savedSearches.digestEmailAria');
const switchButton = (email: string) =>
  screen.queryByRole('button', {
    name: `favorites.savedSearches.digestSwitchToAccount:{"email":"${email}"}`,
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

  it('shows the weekly-email badge only on the row stored for the account address', () => {
    const other: SavedSearch = { ...SEARCH, id: 'uuid-2', name: 'Bio labs' };
    render(
      <SavedSearchesSection
        savedSearches={[SEARCH, other]}
        digests={new Map([
          // Compared case-insensitively, as the cron does.
          ['uuid-1', { email: 'Me@Example.com', optIn: true }],
          ['uuid-2', { email: 'stored@example.com', optIn: true }],
        ])}
        onApplyOptimisticClear={vi.fn()}
        onRemove={vi.fn()}
        onDigestSave={vi.fn()}
        accountEmail="me@example.com"
        t={t}
      />,
    );
    const badges = screen.getAllByText('favorites.savedSearches.digestOnBadge');
    expect(badges).toHaveLength(1);
    expect(badges[0].closest('li')).toHaveTextContent('ML labs');
  });

  it('shows no badge for a row stored for another address, and offers the account address', async () => {
    // The cron holds this row back, so the page must not say it is on.
    const { onDigestSave } = renderSection(
      new Map([['uuid-1', { email: 'stored@example.com', optIn: true }]]),
      vi.fn().mockResolvedValue(true),
      'me@example.com',
    );
    expect(screen.queryByText('favorites.savedSearches.digestOnBadge')).toBeNull();
    expect(
      screen.getByText('favorites.savedSearches.digestNotSentOtherAddress:{"email":"stored@example.com"}'),
    ).toBeInTheDocument();

    fireEvent.click(switchButton('me@example.com')!);
    await waitFor(() =>
      expect(onDigestSave).toHaveBeenCalledWith('uuid-1', { email: 'me@example.com', optIn: true }),
    );
  });

  it('says when switching to the account address fails', async () => {
    renderSection(
      new Map([['uuid-1', { email: 'stored@example.com', optIn: true }]]),
      vi.fn().mockResolvedValue(false),
      'me@example.com',
    );
    fireEvent.click(switchButton('me@example.com')!);
    await waitFor(() =>
      expect(screen.getByText('favorites.savedSearches.digestSaveFailed')).toBeInTheDocument(),
    );
  });

  it('shows a guest\'s opted-in row as not sent, with no badge and no address to switch to', () => {
    renderSection(new Map([['uuid-1', { email: 'user@example.com', optIn: true }]]));
    expect(screen.queryByText('favorites.savedSearches.digestOnBadge')).toBeNull();
    expect(screen.getByText('favorites.savedSearches.digestNotSentNeedsAccount')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /digestSwitchToAccount/ })).toBeNull();
  });

  it('does not let a guest turn the digest on', () => {
    const { onDigestSave } = renderSection(new Map([['uuid-1', { email: '', optIn: false }]]));
    fireEvent.click(digestButton()!);

    expect(screen.getByRole('checkbox')).toBeDisabled();
    expect(emailField()).toBeNull();
    expect(screen.getByText('favorites.savedSearches.digestNeedsAccount')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'favorites.savedSearches.digestSave' }));
    expect(onDigestSave).not.toHaveBeenCalledWith('uuid-1', expect.objectContaining({ optIn: true }));
  });

  it('shows the account email read-only and saves the opt-in to it', async () => {
    const { onDigestSave } = renderSection(
      new Map([['uuid-1', { email: '', optIn: false }]]),
      vi.fn().mockResolvedValue(true),
      'me@example.com',
    );
    fireEvent.click(digestButton()!);
    expect(emailField()).toHaveValue('me@example.com');
    expect(emailField()).toHaveAttribute('readonly');

    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'favorites.savedSearches.digestSave' }));
    await waitFor(() =>
      expect(onDigestSave).toHaveBeenCalledWith('uuid-1', { email: 'me@example.com', optIn: true }),
    );
    // editor closes on success
    expect(emailField()).toBeNull();
  });

  it('shows the account address once it arrives after the editor opened', () => {
    const { setAccountEmail } = renderSection(new Map([['uuid-1', { email: '', optIn: false }]]));
    fireEvent.click(digestButton()!);
    expect(emailField()).toBeNull();

    setAccountEmail('me@example.com');
    expect(emailField()).toHaveValue('me@example.com');
    expect(screen.getByRole('checkbox')).not.toBeDisabled();
  });

  it('surfaces a failure message when the save rejects server-side', async () => {
    renderSection(
      new Map([['uuid-1', { email: 'me@example.com', optIn: true }]]),
      vi.fn().mockResolvedValue(false),
      'me@example.com',
    );
    fireEvent.click(digestButton()!);
    fireEvent.click(screen.getByRole('button', { name: 'favorites.savedSearches.digestSave' }));

    await waitFor(() =>
      expect(screen.getByText('favorites.savedSearches.digestSaveFailed')).toBeInTheDocument(),
    );
  });
});

describe('useSavedSearches account email', () => {
  function emptyReads() {
    vi.mocked(getDeviceId).mockResolvedValue('device-1');
    vi.mocked(supabase.from).mockImplementation(() => {
      const result = { data: [], error: null };
      const builder = {
        select: () => builder,
        eq: () => builder,
        order: () => Promise.resolve(result),
        then: (resolve: (value: typeof result) => unknown) => Promise.resolve(result).then(resolve),
      };
      return builder as unknown as ReturnType<typeof supabase.from>;
    });
  }

  function auth(user: Record<string, unknown> | null, isAnonymous: boolean, email: string | null) {
    return { session: null, user, isAnonymous, email } as unknown as Awaited<ReturnType<typeof getAuthState>>;
  }

  it('reads the signed-in account\'s confirmed email', async () => {
    emptyReads();
    vi.mocked(getAuthState).mockResolvedValueOnce(
      auth({ id: 'u1', email_confirmed_at: '2026-01-01T00:00:00Z' }, false, 'Me@Example.com'),
    );
    const { result } = renderHook(() => useSavedSearches(t));
    await waitFor(() => expect(result.current.accountEmail).toBe('me@example.com'));
  });

  it.each([
    ['a guest', auth({ id: 'u1', email_confirmed_at: '2026-01-01T00:00:00Z' }, true, 'guest@example.com')],
    ['an unconfirmed address', auth({ id: 'u1' }, false, 'me@example.com')],
  ])('gives %s no account email', async (_label, state) => {
    emptyReads();
    vi.mocked(getAuthState).mockResolvedValueOnce(state);
    const { result } = renderHook(() => useSavedSearches(t));
    await waitFor(() => expect(result.current.digests).not.toBeNull());
    expect(result.current.accountEmail).toBeNull();
  });

  it('keeps the digest UI hidden until the account is known', async () => {
    emptyReads();
    let resolveAuth: (state: Awaited<ReturnType<typeof getAuthState>>) => void = () => {};
    vi.mocked(getAuthState).mockReturnValueOnce(new Promise((resolve) => { resolveAuth = resolve; }));
    const { result } = renderHook(() => useSavedSearches(t));
    await act(async () => {});
    expect(result.current.digests).toBeNull();

    await act(async () => {
      resolveAuth(auth({ id: 'u1', email_confirmed_at: '2026-01-01T00:00:00Z' }, false, 'me@example.com'));
    });
    expect(result.current.digests).not.toBeNull();
    expect(result.current.accountEmail).toBe('me@example.com');
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

// M50: the row carries the search's latest email state, and a retry that
// brings the list back reads the digest settings again rather than leaving
// every digest control hidden because the first digest read failed with it.
describe('a saved search\'s email state', () => {
  function renderRows(search: SavedSearch, digest: SavedSearchDigest | undefined) {
    render(
      <SavedSearchesSection
        savedSearches={[search]}
        digests={new Map(digest ? [[search.id, digest]] : [])}
        onApplyOptimisticClear={vi.fn()}
        onRemove={vi.fn()}
        onDigestSave={vi.fn()}
        accountEmail="me@example.com"
        t={t}
      />,
    );
  }
  const lastEmailed = () => screen.queryByText(/favorites\.savedSearches\.lastEmailedAgo/);
  const unsubscribed = () => screen.queryByText(/favorites\.savedSearches\.emailUnsubscribed/);

  it('says when the last digest went out', () => {
    const sentAt = new Date(Date.now() - 3 * 86_400_000).toISOString();
    renderRows(SEARCH, { email: 'me@example.com', optIn: true, lastSentAt: sentAt, unsubscribedAt: null });
    expect(lastEmailed()).toBeInTheDocument();
    expect(unsubscribed()).toBeNull();
  });

  it('says the email was unsubscribed, which outranks the last send', () => {
    renderRows(SEARCH, {
      email: 'me@example.com', optIn: false,
      lastSentAt: '2026-10-01T09:00:00Z', unsubscribedAt: '2026-10-02T09:00:00Z',
    });
    expect(unsubscribed()).toBeInTheDocument();
    expect(lastEmailed()).toBeNull();
  });

  it('says nothing about email for a search that was never emailed', () => {
    renderRows(SEARCH, { email: '', optIn: false, lastSentAt: null, unsubscribedAt: null });
    expect(lastEmailed()).toBeNull();
    expect(unsubscribed()).toBeNull();
  });

  it('says new results are counted before a saved minimum score', () => {
    const note = () => screen.queryByText('favorites.savedSearches.newBeforeMinScore:{"min":60}');
    renderRows({ ...SEARCH, filters: { ...SEARCH.filters, minScore: 60 }, new_match_ids: ['a'] }, undefined);
    expect(note()).toBeInTheDocument();
    cleanup();
    renderRows({ ...SEARCH, filters: { ...SEARCH.filters, minScore: 60 } }, undefined);
    expect(note()).toBeNull();
    cleanup();
    renderRows({ ...SEARCH, new_match_ids: ['a'] }, undefined);
    expect(screen.queryByText(/newBeforeMinScore/)).toBeNull();
  });

  it('a retry that brings the list back reads the failed digest settings again', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.mocked(getDeviceId).mockResolvedValue('device-1');
    const row = {
      id: 'uuid-1', name: 'ML labs', query: 'ml', filters_json: SEARCH.filters,
      sort_by: 'score', tab: 'all', created_at: SEARCH.created_at,
      updated_at: SEARCH.updated_at, last_run_at: null, last_result_ids: [], new_match_ids: [],
    };
    const queue: Array<{ data: unknown; error: { message: string } | null }> = [
      { data: null, error: { message: 'network down' } }, // list
      { data: null, error: { message: 'network down' } }, // digests
      { data: [row], error: null }, // retried list
      {
        data: [{
          id: 'uuid-1', digest_email: 'me@example.com', digest_opt_in: true,
          last_digest_sent_at: '2026-10-12T09:00:00Z', digest_unsubscribed_at: null,
        }],
        error: null,
      },
    ];
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

    const { result } = renderHook(() => useSavedSearches(t));
    await waitFor(() => expect(result.current.loadError).toBe(true));
    expect(result.current.digests).toBeNull();

    await act(async () => { await result.current.retryLoad(); });
    await waitFor(() => expect(result.current.digests).not.toBeNull(), { timeout: 2000 });
    expect(result.current.digests?.get('uuid-1')).toEqual({
      email: 'me@example.com', optIn: true,
      lastSentAt: '2026-10-12T09:00:00Z', unsubscribedAt: null,
    });
    warn.mockRestore();
  });

  it('turning the digest on keeps the last send and clears the unsubscribe', async () => {
    vi.mocked(getDeviceId).mockResolvedValue('device-1');
    const queue: Array<{ data: unknown; error: { message: string } | null }> = [
      { data: [], error: null },
      {
        data: [{
          id: 'uuid-1', digest_email: 'me@example.com', digest_opt_in: false,
          last_digest_sent_at: '2026-10-01T09:00:00Z', digest_unsubscribed_at: '2026-10-02T09:00:00Z',
        }],
        error: null,
      },
      { data: null, error: null }, // the update
    ];
    vi.mocked(supabase.from).mockImplementation(() => {
      const result = queue.shift() ?? { data: [], error: null };
      const builder = {
        select: () => builder,
        update: () => builder,
        eq: () => builder,
        order: () => Promise.resolve(result),
        then: (resolve: (value: typeof result) => unknown) => Promise.resolve(result).then(resolve),
      };
      return builder as unknown as ReturnType<typeof supabase.from>;
    });
    const { result } = renderHook(() => useSavedSearches(t));
    await waitFor(() => expect(result.current.digests?.get('uuid-1')).toBeDefined());

    await act(async () => {
      await result.current.handleDigestSave('uuid-1', { email: 'me@example.com', optIn: true });
    });
    expect(result.current.digests?.get('uuid-1')).toEqual({
      email: 'me@example.com', optIn: true,
      lastSentAt: '2026-10-01T09:00:00Z', unsubscribedAt: null,
    });
  });
});
