import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FavoritesHeader } from './FavoritesHeader';
import type { Opp } from './types';

const { getInteractionsFullMock, sendFavoritesEmailMock } = vi.hoisted(() => ({
  getInteractionsFullMock: vi.fn(),
  sendFavoritesEmailMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  sendFavoritesEmail: sendFavoritesEmailMock,
}));

vi.mock('@/lib/supabase', () => ({
  getInteractionsFull: getInteractionsFullMock,
}));

vi.mock('@/components/EmailMeButton', () => ({
  default: ({ onSend }: { onSend: (email: string) => Promise<unknown> }) => (
    <button type="button" onClick={() => void onSend('student@example.com')}>
      mock-email
    </button>
  ),
}));

const t = (key: string) => key;

beforeEach(() => {
  getInteractionsFullMock.mockReset();
  getInteractionsFullMock.mockResolvedValue(new Map());
  sendFavoritesEmailMock.mockReset();
  sendFavoritesEmailMock.mockResolvedValue({ ok: true, count: 6 });
});

describe('FavoritesHeader email payload', () => {
  it('fails closed when the producer cannot prove a listing record', async () => {
    const opportunities: Opp[] = [
      {
        id: 'faculty',
        title: 'Faculty contact',
        source_type: 'faculty_research',
        deadline: '2026-09-01',
      },
      {
        id: 'listing',
        title: 'Verified listing',
        source_type: 'campus_program',
        deadline: '2026-09-02',
      },
      {
        id: 'missing',
        title: 'Missing type',
        deadline: '2026-09-03',
      },
      {
        id: 'empty',
        title: 'Empty type',
        source_type: '   ',
        deadline: '2026-09-04',
      },
      {
        id: 'unknown',
        title: 'Unknown type',
        source_type: 'unknown',
        deadline: '2026-09-05',
      },
      {
        id: 'unrecognized',
        title: 'Unrecognized type',
        source_type: 'unreviewed_feed',
        deadline: '2026-09-06',
      },
    ];

    render(
      <FavoritesHeader
        opportunities={opportunities}
        serverOpportunitiesCount={opportunities.length}
        selectionMode={false}
        onEnterSelection={() => {}}
        onCancelSelection={() => {}}
        t={t}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'mock-email' }));

    await waitFor(() => expect(sendFavoritesEmailMock).toHaveBeenCalledOnce());
    const items = sendFavoritesEmailMock.mock.calls[0][1] as Array<{
      record_kind: string;
      deadline: string | null;
    }>;
    expect(items.map(({ record_kind, deadline }) => [record_kind, deadline])).toEqual([
      ['faculty_contact', null],
      ['listing', '2026-09-02'],
      ['unknown', null],
      ['unknown', null],
      ['unknown', null],
      ['unknown', null],
    ]);
  });
});
