'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight, ShieldAlert } from 'lucide-react';
import { enumLabel, isoAge } from './admin-utils';
import {
  DEFAULT_PRIORITY,
  OPS_CLOSED_STATUSES,
  OPS_KINDS,
  OPS_OPERATIONAL_RESOLUTIONS,
  OPS_RETRYABLE_KINDS,
  OPS_REVIEW_RESOLUTIONS,
  OPS_STATUSES,
  PRIORITIES,
} from './types';
import type {
  OpsFailureState,
  OpsIncident,
  OpsIncidentEvent,
  OpsIncidentKind,
  OpsIncidentStatus,
  OpsResolution,
  OpsWorkflow,
  Priority,
  TFunc,
} from './types';

const KIND_STYLES: Record<OpsIncidentKind, string> = {
  collector_failure: 'bg-red-50 text-red-700',
  data_drift: 'bg-amber-50 text-amber-700',
  notification_failure: 'bg-orange-50 text-orange-700',
  manual_review: 'bg-sky-50 text-sky-700',
};

const STATUS_STYLES: Record<OpsIncidentStatus, string> = {
  open: 'bg-indigo-50 text-indigo-700',
  acknowledged: 'bg-sky-50 text-sky-700',
  investigating: 'bg-amber-50 text-amber-700',
  resolved: 'bg-emerald-50 text-emerald-700',
  suppressed: 'bg-gray-100 text-gray-500',
};

const PRIORITY_STYLES: Record<Priority, string> = {
  low: 'bg-gray-100 text-gray-500',
  normal: 'bg-gray-100 text-gray-600',
  high: 'bg-amber-50 text-amber-700',
  urgent: 'bg-red-50 text-red-700',
};

const FAILURE_STYLES: Record<OpsFailureState, string> = {
  failed: 'bg-red-50 text-red-700',
  timed_out: 'bg-red-50 text-red-600',
  blocked: 'bg-purple-50 text-purple-700',
  partial: 'bg-amber-50 text-amber-700',
  // 'recovered' is EVIDENCE, not a resolution — green, but the incident is
  // still in the queue until someone closes it.
  recovered: 'bg-emerald-50 text-emerald-700',
};

const inputCls =
  'px-2 py-1 rounded-lg border border-gray-200 bg-white text-[12px] text-gray-700 outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 disabled:opacity-60';

const btnCls =
  'px-2.5 py-1 rounded-lg border border-gray-200 bg-white text-[12px] font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50';

/** Evidence keys we know how to label, in the order they read best per kind. */
const EVIDENCE_ORDER: Record<OpsIncidentKind, string[]> = {
  data_drift: ['metric', 'previous', 'current', 'delta', 'pct_change', 'threshold', 'window'],
  notification_failure: [
    'error_category', 'provider', 'provider_status', 'attempts', 'last_error', 'channel',
  ],
  collector_failure: [
    'error_category', 'error', 'http_status', 'attempts', 'stage', 'duration_seconds',
  ],
  manual_review: [
    'reason', 'source_url', 'source', 'excerpt', 'observed', 'expected', 'conflicting_values',
    'confidence',
  ],
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try { return JSON.stringify(value); } catch { return String(value); }
}

function EvidenceRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2 text-[12px]">
      <span className="w-32 shrink-0 text-gray-400">{label}</span>
      <span className="text-gray-700 break-words min-w-0">{value}</span>
    </div>
  );
}

function DetailEvidence({ incident, t }: { incident: OpsIncident; t: TFunc }) {
  const detail = incident.detail ?? {};
  const ordered = EVIDENCE_ORDER[incident.kind] ?? [];
  const known = ordered.filter((k) => detail[k] !== undefined && detail[k] !== null);
  // Anything the detector recorded that we have no label for is still shown
  // verbatim — hiding unlabelled evidence would quietly drop the reason the
  // incident exists.
  const rest = Object.keys(detail).filter((k) => !known.includes(k));

  const structural: { label: string; value: string }[] = [];
  if (incident.scope) structural.push({ label: t('admin.ops.evidence.scope'), value: incident.scope });
  if (incident.entity_type || incident.entity_id) {
    structural.push({
      label: t('admin.ops.evidence.entity'),
      value: [incident.entity_type, incident.entity_id].filter(Boolean).join(' · '),
    });
  }
  if (incident.field) structural.push({ label: t('admin.ops.evidence.field'), value: incident.field });
  if (incident.attempt_count != null) {
    structural.push({ label: t('admin.ops.evidence.attemptCount'), value: String(incident.attempt_count) });
  }
  if (incident.next_retry_at) {
    structural.push({
      label: t('admin.ops.evidence.nextRetry'),
      value: new Date(incident.next_retry_at).toLocaleString(),
    });
  }
  if (incident.last_success_at) {
    structural.push({
      label: t('admin.ops.evidence.lastSuccess'),
      value: new Date(incident.last_success_at).toLocaleString(),
    });
  }

  const empty = known.length === 0 && rest.length === 0 && structural.length === 0;

  return (
    <div className="mt-2 rounded-lg bg-gray-50 border border-black/[0.04] px-3 py-2 space-y-1">
      <p className="text-[12px] font-medium text-gray-500">{t('admin.ops.evidenceTitle')}</p>
      {empty ? (
        <p className="text-[12px] text-gray-400 italic">{t('admin.ops.evidenceEmpty')}</p>
      ) : (
        <>
          {structural.map((r) => <EvidenceRow key={r.label} label={r.label} value={r.value} />)}
          {known.map((k) => (
            <EvidenceRow
              key={k}
              label={enumLabel(t, 'admin.ops.evidence', k, k)}
              value={formatValue(detail[k])}
            />
          ))}
          {rest.map((k) => (
            <EvidenceRow key={k} label={k} value={formatValue(detail[k])} />
          ))}
        </>
      )}
    </div>
  );
}

function EventTimeline({ events, t }: { events: OpsIncidentEvent[]; t: TFunc }) {
  if (events.length === 0) {
    return <p className="text-[12px] text-gray-400 italic">{t('admin.ops.historyEmpty')}</p>;
  }
  return (
    <ol className="space-y-1.5">
      {events.map((e, i) => (
        <li key={`${e.created_at}-${i}`} className="text-[12px] text-gray-600 flex flex-wrap gap-x-2">
          <span className="text-gray-400 tabular-nums">{new Date(e.created_at).toLocaleString()}</span>
          <span className="font-medium text-gray-700">{e.actor}</span>
          <span>{enumLabel(t, 'admin.ops.action', e.action, e.action)}</span>
          {(e.from_value || e.to_value) && (
            <span className="text-gray-500 font-mono">
              {e.from_value ?? '—'} → {e.to_value ?? '—'}
            </span>
          )}
          {e.note && <span className="text-gray-500 italic w-full">{e.note}</span>}
        </li>
      ))}
    </ol>
  );
}

function resolutionOptions(incident: OpsIncident): readonly OpsResolution[] {
  if (incident.kind === 'manual_review') return OPS_REVIEW_RESOLUTIONS;
  // auto_recovered is detector evidence; offering it before a detector saw a
  // successful run would let an operator record a recovery that never happened.
  return incident.failure_state === 'recovered'
    ? (['auto_recovered', ...OPS_OPERATIONAL_RESOLUTIONS] as OpsResolution[])
    : OPS_OPERATIONAL_RESOLUTIONS;
}

function ResolveBox({ incident, ops, t }: { incident: OpsIncident; ops: OpsWorkflow; t: TFunc }) {
  const [resolution, setResolution] = useState<OpsResolution | ''>('');
  const [note, setNote] = useState('');
  const [finalStatus, setFinalStatus] = useState<OpsIncidentStatus>('resolved');
  const [localError, setLocalError] = useState<string | null>(null);
  const pending = ops.pending[incident.id] ?? false;
  const isReview = incident.kind === 'manual_review';

  return (
    <div className="mt-3 rounded-lg border border-black/[0.06] px-3 py-2.5">
      <p className="text-[12px] font-medium text-gray-500 mb-1.5">{t('admin.ops.resolveTitle')}</p>
      {isReview && (
        <p className="text-[11px] text-gray-500 mb-1.5">{t('admin.ops.reviewAmbiguityHint')}</p>
      )}
      {incident.failure_state === 'recovered' && (
        <p className="text-[11px] text-emerald-800 mb-1.5">{t('admin.ops.recoveredHint')}</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t('admin.ops.resolutionLabel')}
          value={resolution}
          disabled={pending}
          onChange={(e) => { setResolution(e.target.value as OpsResolution | ''); setLocalError(null); }}
          className={inputCls}
        >
          <option value="">{t('admin.ops.resolutionPlaceholder')}</option>
          {resolutionOptions(incident).map((r) => (
            <option key={r} value={r}>{t(`admin.ops.resolution.${r}`)}</option>
          ))}
        </select>
        <select
          aria-label={t('admin.ops.resolveAs')}
          value={finalStatus}
          disabled={pending}
          onChange={(e) => setFinalStatus(e.target.value as OpsIncidentStatus)}
          className={inputCls}
        >
          {OPS_CLOSED_STATUSES.map((s) => (
            <option key={s} value={s}>{t(`admin.ops.status.${s}`)}</option>
          ))}
        </select>
        <input
          type="text"
          aria-label={t('admin.ops.resolutionNote')}
          value={note}
          disabled={pending}
          onChange={(e) => setNote(e.target.value)}
          placeholder={t('admin.ops.resolutionNotePlaceholder')}
          className={`${inputCls} flex-1 min-w-[12rem]`}
        />
        <button
          type="button"
          disabled={pending}
          onClick={async () => {
            if (!resolution) {
              setLocalError(t('admin.ops.resolutionRequired'));
              return;
            }
            setLocalError(null);
            const ok = await ops.onPatch(incident.id, {
              status: finalStatus,
              resolution,
              ...(note.trim() ? { resolution_note: note.trim() } : {}),
            });
            if (ok) setNote('');
          }}
          className="px-3 py-1.5 rounded-lg text-[12px] font-medium text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50"
        >
          {pending ? t('admin.ops.saving') : t('admin.ops.resolveButton')}
        </button>
      </div>
      {localError && <p role="alert" className="mt-1 text-[12px] text-red-700">{localError}</p>}
    </div>
  );
}

function IncidentDetailPanel({ incident, ops, t }: { incident: OpsIncident; ops: OpsWorkflow; t: TFunc }) {
  const [assignee, setAssignee] = useState(incident.assigned_to ?? '');
  const [retryRecorded, setRetryRecorded] = useState(false);
  const detail = ops.details[incident.id];
  const detailLoading = ops.detailLoading[incident.id] ?? false;
  const pending = ops.pending[incident.id] ?? false;
  const err = ops.errors[incident.id];
  const status = incident.status ?? 'open';
  const isClosed = OPS_CLOSED_STATUSES.includes(status);
  const canRetry = OPS_RETRYABLE_KINDS.includes(incident.kind);

  return (
    <div className="mt-2.5 border-t border-black/[0.06] pt-2.5">
      {incident.summary && (
        <p className="text-[13px] text-gray-800 whitespace-pre-wrap break-words">{incident.summary}</p>
      )}

      <DetailEvidence incident={incident} t={t} />

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          type="text"
          aria-label={t('admin.ops.assignee')}
          value={assignee}
          disabled={pending}
          onChange={(e) => setAssignee(e.target.value)}
          placeholder={t('admin.ops.assignPlaceholder')}
          className={`${inputCls} w-40`}
        />
        <button
          type="button"
          disabled={pending}
          onClick={() => ops.onPatch(incident.id, { assigned_to: assignee.trim() || null })}
          className={btnCls}
        >
          {t('admin.ops.assignSave')}
        </button>

        <select
          aria-label={t('admin.ops.priorityLabel')}
          value={incident.priority ?? DEFAULT_PRIORITY}
          disabled={pending}
          onChange={(e) => ops.onPatch(incident.id, { priority: e.target.value as Priority })}
          className={inputCls}
        >
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>{t(`admin.ops.priority.${p}`)}</option>
          ))}
        </select>

        {!isClosed && (
          <>
            <button
              type="button"
              disabled={pending || status === 'acknowledged'}
              onClick={() => ops.onPatch(incident.id, { status: 'acknowledged' })}
              className={btnCls}
            >
              {t('admin.ops.acknowledge')}
            </button>
            <button
              type="button"
              disabled={pending || status === 'investigating'}
              onClick={() => ops.onPatch(incident.id, { status: 'investigating' })}
              className={btnCls}
            >
              {t('admin.ops.investigate')}
            </button>
          </>
        )}

        {canRetry && (
          <button
            type="button"
            disabled={pending}
            onClick={async () => {
              const ok = await ops.onRetry(incident.id);
              if (ok) setRetryRecorded(true);
            }}
            className={btnCls}
          >
            {pending ? t('admin.ops.retrying') : t('admin.ops.retry')}
          </button>
        )}
      </div>

      {retryRecorded && (
        <p className="mt-1.5 text-[12px] text-gray-600">{t('admin.ops.retryRecorded')}</p>
      )}

      {err && (
        <p role="alert" className="mt-1.5 text-[12px] text-red-700">
          {t('admin.ops.mutationFailed', { error: err })}
        </p>
      )}

      {isClosed ? (
        <div className="mt-3 rounded-lg bg-emerald-50/60 border border-emerald-100 px-3 py-2">
          <p className="text-[12px] text-emerald-900">
            {t('admin.ops.resolvedBanner', {
              resolution: enumLabel(t, 'admin.ops.resolution', incident.resolution, '—'),
              actor: incident.resolved_by ?? '—',
              when: incident.resolved_at ? new Date(incident.resolved_at).toLocaleString() : '—',
            })}
          </p>
          {incident.resolution_note && (
            <p className="mt-0.5 text-[12px] text-emerald-800 italic">{incident.resolution_note}</p>
          )}
          <button
            type="button"
            disabled={pending}
            onClick={() => ops.onPatch(incident.id, { status: 'open' })}
            className="mt-1.5 px-2.5 py-1 rounded-lg border border-emerald-200 bg-white text-[12px] font-medium text-emerald-800 hover:bg-emerald-50 disabled:opacity-50"
          >
            {t('admin.ops.reopen')}
          </button>
        </div>
      ) : (
        <ResolveBox incident={incident} ops={ops} t={t} />
      )}

      <div className="mt-3">
        <p className="text-[12px] font-medium text-gray-500 mb-1">{t('admin.ops.history')}</p>
        {detailLoading && !detail ? (
          <p className="text-[12px] text-gray-400 italic">{t('admin.ops.detailLoading')}</p>
        ) : (
          <EventTimeline events={detail?.events ?? []} t={t} />
        )}
      </div>
    </div>
  );
}

function IncidentRow({ incident, ops, t }: { incident: OpsIncident; ops: OpsWorkflow; t: TFunc }) {
  const [expanded, setExpanded] = useState(false);
  const status = incident.status ?? 'open';
  const priority = incident.priority ?? DEFAULT_PRIORITY;

  return (
    <li className="rounded-xl border border-black/[0.06] bg-white px-3.5 py-2.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => {
            const next = !expanded;
            setExpanded(next);
            if (next && !ops.details[incident.id]) ops.onOpen(incident.id);
          }}
          className="inline-flex items-center gap-1 text-[13px] font-medium text-gray-800 hover:text-indigo-700 text-left"
        >
          {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          {incident.title}
        </button>
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${KIND_STYLES[incident.kind] ?? 'bg-gray-100 text-gray-600'}`}>
          {enumLabel(t, 'admin.ops.kind', incident.kind, incident.kind)}
        </span>
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-600'}`}>
          {enumLabel(t, 'admin.ops.status', status, status)}
        </span>
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${PRIORITY_STYLES[priority] ?? 'bg-gray-100 text-gray-600'}`}>
          {enumLabel(t, 'admin.ops.priority', priority, priority)}
        </span>
        {incident.failure_state && (
          <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${FAILURE_STYLES[incident.failure_state] ?? 'bg-gray-100 text-gray-600'}`}>
            {enumLabel(t, 'admin.ops.failureState', incident.failure_state, incident.failure_state)}
          </span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-400">
        {incident.scope && <span className="font-mono">{incident.scope}</span>}
        {(incident.entity_type || incident.entity_id) && (
          <span className="font-mono">
            {[incident.entity_type, incident.entity_id].filter(Boolean).join(':')}
            {incident.field ? `·${incident.field}` : ''}
          </span>
        )}
        <span>{t('admin.ops.occurrences', { n: incident.occurrence_count ?? 1 })}</span>
        {incident.last_detected_at && (
          <span>{t('admin.ops.lastDetected', { when: isoAge(incident.last_detected_at, t) })}</span>
        )}
        <span className="text-gray-500">
          {incident.assigned_to
            ? t('admin.ops.assignedTo', { actor: incident.assigned_to })
            : t('admin.ops.unassigned')}
        </span>
      </div>
      {expanded && <IncidentDetailPanel incident={incident} ops={ops} t={t} />}
    </li>
  );
}

function KindTabs({ ops, t }: { ops: OpsWorkflow; t: TFunc }) {
  const byKind = ops.rollup.open_by_kind ?? {};
  // open_total counts every open row; the per-kind sum only counts the kinds
  // this UI knows about. Prefer the server's total so a kind added backend-first
  // is not silently dropped from the "All" badge.
  const total = ops.rollup.open_total ?? OPS_KINDS.reduce((sum, k) => sum + (byKind[k] ?? 0), 0);
  const tab = (key: OpsIncidentKind | '', label: string, count: number) => {
    const active = ops.filters.kind === key;
    return (
      <button
        key={key || 'all'}
        type="button"
        aria-pressed={active}
        onClick={() => ops.onFiltersChange({ ...ops.filters, kind: key })}
        className={`px-2.5 py-1 rounded-lg text-[12px] font-medium border ${
          active
            ? 'border-indigo-300 bg-indigo-50 text-indigo-700'
            : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
        }`}
      >
        {label} <span className="tabular-nums text-gray-400">{count}</span>
      </button>
    );
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      {tab('', t('admin.ops.kindAll'), total)}
      {OPS_KINDS.map((k) => tab(k, t(`admin.ops.kind.${k}`), byKind[k] ?? 0))}
    </div>
  );
}

export function OpsIncidentsSection({ ops, t }: { ops: OpsWorkflow; t: TFunc }) {
  return (
    <section className="mt-2 mb-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-1 flex items-center gap-2">
        <ShieldAlert className="w-4 h-4 text-indigo-600" />
        {t('admin.ops.title')}
      </h2>
      <p className="text-[12px] text-gray-500 mb-3">{t('admin.ops.subtitle')}</p>

      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <KindTabs ops={ops} t={t} />
        <select
          aria-label={t('admin.ops.filterStatus')}
          value={ops.filters.status}
          onChange={(e) =>
            ops.onFiltersChange({
              ...ops.filters,
              status: e.target.value as OpsWorkflow['filters']['status'],
            })
          }
          className={inputCls}
        >
          <option value="unresolved">{t('admin.ops.filterUnresolved')}</option>
          <option value="all">{t('admin.ops.filterAnyStatus')}</option>
          {OPS_STATUSES.map((s) => (
            <option key={s} value={s}>{t(`admin.ops.status.${s}`)}</option>
          ))}
        </select>
      </div>

      {ops.error && (
        <p role="alert" className="text-[13px] text-red-700 mb-2">
          {t('admin.ops.loadFailed', { error: ops.error })}
        </p>
      )}

      {!ops.loaded && !ops.error ? (
        <p className="text-[13px] text-gray-400 italic">{t('admin.ops.loading')}</p>
      ) : ops.incidents.length === 0 ? (
        <p className="text-[13px] text-gray-400 italic">{t('admin.ops.empty')}</p>
      ) : (
        <ul className="space-y-2">
          {ops.incidents.map((i) => (
            <IncidentRow key={i.id} incident={i} ops={ops} t={t} />
          ))}
        </ul>
      )}
    </section>
  );
}
