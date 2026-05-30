import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string) => {
      if (key.startsWith('detail.tracker.statusLabels.')) {
        return `Label:${key.split('.').pop()}`;
      }
      return key;
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

function isoAgo(ms: number): string {
  return new Date(Date.now() - ms).toISOString();
}

beforeEach(() => {
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

  it('shows a fallback row when history returns an empty array', async () => {
    mockGetStatusChanges.mockResolvedValue([]);
    render(
      <StatusTimeline
        opportunityId="opp-1"
        fallbackType="applied"
        fallbackUpdatedAt={isoAgo(30 * 60_000)}
      />,
    );
    await waitFor(() => expect(screen.getByText('Label:applied')).toBeInTheDocument());
    expect(screen.getByText(/30m ago/)).toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByText('Label:applied')).toBeInTheDocument());
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
    await waitFor(() => expect(screen.getByText(/5m ago/)).toBeInTheDocument());
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
    await waitFor(() => expect(screen.getByText(/3h ago/)).toBeInTheDocument());
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
    await waitFor(() => expect(screen.getByText(/2d ago/)).toBeInTheDocument());
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
    expect(container.querySelector('.bg-blue-500')).not.toBeNull();
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
    await waitFor(() => expect(screen.getByText('Label:applied')).toBeInTheDocument());
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
    await waitFor(() => expect(screen.getByText('Label:applied')).toBeInTheDocument());
    const ageSpans = Array.from(container.querySelectorAll('span'))
      .filter((s) => /\d+[smhd] ago/.test(s.textContent ?? ''));
    expect(ageSpans.length).toBe(0);
  });
});
