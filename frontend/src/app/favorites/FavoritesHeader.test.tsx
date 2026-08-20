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
  default: ({ onSend, notice }: {
    onSend: (email: string) => Promise<unknown>;
    notice?: string;
  }) => (
    <>
      <button type="button" onClick={() => void onSend('student@example.com')}>
        mock-email
      </button>
      {/* Rendered so the truncation notice is asserted as something a user
          would actually see, not as a prop that could be dropped downstream. */}
      {notice ? <span data-testid="email-notice">{notice}</span> : null}
    </>
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
        // A confirmed listing needs BOTH a listing source type and a live
        // truth before the bridge payload may call it one.
        target_truth: {
          listing_state: 'open',
          reference_only: false,
          actionable: true,
          accepting_state: 'accepting',
          reason_code: null,
          verified_at: null,
          expires_at: null,
        },
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

  it('degrades a closed saved target in the bridge payload itself', async () => {
    // Version skew: during the Vercel-first window an OLD backend renders
    // straight from these legacy fields. So the payload has to be honest on
    // its own — a closed listing must not arrive carrying record_kind
    // 'listing' and a due date for that renderer to print.
    const closed: Opp[] = [{
      id: 'closed-listing',
      title: 'Closed last term',
      source_type: 'campus_program',
      deadline: '2026-09-02',
      url: 'https://example.edu/display',
      source_url: 'https://example.edu/scraped',
      target_truth: {
        listing_state: 'closed',
        reference_only: true,
        actionable: false,
        accepting_state: 'not_accepting',
        reason_code: 'listing_closed',
        verified_at: null,
        expires_at: null,
      },
    }];

    render(
      <FavoritesHeader
        opportunities={closed}
        serverOpportunitiesCount={1}
        selectionMode={false}
        onEnterSelection={() => {}}
        onCancelSelection={() => {}}
        t={t}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'mock-email' }));

    await waitFor(() => expect(sendFavoritesEmailMock).toHaveBeenCalledOnce());
    const [item] = sendFavoritesEmailMock.mock.calls[0][1] as Array<Record<string, unknown>>;
    expect(item.opportunity_id).toBe('closed-listing');
    expect(item.record_kind).toBe('unknown');
    expect(item.deadline).toBeNull();
    // source_url, never the display url — and never an application link.
    expect(item.url).toBe('https://example.edu/scraped');
  });

  describe('Compare visibility counts what can be compared', () => {
    const ACTIONABLE = {
      listing_state: 'open',
      reference_only: false,
      actionable: true,
      accepting_state: 'accepting',
      reason_code: null,
      verified_at: null,
      expires_at: null,
    } as const;
    const CLOSED = {
      ...ACTIONABLE,
      listing_state: 'closed',
      reference_only: true,
      actionable: false,
      accepting_state: 'not_accepting',
      reason_code: 'listing_closed',
    } as const;

    function renderWith(opportunities: Opp[]) {
      return render(
        <FavoritesHeader
          opportunities={opportunities}
          // Deliberately the raw saved count: the header must not trust it.
          serverOpportunitiesCount={opportunities.length}
          selectionMode={false}
          onEnterSelection={() => {}}
          onCancelSelection={() => {}}
          t={t}
        />,
      );
    }

    it('hides Compare when both saved targets are historical', () => {
      renderWith([
        { id: 'a', title: 'A', source_type: 'campus_program', target_truth: CLOSED },
        { id: 'b', title: 'B', source_type: 'campus_program', target_truth: CLOSED },
      ] as Opp[]);
      expect(screen.queryByText('favorites.compare')).not.toBeInTheDocument();
    });

    it('hides Compare when only one of two saved targets is still open', () => {
      // One comparable row is not a comparison.
      renderWith([
        { id: 'a', title: 'A', source_type: 'campus_program', target_truth: ACTIONABLE },
        { id: 'b', title: 'B', source_type: 'campus_program', target_truth: CLOSED },
      ] as Opp[]);
      expect(screen.queryByText('favorites.compare')).not.toBeInTheDocument();
    });

    it('hides Compare when the pair is made up by a custom import', () => {
      renderWith([
        { id: 'a', title: 'A', source_type: 'campus_program', target_truth: ACTIONABLE },
        { id: 'c', title: 'Typed in', _customId: 'c1' },
      ] as Opp[]);
      expect(screen.queryByText('favorites.compare')).not.toBeInTheDocument();
    });
  });

  describe('the 50-item email cap is stated, not silently applied', () => {
    const ACTIONABLE_TRUTH = {
      listing_state: 'open', reference_only: false, actionable: true,
      accepting_state: 'accepting', reason_code: null,
      verified_at: null, expires_at: null,
    } as const;

    function saved(n: number, withCustom = 0): Opp[] {
      const rows: Opp[] = Array.from({ length: n }, (_, i) => ({
        id: `s${i}`, title: `Saved ${i}`, source_type: 'campus_program',
        target_truth: { ...ACTIONABLE_TRUTH },
      })) as Opp[];
      for (let i = 0; i < withCustom; i += 1) {
        rows.push({ id: `c${i}`, title: `Typed ${i}`, _customId: `c${i}` } as Opp);
      }
      return rows;
    }

    /** Records interpolation params so the NUMBERS are asserted, not the key.
     *
     *  A `t` that returns its key proves only that some string was requested.
     *  "the first 50 of your 62" and "the first 5 of your 6" are the same key
     *  and different claims, and only one of them is true.
     */
    function renderHeader(opportunities: Opp[]) {
      const calls: { key: string; params?: Record<string, unknown> }[] = [];
      const spyT = ((key: string, params?: Record<string, unknown>) => {
        calls.push({ key, params });
        return key;
      }) as typeof t;
      render(
        <FavoritesHeader
          opportunities={opportunities}
          serverOpportunitiesCount={opportunities.length}
          selectionMode={false}
          onEnterSelection={() => {}}
          onCancelSelection={() => {}}
          t={spyT}
        />,
      );
      return calls;
    }

    it('says how many of how many when the list is truncated', () => {
      // 62 mailable rows, 50 sent. Without this the student receives a digest
      // that looks complete and silently omits twelve saved targets — and
      // nothing in the email or the UI ever says so.
      const calls = renderHeader(saved(62));

      expect(screen.getByTestId('email-notice')).toHaveTextContent(
        'email.favoritesTruncated',
      );
      const notice = calls.find((c) => c.key === 'email.favoritesTruncated');
      expect(notice?.params).toEqual({ shown: 50, total: 62 });
    });

    it('sends exactly the first 50, in order, and says so', async () => {
      const calls = renderHeader(saved(62));
      expect(calls.find((c) => c.key === 'email.favoritesTruncated')).toBeDefined();

      fireEvent.click(screen.getByRole('button', { name: 'mock-email' }));
      await waitFor(() => expect(sendFavoritesEmailMock).toHaveBeenCalled());

      const [, items] = sendFavoritesEmailMock.mock.calls[0];
      expect(items).toHaveLength(50);
      // The first fifty in saved order — not a re-sort, not a sample. The
      // notice promises "the first 50", so the payload has to be them.
      expect(items.map((i: { opportunity_id: string }) => i.opportunity_id))
        .toEqual(Array.from({ length: 50 }, (_, i) => `s${i}`));
      expect(items[0].opportunity_id).toBe('s0');
      expect(items[49].opportunity_id).toBe('s49');
    });

    it('says nothing, and drops nothing, when everything fits', async () => {
      renderHeader(saved(50));
      expect(screen.queryByTestId('email-notice')).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'mock-email' }));
      await waitFor(() => expect(sendFavoritesEmailMock).toHaveBeenCalled());

      const [, items] = sendFavoritesEmailMock.mock.calls[0];
      expect(items).toHaveLength(50);
    });

    it('counts what will actually be mailed, not what is on screen', async () => {
      // Custom imports are filtered out before the slice, so 48 server-backed
      // rows plus 10 typed-in ones is 48 mailed — under the cap, no notice.
      // Counting the rendered list would claim a truncation that never
      // happens, which is the same dishonesty in the other direction.
      renderHeader(saved(48, 10));
      expect(screen.queryByTestId('email-notice')).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'mock-email' }));
      await waitFor(() => expect(sendFavoritesEmailMock).toHaveBeenCalled());

      const [, items] = sendFavoritesEmailMock.mock.calls[0];
      expect(items).toHaveLength(48);
    });
  });

  it('does not offer Compare even when enough favorites are present', () => {
    const onEnterSelection = vi.fn();
    render(
      <FavoritesHeader
        opportunities={[
          { id: 'one', title: 'One' },
          { id: 'two', title: 'Two' },
        ]}
        serverOpportunitiesCount={2}
        selectionMode={false}
        onEnterSelection={onEnterSelection}
        onCancelSelection={() => {}}
        t={t}
      />,
    );

    expect(screen.queryByText('favorites.compare')).not.toBeInTheDocument();
    expect(onEnterSelection).not.toHaveBeenCalled();
  });
});
