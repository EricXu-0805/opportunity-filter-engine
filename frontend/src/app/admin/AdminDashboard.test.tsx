/**
 * What the operator can actually see about unreviewed record kinds.
 *
 * A count that exists only in the API response is a dead field: the whole
 * point of separating unreviewed records out of `listing_total` is that
 * someone has to look at the queue. And a count shown under a scope this
 * build cannot vouch for is worse than no count — it reports a review queue
 * measured by rules nobody here can see.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./TrendChart', () => ({ TrendChart: () => <div data-testid="trend-chart" /> }));
vi.mock('./SourceFreshnessChart', () => ({ SourceFreshnessChart: () => null }));
vi.mock('./CollectorStatusSection', () => ({ CollectorStatusSection: () => null }));
vi.mock('./FeedbackSection', () => ({ FeedbackSection: () => null }));
vi.mock('./OpsIncidentsSection', () => ({ OpsIncidentsSection: () => null }));
vi.mock('./OrdersSection', () => ({ OrdersSection: () => null }));
vi.mock('./SavedSearchHealthSection', () => ({ SavedSearchHealthSection: () => null }));
vi.mock('./RefreshTriggerSection', () => ({ RefreshTriggerSection: () => null }));
vi.mock('./AlertList', () => ({ AlertList: () => null }));
vi.mock('./FreshnessBanner', () => ({ FreshnessBanner: () => null }));
vi.mock('./WorstFieldsSection', () => ({ WorstFieldsSection: () => null }));

import { AdminDashboard } from './AdminDashboard';
import { QUALITY_SCOPE } from './types';
import type { AdminResponse, HistoryEntry, TFunc } from './types';

const EN: Record<string, string> = {
  'admin.unreviewedRecordKind': 'Unreviewed record type',
  'admin.totalRecords': 'Total records',
};
const ZH: Record<string, string> = {
  'admin.unreviewedRecordKind': '未审核记录类型',
  'admin.totalRecords': '总记录数',
};

function makeT(dict: Record<string, string>): TFunc {
  return ((key: string) => (
    key === 'admin.bySourceCols' || key === 'admin.worstFieldsCols'
      ? {} as unknown as string
      : dict[key] ?? key
  )) as unknown as TFunc;
}

function response(overrides: Partial<AdminResponse> = {}): AdminResponse {
  return {
    total: 10,
    quality_scope: QUALITY_SCOPE,
    global: { listing_total: 6 },
    unreviewed_record_kind: { total: 3, by_source: { newsletter: 3 } },
    sources: [],
    worst_fields: [],
    generated_at: '2026-08-20T00:00:00Z',
    ...overrides,
  };
}

function renderDashboard(
  data: AdminResponse | null,
  { t = makeT(EN), history = [] as HistoryEntry[] } = {},
) {
  render(
    <AdminDashboard
      data={data}
      history={history}
      collectorStatus={null}
      collectorHistory={[]}
      health={null}
      savedSearchHealth={null}
      conciergeQueue={null}
      feedbackInbox={null}
      ordersInbox={null}
      tickets={{} as never}
      ops={{} as never}
      actor="op"
      onActorChange={() => {}}
      loading={false}
      error={null}
      adminDisabled={false}
      activeFieldFilter={null}
      setActiveFieldFilter={() => {}}
      triggerStatus={{} as never}
      previousSnapshot={null}
      filteredWorstFields={[]}
      onRefresh={() => {}}
      onLock={() => {}}
      onTriggerRefresh={() => {}}
      onConfirmOrder={async () => {}}
      t={t}
    />,
  );
}

describe('AdminDashboard — the unreviewed review queue is visible', () => {
  it.each([
    ['English', EN, 'Unreviewed record type'],
    ['Chinese', ZH, '未审核记录类型'],
  ])('shows the card with its own label in %s', (_, dict, label) => {
    renderDashboard(response(), { t: makeT(dict) });
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('shows an explicit zero as a settled queue, not as a defect', () => {
    renderDashboard(response({
      unreviewed_record_kind: { total: 0, by_source: {} },
    }));
    expect(screen.getByText('Unreviewed record type')).toBeInTheDocument();
  });

  it.each([
    ['a legacy response with no marker', { quality_scope: undefined }],
    ['a future scope this build does not know', { quality_scope: 'reviewed-record-kind-v2' }],
  ])('hides the card for %s even when a count is present', (_, overrides) => {
    // The count is deliberately a number nothing else on the page renders, so
    // "99 is absent" is a real assertion and not an accident of layout.
    renderDashboard(response({
      ...overrides as Partial<AdminResponse>,
      unreviewed_record_kind: { total: 99, by_source: { newsletter: 99 } },
    }));
    expect(screen.queryByText('Unreviewed record type')).not.toBeInTheDocument();
    expect(screen.queryByText('99')).not.toBeInTheDocument();
  });

  it('hides the card for a correctly-marked response that carries no count', () => {
    renderDashboard(response({ unreviewed_record_kind: undefined }));
    expect(screen.queryByText('Unreviewed record type')).not.toBeInTheDocument();
  });
});

describe('AdminDashboard — the trend plots one population at a time', () => {
  const entry = (t: string): HistoryEntry => ({
    t, total: 10, listing_total: 6, quality_scope: QUALITY_SCOPE,
  });

  it('plots current-scope history under a current-scope response', () => {
    renderDashboard(response(), {
      history: [entry('2026-08-18T00:00:00Z'), entry('2026-08-19T00:00:00Z')],
    });
    expect(screen.getByTestId('trend-chart')).toBeInTheDocument();
  });

  it.each([
    ['legacy', undefined],
    ['future', 'reviewed-record-kind-v2'],
  ])('refuses to plot new-scope history under a %s response', (_, scope) => {
    // The rollback shape: the disk still holds new-scope entries while an
    // older or newer backend answers. Two populations on one axis would call
    // the step between them a trend.
    renderDashboard(response({ quality_scope: scope }), {
      history: [entry('2026-08-18T00:00:00Z'), entry('2026-08-19T00:00:00Z')],
    });
    expect(screen.queryByTestId('trend-chart')).not.toBeInTheDocument();
  });
});
