import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    // Echoes the key plus its vars. The component no longer formats ages
    // itself — it hands (bucket, count) to the dictionary — so the assertions
    // below check exactly that, rather than a hardcoded English rendering
    // which is what this component used to produce for every locale.
    t: (key: string, vars?: Record<string, string | number>) => {
      if (key.startsWith('detail.tracker.statusLabels.')) {
        return `Label:${key.split('.').pop()}`;
      }
      return vars ? `${key}(${Object.values(vars).join(',')})` : key;
    },
  }),
}));

const mockGetStatusChanges = vi.fn();
vi.mock('@/lib/supabase', async () => {
  const actual = await vi.importActual<typeof import('@/lib/supabase')>('@/lib/supabase');
  return {
    ...actual,
    getStatusChanges: (id: string) => mockGetStatusChanges(id),
  };
});

import StatusTimeline from './StatusTimeline';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';

async function owner(uid: string) { advanceOwnerEpoch(uid); await syncLocalIdentityOwner(uid); }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }

function isoAgo(ms: number): string {
  return new Date(Date.now() - ms).toISOString();
}

beforeEach(async () => {
  localStorage.clear();
  await owner('timeline-owner-A');
  mockGetStatusChanges.mockReset();
});

describe('StatusTimeline', () => {
  it('renders the title heading', () => {
    mockGetStatusChanges.mockResolvedValue([]);
    render(
      <StatusTimeline
        opportunityId="opp-1"
        fallbackType="applied"
        fallbackUpdatedAt={isoAgo(60_000)}
      />,
    );
    expect(screen.getByText('detail.tracker.timeline.title')).toBeInTheDocument();
  });

  it('shows the current status without inventing a transition time when history is empty', async () => {
    mockGetStatusChanges.mockResolvedValue([]);
    render(
      <StatusTimeline
        opportunityId="opp-1"
        fallbackType="applied"
        fallbackUpdatedAt={isoAgo(30 * 60_000)}
      />,
    );
    await waitFor(() => expect(screen.getByText('Label:applied')).toBeInTheDocument());
    await screen.findByText('detail.tracker.timeline.empty');
    expect(screen.queryByText(/common\.ago\./)).not.toBeInTheDocument();
  });

  it('renders a chronological list when history returns multiple changes', async () => {
    mockGetStatusChanges.mockResolvedValue([
      { toStatus: 'applied', changedAt: isoAgo(5 * 86_400_000) },
      { toStatus: 'replied', changedAt: isoAgo(3 * 86_400_000) },
      { toStatus: 'interviewing', changedAt: isoAgo(86_400_000) },
    ]);
    render(
      <StatusTimeline
        opportunityId="opp-1"
        fallbackType="applied"
        fallbackUpdatedAt={isoAgo(0)}
      />,
    );
    await screen.findByRole('list');
    expect(screen.getByText('Label:replied')).toBeInTheDocument();
    expect(screen.getByText('Label:interviewing')).toBeInTheDocument();
  });

  it('formats minute ages', async () => {
    mockGetStatusChanges.mockResolvedValue([
      { toStatus: 'replied', changedAt: isoAgo(5 * 60_000) },
    ]);
    render(
      <StatusTimeline
        opportunityId="opp-mins"
        fallbackType="applied"
        fallbackUpdatedAt={isoAgo(0)}
      />,
    );
    await waitFor(() => expect(screen.getByText(/common\.ago\.minutes\(5\)/)).toBeInTheDocument());
  });

  it('formats hour ages', async () => {
    mockGetStatusChanges.mockResolvedValue([
      { toStatus: 'interviewing', changedAt: isoAgo(3 * 3_600_000) },
    ]);
    render(
      <StatusTimeline
        opportunityId="opp-hours"
        fallbackType="applied"
        fallbackUpdatedAt={isoAgo(0)}
      />,
    );
    await waitFor(() => expect(screen.getByText(/common\.ago\.hours\(3\)/)).toBeInTheDocument());
  });

  it('formats day ages', async () => {
    mockGetStatusChanges.mockResolvedValue([
      { toStatus: 'rejected', changedAt: isoAgo(2 * 86_400_000) },
    ]);
    render(
      <StatusTimeline
        opportunityId="opp-days"
        fallbackType="applied"
        fallbackUpdatedAt={isoAgo(0)}
      />,
    );
    await waitFor(() => expect(screen.getByText(/common\.ago\.days\(2\)/)).toBeInTheDocument());
  });

  it('applies the correct dot colours for each status', async () => {
    mockGetStatusChanges.mockResolvedValue([
      { toStatus: 'applied', changedAt: isoAgo(60_000) },
      { toStatus: 'replied', changedAt: isoAgo(60_000) },
      { toStatus: 'interviewing', changedAt: isoAgo(60_000) },
      { toStatus: 'rejected', changedAt: isoAgo(60_000) },
      { toStatus: 'dismissed', changedAt: isoAgo(60_000) },
    ]);
    const { container } = render(
      <StatusTimeline
        opportunityId="opp-color"
        fallbackType="applied"
        fallbackUpdatedAt={isoAgo(60_000)}
      />,
    );
    await waitFor(() => expect(screen.getAllByText(/^Label:/).length).toBe(5));
    expect(container.querySelector('.bg-indigo-500')).not.toBeNull();
    expect(container.querySelector('.bg-violet-500')).not.toBeNull();
    expect(container.querySelector('.bg-amber-500')).not.toBeNull();
    expect(container.querySelector('.bg-gray-400')).not.toBeNull();
    expect(container.querySelector('.bg-gray-300')).not.toBeNull();
  });

  it('renders an ordered list (<ol>) for the timeline', async () => {
    mockGetStatusChanges.mockResolvedValue([
      { toStatus: 'applied', changedAt: isoAgo(60_000) },
    ]);
    const { container } = render(
      <StatusTimeline
        opportunityId="opp-1"
        fallbackType="applied"
        fallbackUpdatedAt={isoAgo(60_000)}
      />,
    );
    await screen.findByRole('list');
    const ol = container.querySelector('ol');
    expect(ol).not.toBeNull();
    expect(ol?.querySelectorAll('li').length).toBe(1);
  });

  it('draws connector spans on all rows except the last', async () => {
    mockGetStatusChanges.mockResolvedValue([
      { toStatus: 'applied', changedAt: isoAgo(86_400_000) },
      { toStatus: 'replied', changedAt: isoAgo(3_600_000) },
      { toStatus: 'interviewing', changedAt: isoAgo(60_000) },
    ]);
    const { container } = render(
      <StatusTimeline
        opportunityId="opp-line"
        fallbackType="applied"
        fallbackUpdatedAt={isoAgo(0)}
      />,
    );
    await waitFor(() => expect(screen.getByText('Label:interviewing')).toBeInTheDocument());
    const connectors = container.querySelectorAll('span.bg-gray-200');
    expect(connectors.length).toBe(2);
  });

  it('omits the age suffix for invalid timestamps', async () => {
    mockGetStatusChanges.mockResolvedValue([
      { toStatus: 'applied', changedAt: 'not-a-date' },
    ]);
    const { container } = render(
      <StatusTimeline
        opportunityId="opp-invalid"
        fallbackType="applied"
        fallbackUpdatedAt={isoAgo(60_000)}
      />,
    );
    await screen.findByRole('list');
    const ageSpans = Array.from(container.querySelectorAll('span'))
      .filter((s) => /common\.ago\./.test(s.textContent ?? ''));
    expect(ageSpans.length).toBe(0);
  });
});


describe('StatusTimeline truthful reads and private scopes', () => {
  const props = { opportunityId: 'opp-A', fallbackType: 'replied' as const, fallbackUpdatedAt: '2026-09-25T10:00:00Z' };
  it('loading is explicit and never dates the current status using the latest notes update', () => {
    mockGetStatusChanges.mockReturnValue(new Promise(() => {}));
    render(<StatusTimeline {...props} />);
    expect(screen.getByText('detail.tracker.timeline.loading')).toBeInTheDocument();
    expect(screen.queryByText(/common\.ago\./)).not.toBeInTheDocument();
  });
  it('a failure is not an empty history; safe retry reads again and uses only real changedAt', async () => {
    mockGetStatusChanges.mockRejectedValueOnce(new Error('private backend detail'))
      .mockResolvedValueOnce([{ fromStatus: 'applied', toStatus: 'replied', changedAt: isoAgo(2 * 86_400_000) }]);
    render(<StatusTimeline {...props} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('detail.tracker.timeline.error');
    expect(screen.queryByText('private backend detail')).not.toBeInTheDocument();
    expect(screen.queryByText('detail.tracker.timeline.empty')).not.toBeInTheDocument();
    expect(screen.queryByText(/common\.ago\./)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'detail.tracker.timeline.retry' }));
    await screen.findByText(/common\.ago\.days\(2\)/);
    expect(mockGetStatusChanges).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('changing opportunity removes old history immediately and ignores the old pending result', async () => {
    const old = deferred<Array<{ toStatus: string; changedAt: string }>>();
    mockGetStatusChanges.mockReturnValueOnce(old.promise).mockResolvedValueOnce([]);
    const { rerender } = render(<StatusTimeline {...props} />);
    await waitFor(() => expect(mockGetStatusChanges).toHaveBeenCalledTimes(1));
    rerender(<StatusTimeline {...props} opportunityId="opp-B" fallbackType="contacted" />);
    await screen.findByText('detail.tracker.timeline.empty');
    await act(async () => { old.resolve([{ toStatus: 'rejected', changedAt: isoAgo(60_000) }]); });
    expect(screen.queryByText('Label:rejected')).not.toBeInTheDocument();
    expect(screen.getByText('Label:contacted')).toBeInTheDocument();
  });
  it('completed history for the old opportunity is not painted while the new read waits', async () => {
    mockGetStatusChanges.mockResolvedValueOnce([{ toStatus: 'rejected', changedAt: isoAgo(60_000) }])
      .mockReturnValueOnce(new Promise(() => {}));
    const { rerender } = render(<StatusTimeline {...props} />);
    await screen.findByText('Label:rejected');
    rerender(<StatusTimeline {...props} opportunityId="opp-B" fallbackType="contacted" />);
    expect(screen.queryByText('Label:rejected')).not.toBeInTheDocument();
    expect(screen.getByText('detail.tracker.timeline.loading')).toBeInTheDocument();
  });
  it('owner change retracts completed history even if the parent has not remounted yet', async () => {
    mockGetStatusChanges.mockResolvedValueOnce([{ toStatus: 'rejected', changedAt: isoAgo(60_000) }])
      .mockReturnValue(new Promise(() => {}));
    render(<StatusTimeline {...props} />);
    await screen.findByText('Label:rejected');
    await act(async () => { await owner('timeline-owner-B'); });
    expect(screen.queryByText('Label:rejected')).not.toBeInTheDocument();
    expect(screen.queryByText('Label:replied')).not.toBeInTheDocument();
  });
  it('a late old-owner response never appears in the new owner scope', async () => {
    const old = deferred<Array<{ toStatus: string; changedAt: string }>>();
    mockGetStatusChanges.mockReturnValueOnce(old.promise).mockResolvedValue([]);
    render(<StatusTimeline {...props} />);
    await waitFor(() => expect(mockGetStatusChanges).toHaveBeenCalledTimes(1));
    await act(async () => { await owner('timeline-owner-B'); });
    await act(async () => { old.resolve([{ toStatus: 'rejected', changedAt: isoAgo(60_000) }]); });
    expect(screen.queryByText('Label:rejected')).not.toBeInTheDocument();
    expect(screen.queryByText(/common\.ago\./)).not.toBeInTheDocument();
  });
  it('unmount observes a late rejection without painting or unhandled failure', async () => {
    let reject!: (reason: Error) => void;
    mockGetStatusChanges.mockReturnValue(new Promise((_resolve, fail) => { reject = fail; }));
    const { unmount } = render(<StatusTimeline {...props} />);
    await waitFor(() => expect(mockGetStatusChanges).toHaveBeenCalledTimes(1));
    unmount();
    await act(async () => { reject(new Error('late private failure')); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
