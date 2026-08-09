import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { translate } from '@/i18n/translate';
import { OpsIncidentsSection } from './OpsIncidentsSection';
import type { OpsIncident, OpsWorkflow, TFunc } from './types';

const t: TFunc = (key, vars) =>
  vars ? `${key} ${Object.entries(vars).map(([k, v]) => `${k}=${v}`).join(' ')}` : key;

const incident = (over: Partial<OpsIncident> = {}): OpsIncident => ({
  id: 'i1',
  kind: 'collector_failure',
  dedup_key: 'collector_failure:uiuc_faculty',
  scope: 'uiuc_faculty',
  title: 'uiuc_faculty collector failed',
  summary: 'HTTP 403 from the department directory',
  detail: { error_category: 'waf_block', http_status: 403, attempts: 3 },
  priority: 'high',
  status: 'open',
  failure_state: 'failed',
  assigned_to: null,
  first_detected_at: '2026-08-01T10:00:00+00:00',
  last_detected_at: '2026-08-04T10:00:00+00:00',
  occurrence_count: 4,
  attempt_count: 3,
  ...over,
});

const ops = (over: Partial<OpsWorkflow> = {}): OpsWorkflow => ({
  incidents: [incident()],
  // The payload shape /admin/ops/incidents actually returns. A flat
  // kind-to-count fixture is what let the badge bug pass its own test.
  rollup: {
    open_by_kind: { collector_failure: 2, data_drift: 3, notification_failure: 1, manual_review: 5 },
    open_by_priority: { high: 4, normal: 7 },
    open_total: 11,
    truncated: false,
  },
  loaded: true,
  error: null,
  filters: { kind: '', status: 'unresolved' },
  onFiltersChange: vi.fn(),
  details: {},
  detailLoading: {},
  onOpen: vi.fn(),
  onPatch: vi.fn().mockResolvedValue(true),
  onRetry: vi.fn().mockResolvedValue(true),
  pending: {},
  errors: {},
  ...over,
});

function expand(name: string | RegExp) {
  fireEvent.click(screen.getByRole('button', { name }));
}

describe('OpsIncidentsSection', () => {
  it('renders the per-kind rollup counts and a total', () => {
    render(<OpsIncidentsSection ops={ops()} t={t} />);
    expect(screen.getByRole('button', { name: 'admin.ops.kindAll 11' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'admin.ops.kind.collector_failure 2' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'admin.ops.kind.data_drift 3' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'admin.ops.kind.notification_failure 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'admin.ops.kind.manual_review 5' })).toBeInTheDocument();
  });

  it('renders row facts: kind, status, priority, failure state, scope, occurrences, assignee', () => {
    render(<OpsIncidentsSection ops={ops()} t={t} />);
    expect(screen.getByText('uiuc_faculty collector failed')).toBeInTheDocument();
    // enumLabel falls back to the raw enum when the identity `t` returns the key
    expect(screen.getByText('collector_failure')).toBeInTheDocument();
    expect(screen.getByText('open')).toBeInTheDocument();
    expect(screen.getByText('high')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.getByText('uiuc_faculty')).toBeInTheDocument();
    expect(screen.getByText('admin.ops.occurrences n=4')).toBeInTheDocument();
    expect(screen.getByText('admin.ops.unassigned')).toBeInTheDocument();
  });

  it('the kind filter narrows the queue through the server query', () => {
    const w = ops();
    const { rerender } = render(<OpsIncidentsSection ops={w} t={t} />);
    fireEvent.click(screen.getByRole('button', { name: 'admin.ops.kind.data_drift 3' }));
    expect(w.onFiltersChange).toHaveBeenCalledWith({ kind: 'data_drift', status: 'unresolved' });

    // …and the section renders whatever the refetch returned for that kind
    rerender(
      <OpsIncidentsSection
        ops={ops({
          filters: { kind: 'data_drift', status: 'unresolved' },
          incidents: [incident({ id: 'i2', kind: 'data_drift', title: 'purdue faculty_count dropped' })],
        })}
        t={t}
      />,
    );
    expect(screen.getByText('purdue faculty_count dropped')).toBeInTheDocument();
    expect(screen.queryByText('uiuc_faculty collector failed')).toBeNull();
  });

  it('the status filter defaults to unresolved', () => {
    const w = ops();
    render(<OpsIncidentsSection ops={w} t={t} />);
    expect(screen.getByLabelText('admin.ops.filterStatus')).toHaveValue('unresolved');
    fireEvent.change(screen.getByLabelText('admin.ops.filterStatus'), { target: { value: 'all' } });
    expect(w.onFiltersChange).toHaveBeenCalledWith({ kind: '', status: 'all' });
  });

  it('renders the empty and error states without pretending the queue is clean', () => {
    render(<OpsIncidentsSection ops={ops({ incidents: [] })} t={t} />);
    expect(screen.getByText('admin.ops.empty')).toBeInTheDocument();

    render(<OpsIncidentsSection ops={ops({ incidents: [], error: 'HTTP 500' })} t={t} />);
    expect(screen.getByRole('alert')).toHaveTextContent('admin.ops.loadFailed error=HTTP 500');
  });

  describe('evidence', () => {
    it('renders drift evidence as metric / previous / current / threshold', () => {
      render(
        <OpsIncidentsSection
          ops={ops({
            incidents: [incident({
              kind: 'data_drift',
              title: 'purdue faculty_count dropped',
              failure_state: null,
              scope: 'purdue',
              detail: { metric: 'faculty_count', previous: 2187, current: 1400, threshold: 0.2 },
            })],
          })}
          t={t}
        />,
      );
      expand('purdue faculty_count dropped');
      // enumLabel falls back to the raw evidence key under the identity `t`
      expect(screen.getByText('metric')).toBeInTheDocument();
      expect(screen.getByText('previous')).toBeInTheDocument();
      expect(screen.getByText('current')).toBeInTheDocument();
      expect(screen.getByText('threshold')).toBeInTheDocument();
      expect(screen.getByText('faculty_count')).toBeInTheDocument();
      expect(screen.getByText('2187')).toBeInTheDocument();
      expect(screen.getByText('1400')).toBeInTheDocument();
      expect(screen.getByText('0.2')).toBeInTheDocument();
    });

    it('renders notification evidence with error category, provider status and attempts', () => {
      render(
        <OpsIncidentsSection
          ops={ops({
            incidents: [incident({
              kind: 'notification_failure',
              title: 'digest send failed',
              detail: { error_category: 'provider_rejected', provider_status: 422, attempts: 2 },
              attempt_count: 2,
              next_retry_at: '2026-08-05T10:00:00+00:00',
            })],
          })}
          t={t}
        />,
      );
      expand('digest send failed');
      expect(screen.getByText('error_category')).toBeInTheDocument();
      expect(screen.getByText('provider_rejected')).toBeInTheDocument();
      expect(screen.getByText('provider_status')).toBeInTheDocument();
      expect(screen.getByText('422')).toBeInTheDocument();
      expect(screen.getByText('admin.ops.evidence.attemptCount')).toBeInTheDocument();
      expect(screen.getByText('admin.ops.evidence.nextRetry')).toBeInTheDocument();
    });

    it('renders review evidence with entity, field and the source excerpt', () => {
      render(
        <OpsIncidentsSection
          ops={ops({
            incidents: [incident({
              kind: 'manual_review',
              title: 'professor rank conflicts',
              entity_type: 'faculty',
              entity_id: 'fac-77',
              field: 'rank',
              scope: null,
              failure_state: null,
              detail: {
                source_url: 'https://example.edu/people/x',
                excerpt: 'Associate Professor of Practice',
                conflicting_values: ['associate', 'assistant'],
              },
            })],
          })}
          t={t}
        />,
      );
      expand('professor rank conflicts');
      // structural rows use their own labels; detail keys fall back to the raw key
      expect(screen.getByText('admin.ops.evidence.entity')).toBeInTheDocument();
      expect(screen.getByText('faculty · fac-77')).toBeInTheDocument();
      expect(screen.getByText('admin.ops.evidence.field')).toBeInTheDocument();
      expect(screen.getByText('source_url')).toBeInTheDocument();
      expect(screen.getByText('excerpt')).toBeInTheDocument();
      expect(screen.getByText('https://example.edu/people/x')).toBeInTheDocument();
      expect(screen.getByText('Associate Professor of Practice')).toBeInTheDocument();
      expect(screen.getByText('["associate","assistant"]')).toBeInTheDocument();
    });

    it('shows unlabelled detector evidence verbatim rather than dropping it', () => {
      render(
        <OpsIncidentsSection
          ops={ops({ incidents: [incident({ detail: { some_new_key: 'novel value' } })] })}
          t={t}
        />,
      );
      expand(/uiuc_faculty collector failed/);
      expect(screen.getByText('some_new_key')).toBeInTheDocument();
      expect(screen.getByText('novel value')).toBeInTheDocument();
    });
  });

  describe('actions', () => {
    it('assigns, re-prioritizes, acknowledges and investigates', () => {
      const w = ops();
      render(<OpsIncidentsSection ops={w} t={t} />);
      expand(/uiuc_faculty collector failed/);

      fireEvent.change(screen.getByLabelText('admin.ops.assignee'), { target: { value: 'bo' } });
      fireEvent.click(screen.getByRole('button', { name: 'admin.ops.assignSave' }));
      expect(w.onPatch).toHaveBeenCalledWith('i1', { assigned_to: 'bo' });

      fireEvent.change(screen.getByLabelText('admin.ops.priorityLabel'), { target: { value: 'urgent' } });
      expect(w.onPatch).toHaveBeenCalledWith('i1', { priority: 'urgent' });

      fireEvent.click(screen.getByRole('button', { name: 'admin.ops.acknowledge' }));
      expect(w.onPatch).toHaveBeenCalledWith('i1', { status: 'acknowledged' });

      fireEvent.click(screen.getByRole('button', { name: 'admin.ops.investigate' }));
      expect(w.onPatch).toHaveBeenCalledWith('i1', { status: 'investigating' });
    });

    it('records a retry without claiming it worked or resolving the incident', async () => {
      const w = ops();
      render(<OpsIncidentsSection ops={w} t={t} />);
      expand(/uiuc_faculty collector failed/);
      fireEvent.click(screen.getByRole('button', { name: 'admin.ops.retry' }));
      await waitFor(() => expect(w.onRetry).toHaveBeenCalledWith('i1'));
      expect(await screen.findByText('admin.ops.retryRecorded')).toBeInTheDocument();
      // no resolution was implied and the incident is still open
      expect(w.onPatch).not.toHaveBeenCalled();
      expect(screen.getByText('open')).toBeInTheDocument();
      // the copy records an attempt and explicitly disclaims knowing the outcome
      expect(translate('en', 'admin.ops.retryRecorded')).toMatch(/recorded/i);
      expect(translate('en', 'admin.ops.retryRecorded')).toMatch(/unknown/i);
    });

    it('offers no retry for kinds an operator cannot re-run', () => {
      render(
        <OpsIncidentsSection
          ops={ops({ incidents: [incident({ kind: 'data_drift', title: 'drifted', failure_state: null })] })}
          t={t}
        />,
      );
      expand('drifted');
      expect(screen.queryByRole('button', { name: 'admin.ops.retry' })).toBeNull();
    });

    it('a failed mutation shows an error and leaves the prior state', () => {
      render(<OpsIncidentsSection ops={ops({ errors: { i1: 'HTTP 500' } })} t={t} />);
      expand(/uiuc_faculty collector failed/);
      expect(screen.getByRole('alert')).toHaveTextContent('admin.ops.mutationFailed error=HTTP 500');
      expect(screen.getByLabelText('admin.ops.priorityLabel')).toHaveValue('high');
      expect(screen.getByText('open')).toBeInTheDocument();
    });
  });

  describe('resolution', () => {
    it('blocks a close with no outcome client-side', () => {
      const w = ops();
      render(<OpsIncidentsSection ops={w} t={t} />);
      expand(/uiuc_faculty collector failed/);
      fireEvent.click(screen.getByRole('button', { name: 'admin.ops.resolveButton' }));
      expect(w.onPatch).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent('admin.ops.resolutionRequired');
    });

    it('lets a manual_review item close as unknown', async () => {
      const w = ops({
        incidents: [incident({
          id: 'r1',
          kind: 'manual_review',
          title: 'publication authorship unclear',
          failure_state: null,
        })],
      });
      render(<OpsIncidentsSection ops={w} t={t} />);
      expand('publication authorship unclear');
      const select = screen.getByLabelText('admin.ops.resolutionLabel');
      // ambiguity is offered alongside the verdicts, not behind them
      for (const option of ['verified', 'rejected', 'unknown', 'conflicting', 'needs_more_evidence']) {
        expect(select.querySelector(`option[value="${option}"]`)).not.toBeNull();
      }
      fireEvent.change(select, { target: { value: 'unknown' } });
      fireEvent.click(screen.getByRole('button', { name: 'admin.ops.resolveButton' }));
      await waitFor(() =>
        expect(w.onPatch).toHaveBeenCalledWith('r1', { status: 'resolved', resolution: 'unknown' }),
      );
      expect(screen.getByText('admin.ops.reviewAmbiguityHint')).toBeInTheDocument();
    });

    it('review items are not offered operational outcomes', () => {
      render(
        <OpsIncidentsSection
          ops={ops({ incidents: [incident({ kind: 'manual_review', title: 'review me', failure_state: null })] })}
          t={t}
        />,
      );
      expand('review me');
      const select = screen.getByLabelText('admin.ops.resolutionLabel');
      expect(select.querySelector('option[value="legitimate_change"]')).toBeNull();
      expect(select.querySelector('option[value="auto_recovered"]')).toBeNull();
    });

    it('offers auto_recovered only once a detector observed a recovery', () => {
      const { unmount } = render(<OpsIncidentsSection ops={ops()} t={t} />);
      expand(/uiuc_faculty collector failed/);
      expect(
        screen.getByLabelText('admin.ops.resolutionLabel').querySelector('option[value="auto_recovered"]'),
      ).toBeNull();
      unmount();

      render(<OpsIncidentsSection ops={ops({ incidents: [incident({ failure_state: 'recovered' })] })} t={t} />);
      expand(/uiuc_faculty collector failed/);
      expect(
        screen.getByLabelText('admin.ops.resolutionLabel').querySelector('option[value="auto_recovered"]'),
      ).not.toBeNull();
      // a recovery is evidence, not a decision — the incident stays in the queue
      expect(screen.getByText('admin.ops.recoveredHint')).toBeInTheDocument();
    });

    it('a closed incident shows its decision and offers reopen', () => {
      const w = ops({
        incidents: [incident({
          status: 'resolved',
          resolution: 'fixed',
          resolution_note: 'unblocked by the new UA',
          resolved_by: 'ana',
          resolved_at: '2026-08-04T12:00:00+00:00',
        })],
      });
      render(<OpsIncidentsSection ops={w} t={t} />);
      expand(/uiuc_faculty collector failed/);
      expect(screen.getByText(/admin\.ops\.resolvedBanner/)).toBeInTheDocument();
      expect(screen.getByText('unblocked by the new UA')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'admin.ops.resolveButton' })).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: 'admin.ops.reopen' }));
      expect(w.onPatch).toHaveBeenCalledWith('i1', { status: 'open' });
    });
  });

  it('renders the event history from the detail response', () => {
    const w = ops({
      details: {
        i1: {
          incident: incident(),
          events: [
            {
              actor: 'detector',
              action: 'detected',
              from_value: null,
              to_value: 'failed',
              note: null,
              created_at: '2026-08-01T10:00:00+00:00',
            },
          ],
        },
      },
    });
    render(<OpsIncidentsSection ops={w} t={t} />);
    expand(/uiuc_faculty collector failed/);
    expect(screen.getByText('detector')).toBeInTheDocument();
    expect(screen.getByText('detected')).toBeInTheDocument();
    expect(screen.getByText('— → failed')).toBeInTheDocument();
  });

  it('loads the detail on first expand only', () => {
    const w = ops();
    render(<OpsIncidentsSection ops={w} t={t} />);
    expand(/uiuc_faculty collector failed/);
    expect(w.onOpen).toHaveBeenCalledWith('i1');
    expect(screen.getByText('admin.ops.historyEmpty')).toBeInTheDocument();
  });

  it('has every i18n key it uses in both en and zh dictionaries', () => {
    const keys = [
      'admin.ops.title',
      'admin.ops.subtitle',
      'admin.ops.loading',
      'admin.ops.empty',
      'admin.ops.loadFailed',
      'admin.ops.kindAll',
      'admin.ops.filterStatus',
      'admin.ops.filterUnresolved',
      'admin.ops.filterAnyStatus',
      'admin.ops.occurrences',
      'admin.ops.lastDetected',
      'admin.ops.assignedTo',
      'admin.ops.unassigned',
      'admin.ops.assignee',
      'admin.ops.assignPlaceholder',
      'admin.ops.assignSave',
      'admin.ops.priorityLabel',
      'admin.ops.acknowledge',
      'admin.ops.investigate',
      'admin.ops.retry',
      'admin.ops.retrying',
      'admin.ops.retryRecorded',
      'admin.ops.saving',
      'admin.ops.detailLoading',
      'admin.ops.history',
      'admin.ops.historyEmpty',
      'admin.ops.evidenceTitle',
      'admin.ops.evidenceEmpty',
      'admin.ops.mutationFailed',
      'admin.ops.resolveTitle',
      'admin.ops.resolveAs',
      'admin.ops.resolutionLabel',
      'admin.ops.resolutionPlaceholder',
      'admin.ops.resolutionNote',
      'admin.ops.resolutionNotePlaceholder',
      'admin.ops.resolutionRequired',
      'admin.ops.resolveButton',
      'admin.ops.resolvedBanner',
      'admin.ops.reopen',
      'admin.ops.reviewAmbiguityHint',
      'admin.ops.recoveredHint',
      ...['collector_failure', 'data_drift', 'notification_failure', 'manual_review'].map(
        (k) => `admin.ops.kind.${k}`,
      ),
      ...['open', 'acknowledged', 'investigating', 'resolved', 'suppressed'].map(
        (s) => `admin.ops.status.${s}`,
      ),
      ...['low', 'normal', 'high', 'urgent'].map((p) => `admin.ops.priority.${p}`),
      ...['failed', 'timed_out', 'blocked', 'partial', 'recovered'].map(
        (f) => `admin.ops.failureState.${f}`,
      ),
      ...[
        'auto_recovered', 'fixed', 'legitimate_change', 'wont_fix', 'duplicate',
        'not_reproducible', 'suppressed', 'verified', 'rejected', 'unknown', 'conflicting',
        'needs_more_evidence',
      ].map((r) => `admin.ops.resolution.${r}`),
      ...[
        'detected', 'recurred', 'recovery_observed', 'assigned', 'unassigned', 'priority_changed',
        'status_changed', 'retried', 'resolved', 'reopened', 'note_added',
      ].map((a) => `admin.ops.action.${a}`),
      ...[
        'scope', 'entity', 'field', 'attemptCount', 'nextRetry', 'lastSuccess', 'metric',
        'previous', 'current', 'delta', 'pct_change', 'threshold', 'window', 'error_category',
        'provider', 'provider_status', 'attempts', 'last_error', 'channel', 'error', 'http_status',
        'stage', 'duration_seconds', 'reason', 'source_url', 'source', 'excerpt', 'observed',
        'expected', 'conflicting_values', 'confidence',
      ].map((e) => `admin.ops.evidence.${e}`),
    ];
    for (const key of keys) {
      expect(translate('en', key), `en missing ${key}`).not.toBe(key);
      expect(translate('zh', key), `zh missing ${key}`).not.toBe(key);
    }
  });
});
