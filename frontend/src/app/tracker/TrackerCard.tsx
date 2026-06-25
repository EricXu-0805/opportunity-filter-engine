'use client';

import { useState } from 'react';
import { BellRing, Calendar, ExternalLink, X } from 'lucide-react';

import { InteractionStatusMenu } from '@/components/InteractionStatusMenu';
import type { InteractionType } from '@/lib/supabase';
import type { Opp, TFunc } from '@/app/favorites/types';

import { dateInDays, isReminderDue } from './use-tracker-data';

export function TrackerCard({
  opp,
  status,
  notes,
  remindAt,
  onChangeStatus,
  onSaveNotes,
  onSetReminder,
  t,
}: {
  opp: Opp;
  status: InteractionType;
  notes?: string;
  remindAt?: string;
  onChangeStatus: (id: string, type: InteractionType) => void;
  onSaveNotes: (id: string, notes: string) => void;
  onSetReminder: (id: string, date: string | null) => void;
  t: TFunc;
}) {
  const [draft, setDraft] = useState(notes ?? '');
  const lab = opp.lab_or_program || opp.organization || opp.department || '';

  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
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

      {opp.deadline && (
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
              aria-label={t('tracker.clearReminder')}
              className="rounded p-0.5 text-gray-300 hover:text-gray-500"
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
                  className="rounded-md border border-gray-200 px-1.5 py-0.5 text-[11px] text-gray-500 hover:border-amber-300 hover:text-amber-700"
                >
                  {t(key)}
                </button>
              ),
            )}
          </>
        )}
      </div>

      <div className="mt-3">
        <InteractionStatusMenu
          opportunityId={opp.id}
          opportunityTitle={opp.title}
          interaction={status}
          onTrackInteraction={onChangeStatus}
        />
      </div>

      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { if (draft !== (notes ?? '')) onSaveNotes(opp.id, draft); }}
        placeholder={t('tracker.notesPlaceholder')}
        rows={2}
        className="mt-3 w-full resize-y rounded-xl border border-gray-200 px-3 py-2 text-xs text-gray-700 placeholder:text-gray-400 focus:border-indigo-300 focus:ring-2 focus:ring-indigo-500/20 outline-none"
      />
    </div>
  );
}
