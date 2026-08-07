'use client';

import { useState } from 'react';
import { BarChart3, ChevronDown, ChevronRight, MessageSquareText, ThumbsDown } from 'lucide-react';
import { StatCard } from './StatCard';
import { enumLabel, isoAge } from './admin-utils';
import {
  DEFAULT_PRIORITY,
  DEFAULT_TICKET_STATUS,
  PRIORITIES,
  TICKET_CLOSING_STATUSES,
  TICKET_OPEN_STATUSES,
  TICKET_RESOLUTIONS,
  TICKET_STATUSES,
} from './types';
import type {
  FeedbackAnalysis,
  FeedbackRateRow,
  Priority,
  ReplyDelivery,
  TFunc,
  FeedbackInbox,
  Ticket,
  TicketEvent,
  TicketResolution,
  TicketStatus,
  TicketWorkflow,
} from './types';

const STATUS_STYLES: Record<TicketStatus, string> = {
  open: 'bg-indigo-50 text-indigo-700',
  triaged: 'bg-sky-50 text-sky-700',
  in_progress: 'bg-amber-50 text-amber-700',
  waiting_on_user: 'bg-violet-50 text-violet-700',
  resolved: 'bg-emerald-50 text-emerald-700',
  closed: 'bg-gray-100 text-gray-500',
};

const PRIORITY_STYLES: Record<Priority, string> = {
  low: 'bg-gray-100 text-gray-500',
  normal: 'bg-gray-100 text-gray-600',
  high: 'bg-amber-50 text-amber-700',
  urgent: 'bg-red-50 text-red-700',
};

/**
 * The reply-delivery vocabulary. There is deliberately no "sent" anywhere in
 * this map: 'stored' means the reply exists in the database and NOTHING left
 * the building, and the UI has to say so.
 */
const DELIVERY_KEYS: Record<ReplyDelivery, string> = {
  stored: 'admin.tickets.deliveryStored',
  emailed: 'admin.tickets.deliveryEmailed',
  email_failed: 'admin.tickets.deliveryFailed',
};

const DELIVERY_STYLES: Record<ReplyDelivery, string> = {
  stored: 'text-gray-500',
  emailed: 'text-emerald-700',
  email_failed: 'text-red-700',
};

const inputCls =
  'px-2 py-1 rounded-lg border border-gray-200 bg-white text-[12px] text-gray-700 outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 disabled:opacity-60';

function RateBreakdown({ title, rows }: { title: string; rows?: FeedbackRateRow[] }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div>
      <p className="text-[11px] font-medium text-gray-400 mb-1">{title}</p>
      <ul className="space-y-1">
        {rows.map((r) => (
          <li key={r.key} className="flex items-center gap-2 text-[12px] text-gray-600">
            <span className="w-24 truncate shrink-0">{r.key}</span>
            <span className="flex-1 h-1.5 rounded-full bg-gray-100 overflow-hidden">
              <span
                className="block h-full rounded-full bg-indigo-400"
                style={{ width: `${Math.round(r.up_rate * 100)}%` }}
              />
            </span>
            <span className="w-16 text-right tabular-nums text-gray-500">
              {Math.round(r.up_rate * 100)}% · {r.n}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AnalysisBlock({ analysis, t }: { analysis: FeedbackAnalysis; t: TFunc }) {
  const replay = analysis.replay;
  return (
    <div className="mt-4">
      <p className="text-[12px] font-medium text-gray-500 mb-2 flex items-center gap-1">
        <BarChart3 className="w-3 h-3" /> {t('admin.feedback.analysisTitle')}
      </p>
      {analysis.insufficient ? (
        <p className="text-[13px] text-gray-400 italic">
          {t('admin.feedback.analysisInsufficient', {
            n: analysis.sample_n,
            needed: analysis.needed ?? 50,
          })}
        </p>
      ) : (
        <>
          <p className="text-[12px] text-gray-600 mb-2">
            {t('admin.feedback.analysisUpRate', {
              rate: Math.round((analysis.up_rate ?? 0) * 100),
              n: analysis.sample_n,
            })}
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <RateBreakdown title={t('admin.feedback.analysisByBucket')} rows={analysis.by_bucket} />
            <RateBreakdown title={t('admin.feedback.analysisByScore')} rows={analysis.by_score_band} />
            <RateBreakdown title={t('admin.feedback.analysisBySchool')} rows={analysis.by_school} />
            <RateBreakdown title={t('admin.feedback.analysisByPosition')} rows={analysis.by_position} />
          </div>
          {replay && (
            <div className="mt-3 text-[12px] text-gray-600">
              <p>
                {t('admin.feedback.analysisAgreement', {
                  value:
                    replay.current_agreement != null
                      ? `${Math.round(replay.current_agreement * 100)}%`
                      : '—',
                })}
                {replay.mode === 'weight_replay' && replay.best_candidate && (
                  <>
                    {' · '}
                    {t('admin.feedback.analysisReplayBest', {
                      weights: `${replay.best_candidate.eligibility}/${replay.best_candidate.readiness}/${replay.best_candidate.upside}`,
                      delta: `${replay.delta != null && replay.delta > 0 ? '+' : ''}${Math.round((replay.delta ?? 0) * 100)}%`,
                    })}
                  </>
                )}
              </p>
              <p className="mt-0.5 text-[11px] text-gray-400">{replay.note}</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function EventTimeline({ events, t }: { events: TicketEvent[]; t: TFunc }) {
  if (events.length === 0) {
    return <p className="text-[12px] text-gray-400 italic">{t('admin.tickets.historyEmpty')}</p>;
  }
  return (
    <ol className="space-y-1.5">
      {events.map((e, i) => (
        <li key={`${e.created_at}-${i}`} className="text-[12px] text-gray-600 flex flex-wrap gap-x-2">
          <span className="text-gray-400 tabular-nums">{new Date(e.created_at).toLocaleString()}</span>
          <span className="font-medium text-gray-700">{e.actor}</span>
          <span>{enumLabel(t, 'admin.tickets.action', e.action, e.action)}</span>
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

function ReplyBox({
  ticket,
  workflow,
  t,
}: {
  ticket: Ticket;
  workflow: TicketWorkflow;
  t: TFunc;
}) {
  const [draft, setDraft] = useState('');
  const [deliver, setDeliver] = useState(false);
  const hasEmail = Boolean(ticket.email);
  const pending = workflow.replyPending[ticket.id] ?? false;
  const err = workflow.replyErrors[ticket.id];
  const delivery = ticket.admin_reply_delivery;

  return (
    <div className="mt-3">
      <p className="text-[12px] font-medium text-gray-500 mb-1">{t('admin.tickets.replyTitle')}</p>
      {ticket.admin_reply && (
        <div className="mb-2 rounded-lg bg-gray-50 border border-black/[0.04] px-3 py-2">
          <p className="text-[13px] text-gray-800 whitespace-pre-wrap break-words">{ticket.admin_reply}</p>
          <p className="mt-1 text-[11px] text-gray-400">
            {ticket.admin_reply_by ?? '—'}
            {ticket.admin_reply_at ? ` · ${new Date(ticket.admin_reply_at).toLocaleString()}` : ''}
          </p>
          {/* Exactly what the backend recorded — never "sent". */}
          {delivery && (
            <p className={`mt-0.5 text-[11px] font-medium ${DELIVERY_STYLES[delivery] ?? 'text-gray-500'}`}>
              {t(DELIVERY_KEYS[delivery] ?? 'admin.tickets.deliveryStored')}
            </p>
          )}
        </div>
      )}
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={3}
        aria-label={t('admin.tickets.replyTitle')}
        placeholder={t('admin.tickets.replyPlaceholder')}
        className="w-full px-3 py-2 rounded-lg border border-gray-200 text-[13px] text-gray-800 outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400"
      />
      <div className="mt-1.5 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1.5 text-[12px] text-gray-600">
          <input
            type="checkbox"
            checked={deliver && hasEmail}
            disabled={!hasEmail || pending}
            onChange={(e) => setDeliver(e.target.checked)}
          />
          {t('admin.tickets.replyAlsoEmail')}
        </label>
        {!hasEmail && (
          <span className="text-[11px] text-gray-400 italic">{t('admin.tickets.replyNoEmail')}</span>
        )}
        <button
          type="button"
          disabled={pending || draft.trim().length === 0}
          onClick={async () => {
            const ok = await workflow.onReply(ticket.id, draft.trim(), deliver && hasEmail);
            // Only a confirmed save may clear the box. A dropped connection
            // must not also eat the operator's text.
            if (ok) {
              setDraft('');
              setDeliver(false);
            }
          }}
          className="px-3 py-1.5 rounded-lg text-[12px] font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
        >
          {pending ? t('admin.tickets.replySaving') : t('admin.tickets.replySave')}
        </button>
        <span className="text-[11px] text-gray-400">{t('admin.tickets.replyNeverResolves')}</span>
      </div>
      {err && (
        <p role="alert" className="mt-1 text-[12px] text-red-700">
          {t('admin.tickets.replyFailed', { error: err })}
        </p>
      )}
    </div>
  );
}

function ResolveBox({
  ticket,
  workflow,
  t,
}: {
  ticket: Ticket;
  workflow: TicketWorkflow;
  t: TFunc;
}) {
  const [resolution, setResolution] = useState<TicketResolution | ''>('');
  const [note, setNote] = useState('');
  const [finalStatus, setFinalStatus] = useState<TicketStatus>('resolved');
  const [localError, setLocalError] = useState<string | null>(null);
  const pending = workflow.pending[ticket.id] ?? false;

  return (
    <div className="mt-3 rounded-lg border border-black/[0.06] px-3 py-2.5">
      <p className="text-[12px] font-medium text-gray-500 mb-1.5">{t('admin.tickets.resolveTitle')}</p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t('admin.tickets.resolutionLabel')}
          value={resolution}
          disabled={pending}
          onChange={(e) => { setResolution(e.target.value as TicketResolution | ''); setLocalError(null); }}
          className={inputCls}
        >
          <option value="">{t('admin.tickets.resolutionPlaceholder')}</option>
          {TICKET_RESOLUTIONS.map((r) => (
            <option key={r} value={r}>{t(`admin.tickets.resolution.${r}`)}</option>
          ))}
        </select>
        <select
          aria-label={t('admin.tickets.resolveAs')}
          value={finalStatus}
          disabled={pending}
          onChange={(e) => setFinalStatus(e.target.value as TicketStatus)}
          className={inputCls}
        >
          {TICKET_CLOSING_STATUSES.map((s) => (
            <option key={s} value={s}>{t(`admin.tickets.status.${s}`)}</option>
          ))}
        </select>
        <input
          type="text"
          aria-label={t('admin.tickets.resolutionNote')}
          value={note}
          disabled={pending}
          onChange={(e) => setNote(e.target.value)}
          placeholder={t('admin.tickets.resolutionNotePlaceholder')}
          className={`${inputCls} flex-1 min-w-[12rem]`}
        />
        <button
          type="button"
          disabled={pending}
          onClick={async () => {
            // Client-side mirror of the backend 400: a ticket never closes
            // without a decision, so we do not even send the request.
            if (!resolution) {
              setLocalError(t('admin.tickets.resolutionRequired'));
              return;
            }
            setLocalError(null);
            const ok = await workflow.onPatch(ticket.id, {
              status: finalStatus,
              resolution,
              ...(note.trim() ? { resolution_note: note.trim() } : {}),
            });
            if (ok) setNote('');
          }}
          className="px-3 py-1.5 rounded-lg text-[12px] font-medium text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50"
        >
          {pending ? t('admin.tickets.saving') : t('admin.tickets.resolveButton')}
        </button>
      </div>
      {localError && (
        <p role="alert" className="mt-1 text-[12px] text-red-700">{localError}</p>
      )}
    </div>
  );
}

function TicketDetailPanel({
  ticket,
  workflow,
  t,
}: {
  ticket: Ticket;
  workflow: TicketWorkflow;
  t: TFunc;
}) {
  const [assignee, setAssignee] = useState(ticket.assigned_to ?? '');
  const detail = workflow.details[ticket.id];
  const detailLoading = workflow.detailLoading[ticket.id] ?? false;
  const pending = workflow.pending[ticket.id] ?? false;
  const err = workflow.errors[ticket.id];
  const status = ticket.status ?? DEFAULT_TICKET_STATUS;
  const isClosed = (TICKET_CLOSING_STATUSES as readonly string[]).includes(status);

  return (
    <div className="mt-2.5 border-t border-black/[0.06] pt-2.5">
      <p className="text-[13px] text-gray-800 whitespace-pre-wrap break-words">{ticket.message}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          type="text"
          aria-label={t('admin.tickets.assignee')}
          value={assignee}
          disabled={pending}
          onChange={(e) => setAssignee(e.target.value)}
          placeholder={t('admin.tickets.assignPlaceholder')}
          className={`${inputCls} w-40`}
        />
        <button
          type="button"
          disabled={pending}
          onClick={() => workflow.onPatch(ticket.id, { assigned_to: assignee.trim() || null })}
          className="px-2.5 py-1 rounded-lg border border-gray-200 bg-white text-[12px] font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          {t('admin.tickets.assignSave')}
        </button>

        <select
          aria-label={t('admin.tickets.priorityLabel')}
          value={ticket.priority ?? DEFAULT_PRIORITY}
          disabled={pending}
          onChange={(e) => workflow.onPatch(ticket.id, { priority: e.target.value as Priority })}
          className={inputCls}
        >
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>{t(`admin.tickets.priority.${p}`)}</option>
          ))}
        </select>

        {!isClosed && (
          <select
            aria-label={t('admin.tickets.statusLabel')}
            value={status}
            disabled={pending}
            onChange={(e) => workflow.onPatch(ticket.id, { status: e.target.value as TicketStatus })}
            className={inputCls}
          >
            {TICKET_OPEN_STATUSES.map((s) => (
              <option key={s} value={s}>{t(`admin.tickets.status.${s}`)}</option>
            ))}
          </select>
        )}
      </div>

      {err && (
        <p role="alert" className="mt-1.5 text-[12px] text-red-700">
          {t('admin.tickets.mutationFailed', { error: err })}
        </p>
      )}

      {isClosed ? (
        <div className="mt-3 rounded-lg bg-emerald-50/60 border border-emerald-100 px-3 py-2">
          <p className="text-[12px] text-emerald-900">
            {t('admin.tickets.resolvedBanner', {
              resolution: enumLabel(t, 'admin.tickets.resolution', ticket.resolution, '—'),
              actor: ticket.resolved_by ?? '—',
              when: ticket.resolved_at ? new Date(ticket.resolved_at).toLocaleString() : '—',
            })}
          </p>
          {ticket.resolution_note && (
            <p className="mt-0.5 text-[12px] text-emerald-800 italic">{ticket.resolution_note}</p>
          )}
          <button
            type="button"
            disabled={pending}
            onClick={() => workflow.onPatch(ticket.id, { status: 'open' })}
            className="mt-1.5 px-2.5 py-1 rounded-lg border border-emerald-200 bg-white text-[12px] font-medium text-emerald-800 hover:bg-emerald-50 disabled:opacity-50"
          >
            {t('admin.tickets.reopen')}
          </button>
        </div>
      ) : (
        <ResolveBox ticket={ticket} workflow={workflow} t={t} />
      )}

      <ReplyBox ticket={ticket} workflow={workflow} t={t} />

      <div className="mt-3">
        <p className="text-[12px] font-medium text-gray-500 mb-1">{t('admin.tickets.history')}</p>
        {detailLoading && !detail ? (
          <p className="text-[12px] text-gray-400 italic">{t('admin.tickets.detailLoading')}</p>
        ) : (
          <EventTimeline events={detail?.events ?? []} t={t} />
        )}
      </div>
    </div>
  );
}

function TicketRow({ ticket, workflow, t }: { ticket: Ticket; workflow: TicketWorkflow; t: TFunc }) {
  const [expanded, setExpanded] = useState(false);
  const status = ticket.status ?? DEFAULT_TICKET_STATUS;
  const priority = ticket.priority ?? DEFAULT_PRIORITY;
  const subject = ticket.subject?.trim();

  return (
    <li className="rounded-xl border border-black/[0.06] bg-white px-3.5 py-2.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <button
          type="button"
          onClick={() => {
            const next = !expanded;
            setExpanded(next);
            if (next && !workflow.details[ticket.id]) workflow.onOpen(ticket.id);
          }}
          aria-expanded={expanded}
          className="inline-flex items-center gap-1 text-[13px] font-medium text-gray-800 hover:text-indigo-700 text-left"
        >
          {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          {subject || t('admin.tickets.noSubject')}
        </button>
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-600'}`}>
          {enumLabel(t, 'admin.tickets.status', status, status)}
        </span>
        <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${PRIORITY_STYLES[priority] ?? 'bg-gray-100 text-gray-600'}`}>
          {enumLabel(t, 'admin.tickets.priority', priority, priority)}
        </span>
        {ticket.category && (
          <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-gray-100 text-gray-600">
            {enumLabel(t, 'admin.tickets.category', ticket.category, ticket.category)}
          </span>
        )}
        <span className="text-[11px] text-gray-400">{isoAge(ticket.created_at, t)}</span>
        <span className="text-[11px] text-gray-500">
          {ticket.assigned_to
            ? t('admin.tickets.assignedTo', { actor: ticket.assigned_to })
            : t('admin.tickets.unassigned')}
        </span>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-400">
        <span>{new Date(ticket.created_at).toLocaleString()}</span>
        {typeof ticket.props?.path === 'string' && ticket.props.path && (
          <span className="font-mono">{ticket.props.path}</span>
        )}
        {ticket.email && (
          <a href={`mailto:${ticket.email}`} className="text-indigo-600 hover:text-indigo-700">
            {ticket.email}
          </a>
        )}
      </div>

      {!expanded && (
        <p className="mt-1 text-[13px] text-gray-800 line-clamp-2 break-words">{ticket.message}</p>
      )}

      {expanded && <TicketDetailPanel ticket={ticket} workflow={workflow} t={t} />}
    </li>
  );
}

function TicketFiltersBar({ workflow, t }: { workflow: TicketWorkflow; t: TFunc }) {
  const f = workflow.filters;
  return (
    <div className="flex flex-wrap items-center gap-2 mb-2">
      <select
        aria-label={t('admin.tickets.filterStatus')}
        value={f.status}
        onChange={(e) => workflow.onFiltersChange({ ...f, status: e.target.value as TicketStatus | '' })}
        className={inputCls}
      >
        <option value="">{t('admin.tickets.filterAnyStatus')}</option>
        {TICKET_STATUSES.map((s) => (
          <option key={s} value={s}>{t(`admin.tickets.status.${s}`)}</option>
        ))}
      </select>
      <select
        aria-label={t('admin.tickets.filterPriority')}
        value={f.priority}
        onChange={(e) => workflow.onFiltersChange({ ...f, priority: e.target.value as Priority | '' })}
        className={inputCls}
      >
        <option value="">{t('admin.tickets.filterAnyPriority')}</option>
        {PRIORITIES.map((p) => (
          <option key={p} value={p}>{t(`admin.tickets.priority.${p}`)}</option>
        ))}
      </select>
      <label className="flex items-center gap-1.5 text-[12px] text-gray-600">
        <input
          type="checkbox"
          checked={f.unresolvedOnly}
          onChange={(e) => workflow.onFiltersChange({ ...f, unresolvedOnly: e.target.checked })}
        />
        {t('admin.tickets.filterUnresolved')}
      </label>
    </div>
  );
}

export function FeedbackSection({
  inbox,
  tickets,
  t,
}: {
  inbox: FeedbackInbox | null;
  tickets: TicketWorkflow;
  t: TFunc;
}) {
  if (!inbox && !tickets.loadError) return null;
  const entries = inbox?.entries ?? [];
  const mf = inbox?.match_feedback;
  return (
    <section className="mt-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3 flex items-center gap-2">
        <MessageSquareText className="w-4 h-4 text-indigo-600" />
        {t('admin.feedback.title')}
      </h2>
      {tickets.loadError && (
        <p role="alert" className="text-[13px] text-red-700 mb-2">
          {t('admin.tickets.loadFailed', { error: tickets.loadError })}
        </p>
      )}
      {!inbox ? null : inbox.status !== 'ok' ? (
        <p className="text-[13px] text-gray-400 italic">{t('admin.feedback.unconfigured')}</p>
      ) : (
        <>
          {mf && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard label={t('admin.feedback.thumbsUp')} value={mf.up} color="green" />
              <StatCard label={t('admin.feedback.thumbsDown')} value={mf.down} color={mf.down > mf.up ? 'amber' : 'gray'} />
              <StatCard label={t('admin.feedback.thumbsUp7d')} value={mf.up_7d} color="blue" />
              <StatCard label={t('admin.feedback.thumbsDown7d')} value={mf.down_7d} color={mf.down_7d > 0 ? 'amber' : 'gray'} />
            </div>
          )}
          {mf?.analysis && <AnalysisBlock analysis={mf.analysis} t={t} />}
          {mf && mf.top_downvoted.length > 0 && (
            <div className="mt-3">
              <p className="text-[12px] font-medium text-gray-500 mb-1 flex items-center gap-1">
                <ThumbsDown className="w-3 h-3" /> {t('admin.feedback.topDownvoted')}
              </p>
              <ul className="text-[12px] text-gray-600 space-y-0.5">
                {mf.top_downvoted.slice(0, 5).map((d) => (
                  <li key={d.opportunity_id} className="truncate">
                    <span className="font-mono text-gray-400">{d.downs}×</span>{' '}
                    {d.title ?? d.opportunity_id}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="mt-4">
            <p className="text-[12px] font-medium text-gray-500 mb-2">
              {t('admin.feedback.inbox', { count: entries.length })}
            </p>
            <TicketFiltersBar workflow={tickets} t={t} />
            {entries.length === 0 ? (
              <p className="text-[13px] text-gray-400 italic">{t('admin.feedback.empty')}</p>
            ) : (
              <ul className="space-y-2">
                {entries.map((e) => (
                  <TicketRow key={e.id} ticket={e} workflow={tickets} t={t} />
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
