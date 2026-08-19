'use client';

import Link from 'next/link';
import { AlertTriangle, ArrowLeft, Database, Lock, RefreshCw } from 'lucide-react';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import { AlertList } from './AlertList';
import { CollectorStatusSection } from './CollectorStatusSection';
import { FreshnessBanner } from './FreshnessBanner';
import { RefreshTriggerSection } from './RefreshTriggerSection';
import { FeedbackSection } from './FeedbackSection';
import { OpsIncidentsSection } from './OpsIncidentsSection';
import { OrdersSection } from './OrdersSection';
import { SavedSearchHealthSection } from './SavedSearchHealthSection';
import { SourceFreshnessChart } from './SourceFreshnessChart';
import { SourceTable } from './SourceTable';
import { StatCard } from './StatCard';
import { TrendChart } from './TrendChart';
import { WorstFieldsSection } from './WorstFieldsSection';
import { diff, listingPct, listingScopedHistory } from './admin-utils';
import type {
  AdminResponse,
  CollectorHistoryEntry,
  CollectorStatus,
  FieldKey,
  HealthResponse,
  HistoryEntry,
  FeedbackInbox,
  OpsWorkflow,
  OrdersInbox,
  SavedSearchHealth,
  TFunc,
  TicketWorkflow,
  TriggerStatus,
  WorstField,
} from './types';

export function AdminDashboard({
  data,
  history,
  collectorStatus,
  collectorHistory,
  health,
  savedSearchHealth,
  feedbackInbox,
  ordersInbox,
  tickets,
  ops,
  actor,
  onActorChange,
  loading,
  error,
  adminDisabled,
  activeFieldFilter,
  setActiveFieldFilter,
  triggerStatus,
  previousSnapshot,
  filteredWorstFields,
  onRefresh,
  onLock,
  onTriggerRefresh,
  onConfirmOrder,
  t,
}: {
  data: AdminResponse | null;
  history: HistoryEntry[];
  collectorStatus: CollectorStatus | null;
  collectorHistory: CollectorHistoryEntry[];
  health: HealthResponse | null;
  savedSearchHealth: SavedSearchHealth | null;
  feedbackInbox: FeedbackInbox | null;
  ordersInbox: OrdersInbox | null;
  tickets: TicketWorkflow;
  ops: OpsWorkflow;
  actor: string;
  onActorChange: (v: string) => void;
  loading: boolean;
  error: string | null;
  adminDisabled: boolean;
  activeFieldFilter: FieldKey | null;
  setActiveFieldFilter: (v: FieldKey | null) => void;
  triggerStatus: TriggerStatus;
  previousSnapshot: HistoryEntry | null;
  filteredWorstFields: WorstField[];
  onRefresh: () => void;
  onLock: () => void;
  onTriggerRefresh: (mode: 'quick' | 'deep') => void;
  onConfirmOrder: (id: string) => Promise<void>;
  t: TFunc;
}) {
  const comparableHistory = listingScopedHistory(history);

  return (
    <div className="min-h-screen bg-gradient-to-b from-white to-gray-50">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        <Link href="/" className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-900 mb-6">
          <ArrowLeft className="w-4 h-4" />
          {t('admin.back')}
        </Link>

        <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 tracking-tight flex items-center gap-3">
              <Database className="w-7 h-7 text-indigo-600" />
              {t('admin.title')}
            </h1>
            <p className="mt-2 text-[14px] text-gray-500">{t('admin.subtitle')}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {/* Refresh is not gated on the data-quality pane: when that pane
                is the thing that failed, retrying it is exactly what the
                operator needs the button for. It IS hidden when the console
                is disabled backend-side (503) — a control whose every call
                can only 503 is a dead control, not a retry. */}
            {!adminDisabled && (
            <button type="button" onClick={onRefresh} disabled={loading} className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-gray-200 bg-white text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50">
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              {t('admin.refresh')}
            </button>
            )}
            <div className="flex flex-col">
              <label className="flex items-center gap-1.5 text-[12px] text-gray-500">
                {t('admin.actor.label')}
                <input
                  type="text"
                  value={actor}
                  onChange={(e) => onActorChange(e.target.value)}
                  placeholder={t('admin.actor.placeholder')}
                  className="w-32 px-2 py-1 rounded-lg border border-gray-200 bg-white text-[12px] text-gray-700 outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400"
                />
              </label>
              <span className="mt-0.5 max-w-[16rem] text-[10px] leading-tight text-gray-400">
                {t('admin.actor.hint')}
              </span>
            </div>
            <button type="button" onClick={onLock} className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-gray-200 bg-white text-sm font-medium text-gray-600 hover:bg-gray-50">
              <Lock className="w-3.5 h-3.5" />
              {t('admin.lock')}
            </button>
          </div>
        </div>

        {data?.data_updated_at && <FreshnessBanner iso={data.data_updated_at} t={t} />}

        {health && health.alerts.length > 0 && <AlertList health={health} t={t} />}

        {error && (
          <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
            <AlertTriangle className="w-4 h-4 text-red-600 mt-0.5 shrink-0" />
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {loading && !data && (
          <p className="text-sm text-gray-500">{t('admin.loading')}</p>
        )}

        {/* Operational surfaces render unconditionally. They are fed by their
            own endpoints, so gating them on /admin/data-quality would take the
            incident queue and the ticket inbox offline every time an unrelated
            read-only pane errored — the exact moment an operator needs them. */}
        <OpsIncidentsSection ops={ops} t={t} />
        <FeedbackSection inbox={feedbackInbox} tickets={tickets} t={t} />
        {RELEASE_SCOPE.payments && (
          <OrdersSection inbox={ordersInbox} onConfirm={onConfirmOrder} t={t} />
        )}

        {data && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-10 mb-8">
              <StatCard label={t('admin.totalRecords')} value={data.total} color="blue" />
              <StatCard label={t('admin.emptyMajors')} value={data.global.empty_majors || 0} color={(data.global.empty_majors || 0) > 50 ? 'amber' : 'green'} pct={listingPct('empty_majors', data)} delta={diff('empty_majors', data, previousSnapshot)} active={activeFieldFilter === 'empty_majors'} onClick={() => setActiveFieldFilter(activeFieldFilter === 'empty_majors' ? null : 'empty_majors')} />
              <StatCard label={t('admin.emptyKeywords')} value={data.global.empty_keywords || 0} color={(data.global.empty_keywords || 0) > 50 ? 'amber' : 'green'} pct={listingPct('empty_keywords', data)} delta={diff('empty_keywords', data, previousSnapshot)} active={activeFieldFilter === 'empty_keywords'} onClick={() => setActiveFieldFilter(activeFieldFilter === 'empty_keywords' ? null : 'empty_keywords')} />
              <StatCard label={t('admin.rollingDeadline')} value={data.global.rolling_deadline || 0} color="green" pct={listingPct('rolling_deadline', data)} hint="legitimate" />
              <StatCard label={t('admin.missingDeadline')} value={data.global.missing_deadline || 0} color={(data.global.missing_deadline || 0) > 100 ? 'amber' : 'gray'} pct={listingPct('missing_deadline', data)} delta={diff('missing_deadline', data, previousSnapshot)} active={activeFieldFilter === 'missing_deadline'} onClick={() => setActiveFieldFilter(activeFieldFilter === 'missing_deadline' ? null : 'missing_deadline')} />
              <StatCard label={t('admin.pastDeadline')} value={data.global.past_deadline || 0} color="gray" />
              <StatCard label={t('admin.flaggedInactive')} value={data.global.flagged_inactive || 0} color="gray" delta={diff('flagged_inactive', data, previousSnapshot)} />
              <StatCard label={t('admin.shortDescription')} value={data.global.short_description || 0} color="gray" />
            </div>

            {comparableHistory.length > 1 ? (
              <section className="mb-10">
                <h2 className="text-[15px] font-semibold text-gray-900 mb-3">{t('admin.trendTitle')}</h2>
                <TrendChart history={comparableHistory} />
              </section>
            ) : (
              <p className="mb-8 text-[12px] text-gray-400 italic">{t('admin.trendEmpty')}</p>
            )}

            <SourceTable rows={data.sources} t={t} />

            <WorstFieldsSection
              rows={filteredWorstFields}
              activeFilter={activeFieldFilter}
              onClearFilter={() => setActiveFieldFilter(null)}
              t={t}
            />

            <CollectorStatusSection status={collectorStatus} t={t} />

            <SourceFreshnessChart history={collectorHistory} t={t} />

            <SavedSearchHealthSection health={savedSearchHealth} t={t} />

            <p className="mt-8 text-[11px] text-gray-400 text-right">
              Generated {new Date(data.generated_at).toLocaleString()}
            </p>
          </>
        )}

        <RefreshTriggerSection
          status={triggerStatus}
          onTrigger={onTriggerRefresh}
          t={t}
        />
      </div>
    </div>
  );
}
