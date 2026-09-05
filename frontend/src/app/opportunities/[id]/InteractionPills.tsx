'use client';

import { AlertTriangle, Lightbulb } from 'lucide-react';
import { useState } from 'react';
import type { InteractionType } from '@/lib/supabase';
import type { ReminderSuggestion } from '@/lib/status-suggestions';
import { INTERACTION_OPTIONS, INTERACTION_PILL } from './types';
import type { TFunc } from './types';

export function InteractionPills({
  interaction,
  suggestion,
  statusSaving = false,
  statusError = false,
  /** True until the interaction read for the current generation has
   *  confirmed a value (including a confirmed null) — a still-loading or
   *  failed read must disable every pill, since we don't yet know whether
   *  a real status already exists (see use-opportunity-detail.ts). */
  interactionUnready = false,
  onTrack,
  onRetryTrack,
  onUseSuggestion,
  onDismissSuggestion,
  /** True while onUseSuggestion's own save is in flight — disables both
   *  suggestion buttons so a second click can't start an overlapping
   *  attempt. */
  suggestionSaving = false,
  /** True after onUseSuggestion's save genuinely fails — the suggestion
   *  itself stays visible/actionable (never cleared on failure); this just
   *  adds a visible error line so the user knows the click did NOT persist
   *  and Use is a real retry, not a fresh, unattempted action. */
  suggestionError = false,
  t,
}: {
  interaction: InteractionType | undefined;
  suggestion: ReminderSuggestion | null;
  /** True while a status add/change/remove write is in flight — pills are
   *  disabled and must not show a not-yet-persisted status as active. */
  statusSaving?: boolean;
  /** True after a status write fails — interaction still reflects the
   *  last known-persisted value; onRetryTrack replays the failed attempt. */
  statusError?: boolean;
  interactionUnready?: boolean;
  onTrack: (type: InteractionType) => void;
  onRetryTrack?: () => void;
  onUseSuggestion: () => void;
  onDismissSuggestion: () => void;
  suggestionSaving?: boolean;
  suggestionError?: boolean;
  t: TFunc;
}) {
  // Mutual exclusion with the suggestion actions below: a status change and
  // a suggestion-accept save can never be in flight at the same time for
  // the same interaction row (see performStatusChange/handleUseSuggestion
  // in use-opportunity-detail.ts, which enforce this at the hook level too
  // — this is the matching UI-level disable, not the only guard).
  const pillsDisabled = statusSaving || interactionUnready || suggestionSaving;
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const suggestionActionsDisabled = suggestionSaving || statusSaving;
  return (
    <div className="border-t border-gray-100 px-5 sm:px-8 py-4 bg-gray-50/50 space-y-2">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t('detail.trackAriaLabel')}>
        <span className="text-[12px] text-gray-500 mr-1">{t('detail.track')}</span>
        {INTERACTION_OPTIONS.map((type) => {
          const active = interaction === type;
          return (
            <button
              key={type}
              type="button"
              aria-pressed={active}
              aria-busy={statusSaving}
              disabled={pillsDisabled}
              onClick={() => {
                // Re-clicking the highlighted pill used to remove the whole
                // tracker row — status, notes, reminder and the
                // last_contacted_at that Confirm Contact wrote — with no
                // confirmation, because it reads as an on-toggle. Destructive
                // removal is reachable only through the confirmed control
                // below, exactly as InteractionStatusMenu already decided for
                // the results and tracker surfaces.
                if (active) return;
                onTrack(type);
              }}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-50 disabled:cursor-wait ${
                active ? INTERACTION_PILL[type] : 'bg-white border-gray-200 text-gray-400 hover:border-gray-300'
              }`}
            >
              {t(`detail.interactions.${type}`)}
            </button>
          );
        })}
        {interaction && !confirmingRemove && (
          <button
            type="button"
            disabled={pillsDisabled}
            onClick={() => setConfirmingRemove(true)}
            className="ml-auto text-[11px] text-gray-400 underline underline-offset-2 hover:text-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded disabled:opacity-50"
          >
            {t('results.statusMenu.remove')}
          </button>
        )}
      </div>
      {confirmingRemove && interaction && (
        <div role="dialog" aria-label={t('results.statusMenu.remove')} className="rounded-lg border border-gray-200 bg-white p-3">
          <p className="mb-3 text-[12px] leading-relaxed text-gray-600">
            {t('results.statusMenu.removeConfirmBody')}
          </p>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setConfirmingRemove(false)}
              className="rounded-lg px-3 py-1.5 text-[12px] font-medium text-gray-600 hover:bg-gray-100"
            >
              {t('common.cancel')}
            </button>
            <button
              type="button"
              onClick={() => {
                setConfirmingRemove(false);
                // The same same-type callback the REMOVE contract already
                // expects — only the trigger changed, not the write path.
                onTrack(interaction);
              }}
              className="rounded-lg bg-red-600 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-red-700"
            >
              {t('results.statusMenu.removeConfirmYes')}
            </button>
          </div>
        </div>
      )}
      {statusError && (
        <p role="alert" className="flex items-center gap-2 text-[12px] text-red-700">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
          {t('detail.trackSaveError')}
          <button
            type="button"
            onClick={onRetryTrack}
            className="font-semibold text-indigo-600 hover:text-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
          >
            {t('common.retry')}
          </button>
        </p>
      )}
      {suggestion && (
        <div
          role="status"
          className="flex flex-wrap items-center gap-2 px-3 py-2 text-[12px] bg-amber-50 border border-amber-200 rounded-lg animate-in"
        >
          <Lightbulb className="w-3.5 h-3.5 text-amber-600 shrink-0" aria-hidden="true" />
          <span className="text-amber-900">
            {t(
              suggestion.reason === 'follow_up_after_reply'
                ? 'detail.tracker.suggestions.followUpAfterReply'
                : 'detail.tracker.suggestions.thankYouAfterInterview',
              { date: suggestion.date },
            )}
          </span>
          <div className="ml-auto flex gap-1.5">
            <button
              type="button"
              onClick={onUseSuggestion}
              disabled={suggestionActionsDisabled}
              aria-busy={suggestionSaving}
              className="px-2.5 py-0.5 text-[11px] font-medium text-white bg-amber-600 hover:bg-amber-700 rounded-md transition-colors disabled:opacity-50 disabled:cursor-wait"
            >
              {t('detail.tracker.suggestions.useButton', { date: suggestion.date })}
            </button>
            <button
              type="button"
              onClick={onDismissSuggestion}
              disabled={suggestionActionsDisabled}
              className="px-2.5 py-0.5 text-[11px] font-medium text-amber-700 hover:text-amber-900 transition-colors disabled:opacity-50 disabled:cursor-wait"
            >
              {t('detail.tracker.suggestions.dismissButton')}
            </button>
          </div>
          {suggestionError && (
            <p role="alert" className="w-full flex items-center gap-1.5 text-[11px] text-red-700">
              <AlertTriangle className="w-3 h-3 shrink-0" aria-hidden="true" />
              {t('detail.tracker.suggestions.saveError')}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
