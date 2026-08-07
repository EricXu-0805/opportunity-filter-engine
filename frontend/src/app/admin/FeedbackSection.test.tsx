import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { translate } from '@/i18n/translate';
import { FeedbackSection } from './FeedbackSection';
import type { FeedbackAnalysis, FeedbackInbox, TFunc, Ticket, TicketWorkflow } from './types';

const t: TFunc = (key, vars) =>
  vars ? `${key} ${Object.entries(vars).map(([k, v]) => `${k}=${v}`).join(' ')}` : key;

const workflow = (over: Partial<TicketWorkflow> = {}): TicketWorkflow => ({
  loadError: null,
  filters: { status: '', priority: '', unresolvedOnly: false },
  onFiltersChange: vi.fn(),
  details: {},
  detailLoading: {},
  onOpen: vi.fn(),
  onPatch: vi.fn().mockResolvedValue(true),
  onReply: vi.fn().mockResolvedValue(true),
  pending: {},
  errors: {},
  replyPending: {},
  replyErrors: {},
  ...over,
});

const okInbox = (overrides: Partial<FeedbackInbox> = {}): FeedbackInbox => ({
  status: 'ok',
  count: 2,
  entries: [
    {
      id: 'f1',
      created_at: '2026-07-04T10:00:00+00:00',
      message: 'The compare page is great',
      email: 'student@illinois.edu',
      props: { path: '/compare' },
    },
    {
      id: 'f2',
      created_at: '2026-07-03T09:00:00+00:00',
      message: 'Add more schools please',
      email: null,
      props: {},
    },
  ],
  match_feedback: {
    up: 10,
    down: 4,
    up_7d: 3,
    down_7d: 1,
    sample_size: 14,
    top_downvoted: [{ opportunity_id: 'opp-1', downs: 3, title: 'CV Lab' }],
  },
  ...overrides,
});

const ticket = (over: Partial<Ticket> = {}): Ticket => ({
  id: 't1',
  created_at: '2026-08-01T10:00:00+00:00',
  subject: 'Broken compare page',
  category: 'bug',
  message: 'Compare crashes on two schools',
  email: 'student@illinois.edu',
  status: 'in_progress',
  priority: 'urgent',
  assigned_to: 'ana',
  props: {},
  ...over,
});

const ticketInbox = (over: Partial<Ticket> = {}): FeedbackInbox => ({
  status: 'ok',
  count: 1,
  entries: [ticket(over)],
});

function expand(name = 'Broken compare page') {
  fireEvent.click(screen.getByRole('button', { name }));
}

describe('FeedbackSection', () => {
  it('renders nothing while the inbox has not loaded', () => {
    const { container } = render(<FeedbackSection inbox={null} tickets={workflow()} t={t} />);
    expect(container.innerHTML).toBe('');
  });

  it('reports a failed inbox read instead of vanishing', () => {
    render(<FeedbackSection inbox={null} tickets={workflow({ loadError: 'HTTP 500' })} t={t} />);
    expect(screen.getByRole('alert')).toHaveTextContent('admin.tickets.loadFailed error=HTTP 500');
    expect(screen.getByText('admin.feedback.title')).toBeInTheDocument();
  });

  it('renders unconfigured as a quiet notice', () => {
    render(
      <FeedbackSection
        inbox={{ status: 'skipped', reason: 'supabase env not configured' }}
        tickets={workflow()}
        t={t}
      />,
    );
    expect(screen.getByText('admin.feedback.unconfigured')).toBeInTheDocument();
  });

  it('renders messages with path, email, and thumbs summary', () => {
    render(<FeedbackSection inbox={okInbox()} tickets={workflow()} t={t} />);
    expect(screen.getByText('The compare page is great')).toBeInTheDocument();
    expect(screen.getByText('/compare')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'student@illinois.edu' })).toHaveAttribute(
      'href',
      'mailto:student@illinois.edu',
    );
    expect(screen.getByText('CV Lab', { exact: false })).toBeInTheDocument();
  });

  it('renders the empty state when there are no messages', () => {
    render(<FeedbackSection inbox={okInbox({ entries: [], count: 0 })} tickets={workflow()} t={t} />);
    expect(screen.getByText('admin.feedback.empty')).toBeInTheDocument();
  });

  const withAnalysis = (analysis: FeedbackAnalysis): FeedbackInbox => {
    const base = okInbox();
    return { ...base, match_feedback: { ...base.match_feedback!, analysis } };
  };

  it('renders the insufficient-sample notice under 50 votes', () => {
    render(
      <FeedbackSection
        inbox={withAnalysis({ insufficient: true, needed: 50, sample_n: 14 })}
        tickets={workflow()}
        t={t}
      />,
    );
    expect(screen.getByText('admin.feedback.analysisTitle')).toBeInTheDocument();
    expect(screen.getByText('admin.feedback.analysisInsufficient n=14 needed=50')).toBeInTheDocument();
    expect(screen.queryByText('admin.feedback.analysisByBucket')).not.toBeInTheDocument();
  });

  it('renders breakdown rows and the degraded replay line at >= 50 votes', () => {
    render(
      <FeedbackSection
        inbox={withAnalysis({
          sample_n: 60,
          up_rate: 0.65,
          by_bucket: [{ key: 'high_priority', n: 40, up_rate: 0.9 }],
          by_score_band: [{ key: '80-100', n: 40, up_rate: 0.9 }, { key: '40-60', n: 20, up_rate: 0.2 }],
          by_school: [{ key: 'uiuc', n: 55, up_rate: 0.7 }],
          by_position: [],
          replay: {
            mode: 'score_band_agreement',
            current_agreement: 0.82,
            best_candidate: null,
            delta: null,
            sample_n: 60,
            note: 'component scores not stored',
          },
        })}
        tickets={workflow()}
        t={t}
      />,
    );
    expect(screen.getByText('admin.feedback.analysisUpRate rate=65 n=60')).toBeInTheDocument();
    expect(screen.getByText('high_priority')).toBeInTheDocument();
    expect(screen.getByText('80-100')).toBeInTheDocument();
    expect(screen.getByText('uiuc')).toBeInTheDocument();
    // empty position breakdown renders nothing
    expect(screen.queryByText('admin.feedback.analysisByPosition')).not.toBeInTheDocument();
    expect(screen.getByText(/analysisAgreement value=82%/)).toBeInTheDocument();
    expect(screen.getByText('component scores not stored')).toBeInTheDocument();
    // degraded mode never shows a weight candidate
    expect(screen.queryByText(/analysisReplayBest/)).not.toBeInTheDocument();
  });

  it('renders the best weight candidate in replay mode', () => {
    render(
      <FeedbackSection
        inbox={withAnalysis({
          sample_n: 80,
          up_rate: 0.5,
          replay: {
            mode: 'weight_replay',
            current_agreement: 0.7,
            best_candidate: { eligibility: 0.4286, readiness: 0.3333, upside: 0.2381 },
            delta: 0.05,
            sample_n: 80,
            note: 'offline replay only — weights are never auto-applied',
          },
        })}
        tickets={workflow()}
        t={t}
      />,
    );
    expect(
      screen.getByText(/analysisReplayBest weights=0\.4286\/0\.3333\/0\.2381 delta=\+5%/),
    ).toBeInTheDocument();
  });
});

describe('FeedbackSection ticket workflow', () => {
  it('renders status, priority, category and assignee on the list row', () => {
    render(<FeedbackSection inbox={ticketInbox()} tickets={workflow()} t={t} />);
    // enumLabel falls back to the raw value when the identity `t` returns the key
    expect(screen.getByText('in_progress')).toBeInTheDocument();
    expect(screen.getByText('urgent')).toBeInTheDocument();
    expect(screen.getByText('bug')).toBeInTheDocument();
    expect(screen.getByText('admin.tickets.assignedTo actor=ana')).toBeInTheDocument();
  });

  it('shows the unassigned label when nobody owns the ticket', () => {
    render(<FeedbackSection inbox={ticketInbox({ assigned_to: null })} tickets={workflow()} t={t} />);
    expect(screen.getByText('admin.tickets.unassigned')).toBeInTheDocument();
  });

  it('loads the event history when a ticket is expanded', () => {
    const w = workflow();
    render(<FeedbackSection inbox={ticketInbox()} tickets={w} t={t} />);
    expand();
    expect(w.onOpen).toHaveBeenCalledWith('t1');
    expect(screen.getByText('admin.tickets.historyEmpty')).toBeInTheDocument();
  });

  it('renders the event timeline from the detail response', () => {
    const w = workflow({
      details: {
        t1: {
          ticket: ticket(),
          events: [
            {
              actor: 'ana',
              action: 'status_changed',
              from_value: 'open',
              to_value: 'in_progress',
              note: 'picked up',
              created_at: '2026-08-02T09:00:00+00:00',
            },
          ],
        },
      },
    });
    render(<FeedbackSection inbox={ticketInbox()} tickets={w} t={t} />);
    expand();
    expect(screen.getByText('ana')).toBeInTheDocument();
    expect(screen.getByText('status_changed')).toBeInTheDocument();
    expect(screen.getByText('open → in_progress')).toBeInTheDocument();
    expect(screen.getByText('picked up')).toBeInTheDocument();
  });

  it('filters call back to the server-side query', () => {
    const w = workflow();
    render(<FeedbackSection inbox={ticketInbox()} tickets={w} t={t} />);
    fireEvent.change(screen.getByLabelText('admin.tickets.filterStatus'), {
      target: { value: 'open' },
    });
    expect(w.onFiltersChange).toHaveBeenCalledWith({ status: 'open', priority: '', unresolvedOnly: false });
    fireEvent.click(screen.getByLabelText('admin.tickets.filterUnresolved'));
    expect(w.onFiltersChange).toHaveBeenCalledWith({ status: '', priority: '', unresolvedOnly: true });
  });

  it('assigns, re-prioritizes and re-statuses through PATCH', () => {
    const w = workflow();
    render(<FeedbackSection inbox={ticketInbox()} tickets={w} t={t} />);
    expand();

    fireEvent.change(screen.getByLabelText('admin.tickets.assignee'), { target: { value: 'bo' } });
    fireEvent.click(screen.getByRole('button', { name: 'admin.tickets.assignSave' }));
    expect(w.onPatch).toHaveBeenCalledWith('t1', { assigned_to: 'bo' });

    fireEvent.change(screen.getByLabelText('admin.tickets.priorityLabel'), { target: { value: 'low' } });
    expect(w.onPatch).toHaveBeenCalledWith('t1', { priority: 'low' });

    fireEvent.change(screen.getByLabelText('admin.tickets.statusLabel'), { target: { value: 'triaged' } });
    expect(w.onPatch).toHaveBeenCalledWith('t1', { status: 'triaged' });
  });

  it('clearing the assignee sends null rather than an empty string', () => {
    const w = workflow();
    render(<FeedbackSection inbox={ticketInbox()} tickets={w} t={t} />);
    expand();
    fireEvent.change(screen.getByLabelText('admin.tickets.assignee'), { target: { value: '  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'admin.tickets.assignSave' }));
    expect(w.onPatch).toHaveBeenCalledWith('t1', { assigned_to: null });
  });

  it('blocks a resolve with no resolution client-side', () => {
    const w = workflow();
    render(<FeedbackSection inbox={ticketInbox()} tickets={w} t={t} />);
    expand();
    fireEvent.click(screen.getByRole('button', { name: 'admin.tickets.resolveButton' }));
    expect(w.onPatch).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('admin.tickets.resolutionRequired');
  });

  it('resolves with a resolution and a note', async () => {
    const w = workflow();
    render(<FeedbackSection inbox={ticketInbox()} tickets={w} t={t} />);
    expand();
    fireEvent.change(screen.getByLabelText('admin.tickets.resolutionLabel'), {
      target: { value: 'data_corrected' },
    });
    fireEvent.change(screen.getByLabelText('admin.tickets.resolutionNote'), {
      target: { value: 'reimported the school' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'admin.tickets.resolveButton' }));
    await waitFor(() =>
      expect(w.onPatch).toHaveBeenCalledWith('t1', {
        status: 'resolved',
        resolution: 'data_corrected',
        resolution_note: 'reimported the school',
      }),
    );
  });

  it('a failed mutation shows an error and leaves the prior state on screen', () => {
    const w = workflow({ errors: { t1: 'HTTP 500' } });
    render(<FeedbackSection inbox={ticketInbox()} tickets={w} t={t} />);
    expand();
    expect(screen.getByRole('alert')).toHaveTextContent('admin.tickets.mutationFailed error=HTTP 500');
    // the controls still show the server state, not the attempted one
    expect(screen.getByLabelText('admin.tickets.statusLabel')).toHaveValue('in_progress');
    expect(screen.getByLabelText('admin.tickets.priorityLabel')).toHaveValue('urgent');
  });

  it('a resolved ticket shows its decision and offers reopen instead of resolve', () => {
    const w = workflow();
    render(
      <FeedbackSection
        inbox={ticketInbox({
          status: 'resolved',
          resolution: 'fixed',
          resolution_note: 'shipped in W15',
          resolved_by: 'ana',
          resolved_at: '2026-08-03T10:00:00+00:00',
        })}
        tickets={w}
        t={t}
      />,
    );
    expand();
    expect(screen.getByText(/admin\.tickets\.resolvedBanner/)).toBeInTheDocument();
    expect(screen.getByText('shipped in W15')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'admin.tickets.resolveButton' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'admin.tickets.reopen' }));
    expect(w.onPatch).toHaveBeenCalledWith('t1', { status: 'open' });
  });

  describe('reply', () => {
    it('posts the draft and the deliver flag, then clears only on success', async () => {
      const w = workflow();
      render(<FeedbackSection inbox={ticketInbox()} tickets={w} t={t} />);
      expand();
      const box = screen.getByLabelText('admin.tickets.replyTitle');
      fireEvent.change(box, { target: { value: 'Fixed, thanks for the report.' } });
      fireEvent.click(screen.getByLabelText('admin.tickets.replyAlsoEmail'));
      fireEvent.click(screen.getByRole('button', { name: 'admin.tickets.replySave' }));
      await waitFor(() =>
        expect(w.onReply).toHaveBeenCalledWith('t1', 'Fixed, thanks for the report.', true),
      );
      await waitFor(() => expect(box).toHaveValue(''));
    });

    it('keeps the draft when the save fails', async () => {
      const w = workflow({ onReply: vi.fn().mockResolvedValue(false) });
      render(<FeedbackSection inbox={ticketInbox()} tickets={w} t={t} />);
      expand();
      const box = screen.getByLabelText('admin.tickets.replyTitle');
      fireEvent.change(box, { target: { value: 'still typing this' } });
      fireEvent.click(screen.getByRole('button', { name: 'admin.tickets.replySave' }));
      await waitFor(() => expect(w.onReply).toHaveBeenCalled());
      expect(box).toHaveValue('still typing this');
    });

    it('surfaces the reply error without eating the draft', async () => {
      const w = workflow({
        onReply: vi.fn().mockResolvedValue(false),
        replyErrors: { t1: 'network down' },
      });
      render(<FeedbackSection inbox={ticketInbox()} tickets={w} t={t} />);
      expand();
      expect(screen.getByRole('alert')).toHaveTextContent('admin.tickets.replyFailed error=network down');
    });

    it('disables the email checkbox when the ticket has no address', () => {
      render(<FeedbackSection inbox={ticketInbox({ email: null })} tickets={workflow()} t={t} />);
      expand();
      expect(screen.getByLabelText('admin.tickets.replyAlsoEmail')).toBeDisabled();
      expect(screen.getByText('admin.tickets.replyNoEmail')).toBeInTheDocument();
    });

    it('never sends deliver=true for a ticket with no address', async () => {
      const w = workflow();
      render(<FeedbackSection inbox={ticketInbox({ email: null })} tickets={w} t={t} />);
      expand();
      fireEvent.change(screen.getByLabelText('admin.tickets.replyTitle'), {
        target: { value: 'noted' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'admin.tickets.replySave' }));
      await waitFor(() => expect(w.onReply).toHaveBeenCalledWith('t1', 'noted', false));
    });

    it.each([
      ['stored', 'admin.tickets.deliveryStored'],
      ['emailed', 'admin.tickets.deliveryEmailed'],
      ['email_failed', 'admin.tickets.deliveryFailed'],
    ] as const)('renders the %s delivery state verbatim', (delivery, key) => {
      render(
        <FeedbackSection
          inbox={ticketInbox({ admin_reply: 'we fixed it', admin_reply_delivery: delivery })}
          tickets={workflow()}
          t={t}
        />,
      );
      expand();
      expect(screen.getByText(key)).toBeInTheDocument();
    });

    it('a stored reply is never described as sent', () => {
      render(
        <FeedbackSection
          inbox={ticketInbox({ admin_reply: 'we fixed it', admin_reply_delivery: 'stored' })}
          tickets={workflow()}
          t={t}
        />,
      );
      expand();
      // 'stored' means nothing left the building — the copy must say so in
      // both locales, and must not claim delivery.
      for (const locale of ['en', 'zh'] as const) {
        const copy = translate(locale, 'admin.tickets.deliveryStored');
        expect(copy).not.toMatch(/\bsent\b/i);
        expect(copy).not.toMatch(/已发送/);
      }
      expect(translate('en', 'admin.tickets.deliveryStored')).toMatch(/not emailed/i);
    });
  });

  it('has every i18n key it uses in both en and zh dictionaries', () => {
    const keys = [
      'admin.tickets.noSubject',
      'admin.tickets.unassigned',
      'admin.tickets.assignedTo',
      'admin.tickets.assignee',
      'admin.tickets.assignPlaceholder',
      'admin.tickets.assignSave',
      'admin.tickets.statusLabel',
      'admin.tickets.priorityLabel',
      'admin.tickets.saving',
      'admin.tickets.detailLoading',
      'admin.tickets.history',
      'admin.tickets.historyEmpty',
      'admin.tickets.filterStatus',
      'admin.tickets.filterPriority',
      'admin.tickets.filterAnyStatus',
      'admin.tickets.filterAnyPriority',
      'admin.tickets.filterUnresolved',
      'admin.tickets.loadFailed',
      'admin.tickets.mutationFailed',
      'admin.tickets.replyTitle',
      'admin.tickets.replyPlaceholder',
      'admin.tickets.replyAlsoEmail',
      'admin.tickets.replyNoEmail',
      'admin.tickets.replySave',
      'admin.tickets.replySaving',
      'admin.tickets.replyNeverResolves',
      'admin.tickets.replyFailed',
      'admin.tickets.deliveryStored',
      'admin.tickets.deliveryEmailed',
      'admin.tickets.deliveryFailed',
      'admin.tickets.resolveTitle',
      'admin.tickets.resolveAs',
      'admin.tickets.resolutionLabel',
      'admin.tickets.resolutionPlaceholder',
      'admin.tickets.resolutionNote',
      'admin.tickets.resolutionNotePlaceholder',
      'admin.tickets.resolutionRequired',
      'admin.tickets.resolveButton',
      'admin.tickets.resolvedBanner',
      'admin.tickets.reopen',
      'admin.actor.label',
      'admin.actor.placeholder',
      'admin.actor.hint',
      ...['open', 'triaged', 'in_progress', 'waiting_on_user', 'resolved', 'closed'].map(
        (s) => `admin.tickets.status.${s}`,
      ),
      ...['low', 'normal', 'high', 'urgent'].map((p) => `admin.tickets.priority.${p}`),
      ...['bug', 'idea', 'data_issue', 'account', 'other'].map((c) => `admin.tickets.category.${c}`),
      ...[
        'fixed', 'expected_behavior', 'duplicate', 'data_corrected', 'unable_to_reproduce',
        'wont_fix', 'user_guidance_provided',
      ].map((r) => `admin.tickets.resolution.${r}`),
      ...[
        'assigned', 'unassigned', 'priority_changed', 'status_changed', 'replied', 'resolved',
        'reopened', 'note_added',
      ].map((a) => `admin.tickets.action.${a}`),
    ];
    for (const key of keys) {
      expect(translate('en', key), `en missing ${key}`).not.toBe(key);
      expect(translate('zh', key), `zh missing ${key}`).not.toBe(key);
    }
  });
});
