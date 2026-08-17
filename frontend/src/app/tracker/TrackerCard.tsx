'use client';

import { BellRing, Calendar, ExternalLink, X } from 'lucide-react';

import { InteractionStatusMenu } from '@/components/InteractionStatusMenu';
import type { InteractionType } from '@/lib/supabase';
import type { Opp, TFunc } from '@/app/favorites/types';

import { dateInDays, isReminderDue } from './use-tracker-data';

export function TrackerCard({
  opp,
  status,
  remindAt,
  draft,
  onDraftChange,
  onChangeStatus,
  onSaveNotes,
  onSetReminder,
  /** True while a status-set/remove or reminder write is in flight for
   *  THIS card — status/reminder controls are disabled; the notes
   *  textarea is unaffected (see notesPending). */
  statusPending = false,
  /** True while THIS card's status write will make it LEAVE the board once
   *  confirmed (a REMOVE, or a SET to 'dismissed') — a strict subset of
   *  statusPending. Disables the notes textarea AND gates onChange/onBlur
   *  (defense-in-depth beyond the `disabled` attribute, since e.g. RTL's
   *  fireEvent bypasses it): a new edit started here has nowhere safe to
   *  land before the card disappears. An ordinary SET's pending window
   *  never sets this — the card is staying, and stays fully editable. */
  leavingPending = false,
  statusError = false,
  onRetryStatus,
  /** Informational only — a save is invoked on every textarea blur, so
   *  this must never disable the textarea itself: a still-in-flight save
   *  must not block the next edit from ever being typed/committed. */
  notesPending = false,
  notesError = false,
  onRetryNotes,
  t,
}: {
  opp: Opp;
  status: InteractionType;
  remindAt?: string;
  /** The live, uncommitted textarea value — a CONTROLLED prop owned by the
   *  caller (useTrackerData's noteDrafts), not component-local state. A
   *  status change moves this card between pipeline columns, which
   *  page.tsx renders as different parent <section> elements; React does
   *  not "move" a component across different parents even with a matching
   *  key, it unmounts and remounts. Local state would be silently
   *  destroyed by that remount before the user ever blurred — real,
   *  observed data loss. A controlled prop survives it: the fresh instance
   *  is simply handed the same value back.
   *
   *  onBlur ALWAYS hands this to onSaveNotes — TrackerCard has no
   *  "is this actually dirty?" gate of its own. It used to compare `draft`
   *  against a `notes` prop (the optimistic display value), but that value
   *  is exactly what a FAILED save leaves showing (never rolled back —
   *  see saveNotes). Editing back to that same failed text, then blurring,
   *  would then look "unchanged" at the card level and never re-attempt
   *  the write — even though the server never actually has it. Only the
   *  hook's confirmed baseline (compared inside saveNotes, not here) can
   *  tell a real no-op apart from a draft that still needs to be sent. */
  draft: string;
  onDraftChange: (id: string, value: string) => void;
  onChangeStatus: (id: string, type: InteractionType) => void;
  onSaveNotes: (id: string, notes: string) => void;
  onSetReminder: (id: string, date: string | null) => void;
  statusPending?: boolean;
  leavingPending?: boolean;
  statusError?: boolean;
  onRetryStatus?: (id: string) => void;
  notesPending?: boolean;
  notesError?: boolean;
  onRetryNotes?: (id: string) => void;
  t: TFunc;
}) {
  const lab = opp.lab_or_program || opp.organization || opp.department || '';

  return (
    <div data-tracker-card-id={opp.id} className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <a
          href={opp.url || undefined}
          target="_blank"
          rel="noopener noreferrer"
          className="group flex-1 text-sm font-semibold leading-snug text-gray-900 hover:text-indigo-700"
        >
          {opp.title}
          {opp.url && (
            <ExternalLink className="ml-1 inline-block h-3 w-3 align-baseline text-gray-300 group-hover:text-indigo-400" />
          )}
        </a>
      </div>

      {lab && <p className="mt-1 text-xs text-gray-500">{lab}</p>}

      {opp.source_type !== 'faculty_research' && opp.deadline && (
        <p className="mt-1.5 flex items-center gap-1 text-xs text-gray-400">
          <Calendar className="h-3 w-3" />
          {opp.deadline}
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        {remindAt ? (
          <>
            <span
              className={`inline-flex items-center gap-1 font-medium ${
                isReminderDue(remindAt) ? 'text-red-600' : 'text-amber-600'
              }`}
            >
              <BellRing className="h-3 w-3" />
              {isReminderDue(remindAt) ? t('tracker.followUpDue') : t('tracker.remindOn')} {remindAt}
            </span>
            <button
              type="button"
              onClick={() => onSetReminder(opp.id, null)}
              disabled={statusPending}
              aria-label={t('tracker.clearReminder')}
              className="rounded p-0.5 text-gray-300 hover:text-gray-500 disabled:opacity-50 disabled:cursor-wait"
            >
              <X className="h-3 w-3" />
            </button>
          </>
        ) : (
          <>
            <span className="inline-flex items-center gap-1 text-gray-400">
              <BellRing className="h-3 w-3" />{t('tracker.remind')}
            </span>
            {([['tracker.remind3', 3], ['tracker.remind7', 7], ['tracker.remind14', 14]] as const).map(
              ([key, days]) => (
                <button
                  key={days}
                  type="button"
                  onClick={() => onSetReminder(opp.id, dateInDays(days))}
                  disabled={statusPending}
                  className="rounded-md border border-gray-200 px-1.5 py-0.5 text-[11px] text-gray-500 hover:border-amber-300 hover:text-amber-700 disabled:opacity-50 disabled:cursor-wait"
                >
                  {t(key)}
                </button>
              ),
            )}
          </>
        )}
      </div>

      {statusError && (
        <p role="alert" className="mt-1.5 flex items-center gap-1.5 text-[11px] text-red-700">
          {t('tracker.statusSaveError')}
          <button
            type="button"
            onClick={() => onRetryStatus?.(opp.id)}
            className="font-semibold text-indigo-600 hover:text-indigo-700"
          >
            {t('common.retry')}
          </button>
        </p>
      )}

      <div className="mt-3">
        <InteractionStatusMenu
          opportunityId={opp.id}
          opportunityTitle={opp.title}
          interaction={status}
          onTrackInteraction={onChangeStatus}
          disabled={statusPending}
        />
      </div>

      <textarea
        value={draft}
        onChange={(e) => { if (!leavingPending) onDraftChange(opp.id, e.target.value); }}
        // Always hands the draft to the hook — no "is this dirty?" check
        // here (see the `draft` prop's doc comment above for why that was
        // wrong). saveNotes itself decides, against the confirmed
        // baseline, whether a network write is actually needed.
        onBlur={() => { if (!leavingPending) onSaveNotes(opp.id, draft); }}
        placeholder={t('tracker.notesPlaceholder')}
        rows={2}
        disabled={leavingPending}
        // Never disabled by notesPending — a save is invoked on every blur,
        // so disabling here could block the very next edit from ever being
        // typed or committed while an earlier save is still in flight.
        // leavingPending is different: the card is about to disappear, so
        // a NEW edit has nowhere safe to land — see the prop's doc comment.
        className="mt-3 w-full resize-y rounded-xl border border-gray-200 px-3 py-2 text-xs text-gray-700 placeholder:text-gray-400 focus:border-indigo-300 focus:ring-2 focus:ring-indigo-500/20 outline-none disabled:opacity-50 disabled:cursor-wait"
      />
      {notesPending && (
        <p className="mt-1 text-[11px] text-gray-400">{t('tracker.notesSaving')}</p>
      )}
      {notesError && (
        <p role="alert" className="mt-1 flex items-center gap-1.5 text-[11px] text-red-700">
          {t('tracker.notesSaveError')}
          <button
            type="button"
            onClick={() => { if (!leavingPending) onRetryNotes?.(opp.id); }}
            disabled={leavingPending}
            // Retrying a notes save while a REMOVE/dismiss is in flight for
            // this SAME id would land its update after the row is already
            // gone (or racing the dismiss's own final-draft flush) — the
            // error stays visible so nothing looks silently resolved, but
            // the action itself waits for the leave to fail (re-enabling
            // it) or succeed (the card leaves/hides, making the point moot).
            className="font-semibold text-indigo-600 hover:text-indigo-700 disabled:opacity-50 disabled:cursor-wait disabled:hover:text-indigo-600"
          >
            {t('common.retry')}
          </button>
        </p>
      )}
    </div>
  );
}
