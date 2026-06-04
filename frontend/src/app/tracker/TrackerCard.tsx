'use client';

import { useState } from 'react';
import { Calendar, ExternalLink } from 'lucide-react';

import { InteractionStatusMenu } from '@/components/InteractionStatusMenu';
import type { InteractionType } from '@/lib/supabase';
import type { Opp, TFunc } from '@/app/favorites/types';

export function TrackerCard({
  opp,
  status,
  notes,
  remindAt,
  onChangeStatus,
  onSaveNotes,
  t,
}: {
  opp: Opp;
  status: InteractionType;
  notes?: string;
  remindAt?: string;
  onChangeStatus: (id: string, type: InteractionType) => void;
  onSaveNotes: (id: string, notes: string) => void;
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
          className="group flex-1 text-sm font-semibold leading-snug text-gray-900 hover:text-blue-700"
        >
          {opp.title}
          {opp.url && (
            <ExternalLink className="ml-1 inline-block h-3 w-3 align-baseline text-gray-300 group-hover:text-blue-400" />
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

      {remindAt && (
        <p className="mt-1 text-xs font-medium text-amber-600">
          {t('tracker.remindOn')} {remindAt}
        </p>
      )}

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
        className="mt-3 w-full resize-y rounded-xl border border-gray-200 px-3 py-2 text-xs text-gray-700 placeholder:text-gray-400 focus:border-blue-300 focus:ring-2 focus:ring-blue-500/20 outline-none"
      />
    </div>
  );
}
